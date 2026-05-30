"""
TikTok Provider — Video Uploader.
Uses TikTok Content Posting API v2 (File Upload approach).

Flow:
  1. POST /v2/post/video/init/        → get upload_url + publish_id
  2. PUT upload_url (chunked)         → upload video binary
  3. POST /v2/post/video/publish/     → publish with metadata
  4. Poll GET /v2/post/publish/status/ → wait for processing

Docs: https://developers.tiktok.com/doc/content-posting-api-reference-upload-video/
"""
import os
import time
import logging
import requests
from typing import Optional, Callable, List

logger = logging.getLogger("VideoManager.TikTok.Uploader")

TIKTOK_API = "https://open.tiktokapis.com/v2"
CHUNK_SIZE = 10 * 1024 * 1024   # 10 MB per chunk
MAX_POLL  = 240                  # max polling attempts (240 * 5s = 20 minutes)
POLL_DELAY = 5                   # seconds between polls

_PRIVACY_MAP = {
    "public":    "PUBLIC_TO_EVERYONE",
    "friends":   "MUTUAL_FOLLOW_FRIENDS",
    "followers": "FOLLOWER_OF_CREATOR",
    "private":   "SELF_ONLY",
    "unlisted":  "SELF_ONLY",
}


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def upload_video(
    file_path: str,
    access_token: str,
    title: str,
    description: str = "",
    tags: Optional[List[str]] = None,
    category_id: str = "",
    privacy: str = "private",
    progress_callback: Optional[Callable[[int, int], None]] = None,
    **kwargs,
) -> dict:
    """
    Upload a video file to TikTok using Content Posting API v2.
    Returns: {"status": "success"|"error", "video_id": str, "url": str, "message": str}
    """
    if not os.path.isfile(file_path):
        return {"status": "error", "message": f"File not found: {file_path}"}

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return {"status": "error", "message": "File is empty"}

    valid_tiktok_privacies = {"PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"}
    if privacy in valid_tiktok_privacies:
        tiktok_privacy = privacy
    else:
        tiktok_privacy = _PRIVACY_MAP.get(privacy, "SELF_ONLY")
    if file_size <= CHUNK_SIZE:
        actual_chunk_size = file_size
        num_chunks = 1
    else:
        actual_chunk_size = CHUNK_SIZE
        num_chunks = file_size // CHUNK_SIZE

    # ── Step 1: Initialize upload ──────────────────────────────────────────
    logger.info(f"TikTok upload init — file: {file_path}, size: {file_size}, chunks: {num_chunks}")
    post_mode = kwargs.get("tiktok_post_mode", "UPLOAD_DRAFT")
    if post_mode == "DIRECT_POST":
        init_url = f"{TIKTOK_API}/post/publish/video/init/"
        init_payload = {
            "post_info": {
                "title": title[:150],
                "description": description[:2200] if description else "",
                "privacy_level": tiktok_privacy,
                "disable_duet": kwargs.get("tiktok_disable_duet", False),
                "disable_comment": kwargs.get("tiktok_disable_comment", False),
                "disable_stitch": kwargs.get("tiktok_disable_stitch", False),
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": actual_chunk_size,
                "total_chunk_count": num_chunks,
            }
        }
    else:
        # UPLOAD_DRAFT (Inbox)
        init_url = f"{TIKTOK_API}/post/publish/inbox/video/init/"
        init_payload = {
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": actual_chunk_size,
                "total_chunk_count": num_chunks,
            }
        }

    resp = requests.post(init_url, headers=_headers(access_token), json=init_payload, timeout=30)
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"TikTok Init API Error: {resp.status_code} - {resp.text}")
        return {"status": "error", "message": f"TikTok Init failed ({resp.status_code}): {resp.text}"}
    body = resp.json()
    error = body.get("error", {})
    if error.get("code") != "ok":
        return {"status": "error", "message": error.get("message", "Init failed")}

    data = body.get("data", {})
    publish_id = data.get("publish_id", "")
    upload_url = data.get("upload_url", "")

    if not publish_id or not upload_url:
        return {"status": "error", "message": "Missing publish_id or upload_url from TikTok"}

    logger.info(f"TikTok upload init OK — publish_id: {publish_id}")

    # ── Step 2: Upload file chunks ─────────────────────────────────────────
    uploaded = 0
    with open(file_path, "rb") as f:
        for chunk_index in range(num_chunks):
            if chunk_index == num_chunks - 1:
                # The last chunk acts as an oversized chunk containing all remaining data
                chunk_data = f.read()
            else:
                chunk_data = f.read(actual_chunk_size)
            
            chunk_len = len(chunk_data)
            range_start = chunk_index * actual_chunk_size
            range_end = range_start + chunk_len - 1

            chunk_headers = {
                "Content-Type": "video/mp4",
                "Content-Length": str(chunk_len),
                "Content-Range": f"bytes {range_start}-{range_end}/{file_size}",
            }
            put_resp = requests.put(upload_url, headers=chunk_headers, data=chunk_data, timeout=300)
            put_resp.raise_for_status()

            uploaded += chunk_len
            logger.info(f"Chunk {chunk_index+1}/{num_chunks} uploaded ({uploaded}/{file_size} bytes)")
            if progress_callback:
                progress_callback(uploaded, file_size)

    # ── Step 3: Poll for publish status ────────────────────────────────────
    logger.info(f"All chunks uploaded. Polling publish status for publish_id={publish_id}")
    status_url = f"{TIKTOK_API}/post/publish/status/fetch/"

    for attempt in range(MAX_POLL):
        time.sleep(POLL_DELAY)
        st_resp = requests.post(
            status_url,
            headers=_headers(access_token),
            json={"publish_id": publish_id},
            timeout=20,
        )
        st_resp.raise_for_status()
        st_body = st_resp.json()
        st_data = st_body.get("data", {})
        st_error = st_body.get("error", {})

        if st_error.get("code") != "ok":
            return {"status": "error", "message": st_error.get("message", "Publish status error")}

        pub_status = st_data.get("status", "")
        logger.info(f"Publish status attempt {attempt+1}: {pub_status}")

        if pub_status == "PUBLISH_COMPLETE":
            video_id = st_data.get("publicaly_available_post_id", [None])[0] or publish_id
            return {
                "status": "success",
                "video_id": video_id,
                "publish_id": publish_id,
                "url": f"https://www.tiktok.com/video/{video_id}",
                "message": "Video published successfully to TikTok",
            }
        elif pub_status in ("FAILED", "ERROR"):
            fail_reason = st_data.get("fail_reason", "Unknown error")
            return {"status": "error", "message": f"TikTok publish failed: {fail_reason}"}
        # PROCESSING_DOWNLOAD / PROCESSING_UPLOAD / IN_REVIEW → keep polling

    return {
        "status": "error",
        "message": f"Timed out waiting for TikTok publish. publish_id={publish_id} — check TikTok Studio.",
    }
