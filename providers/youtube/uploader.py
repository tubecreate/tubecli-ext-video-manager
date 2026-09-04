"""
YouTube Provider — Video Uploader.
Uses YouTube Data API v3 resumable upload with real-time progress callbacks.
"""
import os
import logging
from typing import List, Optional, Callable

logger = logging.getLogger("VideoManager.YouTube.Uploader")

# YouTube video category IDs (common ones)
CATEGORY_IDS = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}

CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB chunks


def _build_service(access_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload_video(
    file_path: str,
    access_token: str,
    title: str,
    description: str = "",
    tags: List[str] = None,
    category_id: str = "22",
    privacy: str = "private",
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    Upload a video to YouTube using resumable upload.

    progress_callback(bytes_uploaded, total_bytes) — called during upload.

    Returns:
        {"status": "success", "video_id": str, "url": str, "message": str}
        {"status": "error", "message": str}
    """
    from googleapiclient.http import MediaFileUpload
    import httplib2

    if not os.path.isfile(file_path):
        return {"status": "error", "message": f"File not found: {file_path}"}

    total_bytes = os.path.getsize(file_path)

    body = {
        "snippet": {
            "title": title[:100],          # YouTube title max 100 chars
            "description": description[:5000] if description else "",
            "tags": (tags or [])[:500],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    try:
        service = _build_service(access_token)

        # Detect MIME type
        ext = os.path.splitext(file_path)[1].lower()
        mime_types = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".avi": "video/x-msvideo",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
            ".flv": "video/x-flv",
            ".wmv": "video/x-ms-wmv",
            ".m4v": "video/mp4",
        }
        mimetype = mime_types.get(ext, "video/*")

        media = MediaFileUpload(
            file_path,
            mimetype=mimetype,
            chunksize=CHUNK_SIZE,
            resumable=True,
        )

        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        # Execute resumable upload with progress tracking
        response = None
        bytes_uploaded = 0

        while response is None:
            status, response = request.next_chunk()
            if status:
                bytes_uploaded = int(status.resumable_progress)
                if progress_callback:
                    progress_callback(bytes_uploaded, total_bytes)

        # Final progress broadcast
        if progress_callback:
            progress_callback(total_bytes, total_bytes)

        video_id = response.get("id", "")
        # We asked for part="snippet,status", so the inserted resource tells us which
        # channel YouTube actually filed the video under — free, no extra quota. It is
        # the only way a caller can find out that its chosen channel was not honoured
        # (videos.insert has no destination field; the token decides).
        actual_channel_id = (response.get("snippet") or {}).get("channelId", "")
        return {
            "status": "success",
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "message": f"Video uploaded successfully: {video_id}",
            "title": title,
            "channel_id": actual_channel_id,
        }

    except InterruptedError:
        raise
    except Exception as e:
        logger.error(f"upload_video failed: {e}")
        return {"status": "error", "message": str(e)}


def set_thumbnail(video_id: str, thumbnail_path: str, access_token: str) -> dict:
    """
    Set a custom thumbnail for a video.
    Requires thumbnail upload permissions (youtube.force-ssl scope).
    """
    from googleapiclient.http import MediaFileUpload

    if not os.path.isfile(thumbnail_path):
        return {"status": "error", "message": f"Thumbnail file not found: {thumbnail_path}"}

    ext = os.path.splitext(thumbnail_path)[1].lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    mimetype = mime_types.get(ext, "image/jpeg")

    try:
        service = _build_service(access_token)
        media = MediaFileUpload(thumbnail_path, mimetype=mimetype)
        service.thumbnails().set(
            videoId=video_id,
            media_body=media,
        ).execute()

        return {
            "status": "success",
            "video_id": video_id,
            "message": f"Thumbnail set for video '{video_id}'",
        }
    except Exception as e:
        logger.warning(f"set_thumbnail failed for '{video_id}': {e}")
        return {"status": "error", "message": str(e)}


def list_categories(access_token: str, region_code: str = "US") -> dict:
    """List available YouTube video categories for a region."""
    try:
        service = _build_service(access_token)
        resp = service.videoCategories().list(
            part="snippet",
            regionCode=region_code,
            hl="en",
        ).execute()
        categories = [
            {
                "id": cat["id"],
                "title": cat["snippet"]["title"],
                "assignable": cat["snippet"].get("assignable", False),
            }
            for cat in resp.get("items", [])
            if cat["snippet"].get("assignable", False)
        ]
        return {"status": "success", "categories": categories}
    except Exception as e:
        # Fallback to hardcoded list
        return {
            "status": "success",
            "categories": [{"id": k, "title": v, "assignable": True} for k, v in CATEGORY_IDS.items()],
            "note": f"Fallback list (API error: {str(e)[:100]})",
        }
