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
    description: str
    tags: list
    category_id: str
    privacy: str
    thumbnail_path: str

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
            task.finished_at = datetime.now().isoformat()
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
        dead = []
        for cb in task._subscribers:
            try:
                cb(payload)
            except Exception:
                dead.append(cb)
        for cb in dead:
            task._subscribers.remove(cb)

    # ── Upload Runner ────────────────────────────────────────────

    def _run_upload(self, task: UploadTask):
        """Worker thread: resolve token → call provider → upload."""
        task.started_at = datetime.now().isoformat()
        task.status = UploadStatus.UPLOADING
        task.total_bytes = os.path.getsize(task.file_path)
        self._broadcast(task)

        try:
            # Resolve access token
            from core.token_resolver import resolve_token
            # task.email is the primary key; task.cred_id may be a token_id or credential_id
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

            result = provider_obj.upload_video(
                file_path=task.file_path,
                access_token=access_token,
                title=task.title,
                description=task.description,
                tags=task.tags,
                category_id=task.category_id,
                privacy=task.privacy,
                progress_callback=progress_cb,
            )

            if result.get("status") == "success":
                task.video_id = result.get("video_id", "")
                task.video_url = result.get("url", "")
                task.status = UploadStatus.PROCESSING
                task.progress_pct = 100
                self._broadcast(task)

                # Upload thumbnail if provided
                if task.thumbnail_path and os.path.isfile(task.thumbnail_path) and task.video_id:
                    try:
                        provider_obj.set_thumbnail(task.video_id, task.thumbnail_path, access_token)
                        logger.info(f"Thumbnail set for video {task.video_id}")
                    except Exception as e:
                        logger.warning(f"Thumbnail upload failed (non-critical): {e}")

                task.status = UploadStatus.DONE
            else:
                raise RuntimeError(result.get("message", "Upload failed"))

        except InterruptedError:
            task.status = UploadStatus.CANCELLED
            task.error_message = "Cancelled by user"
        except Exception as e:
            logger.error(f"Upload task {task.task_id} failed: {e}")
            task.status = UploadStatus.ERROR
            task.error_message = str(e)[:500]

        task.finished_at = datetime.now().isoformat()
        self._broadcast(task)

    def shutdown(self):
        self._executor.shutdown(wait=False)


# Global singleton
upload_queue = UploadQueue(max_workers=MAX_WORKERS)
