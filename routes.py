"""
Video Manager REST API Routes.
FastAPI router for all video management and upload operations.
"""
import os
import sys
import json
import asyncio
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("VideoManager.Routes")

# Ensure this extension's directory is in sys.path for local imports (core, providers)
_EXT_DIR = os.path.dirname(os.path.abspath(__file__))
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

router = APIRouter(prefix="/api/v1/video_manager", tags=["Video Manager"])



# ── Helpers ──────────────────────────────────────────────────────────

# Maps video-platform provider to auth-manager provider and scope keyword
_PROVIDER_AUTH_MAP = {
    "youtube": ("google", "youtube"),
    "facebook": ("facebook", ""),
    "tiktok": ("tiktok", ""),
}

def _auth_provider(video_provider: str) -> str:
    """Map video platform provider to auth provider name."""
    return _PROVIDER_AUTH_MAP.get(video_provider, ("google", ""))[0]

def _get_token(email: str = "", cred_id: str = "", token_id: str = "", provider: str = "google"):
    from core.token_resolver import resolve_token
    # Resolve auth provider — e.g. youtube→google, facebook→facebook
    auth_prov = _PROVIDER_AUTH_MAP.get(provider, (provider, ""))[0]
    scope_kw = _PROVIDER_AUTH_MAP.get(provider, ("", ""))[1]
    token = resolve_token(email=email, cred_id=cred_id or token_id, provider=auth_prov, required_scope_keyword=scope_kw)
    if not token:
        raise HTTPException(
            status_code=401,
            detail=f"No valid token found for provider='{provider}'. Please authorize via Auth Manager first."
        )
    return token


def _get_provider(provider_id: str = "youtube"):
    from core.provider_registry import get as get_provider
    try:
        return get_provider(provider_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Request Models ────────────────────────────────────────────────────

class UpdateVideoRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    category_id: Optional[str] = None
    privacy: Optional[str] = None


class EnqueueUploadRequest(BaseModel):
    provider: str = "youtube"
    email: str = ""
    cred_id: str = ""
    token_id: str = ""  # Prefer token_id for exact resolution
    channel_id: str = ""  # The target channel/page ID
    file_path: str           # Path from File Manager
    title: str
    description: str = ""
    tags: List[str] = []
    category_id: str = "22"
    privacy: str = "private"
    thumbnail_path: str = ""


# ── Providers ────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers():
    """List all registered video providers."""
    from core.provider_registry import list_providers
    return {"success": True, "providers": list_providers()}


# ── Accounts ─────────────────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(
    provider: str = Query("youtube", description="Provider ID"),
):
    """List authorized email accounts for the given provider."""
    from core.token_resolver import list_authorized_accounts
    provider_map = {"youtube": ("google", "youtube"), "facebook": ("facebook", ""), "tiktok": ("tiktok", "")}
    auth_provider, scope_kw = provider_map.get(provider, ("google", ""))
    accounts = list_authorized_accounts(provider=auth_provider, scope_keyword=scope_kw)
    return {"success": True, "accounts": accounts, "count": len(accounts)}


# ── Channels ─────────────────────────────────────────────────────────

