"""
Base provider abstract class — defines the unified interface for all video platform providers.
All providers (YouTube, Facebook, TikTok...) must implement this interface.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Callable, Dict, Any


class VideoMetadata:
    """Standardized video metadata schema across all providers."""
    def __init__(self, **kwargs):
        self.id: str = kwargs.get("id", "")
        self.title: str = kwargs.get("title", "")
        self.description: str = kwargs.get("description", "")
        self.tags: List[str] = kwargs.get("tags", [])
        self.thumbnail_url: str = kwargs.get("thumbnail_url", "")
        self.status: str = kwargs.get("status", "")          # public|private|unlisted|processing
        self.url: str = kwargs.get("url", "")
        self.duration: int = kwargs.get("duration", 0)        # seconds
        self.views: int = kwargs.get("views", 0)
        self.likes: int = kwargs.get("likes", 0)
        self.comments: int = kwargs.get("comments", 0)
        self.published_at: str = kwargs.get("published_at", "")
        self.channel_id: str = kwargs.get("channel_id", "")
        self.channel_title: str = kwargs.get("channel_title", "")
        self.provider: str = kwargs.get("provider", "")
        self.category_id: str = kwargs.get("category_id", "")
        self.extra: Dict[str, Any] = kwargs.get("extra", {})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "thumbnail_url": self.thumbnail_url,
            "status": self.status,
            "url": self.url,
            "duration": self.duration,
            "views": self.views,
            "likes": self.likes,
            "comments": self.comments,
            "published_at": self.published_at,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "provider": self.provider,
            "category_id": self.category_id,
            "extra": self.extra,
        }


class ChannelInfo:
    """Standardized channel/account info schema."""
    def __init__(self, **kwargs):
        self.id: str = kwargs.get("id", "")
        self.title: str = kwargs.get("title", "")
        self.description: str = kwargs.get("description", "")
        self.thumbnail_url: str = kwargs.get("thumbnail_url", "")
        self.subscribers: int = kwargs.get("subscribers", 0)
        self.total_views: int = kwargs.get("total_views", 0)
        self.video_count: int = kwargs.get("video_count", 0)
        self.url: str = kwargs.get("url", "")
        self.provider: str = kwargs.get("provider", "")
        self.extra: Dict[str, Any] = kwargs.get("extra", {})

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "thumbnail_url": self.thumbnail_url,
            "subscribers": self.subscribers,
            "total_views": self.total_views,
            "video_count": self.video_count,
            "url": self.url,
            "provider": self.provider,
            "extra": self.extra,
        }


class VideoProvider(ABC):
    """Abstract base class that all platform providers must implement."""

    provider_id: str = ""       # e.g. "youtube", "facebook", "tiktok"
    provider_name: str = ""     # e.g. "YouTube", "Facebook", "TikTok"
    provider_icon: str = ""     # e.g. "📺"

    # ── Account / Channel ────────────────────────────────────────

    @abstractmethod
    def list_channels(self, access_token: str) -> List[ChannelInfo]:
        """List all channels/pages/accounts linked to this token."""
        raise NotImplementedError

    @abstractmethod
    def get_channel(self, channel_id: str, access_token: str) -> Optional[ChannelInfo]:
        """Get detailed info for a specific channel."""
        raise NotImplementedError

    # ── Video CRUD ───────────────────────────────────────────────

    @abstractmethod
    def list_videos(
        self,
        channel_id: str,
        access_token: str,
        page_token: str = "",
        max_results: int = 50,
    ) -> dict:
        """
        List videos for a channel.
        Returns: {
            "videos": [VideoMetadata.to_dict(), ...],
            "next_page_token": str,
            "total": int,
        }
        """
        raise NotImplementedError

    @abstractmethod
    def get_video(self, video_id: str, access_token: str) -> Optional[VideoMetadata]:
        """Get detailed info for a specific video."""
        raise NotImplementedError

    @abstractmethod
    def update_video(
        self,
        video_id: str,
        access_token: str,
        title: str = None,
        description: str = None,
        tags: List[str] = None,
        category_id: str = None,
        privacy: str = None,
    ) -> dict:
        """Update video metadata. Returns {"status": "success"|"error", "message": str}"""
        raise NotImplementedError

    @abstractmethod
    def delete_video(self, video_id: str, access_token: str) -> dict:
        """Delete a video. Returns {"status": "success"|"error", "message": str}"""
        raise NotImplementedError

    # ── Upload ───────────────────────────────────────────────────

    @abstractmethod
    def upload_video(
        self,
        file_path: str,
        access_token: str,
        title: str,
        description: str = "",
        tags: List[str] = None,
        category_id: str = "22",
        privacy: str = "private",
        progress_callback: Optional[Callable[[int, int], None]] = None,
        page_id: str = "",
    ) -> dict:
        """
        Upload a video file.

        progress_callback(bytes_uploaded, total_bytes)

        page_id — the destination the user picked in the UI: a Facebook Page id,
        a TikTok account id, a YouTube channel id. EVERY provider must accept it,
        even one that cannot act on it.

        WHY it lives in the base signature instead of being decided per provider
        by the caller: UploadQueue resolves providers through provider_registry,
        so it deliberately knows nothing about which platform it is driving. The
        moment the queue has to remember "Facebook and TikTok take page_id but
        YouTube does not", every new provider becomes an edit to the queue — the
        exact coupling the registry exists to remove. Facebook and TikTok had
        already grown the parameter on their own while this abstract signature
        was left behind, so the de-facto contract was page_id all along; the base
        class simply never said so, and YouTube crashed with a TypeError on every
        queued upload. Naming it in one place makes all three honest.

        WHY an explicit parameter and not **kwargs: a catch-all would also
        swallow genuine typos forever. A named parameter keeps
        inspect.getcallargs() able to prove the queue and the providers still
        agree — which is what tests/upload_queue_contract_test.py asserts.

        A provider that cannot choose a destination (YouTube: the OAuth token
        already belongs to exactly one channel) must accept page_id, document
        that it ignores it, and upload anyway — never raise.

        Returns: {"status": "success"|"error", "video_id": str, "url": str, "message": str}
        """
        raise NotImplementedError

    # ── Thumbnail ────────────────────────────────────────────────

    def set_thumbnail(
        self, video_id: str, thumbnail_path: str, access_token: str
    ) -> dict:
        """Set a custom thumbnail. Override in provider if supported."""
        return {"status": "error", "message": "Thumbnail not supported by this provider"}
