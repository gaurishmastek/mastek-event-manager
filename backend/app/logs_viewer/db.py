import logging

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient, uri_parser

from .config import LogsSettings

internal_logger = logging.getLogger("logs_viewer.internal")

_client: AsyncMongoClient | None = None
_collection = None
_target = "MongoDB"


def describe_target(settings: LogsSettings) -> str:
    """Where we connect, for error messages: hosts, database and collection, never the password."""
    url = settings.mongodb_url
    if url.startswith("mongodb+srv://"):
        # Don't parse SRV URLs here: that triggers a DNS lookup.
        hosts = url.split("@")[-1].split("/")[0].split("?")[0]
    else:
        try:
            nodes = uri_parser.parse_uri(url, validate=False)["nodelist"]
            hosts = ", ".join(f"{h}:{p}" for h, p in nodes)
        except Exception:
            hosts = "an invalid LOGS_MONGODB_URL"
    return f"{hosts} (database '{settings.mongodb_db}', collection '{settings.mongodb_collection}')"


async def connect(settings: LogsSettings, collection=None):
    """Open the MongoDB connection and make sure indexes exist.

    `collection` lets tests pass in a ready-made (e.g. mock) collection.
    """
    global _client, _collection, _target
    _target = describe_target(settings)
    if collection is None:
        _client = AsyncMongoClient(
            settings.mongodb_url, tz_aware=True, serverSelectionTimeoutMS=5000
        )
        collection = _client[settings.mongodb_db][settings.mongodb_collection]
    _collection = collection
    try:
        await ensure_indexes(collection, settings)
    except Exception as exc:
        # Never stop the host app from starting because the logs DB is down.
        internal_logger.warning("Could not reach logs MongoDB at startup: %s", exc)
    return collection


async def ensure_indexes(collection, settings: LogsSettings) -> None:
    await collection.create_index([("timestamp", DESCENDING)])
    await collection.create_index([("levels", ASCENDING), ("timestamp", DESCENDING)])
    await collection.create_index([("status_code", ASCENDING), ("timestamp", DESCENDING)])
    await collection.create_index([("path", ASCENDING), ("timestamp", DESCENDING)])
    await collection.create_index([("request_id", ASCENDING)])
    if settings.retention_days > 0:
        await collection.create_index(
            [("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"
        )


def target() -> str:
    return _target


def get_collection():
    if _collection is None:
        raise RuntimeError("Logs database is not connected yet")
    return _collection


async def close() -> None:
    global _client, _collection
    if _client is not None:
        await _client.close()
    _client = None
    _collection = None
