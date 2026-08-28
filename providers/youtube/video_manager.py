"""
YouTube Provider — Video Manager (CRUD).
List, get, update, delete videos via YouTube Data API v3.
"""
import logging
from typing import List, Optional

logger = logging.getLogger("VideoManager.YouTube.VideoManager")


def _build_service(access_token: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _parse_video_item(item: dict) -> dict:
    """Parse a YouTube API video item into unified VideoMetadata dict."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    status = item.get("status", {})
    content = item.get("contentDetails", {})
    thumbnails = snippet.get("thumbnails", {})

    thumb = (
        thumbnails.get("maxres", {}).get("url")
        or thumbnails.get("high", {}).get("url")
        or thumbnails.get("medium", {}).get("url")
        or thumbnails.get("default", {}).get("url", "")
    )
    video_id = item.get("id", "")
    privacy = status.get("privacyStatus", "private")
    upload_status = status.get("uploadStatus", "")

    # Determine unified status.
    #
    # YouTube's uploadStatus enum is deleted / failed / processed / rejected /
    # uploaded. "processed" is the TERMINAL state of every normal video —
    # "uploaded" only means the bytes arrived and processing has not finished.
    # This used to treat only "uploaded" as finished, so every video on a
    # healthy channel got status="processed": the card fell through to the red
    # badge and printed PROCESSED, nothing could be filtered by privacy, and the
    # edit modal pre-filled its privacy <select> with a value it has no option
    # for — so saving without touching that field sent privacy "" to the API.
    if upload_status in ("uploaded", "processed"):
        unified_status = privacy
    elif upload_status in ("failed", "rejected", "deleted"):
        unified_status = upload_status
    elif upload_status:
        unified_status = "processing"
    else:
        unified_status = privacy

    # Parse duration (ISO 8601 → seconds)
    duration_secs = _parse_duration(content.get("duration", "PT0S"))

    return {
        "id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "tags": snippet.get("tags", []),
        "thumbnail_url": thumb,
        "status": unified_status,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "duration": duration_secs,
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        "published_at": snippet.get("publishedAt", ""),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "provider": "youtube",
        "category_id": snippet.get("categoryId", ""),
        "extra": {
            "upload_status": upload_status,
            "privacy_status": privacy,
            "license": status.get("license", ""),
            "embeddable": status.get("embeddable", True),
            "default_language": snippet.get("defaultLanguage", ""),
            "live_broadcast_content": snippet.get("liveBroadcastContent", "none"),
        },
    }


def _parse_duration(duration: str) -> int:
    """Convert ISO 8601 duration (PT1H2M3S) to total seconds."""
    import re
    match = re.match(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration
    )
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def list_videos(
    channel_id: str,
    access_token: str,
    page_token: str = "",
    max_results: int = 50,
    uploads_playlist_id: str = "",  # Optional: pass from channel.extra["uploads_playlist"] to save quota
) -> dict:
    """
    List videos in a channel (ordered by date, newest first).

    Uses playlistItems.list on the "uploads" playlist (1 quota unit) if
    uploads_playlist_id is provided.  Falls back to search.list (100 quota
    units) otherwise.

    Returns: { videos: [...], next_page_token: str, total: int }
    """
    try:
        service = _build_service(access_token)

        if not uploads_playlist_id:
            # Fetch the uploads playlist ID from the channel resource (1 unit)
            ch_resp = service.channels().list(
                part="contentDetails",
                id=channel_id,
            ).execute()
            items = ch_resp.get("items", [])
            if items:
                uploads_playlist_id = (
                    items[0]
                    .get("contentDetails", {})
                    .get("relatedPlaylists", {})
                    .get("uploads", "")
                )

        if uploads_playlist_id:
            # Use playlistItems (costs 1 quota unit)
            pl_params = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(max_results, 50),
            }
            if page_token:
                pl_params["pageToken"] = page_token

            pl_resp = service.playlistItems().list(**pl_params).execute()
            video_ids = [
                item["contentDetails"]["videoId"]
                for item in pl_resp.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            ]
            next_page = pl_resp.get("nextPageToken", "")
            total = pl_resp.get("pageInfo", {}).get("totalResults", 0)
        else:
            # Fallback: search (costs 100 quota units — avoid if possible)
            logger.warning(f"No uploads playlist found for channel '{channel_id}', falling back to search.list (100 quota units)")
            search_params = {
                "part": "id",
                "channelId": channel_id,
                "type": "video",
                "order": "date",
                "maxResults": min(max_results, 50),
            }
            if page_token:
                search_params["pageToken"] = page_token

            search_resp = service.search().list(**search_params).execute()
            video_ids = [
                item["id"]["videoId"]
                for item in search_resp.get("items", [])
                if item.get("id", {}).get("videoId")
            ]
            next_page = search_resp.get("nextPageToken", "")
            total = search_resp.get("pageInfo", {}).get("totalResults", 0)

        if not video_ids:
            return {"videos": [], "next_page_token": "", "total": 0}

        # Step 2: Batch fetch full video details (1 quota unit per 50 videos)
        videos_resp = service.videos().list(
            part="snippet,status,statistics,contentDetails",
            id=",".join(video_ids),
            maxResults=50,
        ).execute()

        videos = [_parse_video_item(item) for item in videos_resp.get("items", [])]
        return {
            "videos": videos,
            "next_page_token": next_page,
            "total": total,
        }

    except Exception as e:
        logger.error(f"list_videos failed for channel '{channel_id}': {e}")
        raise


def get_video(video_id: str, access_token: str) -> Optional[dict]:
    """Get full metadata for a single video."""
    try:
        service = _build_service(access_token)
        resp = service.videos().list(
            part="snippet,status,statistics,contentDetails,localizations",
            id=video_id,
        ).execute()

        items = resp.get("items", [])
        if not items:
            return None
        return _parse_video_item(items[0])

    except Exception as e:
        logger.error(f"get_video '{video_id}' failed: {e}")
        raise


def update_video(
    video_id: str,
    access_token: str,
    title: str = None,
    description: str = None,
    tags: List[str] = None,
    category_id: str = None,
    privacy: str = None,
) -> dict:
    """
    Update video metadata (snippet and/or status).
    Only fields that are not None will be updated.
    """
    try:
        service = _build_service(access_token)

        # Fetch current video to merge
        current_resp = service.videos().list(
            part="snippet,status",
            id=video_id,
        ).execute()

        items = current_resp.get("items", [])
        if not items:
            return {"status": "error", "message": f"Video '{video_id}' not found"}

        item = items[0]
        snippet = item.get("snippet", {})
        video_status = item.get("status", {})

        parts_to_update = []
        body: dict = {"id": video_id}

        # Update snippet fields
        snippet_changed = False
        if title is not None:
            snippet["title"] = title
            snippet_changed = True
        if description is not None:
            snippet["description"] = description
            snippet_changed = True
        if tags is not None:
            snippet["tags"] = tags
            snippet_changed = True
        if category_id is not None:
            snippet["categoryId"] = category_id
            snippet_changed = True

        if snippet_changed:
            body["snippet"] = snippet
            parts_to_update.append("snippet")

        # Update status
        if privacy is not None:
            video_status["privacyStatus"] = privacy
            body["status"] = video_status
            parts_to_update.append("status")

        if not parts_to_update:
            return {"status": "error", "message": "No fields to update"}

        service.videos().update(
            part=",".join(parts_to_update),
            body=body,
        ).execute()

        return {
            "status": "success",
            "video_id": video_id,
            "message": f"Video '{video_id}' updated successfully",
            "updated_fields": parts_to_update,
        }

    except Exception as e:
        logger.error(f"update_video '{video_id}' failed: {e}")
        return {"status": "error", "message": str(e)}


def delete_video(video_id: str, access_token: str) -> dict:
    """Permanently delete a video."""
    try:
        service = _build_service(access_token)
        service.videos().delete(id=video_id).execute()
        return {
            "status": "success",
            "video_id": video_id,
            "message": f"Video '{video_id}' deleted",
        }
    except Exception as e:
        logger.error(f"delete_video '{video_id}' failed: {e}")
        return {"status": "error", "message": str(e)}
