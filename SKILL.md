# SKILL.md — Video Manager Extension

## Mô tả
Extension **Video Manager** cho phép quản lý và upload video lên các nền tảng mạng xã hội: **YouTube**, **Facebook** (Fanpage). Sử dụng tài khoản đã được cấp quyền thông qua **Auth Manager**.

## Khi nào dùng
- User yêu cầu "upload video lên YouTube", "đăng video lên Facebook", "post lên fanpage"
- User muốn "xem danh sách video kênh YouTube/Facebook"
- User muốn "xem danh sách kênh YouTube" hoặc "xem fanpage Facebook"
- User muốn "xóa video [ID]", "cập nhật tiêu đề/mô tả/quyền riêng tư video"
- User hỏi "video [ID] đang ở trạng thái gì?" hay "tiến độ upload thế nào?"

## Cách kích hoạt (AI OUTPUT JSON)

### 1. Xem danh sách kênh/fanpage:
```json
{"action": "list_channels", "provider": "youtube"}
```
```json
{"action": "list_channels", "provider": "facebook"}
```
> **Lưu ý:** Lệnh này sẽ liệt kê **TẤT CẢ** các kênh/fanpage từ **TẤT CẢ** các tài khoản đã đăng nhập. AI hãy đọc kỹ danh sách này để biết kênh nào thuộc về Email nào!

### 2. Xem danh sách video:
```json
{"action": "list_videos", "provider": "youtube", "channel_id": "UCxxxxxx", "email": "user@gmail.com"}
```
```json
{"action": "list_videos", "provider": "facebook", "channel_id": "PAGE_ID", "email": "user@facebook.com"}
```
> Nếu người dùng muốn thao tác với kênh cụ thể, **BẮT BUỘC** phải truyền `email` đi kèm.

### 3. Upload video lên YouTube:
```json
{
  "action": "upload_video",
  "provider": "youtube",
  "email": "user@gmail.com",
  "file_path": "/path/to/video.mp4",
  "title": "Tiêu đề video",
  "description": "Mô tả video...",
  "privacy": "private",
  "tags": ["tag1", "tag2"]
}
```

### 4. Upload video lên Facebook Fanpage:
```json
{
  "action": "upload_video",
  "provider": "facebook",
  "email": "ID: PAGE_ID",
  "file_path": "/path/to/video.mp4",
  "title": "Tiêu đề video",
  "description": "Mô tả video...",
  "privacy": "public"
}
```
> `privacy`: `public` (EVERYONE), `private` (SELF), `unlisted` (SELF).
> Email cho Facebook thường là `"ID: <PAGE_ID>"` — xem từ kết quả list_channels.

### 5. Cập nhật video:
```json
{
  "action": "update_video",
  "provider": "youtube",
  "video_id": "dQw4w9WgXcQ",
  "email": "user@gmail.com",
  "title": "Tiêu đề mới",
  "privacy": "public"
}
```

### 6. Xóa video:
```json
{"action": "delete_video", "provider": "youtube", "video_id": "dQw4w9WgXcQ", "email": "user@gmail.com"}
```

### 7. Kiểm tra tiến độ upload:
```json
{"action": "video_status", "task_id": "abc123..."}
```

## Lưu ý quan trọng
- Bạn là **Orchestrator** — chỉ output JSON, KHÔNG tự làm việc upload.
- Nếu user chưa cấp quyền:
  - **YouTube**: Auth Manager → Google → YouTube — Quản lý kênh → Authorize
  - **Facebook**: Auth Manager → Facebook → Fanpage — Quản lý → Authorize (hoặc thêm Page Access Token thủ công)
- Khi upload, file_path phải là đường dẫn tuyệt đối. Nếu user chưa chỉ rõ, hỏi hoặc dùng **File Manager**.
- Upload video chạy **nền** — trả về task_id ngay, progress stream qua SSE.
- Khi user nói "đăng lên facebook", "post lên fanpage" → dùng `"provider": "facebook"`.
- Khi user nói "upload youtube", "up lên kênh" → dùng `"provider": "youtube"`.
