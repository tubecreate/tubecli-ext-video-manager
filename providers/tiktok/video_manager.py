"""
TikTok Provider — Video Manager (CRUD).
List, get, update, delete videos via TikTok Content Posting API v2.

TikTok API docs: https://developers.tiktok.com/doc/content-posting-api-reference-query-video/
"""
import logging
import requests
from typing import Optional, List

logger = logging.getLogger("VideoManager.TikTok.VideoManager")

TIKTOK_API = "https://open.tiktokapis.com/v2"

# Privacy values: TikTok → unified
_PRIVACY_MAP = {
    "PUBLIC_TO_EVERYONE":   "public",
    "MUTUAL_FOLLOW_FRIENDS": "friends",
    "FOLLOWER_OF_CREATOR":  "followers",
    "SELF_ONLY":            "private",
}
# Unified → TikTok privacy value
_PRIVACY_REVERSE = {v: k for k, v in _PRIVACY_MAP.items()}
_PRIVACY_REVERSE["unlisted"] = "SELF_ONLY"  # closest equivalent


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _parse_video(item: dict, open_id: str = "") -> dict:
    """Parse TikTok API video item into unified VideoMetadata dict."""
    # privacy_level is not available via Display API without special permissions;
    # default to PUBLIC_TO_EVERYONE so the badge doesn't misleadingly show Private.
    privacy_raw = item.get("privacy_level", "PUBLIC_TO_EVERYONE")
    privacy = _PRIVACY_MAP.get(privacy_raw, "private")
    video_id = item.get("id", "")

    return {
        "id": video_id,
        "title": item.get("title", ""),
        "description": item.get("video_description", ""),
        "tags": [],  # TikTok doesn't return tags via API
        "thumbnail_url": item.get("cover_image_url", ""),
        "status": privacy,
        "url": item.get("share_url", f"https://www.tiktok.com/@user/video/{video_id}"),
        "duration": item.get("duration", 0),
        "views": item.get("view_count", 0),
        "likes": item.get("like_count", 0),
        "comments": item.get("comment_count", 0),
        "published_at": item.get("create_time", ""),
        "channel_id": open_id,
        "channel_title": "",
        "provider": "tiktok",
        "category_id": "",
        "extra": {
            "privacy_level": privacy_raw,
            "share_count": item.get("share_count", 0),
            "embed_link": item.get("embed_link", ""),
        },
    }


def list_videos(
    open_id: str,
    access_token: str,
    page_token: str = "",
    max_results: int = 20,
) -> dict:
    """
    List videos for a TikTok user (open_id = channel_id in unified model).
    Uses: POST /v2/video/list/
    """
    # TikTok Display API: `fields` MUST be a URL query param, not in JSON body.
    # Note: privacy_level & embed_link require extra app permissions — excluded to avoid 400.
    fields = "id,title,video_description,cover_image_url,share_url,duration,view_count,like_count,comment_count,share_count,create_time"
    url = f"{TIKTOK_API}/video/list/"

    payload: dict = {
        "max_count": min(max_results, 20),
    }
    if page_token:
        try:
            payload["cursor"] = int(page_token)
        except (ValueError, TypeError):
            pass  # ignore bad cursor

    try:
        resp = requests.post(
            url,
            headers=_headers(access_token),
            params={"fields": fields},  # <-- query param, NOT body
            json=payload,
            timeout=30,
        )
        body = resp.json()
        logger.info(f"[TikTok video/list] status={resp.status_code} body={str(body)[:300]}")

        # Check TikTok-level error even on 200
        tiktok_error = body.get("error", {})
        if isinstance(tiktok_error, dict) and tiktok_error.get("code") not in ("ok", None, ""):
            logger.error(f"TikTok video/list error: {tiktok_error}")
            return {"videos": [], "next_page_token": "", "total": 0}

        if not resp.ok:
            logger.error(f"TikTok video/list HTTP {resp.status_code}: {body}")
            return {"videos": [], "next_page_token": "", "total": 0}

        data = body.get("data", {})
        items = data.get("videos", []) or []
        has_more = data.get("has_more", False)
        next_cursor = str(data.get("cursor", "")) if has_more else ""

        videos = [_parse_video(v, open_id) for v in items]
        logger.info(f"[TikTok video/list] parsed {len(videos)} videos")
        return {
            "videos": videos,
            "next_page_token": next_cursor,
            "total": len(videos),
        }
    except Exception as e:
        logger.error(f"list_videos failed for open_id='{open_id}': {e}", exc_info=True)
        return {"videos": [], "next_page_token": "", "total": 0}


def get_video(video_id: str, access_token: str, open_id: str = "") -> Optional[dict]:
    """
    Get details for a single video.
    Uses: POST /v2/video/query/
    """
    # TikTok Display API: `fields` MUST be a URL query param, not in JSON body.
    # Note: privacy_level & embed_link require extra app permissions — excluded.
    fields = "id,title,video_description,cover_image_url,share_url,duration,view_count,like_count,comment_count,share_count,create_time"
    url = f"{TIKTOK_API}/video/query/"

    payload = {
        "filters": {"video_ids": [video_id]},
    }
    try:
        resp = requests.post(
            url,
            headers=_headers(access_token),
            params={"fields": fields},  # <-- query param
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        items = body.get("data", {}).get("videos", []) or []
        if not items:
            return None
        return _parse_video(items[0], open_id)
    except Exception as e:
        logger.error(f"get_video '{video_id}' failed: {e}")
        return None


def update_video(
    video_id: str,
    access_token: str,
    title: str = None,
    description: str = None,
    privacy: str = None,
    **kwargs,
) -> dict:
    """
    Update video metadata.
    Uses: POST /v2/video/update/
    Note: TikTok only supports updating privacy_level and title via API.
    """
    url = f"{TIKTOK_API}/video/update/"
    payload: dict = {"video_id": video_id}

    if title is not None:
        payload["title"] = title[:150]  # TikTok title max 150 chars
    if description is not None:
        payload["video_description"] = description[:2200]
    if privacy is not None:
        tiktok_privacy = _PRIVACY_REVERSE.get(privacy, "SELF_ONLY")
        payload["privacy_level"] = tiktok_privacy

    if len(payload) == 1:  # only video_id, nothing to update
        return {"status": "error", "message": "No fields to update"}

    try:
        resp = requests.post(url, headers=_headers(access_token), json=payload, timeout=20)
        resp.raise_for_status()
        body = resp.json()
        error = body.get("error", {})
        if error.get("code") != "ok":
            return {"status": "error", "message": error.get("message", "Update failed")}
        return {"status": "success", "video_id": video_id, "message": "Video updated"}
    except Exception as e:
        logger.error(f"update_video '{video_id}' failed: {e}")
        return {"status": "error", "message": str(e)}


def delete_video(video_id: str, access_token: str) -> dict:
    """
    Delete a video.
    Uses: POST /v2/video/delete/
    """
    url = f"{TIKTOK_API}/video/delete/"
    payload = {"video_id": video_id}
    try:
        resp = requests.post(url, headers=_headers(access_token), json=payload, timeout=20)
        resp.raise_for_status()
        body = resp.json()
        error = body.get("error", {})
        if error.get("code") != "ok":
            return {"status": "error", "message": error.get("message", "Delete failed")}
        return {"status": "success", "video_id": video_id, "message": "Video deleted"}
    except Exception as e:
        logger.error(f"delete_video '{video_id}' failed: {e}")
        return {"status": "error", "message": str(e)}
