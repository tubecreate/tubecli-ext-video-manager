"""
Video Manager Extension — Entry point.
Multi-platform video management & upload extension for TubeCLI.
Supports YouTube (Phase 1), Facebook & TikTok (coming soon).
"""
import os
import sys
import logging
from typing import Dict, Any, List, Optional

try:
    from tubecli.core.extension_manager import Extension
    from tubecli.config import DATA_DIR
except ImportError:
    # Running standalone (external extension context)
    from zhiying.core.extension_manager import Extension
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

logger = logging.getLogger("VideoManagerExtension")

TUBECLI_BASE_URL = os.environ.get("TUBECLI_BASE_URL", "http://localhost:5295")


class VideoManagerExtension(Extension):
    name = "video_manager"
    description = "Quản lý & upload video đa nền tảng: YouTube, Facebook, TikTok"
    version = "1.0.0"
    author = "TubeCreate"
    enabled_by_default = False

    def setup(self):
        """Ensure extension directory is in sys.path for local imports."""
        ext_dir = self.extension_dir or os.path.dirname(os.path.abspath(__file__))
        if ext_dir not in sys.path:
            sys.path.insert(0, ext_dir)

    def on_enable(self):
        """Register all providers when extension is enabled."""
        self.setup()
        try:
            import providers.youtube  # triggers auto-register
            logger.info("✅ YouTube provider registered")
        except Exception as e:
            logger.error(f"Failed to register YouTube provider: {e}")
        try:
            import providers.facebook  # triggers auto-register
            logger.info("✅ Facebook provider registered")
        except Exception as e:
            logger.warning(f"Facebook provider not loaded: {e}")

    def on_disable(self):
        """Shutdown upload queue gracefully."""
        try:
            from core.upload_queue import upload_queue
            upload_queue.shutdown()
            logger.info("Upload queue shutdown")
        except Exception:
            pass

    def get_routes(self):
        """Return FastAPI router."""
        import importlib.util
        ext_dir = self.extension_dir or os.path.dirname(os.path.abspath(__file__))

        # Ensure extension directory is in sys.path first
        if ext_dir not in sys.path:
            sys.path.insert(0, ext_dir)

        try:
            # Import providers to trigger registration
            import importlib
            providers_init = os.path.join(ext_dir, "providers", "youtube", "__init__.py")
            if os.path.exists(providers_init):
                spec = importlib.util.spec_from_file_location(
                    "video_manager_providers_youtube", providers_init
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules["video_manager_providers_youtube"] = mod
                    spec.loader.exec_module(mod)
            logger.info("✅ YouTube provider loaded")
        except Exception as e:
            logger.warning(f"Could not pre-load YouTube provider: {e}")

        try:
            import importlib
            fb_init = os.path.join(ext_dir, "providers", "facebook", "__init__.py")
            if os.path.exists(fb_init):
                spec = importlib.util.spec_from_file_location(
                    "video_manager_providers_facebook", fb_init
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules["video_manager_providers_facebook"] = mod
                    spec.loader.exec_module(mod)
            logger.info("✅ Facebook provider loaded")
        except Exception as e:
            logger.warning(f"Could not pre-load Facebook provider: {e}")

        try:
            # Load routes.py using absolute path to avoid name conflicts
            routes_file = os.path.join(ext_dir, "routes.py")
            spec = importlib.util.spec_from_file_location("video_manager_routes", routes_file)
            if not spec or not spec.loader:
                logger.error(f"Cannot load routes.py from {routes_file}")
                return None
            routes_mod = importlib.util.module_from_spec(spec)
            sys.modules["video_manager_routes"] = routes_mod
            spec.loader.exec_module(routes_mod)
            logger.info("✅ Video Manager routes loaded successfully")
            return routes_mod.router
        except Exception as e:
            logger.error(f"Failed to load Video Manager routes: {e}")
            import traceback
            traceback.print_exc()
            return None

    def get_nodes(self) -> Dict[str, Any]:
        """Return workflow nodes provided by this extension."""
        try:
            self.setup()
            from nodes.youtube_upload_node import YouTubeUploadNode
            return {"youtube_upload": YouTubeUploadNode}
        except Exception as e:
            logger.warning(f"Could not load YouTube upload node: {e}")
            return {}

    def get_skill_md(self) -> Optional[str]:
        """Return SKILL.md content for AI agent routing."""
        return self._read_skill_file("SKILL.md")

    def get_telegram_actions(self) -> Dict[str, Any]:
        """Register Telegram chat action handlers."""
        return {
            "list_videos": self._action_list_videos,
            "upload_video": self._action_upload_video,
            "update_video": self._action_update_video,
            "delete_video": self._action_delete_video,
            "list_channels": self._action_list_channels,
            "video_status": self._action_video_status,
        }

    # ── Helper ────────────────────────────────────────────────────

    def _read_skill_file(self, filename: str) -> Optional[str]:
        if self.extension_dir:
            path = os.path.join(self.extension_dir, filename)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    pass
        return None

    async def _call_api(self, path: str, method: str = "GET", json_body: dict = None) -> dict:
        """Call internal TubeCLI API asynchronously to prevent event loop deadlocks."""
        import httpx
        url = f"{TUBECLI_BASE_URL}/api/v1/video_manager{path}"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if method == "GET":
                    resp = await client.get(url)
                elif method == "POST":
                    resp = await client.post(url, json=json_body)
                elif method == "PUT":
                    resp = await client.put(url, json=json_body)
                elif method == "DELETE":
                    resp = await client.delete(url)
                else:
                    return {"status": "error", "message": f"Unknown method: {method}"}
                
                if resp.status_code in (200, 201):
                    return resp.json()
                return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"status": "error", "message": str(e)[:300]}

    # ── Telegram Actions ──────────────────────────────────────────

    async def _action_list_channels(self, action_data: dict, context: dict) -> str:
        provider = action_data.get("provider", "youtube")
        email = action_data.get("email", "")
        print(f"[VideoManager] list_channels called: provider={provider}, email={email}")

        try:
            emails_to_fetch = [email] if email else []
            
            # If no explicit email, fetch all connected accounts 
            if not emails_to_fetch:
                acct_result = await self._call_api(f"/accounts?provider={provider}")
                print(f"[VideoManager] accounts result: {acct_result.get('success')}, count={acct_result.get('count', 0)}")
                if acct_result.get("success") and acct_result.get("accounts"):
                    emails_to_fetch = [a["email"] for a in acct_result["accounts"] if a.get("email")]
                    
            if not emails_to_fetch:
                emails_to_fetch = [""]

            print(f"[VideoManager] Will fetch channels for {len(emails_to_fetch)} accounts")
            
            lines = [f"📺 Danh sách Kênh {provider.capitalize()}:\n"]
            found_any = False

            for em in list(set(emails_to_fetch)):
                try:
                    result = await self._call_api(f"/channels?provider={provider}&email={em}")
                    channels = result.get("channels", []) if result.get("success") else []
                    print(f"[VideoManager] channels for {em}: {len(channels)} found")
                    
                    if channels:
                        found_any = True
                        if em:
                            lines.append(f"📧 Tài khoản: {em}")
                        for ch in channels[:10]:
                            try:
                                subs = int(ch.get('subscribers', 0) or 0)
                            except (ValueError, TypeError):
                                subs = 0
                            try:
                                vids = int(ch.get('video_count', 0) or 0)
                            except (ValueError, TypeError):
                                vids = 0
                            
                            title = str(ch.get('title', 'Unknown'))
                            ch_id = str(ch.get('id', ''))
                            ch_url = str(ch.get('url', ''))
                            
                            lines.append(
                                f"• {title}\n"
                                f"  {subs:,} subscribers | {vids:,} videos\n"
                                f"  {ch_url}"
                            )
                        lines.append("---")
                except Exception as ch_err:
                    print(f"[VideoManager] Error fetching channels for {em}: {ch_err}")
                    continue

            if not found_any:
                return "Không tìm thấy kênh nào."

            final_text = "\n".join(lines).strip()
            print(f"[VideoManager] Final response length: {len(final_text)} chars")
            return final_text
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"Lỗi lấy danh sách kênh: {str(e)[:300]}"

    async def _action_list_videos(self, action_data: dict, context: dict) -> str:
        channel_id = action_data.get("channel_id", "")
        provider = action_data.get("provider", "youtube")
        email = action_data.get("email", "")
        max_results = action_data.get("max_results", 10)

        if not channel_id:
            return "❌ Thiếu channel_id. Trước tiên hãy xem danh sách kênh."

        result = await self._call_api(
            f"/videos?channel_id={channel_id}&provider={provider}&email={email}&max_results={max_results}"
        )
        if not result.get("success"):
            return f"❌ {result.get('message', 'Lỗi lấy danh sách video')}"

        videos = result.get("videos", [])
        if not videos:
            return "🎬 Chưa có video nào trong kênh này."

        lines = [f"🎬 **{result.get('total', len(videos))} videos** (hiển thị {len(videos)}):\n"]
        for v in videos[:15]:
            status_icon = {"public": "🌍", "private": "🔒", "unlisted": "🔗"}.get(v.get("status", ""), "❓")
            
            try:
                views = int(v.get('views', 0))
            except (ValueError, TypeError):
                views = 0
                
            try:
                likes = int(v.get('likes', 0))
            except (ValueError, TypeError):
                likes = 0
                
            title_safe = str(v['title']).replace('*', '').replace('_', '').replace('[', '').replace(']', '')
            
            lines.append(
                f"{status_icon} **{title_safe}**\n"
                f"   👁️ {views:,} views • ❤️ {likes:,}\n"
                f"   🆔 `{v['id']}`"
            )

        if result.get("next_page_token"):
            lines.append("\n💡 Còn nhiều video hơn — yêu cầu trang tiếp theo.")

        return "\n".join(lines)

    async def _action_upload_video(self, action_data: dict, context: dict) -> str:
        file_path = action_data.get("file_path", "")
        provider = action_data.get("provider", "youtube")
        email = action_data.get("email", "")
        title = action_data.get("title", "Video")
        description = action_data.get("description", "")
        privacy = action_data.get("privacy", "private")

        if not file_path:
            return "❌ Thiếu file_path. Hãy chỉ đường dẫn file video cần upload."

        payload = {
            "provider": provider, "email": email, "file_path": file_path,
            "title": title, "description": description,
            "tags": action_data.get("tags", []),
            "privacy": privacy, "category_id": action_data.get("category_id", "22"),
            "thumbnail_path": action_data.get("thumbnail_path", ""),
        }
        result = await self._call_api("/upload", method="POST", json_body=payload)
        if result.get("success"):
            task_id = result.get("task_id", "")
            return (
                f"✅ **Video đã được xếp vào hàng đợi upload!**\n\n"
                f"🆔 Task ID: `{task_id}`\n"
                f"📹 **{title}** → {provider}\n"
                f"🔒 Quyền riêng tư: {privacy}\n\n"
                f"💡 Kiểm tra tiến độ: `/video_status {task_id}`"
            )
        return f"❌ {result.get('message', 'Không thể upload video')}"

    async def _action_update_video(self, action_data: dict, context: dict) -> str:
        video_id = action_data.get("video_id", "")
        provider = action_data.get("provider", "youtube")
        email = action_data.get("email", "")

        if not video_id:
            return "❌ Thiếu video_id."

        update_body = {}
        for field in ["title", "description", "tags", "category_id", "privacy"]:
            if field in action_data:
                update_body[field] = action_data[field]

        result = await self._call_api(
            f"/videos/{video_id}?provider={provider}&email={email}",
            method="PUT",
            json_body=update_body,
        )
        if result.get("success"):
            return f"✅ Video `{video_id}` đã được cập nhật thành công!"
        return f"❌ {result.get('message', 'Lỗi cập nhật video')}"

    async def _action_delete_video(self, action_data: dict, context: dict) -> str:
        video_id = action_data.get("video_id", "")
        provider = action_data.get("provider", "youtube")
        email = action_data.get("email", "")

        if not video_id:
            return "❌ Thiếu video_id."

        result = await self._call_api(
            f"/videos/{video_id}?provider={provider}&email={email}",
            method="DELETE",
        )
        if result.get("success"):
            return f"🗑️ Video `{video_id}` đã được xóa thành công."
        return f"❌ {result.get('message', 'Lỗi xóa video')}"

    async def _action_video_status(self, action_data: dict, context: dict) -> str:
        task_id = action_data.get("task_id", "")
        if not task_id:
            return "❌ Thiếu task_id."

        result = await self._call_api(f"/upload/tasks/{task_id}")
        if not result.get("success"):
            return f"❌ Task `{task_id}` không tìm thấy."

        task = result.get("task", {})
        status = task.get("status", "unknown")
        status_icons = {
            "queued": "⏳", "uploading": "📤", "processing": "⚙️",
            "done": "✅", "error": "❌", "cancelled": "🚫",
        }
        icon = status_icons.get(status, "❓")
        pct = task.get("progress_pct", 0)

        msg = (
            f"{icon} **Upload Task**\n\n"
            f"🆔 `{task_id[:12]}...`\n"
            f"📹 **{task.get('title', 'N/A')}**\n"
            f"📊 Trạng thái: **{status}** ({pct}%)\n"
        )
        if task.get("video_id"):
            msg += f"🎬 Video ID: `{task['video_id']}`\n"
            msg += f"🔗 {task.get('video_url', '')}\n"
        if task.get("error_message"):
            msg += f"❗ Lỗi: {task['error_message'][:200]}\n"

        return msg
