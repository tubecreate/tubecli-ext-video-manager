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
```bash
tubecli ext install https://github.com/tubecreate/tubecli-ext-video-manager.git
```

### Cách 2: Clone thủ công dành cho Developer
```bash
# 1. Di chuyển vào thư mục lưu trữ
cd path/to/tubecli/data/extensions_external

# 2. Clone repository bằng git
git clone https://github.com/tubecreate/tubecli-ext-video-manager.git video_manager

# 3. Kích hoạt extension để nạp core
tubecli ext enable video_manager
```

## 📖 Cách hoạt động
Mở giao diện TubeCLI Dashboard, nhấp vào menu **Video Manager** ở sidebar.
2. Chọn một kênh đã kết nối.
3. Bấm "Bắt đầu Upload", chọn file hoặc nhập đường dẫn và bấm upload.


## 🔖 Đánh số phiên bản

Một quy ước duy nhất: **`YYYY.MM.DD.HHMMSS`** — giờ build theo đồng hồ máy build,
mỗi trường luôn đủ số 0 ở đầu (`2026.09.04.180000`, không phải `2026.9.4.18`).

Lý do phải chốt một kiểu: `extension_manager.compare_versions()` so từng đoạn
bằng số nguyên, nên trộn `HH` với `HHMMSS` trong cùng một ngày sẽ **đảo ngược thứ
tự** — `2026.08.28.14` (14 giờ) bị coi là CŨ HƠN `2026.08.28.081729` (8 giờ 17),
vì 14 < 81729. Extension này đã đi qua ba kiểu (`1.0.0` semver →
`2026.05.30.1415` → `2026.05.30.14`), nên sai lệch đó là chuyện đã suýt xảy ra
chứ không phải giả định.

Ràng buộc được `tests/lat1_test.py` canh, không chỉ nằm trong tài liệu này.

---
*Phát triển bởi đội ngũ TubeCreate.*
