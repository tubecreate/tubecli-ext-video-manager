"""
YouTube Provider — Channel Manager.
Uses YouTube Data API v3 to list and get channel information.
"""
import logging
from typing import List, Optional

logger = logging.getLogger("VideoManager.YouTube.ChannelManager")

YT_API_BASE = "https://www.googleapis.com/youtube/v3"


def _build_service(access_token: str):
    """Build authenticated YouTube API v3 service."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(token=access_token)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def list_channels(access_token: str) -> List[dict]:
    """
    List all channels owned by the authenticated user.
    Returns list of ChannelInfo dicts.
    """
    try:
        service = _build_service(access_token)
        response = service.channels().list(
            part="snippet,statistics,contentDetails,brandingSettings",
            mine=True,
            maxResults=50,
        ).execute()

        channels = []
        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url", "")
            )
            channel_id = item.get("id", "")
            channels.append({
                "id": channel_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "thumbnail_url": thumb,
                "subscribers": int(stats.get("subscriberCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "url": f"https://www.youtube.com/channel/{channel_id}",
                "country": snippet.get("country", ""),
                "custom_url": snippet.get("customUrl", ""),
                "published_at": snippet.get("publishedAt", ""),
                "provider": "youtube",
                "extra": {
                    "uploads_playlist": item.get("contentDetails", {})
                        .get("relatedPlaylists", {})
                        .get("uploads", ""),
                    "hidden_subscriber_count": stats.get("hiddenSubscriberCount", False),
                    "banner_url": item.get("brandingSettings", {})
                        .get("image", {})
                        .get("bannerExternalUrl", ""),
                },
            })
        return channels

    except Exception as e:
        logger.error(f"list_channels failed: {e}")
        raise


def get_channel(channel_id: str, access_token: str) -> Optional[dict]:
    """Get detailed info for a specific channel by ID."""
    try:
        service = _build_service(access_token)
        response = service.channels().list(
            part="snippet,statistics,contentDetails,brandingSettings,topicDetails",
            id=channel_id,
        ).execute()

        items = response.get("items", [])
        if not items:
            return None

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})
        thumb = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url", "")
        )

        return {
            "id": item.get("id", ""),
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "thumbnail_url": thumb,
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "url": f"https://www.youtube.com/channel/{channel_id}",
            "country": snippet.get("country", ""),
            "custom_url": snippet.get("customUrl", ""),
            "published_at": snippet.get("publishedAt", ""),
            "provider": "youtube",
            "extra": {
                "uploads_playlist": item.get("contentDetails", {})
                    .get("relatedPlaylists", {})
                    .get("uploads", ""),
                "banner_url": item.get("brandingSettings", {})
                    .get("image", {})
                    .get("bannerExternalUrl", ""),
                "topics": item.get("topicDetails", {}).get("topicCategories", []),
            },
        }

    except Exception as e:
        logger.error(f"get_channel '{channel_id}' failed: {e}")
        raise
