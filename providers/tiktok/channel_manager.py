"""
TikTok Provider — Channel Manager.
TikTok uses open_id as the "channel" — one token = one creator account.
Uses: GET /v2/user/info/
"""
import logging
import requests

logger = logging.getLogger("VideoManager.TikTok.ChannelManager")

TIKTOK_API = "https://open.tiktokapis.com/v2"


def list_channels(access_token: str) -> list:
    """
    Returns the TikTok user profile as a single-item channel list.
    TikTok = 1 account per token (no multi-channel like YouTube).
    """
    # Only request fields that are guaranteed to work in sandbox
    fields = "open_id,display_name,avatar_url,follower_count,video_count"
    url = f"{TIKTOK_API}/user/info/"

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": fields},
            timeout=20,
        )
        body = resp.json()
        logger.info(f"[TikTok user/info] status={resp.status_code} body={str(body)[:500]}")

        # TikTok returns errors inside the body even on 200
        tiktok_error = body.get("error", {})
        if isinstance(tiktok_error, dict) and tiktok_error.get("code") not in ("ok", None, ""):
            logger.error(f"TikTok user/info error: {tiktok_error}")
            return []

        if not resp.ok:
            logger.error(f"TikTok user/info HTTP {resp.status_code}: {body}")
            return []

        data = body.get("data", {}).get("user", {})

        if not data:
            logger.warning(f"No user data returned from TikTok user/info. body={body}")
            return []

        open_id = data.get("open_id", "")
        return [{
            "id": open_id,
            "title": data.get("display_name", "TikTok Account"),
            "description": "",
            "thumbnail_url": data.get("avatar_url", ""),
            "subscribers": data.get("follower_count", 0),
            "total_views": 0,
            "video_count": data.get("video_count", 0),
            "url": data.get("profile_deep_link", f"https://www.tiktok.com/@{open_id}"),
            "provider": "tiktok",
            "extra": {"open_id": open_id},
        }]
    except Exception as e:
        logger.error(f"list_channels (TikTok) failed: {e}", exc_info=True)
        return []  # Return empty instead of raising, to avoid HTTP 500


def get_channel(channel_id: str, access_token: str) -> dict:
    """Get channel info — same as list_channels since TikTok is 1 account per token."""
    channels = list_channels(access_token)
    for ch in channels:
        if ch["id"] == channel_id:
            return ch
    return channels[0] if channels else {}
