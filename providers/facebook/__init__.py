"""
Facebook Provider — Video upload to Facebook Pages via Graph API v19.
Uses resumable upload for large files with progress tracking.
"""
import os
import logging
import requests
from typing import List, Optional, Callable

from core.base_provider import VideoProvider, ChannelInfo, VideoMetadata

logger = logging.getLogger("VideoManager.Facebook")

GRAPH_API = "https://graph.facebook.com/v19.0"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB chunks


class FacebookProvider(VideoProvider):
    provider_id = "facebook"
    provider_name = "Facebook"
    provider_icon = "📘"

    def list_channels(self, access_token: str) -> List[ChannelInfo]:
        """List Facebook Pages managed by the user."""
        try:
            # First get user pages
            resp = requests.get(
                f"{GRAPH_API}/me/accounts",
                params={
                    "access_token": access_token,
                    "fields": "id,name,category,fan_count,picture,link",
                    "limit": 100,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                logger.error(f"Failed to list FB pages: {resp.text[:300]}")
                return []

            data = resp.json()
            channels = []
            for page in data.get("data", []):
                pic_url = ""
                if page.get("picture", {}).get("data", {}).get("url"):
                    pic_url = page["picture"]["data"]["url"]

                channels.append(ChannelInfo(
                    id=page.get("id", ""),
                    title=page.get("name", ""),
                    description=page.get("category", ""),
                    thumbnail_url=pic_url,
                    subscribers=page.get("fan_count", 0),
                    url=page.get("link", f"https://facebook.com/{page.get('id', '')}"),
                    provider="facebook",
                    extra={
                        "access_token": page.get("access_token", ""),  # Page-specific token
                        "category": page.get("category", ""),
                    },
                ))
            return channels
        except Exception as e:
            logger.error(f"list_channels failed: {e}")
            return []

    def get_channel(self, channel_id: str, access_token: str) -> Optional[ChannelInfo]:
        """Get info for a specific Facebook Page."""
        try:
            resp = requests.get(
                f"{GRAPH_API}/{channel_id}",
                params={
                    "access_token": access_token,
                    "fields": "id,name,category,fan_count,picture,link,about",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            page = resp.json()
            pic_url = ""
            if page.get("picture", {}).get("data", {}).get("url"):
                pic_url = page["picture"]["data"]["url"]
            return ChannelInfo(
                id=page.get("id", ""),
                title=page.get("name", ""),
                description=page.get("about", page.get("category", "")),
                thumbnail_url=pic_url,
                subscribers=page.get("fan_count", 0),
                url=page.get("link", ""),
                provider="facebook",
            )
        except Exception as e:
            logger.error(f"get_channel failed: {e}")
            return None

    def list_videos(self, channel_id: str, access_token: str,
                    page_token: str = "", max_results: int = 50) -> dict:
        """List videos on a Facebook Page."""
        try:
            params = {
                "access_token": access_token,
                "fields": "id,title,description,length,views,likes.summary(true),created_time,permalink_url,thumbnails",
                "limit": max_results,
            }
            if page_token:
                params["after"] = page_token
            
            resp = requests.get(f"{GRAPH_API}/{channel_id}/videos", params=params, timeout=15)
            if resp.status_code != 200:
                return {"videos": [], "next_page_token": "", "total": 0}
            
            data = resp.json()
            videos = []
            for v in data.get("data", []):
                thumb_url = ""
                thumbs = v.get("thumbnails", {}).get("data", [])
                if thumbs:
                    thumb_url = thumbs[0].get("uri", "")
                
                videos.append(VideoMetadata(
                    id=v.get("id", ""),
                    title=v.get("title", ""),
                    description=v.get("description", ""),
                    duration=int(v.get("length", 0)),
                    views=int(v.get("views", 0)),
                    likes=v.get("likes", {}).get("summary", {}).get("total_count", 0),
                    published_at=v.get("created_time", ""),
                    url=v.get("permalink_url", ""),
                    thumbnail_url=thumb_url,
                    channel_id=channel_id,
                    provider="facebook",
                ).to_dict())
            
            paging = data.get("paging", {})
            next_token = paging.get("cursors", {}).get("after", "")
            
            return {"videos": videos, "next_page_token": next_token, "total": len(videos)}
        except Exception as e:
            logger.error(f"list_videos failed: {e}")
            return {"videos": [], "next_page_token": "", "total": 0}

    def get_video(self, video_id: str, access_token: str) -> Optional[VideoMetadata]:
        """Get info for a specific Facebook video."""
        try:
            resp = requests.get(
                f"{GRAPH_API}/{video_id}",
                params={
                    "access_token": access_token,
                    "fields": "id,title,description,length,views,likes.summary(true),created_time,permalink_url",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                return None
            v = resp.json()
            return VideoMetadata(
                id=v.get("id", ""),
                title=v.get("title", ""),
                description=v.get("description", ""),
                duration=int(v.get("length", 0)),
                views=int(v.get("views", 0)),
                published_at=v.get("created_time", ""),
                url=v.get("permalink_url", ""),
                provider="facebook",
            )
        except Exception as e:
            logger.error(f"get_video failed: {e}")
            return None

    def update_video(self, video_id: str, access_token: str,
                     title: str = None, description: str = None,
                     tags: List[str] = None, category_id: str = None,
                     privacy: str = None) -> dict:
        """Update video metadata on Facebook."""
        try:
            data = {}
            if title is not None:
                data["title"] = title
            if description is not None:
                data["description"] = description
            
            resp = requests.post(
                f"{GRAPH_API}/{video_id}",
                params={"access_token": access_token},
                json=data,
                timeout=15,
            )
            if resp.status_code == 200:
                return {"status": "success", "message": "Video updated"}
            return {"status": "error", "message": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_video(self, video_id: str, access_token: str) -> dict:
        """Delete a video from Facebook."""
        try:
            resp = requests.delete(
                f"{GRAPH_API}/{video_id}",
                params={"access_token": access_token},
                timeout=15,
            )
            if resp.status_code == 200:
                return {"status": "success", "message": "Video deleted"}
            return {"status": "error", "message": resp.text[:300]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

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
        Upload video to Facebook Page using resumable upload (Graph API v19).
        
        For Page uploads, we need a Page Access Token.
        If page_id is empty, try to get the first page or post to user's timeline.
        
        Returns: {"status": "success"|"error", "video_id": str, "url": str, "message": str}
        """
        if not os.path.isfile(file_path):
            return {"status": "error", "message": f"File not found: {file_path}"}

        total_bytes = os.path.getsize(file_path)
        
        # Resolve page: get page-specific access token if possible
        target_id = page_id or "me"
        page_token = access_token
        
        if not page_id:
            # Try to get first managed page + its page token
            try:
                pages = self.list_channels(access_token)
                if pages:
                    first_page = pages[0]
                    target_id = first_page.id
                    # Page-specific token from extra
                    pt = first_page.extra.get("access_token", "")
                    if pt:
                        page_token = pt
                        logger.info(f"Using Page Token for '{first_page.title}' ({target_id})")
            except Exception as e:
                logger.warning(f"Could not resolve page: {e}. Posting to 'me'.")

        try:
            # For small files (<1GB), use simple upload
            if total_bytes < 1024 * 1024 * 1024:
                return self._simple_upload(
                    file_path, page_token, target_id, title, description,
                    privacy, total_bytes, progress_callback
                )
            else:
                # Resumable upload for large files
                return self._resumable_upload(
                    file_path, page_token, target_id, title, description,
                    privacy, total_bytes, progress_callback
                )
        except InterruptedError:
            raise
        except Exception as e:
            logger.error(f"Facebook upload failed: {e}")
            return {"status": "error", "message": str(e)}

    def _simple_upload(
        self, file_path, access_token, target_id, title, description,
        privacy, total_bytes, progress_callback
    ) -> dict:
        """Simple single-request video upload (for files <1GB)."""
        logger.info(f"Facebook simple upload: {file_path} -> {target_id}")
        
        # Map privacy to Facebook format
        fb_privacy = {"public": "EVERYONE", "private": "SELF", "unlisted": "SELF"}
        privacy_value = fb_privacy.get(privacy, "EVERYONE")
        
        with open(file_path, "rb") as video_file:
            # Read file and track progress
            file_data = video_file.read()
            
            if progress_callback:
                progress_callback(total_bytes // 2, total_bytes)  # 50% while uploading
            
            resp = requests.post(
                f"{GRAPH_API}/{target_id}/videos",
                files={"source": (os.path.basename(file_path), file_data, "video/mp4")},
                data={
                    "access_token": access_token,
                    "title": title[:255],
                    "description": description[:5000] if description else "",
                    "privacy": f'{{"value":"{privacy_value}"}}',
                },
                timeout=300,  # 5 min timeout for upload
            )
        
        if progress_callback:
            progress_callback(total_bytes, total_bytes)
        
        if resp.status_code == 200:
            data = resp.json()
            video_id = data.get("id", "")
            return {
                "status": "success",
                "video_id": video_id,
                "url": f"https://www.facebook.com/watch/?v={video_id}" if video_id else "",
                "message": f"Video uploaded to Facebook: {video_id}",
                "title": title,
            }
        else:
            error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            err_msg = error.get("error", {}).get("message", resp.text[:300])
            return {"status": "error", "message": f"Facebook upload failed: {err_msg}"}

    def _resumable_upload(
        self, file_path, access_token, target_id, title, description,
        privacy, total_bytes, progress_callback
    ) -> dict:
        """Resumable chunked upload for large files."""
        logger.info(f"Facebook resumable upload: {file_path} ({total_bytes} bytes) -> {target_id}")
        
        # Step 1: Start upload session
        start_resp = requests.post(
            f"{GRAPH_API}/{target_id}/videos",
            data={
                "access_token": access_token,
                "upload_phase": "start",
                "file_size": total_bytes,
            },
            timeout=30,
        )
        if start_resp.status_code != 200:
            return {"status": "error", "message": f"Failed to start upload: {start_resp.text[:300]}"}
        
        start_data = start_resp.json()
        upload_session_id = start_data.get("upload_session_id")
        video_id = start_data.get("video_id")
        
        if not upload_session_id:
            return {"status": "error", "message": "No upload_session_id returned"}
        
        # Step 2: Upload chunks
        bytes_uploaded = 0
        with open(file_path, "rb") as f:
            while bytes_uploaded < total_bytes:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                
                if progress_callback:
                    progress_callback(bytes_uploaded, total_bytes)
                
                chunk_resp = requests.post(
                    f"{GRAPH_API}/{target_id}/videos",
                    files={"video_file_chunk": (os.path.basename(file_path), chunk, "video/mp4")},
                    data={
                        "access_token": access_token,
                        "upload_phase": "transfer",
                        "upload_session_id": upload_session_id,
                        "start_offset": bytes_uploaded,
                    },
                    timeout=120,
                )
                
                if chunk_resp.status_code != 200:
                    return {"status": "error", "message": f"Chunk upload failed at {bytes_uploaded}: {chunk_resp.text[:200]}"}
                
                chunk_data = chunk_resp.json()
                bytes_uploaded = int(chunk_data.get("start_offset", bytes_uploaded + len(chunk)))
        
        # Step 3: Finish upload
        fb_privacy = {"public": "EVERYONE", "private": "SELF", "unlisted": "SELF"}
        privacy_value = fb_privacy.get(privacy, "EVERYONE")
        
        finish_resp = requests.post(
            f"{GRAPH_API}/{target_id}/videos",
            data={
                "access_token": access_token,
                "upload_phase": "finish",
                "upload_session_id": upload_session_id,
                "title": title[:255],
                "description": description[:5000] if description else "",
                "privacy": f'{{"value":"{privacy_value}"}}',
            },
            timeout=30,
        )
        
        if progress_callback:
            progress_callback(total_bytes, total_bytes)
        
        if finish_resp.status_code == 200:
            data = finish_resp.json()
            final_id = data.get("id", video_id)
            return {
                "status": "success",
                "video_id": final_id,
                "url": f"https://www.facebook.com/watch/?v={final_id}" if final_id else "",
                "message": f"Video uploaded to Facebook: {final_id}",
                "title": title,
            }
        else:
            return {"status": "error", "message": f"Finish failed: {finish_resp.text[:300]}"}


# Auto-register when module is imported
from core import provider_registry
provider_registry.register("facebook", FacebookProvider)
