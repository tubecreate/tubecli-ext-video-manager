# Video Manager Extension for TubeCLI

Quản lý kênh và tự động upload video đa nền tảng (YouTube, Facebook, TikTok). Hỗ trợ upload ngầm, có tiến trình SSE và quản lý metadata.

## 🌟 Tính năng chính
- Hỗ trợ Google Auth (chọn nhanh tài khoản).
- Trình duyệt file (File picker) chọn file từ server.
- Tự động xếp hàng ưu tiên (Queue) và streaming tiến trình uplaod ngầm.
- Cấu hình tiêu đề, mô tả, quyền riêng tư, và tags.

## 🚀 Hướng dẫn cài đặt

Hệ thống yêu cầu phải cài đặt core [TubeCLI](https://github.com/tubecreate/tubecli) trước.

### Cách 1: Cài đặt trực tiếp (Khuyên dùng)
Bạn có thể tự động cài thông qua CLI có sẵn:
`ash
tubecli ext install https://github.com/tubecreate/tubecli-ext-video-manager.git
`

### Cách 2: Clone thủ công dành cho Developer
`ash
# 1. Di chuyển vào thư mục lưu trữ
cd path/to/tubecli/data/extensions_external

# 2. Clone repository bằng git
git clone https://github.com/tubecreate/tubecli-ext-video-manager.git video_manager

# 3. Kích hoạt extension để nạp core
tubecli ext enable video_manager
`

## 📖 Cách hoạt động
Mở giao diện TubeCLI Dashboard, nhấp vào menu **Video Manager** ở sidebar.
2. Chọn một kênh đã kết nối.
3. Bấm "Bắt đầu Upload", chọn file hoặc nhập đường dẫn và bấm upload.

---
*Phát triển bởi đội ngũ TubeCreate.*
