import asyncio
import logging
from collections import deque

from .config import LogsSettings
from .models import LogEntry

# Logs from this module are never captured, so a MongoDB outage cannot loop.
internal_logger = logging.getLogger("logs_viewer.internal")


class LogWriter:
    """Buffers finished log entries and writes them to MongoDB in batches,
    so recording a request never waits on the database."""

    def __init__(self, settings: LogsSettings):
        self.settings = settings
        self._queue: asyncio.Queue[LogEntry] | None = None
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._collection = None
        self.dropped = 0
        # Server startup lines are logged before the app's lifespan starts the writer; keep a few until then
        self._pending: deque[LogEntry] = deque(maxlen=100)

    async def start(self, collection) -> None:
        self._collection = collection
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self.settings.queue_max_size)
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._task = asyncio.create_task(self._run(), name="logs-viewer-writer")
        while self._pending:
            self._put(self._pending.popleft())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self.flush_now()
        self._task = None
        self._queue = None
        self._loop = None

    def submit(self, entry: LogEntry) -> None:
        """Queue an entry. Safe to call from any thread; drops when full or stopped."""
        if self._queue is None or self._loop is None:
            if self._task is None:
                self._pending.append(entry)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._put(entry)
        else:
            self._loop.call_soon_threadsafe(self._put, entry)

    def _put(self, entry: LogEntry) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            self.dropped += 1
            return
        if self._queue.qsize() >= self.settings.batch_size:
            self._wake.set()

    def _drain(self) -> list[LogEntry]:
        batch: list[LogEntry] = []
        while self._queue is not None and not self._queue.empty() and len(batch) < self.settings.batch_size:
            batch.append(self._queue.get_nowait())
        return batch

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), self.settings.flush_interval_seconds)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            await self.flush_now()

    async def flush_now(self) -> None:
        """Write everything queued so far (also used by tests and shutdown)."""
        async with self._lock:
            while self._queue is not None and not self._queue.empty():
                await self._flush(self._drain())

    async def _flush(self, batch: list[LogEntry]) -> None:
        if not batch or self._collection is None:
            return
        docs = [e.model_dump(exclude_none=True) for e in batch]
        try:
            await self._collection.insert_many(docs, ordered=False)
        except Exception:
            internal_logger.exception("Failed to write %d log entries to MongoDB", len(docs))
