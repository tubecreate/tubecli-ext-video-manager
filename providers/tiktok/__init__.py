from core.base_provider import VideoProvider, ChannelInfo, VideoMetadata
from core import provider_registry
from . import channel_manager, video_manager, uploader
from typing import List, Optional

class TikTokProvider(VideoProvider):
    provider_id = "tiktok"
    provider_name = "TikTok"
    provider_icon = "🎵"

    def list_channels(self, access_token: str) -> List[ChannelInfo]:
        channels = channel_manager.list_channels(access_token)
        return [ChannelInfo(**c) for c in channels]

    def get_channel(self, channel_id: str, access_token: str) -> Optional[ChannelInfo]:
        ch = channel_manager.get_channel(channel_id, access_token)
        if ch:
            return ChannelInfo(**ch)
        return None

    def list_videos(self, channel_id: str, access_token: str, page_token: str = "", max_results: int = 20) -> dict:
        return video_manager.list_videos(channel_id, access_token, page_token, max_results)

    def get_video(self, video_id: str, access_token: str) -> Optional[VideoMetadata]:
        v = video_manager.get_video(video_id, access_token)
        if v:
            return VideoMetadata(**v)
        return None

    def update_video(self, video_id: str, access_token: str, title: str = None, description: str = None, tags: List[str] = None, category_id: str = None, privacy: str = None) -> dict:
        return video_manager.update_video(video_id, access_token, title, description, privacy)

    def delete_video(self, video_id: str, access_token: str) -> dict:
        return video_manager.delete_video(video_id, access_token)

    def upload_video(self, file_path: str, access_token: str, title: str, description: str = "", tags: List[str] = None, category_id: str = "22", privacy: str = "private", progress_callback = None, page_id: str = "") -> dict:
        return uploader.upload_video(file_path, access_token, title, description, tags, category_id, privacy, progress_callback, page_id=page_id)

provider_registry.register("tiktok", TikTokProvider)
