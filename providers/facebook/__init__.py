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
        channels = []
        try:
            # First get user pages
            resp = requests.get(
                f"{GRAPH_API}/me/accounts",
                params={
                    "access_token": access_token,
                    "fields": "id,name,category,fan_count,picture,link,access_token",
                    "limit": 100,
                },
                timeout=15,
            )
            # If token is a Page Token instead of a User Token, me/accounts often fails or returns empty
            if resp.status_code == 200:
                data = resp.json()
                pages_data = data.get("data", [])
                logger.info(f"[list_channels] /me/accounts returned {len(pages_data)} pages")
                for page in pages_data:
                    pic_url = ""
                    if page.get("picture", {}).get("data", {}).get("url"):
                        pic_url = page["picture"]["data"]["url"]
                    
                    has_page_token = bool(page.get("access_token", ""))
                    logger.info(f"  Page: {page.get('name','')} (ID: {page.get('id','')}) has_token={has_page_token}")

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
            else:
                logger.warning(f"[list_channels] /me/accounts failed: {resp.status_code} {resp.text[:300]}")
            
            # Granular Permissions (New Facebook Auth Model)
            # /me/accounts may omit some pages. We extract ALL Page IDs from the granular_scopes of the token.
            logger.info("[list_channels] Checking granular permissions to supplement channels list...")
            debug_resp = requests.get(
                f"{GRAPH_API}/debug_token",
                params={
                    "input_token": access_token,
                    "access_token": access_token,
                },
                timeout=15,
            )
            if debug_resp.status_code == 200:
                debug_data = debug_resp.json().get("data", {})
                target_ids = set()
                for scope_item in debug_data.get("granular_scopes", []):
                    for tid in scope_item.get("target_ids", []):
                        target_ids.add(tid)
                        
                found_ids = {c.id for c in channels}
                missing_ids = target_ids - found_ids
                
                if missing_ids:
                    logger.info(f"[list_channels] Found {len(missing_ids)} missing target_ids from debug_token: {missing_ids}")
                    for pid in missing_ids:
                            try:
                                p_resp = requests.get(
                                    f"{GRAPH_API}/{pid}",
                                    params={
                                        "access_token": access_token,
                                        "fields": "id,name,category,fan_count,picture,link,access_token",
                                    },
                                    timeout=15,
                                )
                                if p_resp.status_code == 200:
                                    page = p_resp.json()
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
                                            "access_token": page.get("access_token", access_token),
                                            "category": page.get("category", ""),
                                        },
                                    ))
                            except Exception as e:
                                logger.warning(f"[list_channels] Failed to query page {pid}: {e}")

            # Fallback 2 for Page Access Tokens! 
            # If still no channels, query /me directly to fetch the Page itself (or user profile)
            if not channels:
                me_resp = requests.get(
                    f"{GRAPH_API}/me",
                    params={
                        "access_token": access_token,
                        "fields": "id,name,picture,link",
                    },
                    timeout=15,
                )
                print(f"DEBUG FALLBACK: {me_resp.status_code} | {me_resp.text[:300]}")
                if me_resp.status_code == 200:
                    page = me_resp.json()
                    # A valid page has an id and name
                    if page.get("id") and page.get("name"):
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
                                "access_token": access_token,  # use the provided page token
                                "category": page.get("category", ""),
                            },
                        ))
            
            logger.error(f"DEBUG FINAL CHANNELS: {channels}")
            return channels
        except Exception as e:
            logger.error(f"list_channels failed: {e}")
            import traceback; traceback.print_exc()
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

    def _get_page_token(self, channel_id: str, user_access_token: str) -> str:
        """Resolve the page-specific access token using the user access token."""
        try:
            pages = self.list_channels(user_access_token)
            for p in pages:
                if p.id == channel_id:
                    pt = p.extra.get("access_token")
                    if pt:
                        logger.info(f"[Facebook] Resolved page token for page ID {channel_id}")
                        return pt
        except Exception as e:
            logger.warning(f"[Facebook] Failed to resolve page token for {channel_id}: {e}")
        return user_access_token

    def list_videos(self, channel_id: str, access_token: str,
                    page_token: str = "", max_results: int = 50) -> dict:
        """List videos on a Facebook Page."""
        try:
            page_access_token = self._get_page_token(channel_id, access_token)
            params = {
                "access_token": page_access_token,
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
        
        try:
            pages = self.list_channels(access_token)
            if not page_id and pages:
                # Fallback to first page if none provided
                first_page = pages[0]
                target_id = first_page.id
                pt = first_page.extra.get("access_token", "")
                if pt:
                    page_token = pt
                    logger.info(f"Using Page Token for '{first_page.title}' ({target_id})")
            elif page_id and pages:
                # Find the specific page's token
                for p in pages:
                    if p.id == page_id:
                        pt = p.extra.get("access_token", "")
                        if pt:
                            page_token = pt
                            logger.info(f"Using Page Token for specified page '{p.title}' ({target_id})")
                        break
        except Exception as e:
            logger.warning(f"Could not resolve page token for upload: {e}. Falling back to default token.")

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
