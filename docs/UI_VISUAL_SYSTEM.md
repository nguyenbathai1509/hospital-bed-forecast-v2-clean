# Giao diện và CSS

Đợt chỉnh này chỉ thay lớp trình bày, giữ nội dung, thứ tự điều hướng, điều kiện xác nhận và nghiệp vụ dự báo.

## Thiết kế

- Thanh điều hướng xanh đậm, nền làm việc sáng, điểm nhấn xanh ngọc. Giảm bóng đổ và chuyển động để ưu tiên dữ liệu.
- Tiêu đề trang có khoảng cách an toàn với thanh công cụ cố định; tiêu đề mục và thẻ số liệu có cấp độ rõ ràng.
- Dự báo số giường được nhấn nhẹ trong thẻ dự báo; không thay màu dựa trên suy đoán tình trạng nghiệp vụ. Cảnh báo vẫn dùng trạng thái gốc.
- Nút chính, phụ, tải xuống và gửi biểu mẫu thống nhất kích thước, màu và viền. Nút bị vô hiệu hóa vẫn đọc được chữ; không dùng opacity toàn nút.
- Chú thích bỏ opacity 0.6 mặc định để không bị mờ dù đã đặt đúng màu chữ.
- Giữ chỉ báo radio, viền focus bàn phím, cuộn bảng ngang và cơ chế đóng/mở sidebar của Streamlit. Hỗ trợ reduced motion và bố cục hẹp.

## Phân chia mã

- `.streamlit/config.toml`: theme gốc cho nội dung, sidebar, bảng canvas và menu thả xuống.
- `app/theme.css`: token màu, khoảng cách, trạng thái tương tác và breakpoint. Không dùng selector trần `p`, `label` hay tên lớp Emotion sinh tự động.
- `app/styles.py`: nạp CSS và render các khối sidebar có escape HTML.
- Container cần nền riêng dùng key `hb-panel-*`; điều hướng dùng key `hb-navigation`. Không suy đoán container từ vị trí phần tử con hoặc chuỗi inline style.

CSS vẫn có phụ thuộc vào `data-testid`, `kind` của Streamlit. Đã kiểm tra với Streamlit 1.49.1; sau khi nâng phiên bản cần kiểm tra lại, đặc biệt `primaryFormSubmit`, sidebar và caption. Không khẳng định toàn bộ ứng dụng đã qua kiểm định accessibility.

## Kiểm tra

```powershell
python -m pytest tests/test_ui_theme.py tests/test_ui_structure.py tests/test_ui_uncertainty.py -q
python -m pytest -q
```

`tests/fixtures/ui_gallery.py` là bộ mẫu giao diện, không gọi backend và không chạy thao tác nghiệp vụ. Có thể mở riêng bằng Streamlit ở cổng 8512.

`scripts/verify_ui_browser.mjs` sử dụng Node >=22 và Edge/Chromium đã bật remote debugging ở localhost:9223. Không cần npm package mới.

- `node scripts/verify_ui_browser.mjs`: kiểm tra ứng dụng tại localhost:8511, lần lượt điều hướng 8 trang, lưu ảnh trong `reports/ui_review/`. Biến `UI_REVIEW_URL` cho phép đổi địa chỉ ứng dụng kiểm tra. Không nhấn nút huấn luyện, đổi mô hình, chạy pipeline hoặc xác nhận dự báo.
- `node scripts/verify_ui_browser.mjs --controls`: kiểm tra bộ mẫu tại localhost:8512, màu chữ/nền, trạng thái nút, hover, focus, reduced motion, tiêu đề và tràn ngang ở 390px.

Ảnh chụp ứng dụng thật có thể chứa dữ liệu dự án; chỉ lưu cục bộ trong reports (đã được bỏ qua bởi Git), không tải ra dịch vụ ngoài. Browser review hiện là công cụ kiểm tra thủ công có hỗ trợ assertion, không tự khởi chạy/dừng các server hay trình duyệt.
