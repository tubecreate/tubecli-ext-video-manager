# SKILL.md — Video Manager Extension

## Mô tả
Extension **Video Manager** cho phép quản lý và upload video lên các nền tảng mạng xã hội như **YouTube**, Facebook (sắp ra), TikTok (sắp ra). Sử dụng tài khoản đã được cấp quyền thông qua **Auth Manager** (không cần nhập lại mật khẩu).

## Khi nào dùng
- User yêu cầu "upload video lên YouTube", "đăng video lên [nền tảng]"
- User muốn "xem danh sách video kênh YouTube của tôi"
- User muốn "xem danh sách kênh YouTube"
- User muốn "xóa video [ID]", "xóa video [tiêu đề]"
- User muốn "cập nhật tiêu đề/mô tả/quyền riêng tư video"
- User hỏi "video [ID] đang ở trạng thái gì?" hay "tiến độ upload thế nào?"

## Cách kích hoạt (AI OUTPUT JSON)

### 1. Xem danh sách kênh YouTube:
```json
{"action": "list_channels", "provider": "youtube"}
```
> **Lưu ý:** Lệnh này sẽ liệt kê **TẤT CẢ** các kênh từ **TẤT CẢ** các tài khoản Email đã đăng nhập. AI hãy đọc kỹ danh sách này để biết kênh nào thuộc về Email nào!

### 2. Xem danh sách video của kênh:
```json
{"action": "list_videos", "provider": "youtube", "channel_id": "UCxxxxxx", "email": "user@gmail.com", "max_results": 10}
```
> Nếu người dùng muốn thao tác với một kênh cụ thể, bạn **BẮT BUỘC** phải truyền tham số `email` đi kèm theo kênh đó (nhìn vào danh sách trả về của `list_channels` để biết email quản lý kênh là gì). Đừng bỏ trống email trừ khi chỉ có 1 tài khoản duy nhất.

### 3. Upload video (QUAN TRỌNG: cần file_path từ File Manager):
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
`privacy` có thể là: `public`, `private`, `unlisted`.
> **QUAN TRỌNG:** Phải truyền tham số `email` quản lý kênh đích để tránh upload nhầm sang kênh cũ của người dùng. Hãy hỏi người dùng muốn ưu tiên đăng lên tài khoản nào nếu chưa rõ.

### 4. Cập nhật video:
```json
{
  "action": "update_video",
  "provider": "youtube",
  "video_id": "dQw4w9WgXcQ",
  "email": "user@gmail.com",
  "title": "Tiêu đề mới",
  "description": "Mô tả mới",
  "privacy": "public"
}
```

### 5. Xóa video:
```json
{"action": "delete_video", "provider": "youtube", "video_id": "dQw4w9WgXcQ", "email": "user@gmail.com"}
```

### 6. Kiểm tra tiến độ upload:
```json
{"action": "video_status", "task_id": "abc123..."}
```

## Lưu ý quan trọng
- Bạn là **Orchestrator** — chỉ output JSON, KHÔNG tự làm việc upload.
- Nếu user chưa cấp quyền cho YouTube, hướng dẫn họ vào **Auth Manager** → **Google** → chọn service **YouTube — Quản lý kênh** và authorize.
- Khi upload, file_path phải là đường dẫn tuyệt đối đến file video trên máy tính. Nếu user chưa chỉ rõ đường dẫn, hãy hỏi họ hoặc gợi ý dùng **File Manager** để chọn file.
- Upload video chạy **nền** (background) — trả về task_id ngay lập tức, progress stream qua SSE.
