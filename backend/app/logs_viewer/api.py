"""HTTP API the logs UI reads from. Mounted at settings.api_prefix (default /api/logs)."""

import asyncio
import base64
import csv
import inspect
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import ConfigurationError, OperationFailure, PyMongoError

from . import db
from .config import LogsSettings, get_settings
from .demo import fake_entries


def mongo_error_message(exc: Exception) -> str:
    target = db.target()
    if isinstance(exc, OperationFailure) and exc.code in (13, 18):
        return (
            f"MongoDB at {target} rejected the username or password. "
            "Check LOGS_MONGODB_URL in the backend .env file."
        )
    if isinstance(exc, ConfigurationError):
        return f"LOGS_MONGODB_URL is not a valid MongoDB connection string ({exc}). Fix it in the backend .env file."
    return (
        f"Cannot connect to MongoDB at {target}. Make sure MongoDB is running and "
        "LOGS_MONGODB_URL in the backend .env file is correct, then restart the backend."
    )


async def _aggregate(collection, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # pymongo's AsyncCollection.aggregate is a coroutine that returns a cursor;
    # Motor-style collections return the cursor directly. Accept both.
    cursor = collection.aggregate(pipeline)
    if inspect.isawaitable(cursor):
        cursor = await cursor
    return [d async for d in cursor]


class LogsRoute(APIRoute):
    """Turns MongoDB failures into a clear 503 instead of a bare 500."""

    def get_route_handler(self) -> Callable:
        handler = super().get_route_handler()

        async def route_handler(request: Request):
            try:
                return await handler(request)
            except PyMongoError as exc:
                return JSONResponse(
                    status_code=503,
                    content={"detail": mongo_error_message(exc), "code": "mongodb_unavailable"},
                )

        return route_handler


router = APIRouter(tags=["logs"], route_class=LogsRoute)

RANGES = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
FACET_FIELDS = ("level", "status", "method", "route", "host", "service", "environment", "type")
EXPORT_LIMIT = 10_000
STREAM_POLL_SECONDS = 2.0
STREAM_LOOKBACK = timedelta(seconds=5)


def _naive_utc(value: datetime) -> datetime:
    """MongoDB stores UTC; naive UTC values query the same in pymongo and in mocks."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("_id", "expires_at")}
    out["id"] = str(doc["_id"])
    out["timestamp"] = _iso(doc["timestamp"])
    out["messages"] = [{**m, "timestamp": _iso(m["timestamp"])} for m in doc.get("messages", [])]
    return out


@dataclass
class LogFilters:
    """Query parameters shared by every endpoint. Repeat a parameter to OR values,
    e.g. ?level=error&level=fatal."""

    q: str | None = None
    range: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    level: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    method: list[str] = field(default_factory=list)
    route: list[str] = field(default_factory=list)
    path: str | None = None
    host: list[str] = field(default_factory=list)
    service: list[str] = field(default_factory=list)
    environment: list[str] = field(default_factory=list)
    type: list[str] = field(default_factory=list)

    def window(self) -> tuple[datetime, datetime]:
        end = _naive_utc(self.end) if self.end else _naive_utc(datetime.now(timezone.utc))
        if self.start:
            return _naive_utc(self.start), end
        return end - RANGES.get(self.range or "1h", RANGES["1h"]), end

    def to_query(self, skip: str | None = None) -> dict[str, Any]:
        """Build the MongoDB filter. `skip` leaves out one facet's own filter so
        the sidebar still shows counts for the other options of that facet."""
        start, end = self.window()
        clauses: list[dict[str, Any]] = [{"timestamp": {"$gte": start, "$lte": end}}]

        if self.q:
            rx = {"$regex": re.escape(self.q.strip()), "$options": "i"}
            clauses.append(
                {
                    "$or": [
                        {"path": rx},
                        {"messages.message": rx},
                        {"request_id": rx},
                        {"host": rx},
                        {"method": rx},
                    ]
                }
            )
        if self.path:
            clauses.append({"path": {"$regex": "^" + re.escape(self.path)}})
        if self.level and skip != "level":
            clauses.append({"levels": {"$in": self.level}})
        if self.status and skip != "status":
            clauses.append({"$or": [_status_clause(s) for s in self.status]})
        for name in ("method", "route", "host", "service", "environment", "type"):
            values = getattr(self, name)
            if values and skip != name:
                if name == "method":
                    values = [v.upper() for v in values]
                clauses.append({name: {"$in": values}})
        return {"$and": clauses}


def _status_clause(value: str) -> dict[str, Any]:
    value = value.strip().lower()
    if re.fullmatch(r"[1-5]xx", value):
        base = int(value[0]) * 100
        return {"status_code": {"$gte": base, "$lt": base + 100}}
    if value.isdigit():
        return {"status_code": int(value)}
    raise HTTPException(422, f"Invalid status filter: {value!r} (use e.g. 404 or 5xx)")


def get_filters(
    q: Annotated[str | None, Query(description="Free-text search")] = None,
    range: Annotated[str | None, Query(description=f"One of {', '.join(RANGES)}")] = None,
    start: datetime | None = None,
    end: datetime | None = None,
    level: Annotated[list[str], Query()] = [],
    status: Annotated[list[str], Query(description="Exact code or class like 4xx")] = [],
    method: Annotated[list[str], Query()] = [],
    route: Annotated[list[str], Query()] = [],
    path: Annotated[str | None, Query(description="Path prefix")] = None,
    host: Annotated[list[str], Query()] = [],
    service: Annotated[list[str], Query()] = [],
    environment: Annotated[list[str], Query()] = [],
    type: Annotated[list[str], Query()] = [],
) -> LogFilters:
    if range is not None and range not in RANGES:
        raise HTTPException(422, f"Invalid range {range!r}; use one of {', '.join(RANGES)}")
    return LogFilters(
        q, range, start, end, level, status, method, route, path, host, service, environment, type
    )


Filters = Annotated[LogFilters, Depends(get_filters)]


def _encode_cursor(doc: dict[str, Any]) -> str:
    raw = f"{_iso(doc['timestamp'])}|{doc['_id']}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        ts_raw, oid_raw = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        ts = _naive_utc(datetime.fromisoformat(ts_raw.replace("Z", "+00:00")))
        oid = ObjectId(oid_raw)
    except (ValueError, InvalidId) as exc:
        raise HTTPException(422, "Invalid cursor") from exc
    return {"$or": [{"timestamp": {"$lt": ts}}, {"timestamp": ts, "_id": {"$lt": oid}}]}


@router.get("")
async def list_logs(
    filters: Filters,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: str | None = None,
):
    """Newest first. Pass `next_cursor` back as `cursor` to load older entries."""
    query = filters.to_query()
    if cursor:
        query["$and"].append(_decode_cursor(cursor))
    docs = [
        d
        async for d in db.get_collection()
        .find(query)
        .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
        .limit(limit + 1)
    ]
    has_more = len(docs) > limit
    docs = docs[:limit]
    return {
        "items": [serialize(d) for d in docs],
        "next_cursor": _encode_cursor(docs[-1]) if has_more else None,
    }


async def _facet_counts(filters: LogFilters, name: str) -> list[dict[str, Any]]:
    collection = db.get_collection()
    pipeline: list[dict[str, Any]] = [{"$match": filters.to_query(skip=name)}]
    if name == "level":
        pipeline += [{"$unwind": "$levels"}, {"$group": {"_id": "$levels", "count": {"$sum": 1}}}]
    elif name == "status":
        pipeline += [
            {"$match": {"status_code": {"$ne": None}}},
            {"$group": {"_id": "$status_code", "count": {"$sum": 1}}},
        ]
    else:
        pipeline += [
            {"$match": {name: {"$ne": None}}},
            {"$group": {"_id": f"${name}", "count": {"$sum": 1}}},
        ]
    pipeline += [{"$sort": {"count": -1}}, {"$limit": 50}]
    return [{"value": d["_id"], "count": d["count"]} for d in await _aggregate(collection, pipeline)]


@router.get("/facets")
async def facets(filters: Filters):
    """Counts for each sidebar filter (level, status, method, route, host, ...)."""
    results = await asyncio.gather(*(_facet_counts(filters, n) for n in FACET_FIELDS))
    out = dict(zip(FACET_FIELDS, results))
    for level in ("warning", "error", "fatal"):
        if not any(item["value"] == level for item in out["level"]):
            out["level"].append({"value": level, "count": 0})
    return out


@router.get("/histogram")
async def histogram(filters: Filters, buckets: Annotated[int, Query(ge=1, le=200)] = 60):
    """Entry counts over time for the timeline strip, split by level."""
    start, end = filters.window()
    step = (end - start) / buckets
    boundaries = [start + step * i for i in range(buckets)] + [end + timedelta(microseconds=1)]
    pipeline = [
        {"$match": filters.to_query()},
        {
            "$bucket": {
                "groupBy": "$timestamp",
                "boundaries": boundaries,
                "default": "other",
                "output": {
                    "total": {"$sum": 1},
                    "warning": {"$sum": {"$cond": [{"$eq": ["$level", "warning"]}, 1, 0]}},
                    "error": {"$sum": {"$cond": [{"$in": ["$level", ["error", "fatal"]]}, 1, 0]}},
                },
            }
        },
    ]
    found = {
        _naive_utc(d["_id"]): d
        for d in await _aggregate(db.get_collection(), pipeline)
        if d["_id"] != "other"
    }
    series = []
    for b in boundaries[:-1]:
        d = found.get(b, {})
        series.append(
            {
                "start": _iso(b),
                "total": d.get("total", 0),
                "warning": d.get("warning", 0),
                "error": d.get("error", 0),
            }
        )
    return {"start": _iso(start), "end": _iso(end), "bucket_seconds": step.total_seconds(), "buckets": series}


@router.get("/export")
async def export(filters: Filters, format: Annotated[str, Query(pattern="^(json|csv)$")] = "json"):
    """Download the filtered logs (newest first, up to 10,000 entries)."""
    cursor = (
        db.get_collection()
        .find(filters.to_query())
        .sort([("timestamp", DESCENDING), ("_id", DESCENDING)])
        .limit(EXPORT_LIMIT)
    )
    docs = [serialize(d) async for d in cursor]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if format == "json":
        body = json.dumps(docs, indent=2)
        media = "application/json"
    else:
        buf = io.StringIO()
        cols = ["timestamp", "level", "status_code", "method", "host", "path", "duration_ms", "request_id", "messages"]
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for d in docs:
            writer.writerow({**d, "messages": " | ".join(m["message"] for m in d["messages"])})
        body = buf.getvalue()
        media = "text/csv"
    return StreamingResponse(
        iter([body]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="logs-{stamp}.{format}"'},
    )


@router.get("/stream")
async def stream(request: Request, filters: Filters):
    """Server-Sent Events feed of new entries matching the filters (the Live button).

    Polls MongoDB so it works on any deployment, including ones without a replica set.
    Each event carries its id, so a dropped connection resumes from `Last-Event-ID`.
    """
    collection = db.get_collection()
    resume_from = request.headers.get("last-event-id")

    async def events():
        newest = datetime.now(timezone.utc)
        if resume_from and ObjectId.is_valid(resume_from):
            newest = ObjectId(resume_from).generation_time
        # Several backend workers insert at once, and ids only sort by whole seconds,
        # so look back a few seconds on every poll and skip what was already sent.
        seen: dict[ObjectId, datetime] = {}
        yield "retry: 3000\n\n"
        yield "event: ready\ndata: {}\n\n"
        while not await request.is_disconnected():
            try:
                query = filters.to_query()
                # Live mode always looks forward from now, whatever time range is selected.
                query["$and"][0] = {"_id": {"$gte": ObjectId.from_datetime(newest - STREAM_LOOKBACK)}}
                async for doc in collection.find(query).sort([("_id", ASCENDING)]).limit(500):
                    if doc["_id"] in seen:
                        continue
                    seen[doc["_id"]] = doc["_id"].generation_time
                    newest = max(newest, seen[doc["_id"]])
                    yield f"id: {doc['_id']}\nevent: log\ndata: {json.dumps(serialize(doc))}\n\n"
                for old in [k for k, t in seen.items() if t < newest - 4 * STREAM_LOOKBACK]:
                    del seen[old]
                yield ": keep-alive\n\n"
            except PyMongoError as exc:
                yield f"event: failure\ndata: {json.dumps({'detail': mongo_error_message(exc)})}\n\n"
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _settings(request: Request) -> LogsSettings:
    return getattr(request.app.state, "logs_settings", None) or get_settings()


@router.get("/status")
async def status(request: Request):
    """Whether the logs database is reachable. Useful when the UI shows an error."""
    collection = db.get_collection()
    await collection.database.command("ping")
    return {"mongodb": "connected", "target": db.target(), "demo_data": _settings(request).enable_demo_data}


@router.post("/demo/seed")
async def seed_demo_data(
    request: Request,
    count: Annotated[int, Query(ge=1, le=5000)] = 200,
    hours: Annotated[float, Query(ge=0, le=720, description="Spread over the last N hours; 0 = right now")] = 1.0,
):
    """Insert fake logs so the UI has data. Disabled unless LOGS_ENABLE_DEMO_DATA=true."""
    settings = _settings(request)
    if not settings.enable_demo_data:
        raise HTTPException(404, "Demo data is disabled. Set LOGS_ENABLE_DEMO_DATA=true to enable it.")
    entries = fake_entries(count, hours, settings.service_name, settings.environment, settings.retention_days)
    collection = db.get_collection()
    await collection.insert_many([e.model_dump(exclude_none=True) for e in entries])
    return {"inserted": len(entries)}


@router.get("/{log_id}")
async def get_log(log_id: str):
    """One entry by its id or request id (for the detail panel and shareable links)."""
    collection = db.get_collection()
    doc = None
    if ObjectId.is_valid(log_id):
        doc = await collection.find_one({"_id": ObjectId(log_id)})
    if doc is None:
        doc = await collection.find_one({"request_id": log_id}, sort=[("timestamp", DESCENDING)])
    if doc is None:
        raise HTTPException(404, "Log entry not found")
    return serialize(doc)
