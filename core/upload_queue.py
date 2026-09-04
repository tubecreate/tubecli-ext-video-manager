"""
Upload Queue — Multi-threaded upload queue with real-time progress tracking.
Supports concurrent uploads (configurable max workers), SSE progress streaming,
task status persistence, and thumbnail management.
"""
import os
import uuid
import logging
import threading
import time
from typing import Dict, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("VideoManager.UploadQueue")

MAX_WORKERS = 3   # Max concurrent uploads

# How many finished tasks stay in memory. clear_finished() existed but nothing
# ever called it, so a long-running server grew the task dict forever. 50 is the
# UI's own default page size (GET /upload/tasks?limit=50), so trimming at this
# depth removes nothing the user could see.
FINISHED_HISTORY = 50


class UploadStatus(str, Enum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    PROCESSING = "processing"   # Provider-side processing (e.g. YouTube transcoding)
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class UploadTask:
    task_id: str
    provider: str
    email: str
    cred_id: str
    file_path: str
    title: str
    description: str = ""
    tags: list = field(default_factory=list)
    category_id: str = "22"
    privacy: str = "private"
    thumbnail_path: str = ""
    channel_id: str = ""

    status: UploadStatus = UploadStatus.QUEUED
    progress_pct: int = 0
    bytes_uploaded: int = 0
    total_bytes: int = 0
    video_id: str = ""
    video_url: str = ""
    error_message: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: str = ""
    finished_at: str = ""

    # SSE subscribers: list of callables receiving progress updates
    _subscribers: list = field(default_factory=list, repr=False, compare=False)
    _cancel_event: threading.Event = field(
        default_factory=threading.Event, repr=False, compare=False
    )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "provider": self.provider,
            "email": self.email,
            # The destination the user picked. It was missing, so when a video
            # landed on the wrong channel/page the task record could not even say
            # which one had been asked for. cred_id stays out on purpose.
            "channel_id": self.channel_id,
            "file_path": self.file_path,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "category_id": self.category_id,
            "privacy": self.privacy,
            "thumbnail_path": self.thumbnail_path,
            "status": self.status.value if isinstance(self.status, UploadStatus) else self.status,
            "progress_pct": self.progress_pct,
            "bytes_uploaded": self.bytes_uploaded,
            "total_bytes": self.total_bytes,
            "video_id": self.video_id,
            "video_url": self.video_url,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class UploadQueue:
    """
    Thread-safe upload queue with configurable concurrency.
    Each upload runs in its own thread; progress is broadcast to SSE subscribers.
    """

    def __init__(self, max_workers: int = MAX_WORKERS):
        self._tasks: Dict[str, UploadTask] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vm_upload")

    # ── Task Management ──────────────────────────────────────────

    def enqueue(
        self,
        provider: str,
        email: str,
        cred_id: str,
        channel_id: str,
        file_path: str,
        title: str,
        description: str = "",
        tags: list = None,
        category_id: str = "22",
        privacy: str = "private",
        thumbnail_path: str = "",
    ) -> UploadTask:
        """Add a new upload task to the queue and start it immediately."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Video file not found: {file_path}")

        task = UploadTask(
            task_id=uuid.uuid4().hex,
            provider=provider,
            email=email,
            cred_id=cred_id,
            channel_id=channel_id,
            file_path=file_path,
            title=title,
            description=description,
            tags=tags or [],
            category_id=category_id,
            privacy=privacy,
            thumbnail_path=thumbnail_path,
        )

        with self._lock:
            self._tasks[task.task_id] = task

        # Submit to thread pool
        self._executor.submit(self._run_upload, task)
        logger.info(f"Enqueued upload task {task.task_id}: '{title}' → {provider}")
        return task

    def get_task(self, task_id: str) -> Optional[UploadTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> list:
        with self._lock:
            tasks = list(self._tasks.values())
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def cancel_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if not task:
            return False
        task._cancel_event.set()
        if task.status == UploadStatus.QUEUED:
            task.status = UploadStatus.CANCELLED
            task.error_message = "Cancelled by user"
            task.finished_at = datetime.now().isoformat()
            # The SSE stream only closes on done/error/cancelled. Without this
            # broadcast the browser kept a spinner up for a task that will never
            # run, and only found out on the next manual queue refresh.
            self._broadcast(task)
        return True

    def clear_finished(self, keep_last: int = 20):
        """Remove old finished/errored tasks, keeping most recent N."""
        with self._lock:
            finished = [
                (tid, t) for tid, t in self._tasks.items()
                if t.status in (UploadStatus.DONE, UploadStatus.ERROR, UploadStatus.CANCELLED)
            ]
            finished.sort(key=lambda x: x[1].finished_at or "", reverse=True)
            for tid, _ in finished[keep_last:]:
                del self._tasks[tid]

    # ── SSE Subscribe ────────────────────────────────────────────

    def subscribe(self, task_id: str, callback: Callable[[dict], None]):
        """Subscribe to progress updates for a task via callback."""
        task = self.get_task(task_id)
        if task:
            with self._lock:
                task._subscribers.append(callback)
            # Send current state immediately
            callback(task.to_dict())

    def _broadcast(self, task: UploadTask):
        """Broadcast latest task state to all SSE subscribers."""
        payload = task.to_dict()
        # Snapshot under the lock. subscribe() appends from the request thread
        # while this runs on the upload thread; iterating a list that another
        # thread is appending to raises RuntimeError, and thrown from the worker
        # that used to kill the upload thread outright (see _run_upload).
        with self._lock:
            subscribers = list(task._subscribers)
        dead = []
        for cb in subscribers:
            try:
                cb(payload)
            except Exception:
                dead.append(cb)
        if dead:
            with self._lock:
                for cb in dead:
                    if cb in task._subscribers:
                        task._subscribers.remove(cb)

    # ── Upload Runner ────────────────────────────────────────────

    def _run_upload(self, task: UploadTask):
        """Worker thread: resolve token → call provider → upload.

        WHY the whole body is wrapped: this runs on a ThreadPoolExecutor and
        nobody ever awaits the Future, so anything that escapes here is dropped
        on the floor. The task would then sit at "uploading 0%" forever — the SSE
        stream closes only on done/error/cancelled — leaving a spinner in the
        browser and an empty error_message. The setup lines used to live outside
        the try, and os.path.getsize() can raise on its own if the file is moved
        between enqueue and the worker picking the task up.
        """
        try:
            # Cancel must be honoured BEFORE the first byte. cancel_task() only
            # sets the flag and marks a QUEUED task cancelled; this worker then
            # overwrote the status and uploaded anyway. The flag is read inside
            # progress_cb, but for a file smaller than one chunk next_chunk()
            # ships the whole video before any progress fires — so a cancelled
            # upload still went live on the channel.
            if task._cancel_event.is_set():
                task.status = UploadStatus.CANCELLED
                task.error_message = task.error_message or "Cancelled by user"
            else:
                self._do_upload(task)
        except InterruptedError:
            task.status = UploadStatus.CANCELLED
            task.error_message = "Cancelled by user"
        except Exception as e:
            logger.error(f"Upload task {task.task_id} failed: {e}")
            task.status = UploadStatus.ERROR
            task.error_message = str(e)[:500]

        task.finished_at = datetime.now().isoformat()
        self._broadcast(task)
        # Nothing else ever trimmed the dict. Runs last so the task we just
        # finished is the newest one and always survives the cut.
        try:
            self.clear_finished(keep_last=FINISHED_HISTORY)
        except Exception as e:
            logger.warning(f"clear_finished failed (non-critical): {e}")

    def _do_upload(self, task: UploadTask):
        """The actual upload. Raises on failure; _run_upload owns the bookkeeping."""
        task.started_at = datetime.now().isoformat()
        task.status = UploadStatus.UPLOADING
        task.total_bytes = os.path.getsize(task.file_path)
        self._broadcast(task)

        # Resolve access token.
        # NOTE: task.cred_id carries whatever the caller had — routes.py sends
        # `token_id or cred_id`. Send a token_id whenever you have one: several
        # tokens can share one credential_id (this box has nine YouTube tokens on
        # a single credential), and resolve_token() returns the first match it
        # finds, i.e. an arbitrary account.
        from core.token_resolver import resolve_token
        access_token = resolve_token(
            email=task.email,
            cred_id=task.cred_id,
            provider="google" if task.provider == "youtube" else task.provider,
            required_scope_keyword=task.provider,
        )
        if not access_token:
            raise RuntimeError(
                f"No valid token found for provider='{task.provider}' email='{task.email}'. "
                "Please authorize via Auth Manager first."
            )

        # Get provider and upload
        from core.provider_registry import get as get_provider
        provider_obj = get_provider(task.provider)

        def progress_cb(bytes_done: int, total: int):
            if task._cancel_event.is_set():
                raise InterruptedError("Upload cancelled by user")
            task.bytes_uploaded = bytes_done
            task.total_bytes = total
            task.progress_pct = int(bytes_done / total * 100) if total > 0 else 0
            self._broadcast(task)

        # page_id is part of VideoProvider.upload_video for every provider — see
        # the WHY in core/base_provider.py. The queue drives providers through the
        # registry, so it must not special-case platforms.
        result = provider_obj.upload_video(
            file_path=task.file_path,
            access_token=access_token,
            title=task.title,
            description=task.description,
            tags=task.tags,
            category_id=task.category_id,
            privacy=task.privacy,
            progress_callback=progress_cb,
            page_id=task.channel_id,
        )

        result = result or {}
        if result.get("status") != "success":
            raise RuntimeError(result.get("message", "Upload failed"))

        task.video_id = result.get("video_id", "")
        task.video_url = result.get("url", "")
        task.status = UploadStatus.PROCESSING
        task.progress_pct = 100
        self._broadcast(task)

        # The video is already published, so a mismatch is a report, not a failure.
        landed_on = result.get("channel_id", "")
        if task.channel_id and landed_on and landed_on != task.channel_id:
            logger.warning(
                f"Task {task.task_id} targeted channel '{task.channel_id}' but the "
                f"video was published to '{landed_on}' — the token owns a different channel."
            )

        # Upload thumbnail if provided
        if task.thumbnail_path and os.path.isfile(task.thumbnail_path) and task.video_id:
            try:
                provider_obj.set_thumbnail(task.video_id, task.thumbnail_path, access_token)
                logger.info(f"Thumbnail set for video {task.video_id}")
            except Exception as e:
                logger.warning(f"Thumbnail upload failed (non-critical): {e}")

        task.status = UploadStatus.DONE

    def shutdown(self):
        self._executor.shutdown(wait=False)


# Global singleton
upload_queue = UploadQueue(max_workers=MAX_WORKERS)
