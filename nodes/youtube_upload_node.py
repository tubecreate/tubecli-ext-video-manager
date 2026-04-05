"""
YouTube Upload Node — TubeCLI Workflow Node for uploading videos via AI Workflows.
Registers as "youtube_upload" in the node registry.
"""
import os
import logging
from typing import Any, Dict

logger = logging.getLogger("VideoManager.YouTubeUploadNode")


class YouTubeUploadNode:
    """
    Workflow node that uploads a video file to YouTube.

    Input ports:
        file_path     (str)  — absolute path to video file
        title         (str)  — video title
        description   (str)  — video description
        email         (str)  — authorized YouTube account email
        privacy       (str)  — public | private | unlisted (default: private)
        tags          (str)  — comma-separated tags
        category_id   (str)  — YouTube category ID (default: 22 = People & Blogs)

    Output ports:
        video_id      (str)  — YouTube video ID
        video_url     (str)  — full YouTube URL
        status        (str)  — done | error
        message       (str)  — result message
    """

    node_type = "youtube_upload"
    node_label = "📺 YouTube Upload"
    node_category = "Video"

    # ── Port definitions (for Workflow Builder UI) ──────────────
    INPUT_PORTS = [
        {"id": "file_path",   "label": "Video File Path", "type": "string", "required": True},
        {"id": "title",       "label": "Title",           "type": "string", "required": True},
        {"id": "description", "label": "Description",     "type": "string", "required": False},
        {"id": "email",       "label": "YouTube Account Email", "type": "string", "required": False},
        {"id": "privacy",     "label": "Privacy",         "type": "select",
         "options": ["private", "public", "unlisted"], "default": "private"},
        {"id": "tags",        "label": "Tags (comma,separated)", "type": "string", "required": False},
        {"id": "category_id", "label": "Category ID",    "type": "string", "default": "22"},
    ]

    OUTPUT_PORTS = [
        {"id": "video_id",  "label": "Video ID",  "type": "string"},
        {"id": "video_url", "label": "Video URL",  "type": "string"},
        {"id": "status",    "label": "Status",     "type": "string"},
        {"id": "message",   "label": "Message",    "type": "string"},
    ]

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Synchronous execute for workflow engine."""
        file_path = inputs.get("file_path", self.config.get("file_path", ""))
        title = inputs.get("title", self.config.get("title", "Untitled"))
        description = inputs.get("description", self.config.get("description", ""))
        email = inputs.get("email", self.config.get("email", ""))
        privacy = inputs.get("privacy", self.config.get("privacy", "private"))
        tags_raw = inputs.get("tags", self.config.get("tags", ""))
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        category_id = inputs.get("category_id", self.config.get("category_id", "22"))

        if not file_path:
            return {"video_id": "", "video_url": "", "status": "error",
                    "message": "Missing required 'file_path' input"}

        if not os.path.isfile(file_path):
            return {"video_id": "", "video_url": "", "status": "error",
                    "message": f"File not found: {file_path}"}

        try:
            from core.token_resolver import resolve_token
            from core.provider_registry import get as get_provider

            access_token = resolve_token(
                email=email,
                provider="google",
                required_scope_keyword="youtube",
            )
            if not access_token:
                return {
                    "video_id": "", "video_url": "", "status": "error",
                    "message": "No YouTube token found. Authorize via Auth Manager first."
                }

            provider = get_provider("youtube")
            result = provider.upload_video(
                file_path=file_path,
                access_token=access_token,
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
                privacy=privacy,
            )

            if result.get("status") == "success":
                return {
                    "video_id": result.get("video_id", ""),
                    "video_url": result.get("url", ""),
                    "status": "done",
                    "message": result.get("message", "Upload complete"),
                }
            else:
                return {
                    "video_id": "", "video_url": "", "status": "error",
                    "message": result.get("message", "Upload failed"),
                }

        except Exception as e:
            logger.error(f"YouTubeUploadNode error: {e}")
            return {"video_id": "", "video_url": "", "status": "error", "message": str(e)}

    @classmethod
    def get_definition(cls) -> dict:
        """Return node definition for Workflow Builder."""
        return {
            "type": cls.node_type,
            "label": cls.node_label,
            "category": cls.node_category,
            "input_ports": cls.INPUT_PORTS,
            "output_ports": cls.OUTPUT_PORTS,
        }
