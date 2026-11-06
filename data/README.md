# Nguồn dữ liệu Excel

Không commit hoặc tải dữ liệu xuất từ bệnh viện lên dịch vụ công khai.

API hiện đọc cố định hai file trong thư mục `data` của project chạy backend:

- `HSNoi.xlsx`
- `hsNgoai.xlsx`

Sheet: `Export Worksheet`. Giữ đầy đủ lịch sử và đúng 16 cột theo [source contract](../src/contracts.py); cập nhật ngày mới đồng bộ cho cả hai khoa. Nếu dùng công thức, lưu kết quả đã tính bằng Excel trước khi nhập; openpyxl không tự tính công thức.

Thay file không tự chạy pipeline. Xem [quy trình cập nhật và kiểm tra dữ liệu](../docs/OPERATIONS.md) trước khi thao tác; giao diện chưa hỗ trợ upload/chọn đường dẫn nguồn.