@router.get("/channels")
async def list_channels(
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
):
    """List all channels/pages for the authenticated account."""
    token = _get_token(email=email, cred_id=cred_id, provider=provider)
    prov = _get_provider(provider)
    try:
        channels = prov.list_channels(token)
        return {"success": True, "channels": [c.to_dict() for c in channels], "count": len(channels)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/channels/{channel_id}")
async def get_channel(
    channel_id: str,
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
):
    """Get detailed info for a specific channel."""
    token = _get_token(email=email, cred_id=cred_id, provider=provider)
    prov = _get_provider(provider)
    try:
        channel = prov.get_channel(channel_id, token)
        if not channel:
            raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")
        return {"success": True, "channel": channel.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Videos ───────────────────────────────────────────────────────────

@router.get("/videos")
async def list_videos(
    channel_id: str = Query(..., description="Channel ID"),
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
    page_token: str = Query(""),
    max_results: int = Query(50, ge=1, le=50),
):
    """List videos in a channel with pagination."""
    token = _get_token(email=email, cred_id=cred_id, provider=provider)
    prov = _get_provider(provider)
    try:
        result = prov.list_videos(channel_id, token, page_token=page_token, max_results=max_results)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/videos/{video_id}")
async def get_video(
    video_id: str,
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
):
    """Get detailed info for a specific video."""
    token = _get_token(email=email, cred_id=cred_id, provider=provider)
    prov = _get_provider(provider)
    try:
        video = prov.get_video(video_id, token)
        if not video:
            raise HTTPException(status_code=404, detail=f"Video '{video_id}' not found")
        return {"success": True, "video": video.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/videos/{video_id}")
async def update_video(
    video_id: str,
    body: UpdateVideoRequest,
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
):
    """Update video metadata (title, description, tags, privacy)."""
    token = _get_token(email=email, cred_id=cred_id, provider=provider)
    prov = _get_provider(provider)
    try:
        result = prov.update_video(
            video_id=video_id,
            access_token=token,
            title=body.title,
            description=body.description,
            tags=body.tags,
            category_id=body.category_id,
            privacy=body.privacy,
        )
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/videos/{video_id}")
async def delete_video(
    video_id: str,
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
):
    """Permanently delete a video."""
    token = _get_token(email=email, cred_id=cred_id, provider=provider)
    prov = _get_provider(provider)
    try:
        result = prov.delete_video(video_id, token)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Thumbnail Management ──────────────────────────────────────────────

@router.post("/videos/{video_id}/thumbnail")
async def set_thumbnail(
    video_id: str,
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
    thumbnail_path: str = Query(..., description="Absolute path to thumbnail image (from File Manager)"),
):
    """Set custom thumbnail for a video (path from File Manager)."""
    token = _get_token(email=email, cred_id=cred_id, provider=provider)
    prov = _get_provider(provider)

    if not os.path.isfile(thumbnail_path):
        raise HTTPException(status_code=404, detail=f"Thumbnail file not found: {thumbnail_path}")

    try:
        result = prov.set_thumbnail(video_id, thumbnail_path, token)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return {"success": True, **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Upload Queue ──────────────────────────────────────────────────────

@router.post("/upload")
async def enqueue_upload(body: EnqueueUploadRequest):
    """
    Enqueue a video upload task.
    Uses file_path from File Manager — no binary upload needed.
    Returns immediately with task_id; use /upload/progress/{task_id} for SSE updates.
    """
    from core.upload_queue import upload_queue

    if not os.path.isfile(body.file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Video file not found: {body.file_path}. Use File Manager to select a local file."
        )

    try:
        task = upload_queue.enqueue(
            provider=body.provider,
            email=body.email,
            cred_id=body.token_id or body.cred_id,
            channel_id=body.channel_id,
            file_path=body.file_path,
            title=body.title,
            description=body.description,
            tags=body.tags,
            category_id=body.category_id,
            privacy=body.privacy,
            thumbnail_path=body.thumbnail_path,
        )
        return {"success": True, "task_id": task.task_id, "status": task.status, "message": "Upload queued"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/upload/tasks")
async def list_upload_tasks(limit: int = Query(50, ge=1, le=200)):
    """List all upload tasks (queue history)."""
    from core.upload_queue import upload_queue
    return {"success": True, "tasks": upload_queue.list_tasks(limit=limit)}


@router.get("/upload/tasks/{task_id}")
async def get_upload_task(task_id: str):
    """Get status of a specific upload task."""
    from core.upload_queue import upload_queue
    task = upload_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"success": True, "task": task.to_dict()}


@router.delete("/upload/tasks/{task_id}")
async def cancel_upload(task_id: str):
    """Cancel an in-progress or queued upload."""
    from core.upload_queue import upload_queue
    success = upload_queue.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"success": True, "message": f"Task '{task_id}' cancellation requested"}


@router.get("/upload/progress/{task_id}")
async def stream_upload_progress(task_id: str):
    """
    Server-Sent Events stream for real-time upload progress.
    Connect with EventSource in the browser.
    """
    from core.upload_queue import upload_queue

    task = upload_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    loop = asyncio.get_running_loop()

    def on_update(data: dict):
        try:
            if not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, data)
        except asyncio.QueueFull:
            pass  # Drop rapid progress updates if queue is full
        except Exception:
            pass

    upload_queue.subscribe(task_id, on_update)

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(data)}\n\n"
                    # Stop streaming when task is finished
                    status = data.get("status", "")
                    if status in ("done", "error", "cancelled"):
                        yield f"data: {json.dumps({'event': 'close'})}\n\n"
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"  # Keep connection alive
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Video Categories ──────────────────────────────────────────────────

@router.get("/categories")
async def list_categories(
    provider: str = Query("youtube"),
    email: str = Query(""),
    cred_id: str = Query(""),
    region_code: str = Query("US"),
):
    """List available video categories for a provider/region."""
    if provider == "youtube":
        token = _get_token(email=email, cred_id=cred_id, provider=provider)
        from providers.youtube.uploader import list_categories
        return list_categories(token, region_code=region_code)
    return {"status": "success", "categories": [], "note": f"Categories not available for {provider}"}
