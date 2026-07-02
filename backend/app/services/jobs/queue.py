import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine

from app.config import settings

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str
    repository_id: str
    coro_factory: Callable[[], Coroutine[Any, Any, str]]
    state: TaskState = TaskState.QUEUED
    retry_count: int = 0
    error: str | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class JobQueue:
    """Async job queue with retries, cancellation, and concurrency control."""

    def __init__(self, max_concurrent: int = 2) -> None:
        self._queue: asyncio.Queue[Task] = asyncio.Queue()
        self._tasks: dict[str, Task] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._worker_task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Job queue started")

    async def stop(self) -> None:
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    def enqueue(
        self,
        repository_id: str,
        coro_factory: Callable[[], Coroutine[Any, Any, str]],
    ) -> str:
        task_id = str(uuid.uuid4())
        task = Task(id=task_id, repository_id=repository_id, coro_factory=coro_factory)
        self._tasks[task_id] = task
        self._queue.put_nowait(task)
        return task_id

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        if task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            return False
        task.cancel_event.set()
        task.state = TaskState.CANCELLED
        return True

    def get_task(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            asyncio.create_task(self._execute(task))

    async def _execute(self, task: Task) -> None:
        async with self._semaphore:
            if task.cancel_event.is_set():
                task.state = TaskState.CANCELLED
                return

            task.state = TaskState.RUNNING
            try:
                await asyncio.wait_for(
                    task.coro_factory(),
                    timeout=settings.job_timeout_seconds,
                )
                if task.cancel_event.is_set():
                    task.state = TaskState.CANCELLED
                else:
                    task.state = TaskState.COMPLETED
            except asyncio.TimeoutError:
                task.error = "Job timed out"
                await self._handle_failure(task)
            except asyncio.CancelledError:
                task.state = TaskState.CANCELLED
            except Exception as e:
                task.error = str(e)
                await self._handle_failure(task)

    async def _handle_failure(self, task: Task) -> None:
        if task.cancel_event.is_set():
            task.state = TaskState.CANCELLED
            return

        if task.retry_count < settings.max_job_retries:
            task.retry_count += 1
            delay = settings.retry_backoff_base ** task.retry_count
            task.state = TaskState.QUEUED
            logger.warning(
                "Retrying task %s (attempt %d) after %.1fs",
                task.id, task.retry_count, delay,
            )
            await asyncio.sleep(delay)
            if not task.cancel_event.is_set():
                self._queue.put_nowait(task)
        else:
            task.state = TaskState.FAILED
            logger.error("Task %s failed after %d retries: %s", task.id, task.retry_count, task.error)


job_queue = JobQueue(max_concurrent=2)
