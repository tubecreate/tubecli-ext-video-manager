"""
YouTube Provider — unified VideoProvider implementation.
Wires channel_manager, video_manager, and uploader into the base interface.
"""
from typing import List, Optional, Callable

from core.base_provider import VideoProvider, ChannelInfo, VideoMetadata
import providers.youtube.channel_manager as _ch
import providers.youtube.video_manager as _vm
import providers.youtube.uploader as _up


class YouTubeProvider(VideoProvider):
    provider_id = "youtube"
    provider_name = "YouTube"
    provider_icon = "📺"

    def list_channels(self, access_token: str) -> List[ChannelInfo]:
        raw = _ch.list_channels(access_token)
        return [ChannelInfo(**r) for r in raw]

    def get_channel(self, channel_id: str, access_token: str) -> Optional[ChannelInfo]:
        raw = _ch.get_channel(channel_id, access_token)
        return ChannelInfo(**raw) if raw else None

    def list_videos(
        self,
        channel_id: str,
        access_token: str,
        page_token: str = "",
        max_results: int = 50,
    ) -> dict:
        return _vm.list_videos(channel_id, access_token, page_token, max_results)

    def get_video(self, video_id: str, access_token: str) -> Optional[VideoMetadata]:
        raw = _vm.get_video(video_id, access_token)
        return VideoMetadata(**raw) if raw else None

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
        return _vm.update_video(video_id, access_token, title, description, tags, category_id, privacy)

    def delete_video(self, video_id: str, access_token: str) -> dict:
        return _vm.delete_video(video_id, access_token)

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
    ) -> dict:
        return _up.upload_video(
            file_path=file_path,
            access_token=access_token,
            title=title,
            description=description,
            tags=tags,
            category_id=category_id,
            privacy=privacy,
            progress_callback=progress_callback,
        )

    def set_thumbnail(self, video_id: str, thumbnail_path: str, access_token: str) -> dict:
        return _up.set_thumbnail(video_id, thumbnail_path, access_token)


# Auto-register when module is imported
from core import provider_registry
provider_registry.register("youtube", YouTubeProvider)
