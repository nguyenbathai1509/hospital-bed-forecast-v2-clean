# Nghiệm thu toàn quy trình với backend thật

## Kết quả

**Đạt các kịch bản đã chạy** ngày 13/09/2026 trên SQL Server và FastAPI thật, với worker huấn luyện thật. Không thay thế các dịch vụ bằng mock, không rút gọn lưới siêu tham số hay bỏ LSTM.

| Bước | Kết quả quan sát |
| --- | --- |
| Tạo môi trường riêng | Database mới `HospitalBedForecastV2_E2E`, áp dụng đủ 11 migration |
| Xử lý dữ liệu ban đầu | Ngày 30/06/2026, 362 dòng RAW và CLEAN |
| Thêm ngày mới | Ngày 01/07/2026, RAW/CLEAN tăng lên 364 dòng |
| Huấn luyện nền | Tác vụ đi qua PENDING → RUNNING → COMPLETED, đủ RF/XGBoost/SVR/LSTM cho H+1 và H+3 |
| Đánh giá | Cả 8 mô hình có 74 dòng đánh giá test; ngày cuối tập test cập nhật thành 01/07/2026 |
| Chọn mô hình | Xem kế hoạch và xác nhận sử dụng cho cả hai mốc dự báo thành công |
| Xem thử dự báo | Không lưu bản nháp, dự báo chính thức hoặc bản ghi giám sát |
| Tạo bản nháp | Có 4 bản nháp cho 2 khoa × 2 mốc; gọi lại tái sử dụng, không tạo trùng |
| Xác nhận chính thức | Có đủ 4 dự báo chính thức |
| Chưa có dữ liệu thực tế | Giám sát báo cả 4 dự báo đang chờ dữ liệu thực tế |
| Thêm dữ liệu đến 04/07 | RAW/CLEAN tăng lên 370 dòng; cả 4 dự báo được đối chiếu với thực tế thử |
| Tính bất biến và chạy lại | Dự báo chính thức giữ nguyên; chạy lại nguồn giống hệt không tăng số dòng RAW/CLEAN, bản nháp, chính thức hoặc bản ghi đối chiếu |

Các ngày thêm vào là **dữ liệu tổng hợp giả lập**, liên tục theo ngày, cân đối số bệnh nhân và thống nhất giữa hai khoa. Không coi đây là số liệu thực tế tương lai của bệnh viện. Kết quả này kiểm chứng quy trình kỹ thuật, không chứng nhận chất lượng dự báo hay khả năng triển khai lâm sàng.

## Cách ly và kiểm tra bảo toàn

- `.env` chính giữ nguyên; database đang dùng vẫn là `HospitalBedForecastV2`.
- Sao chép mã nguồn và hai workbook vào thư mục thử; không sao chép `.env` hoặc kho mô hình vận hành.
- API/worker riêng nhận `V2_DB_NAME=HospitalBedForecastV2_E2E` qua môi trường tiến trình; đường dẫn module, thư mục làm việc và kho artifact đều thuộc bản sao.
- Kiểm tra `DB_NAME()` và marker token của database trước khi chạy. Không dùng lại, xóa hoặc ghi đè một database E2E có sẵn.
- Chỉ lắng nghe localhost:8013 trong khi thử; máy chủ thử đã dừng sau nghiệm thu.
- So sánh số dòng và hash nội dung **24 bảng** của database chính; so sánh SHA-256 **144 file** gồm Excel gốc, `.env` và kho mô hình gốc. Kết quả trước/sau: **không thay đổi**.

Database E2E và artifact thử được giữ lại để kiểm tra lại bằng chứng; không được tự động xóa. Không trỏ giao diện vận hành sang database này vì nó chứa dữ liệu giả lập.

## Vấn đề công cụ thử đã phát hiện và xử lý

Trong lần thêm ngày đầu, openpyxl lưu workbook có công thức nhưng không tính lại cache Excel, làm trống giá trị đọc của cột công suất ở 362 dòng lịch sử. Đây là lỗi chuẩn bị dữ liệu của công cụ thử, không phải lỗi tính công suất của project.

Đã sửa công cụ để đọc các giá trị Excel đã được tính sẵn (`data_only=True`) trước khi thêm ngày. Bản sao thử ban đầu được lưu lại, sau đó dựng lại workbook thử từ nguồn gốc và chạy lại pipeline. Kết quả:

- `ERROR=0`, `WARNING=0`, `CHECK=2` — hai CHECK là các vấn đề cân đối đã có trong nguồn gốc, không tự ý sửa số liệu nguồn.
- Hash các giá trị đặc trưng và nhãn huấn luyện không đổi sau sửa workbook (không tính ID/thời gian dựng/metadata phiên bản).
- Hash toàn bộ dự báo chính thức không đổi.
- Kiểm tra bảo toàn môi trường gốc lần nữa vẫn đạt.

Có kiểm thử hồi quy dùng workbook chứa công thức với cached value để tránh lặp lại lỗi này.

## Bằng chứng cục bộ

Thư mục lần chạy:

`reports/e2e_acceptance/20260913T032819Z_889fb246/`

- `manifest.json`: các bước, thời điểm, số lượng, kết quả cách ly và kiểm tra lại workbook.
- `runner.log`, `runner-error.log`, `api.log`: nhật ký nghiệm thu/API.
- `protected_before.json`, `protected_after.json`: số dòng và hash, không lưu nội dung từng dòng của database chính.
- `project/reports/training_jobs/`: nhật ký worker thật.
- `project/models/registry/`: artifact mô hình thử.
- `fixture_before_repair/`: bản sao workbook trước khi khắc phục cache công thức.

Mã tác vụ: `TJOB_20260913T032917Z_8E687B3E`.

Mã huấn luyện: `TRN_20260913T032920Z_48937BF0`.

Thư mục reports không được đưa vào Git. Không tải bằng chứng hoặc workbook lên dịch vụ bên ngoài.

## Công cụ nghiệm thu

`scripts/run_e2e_acceptance.py` là công cụ **có thao tác ghi vào database thử**, không thuộc bộ pytest mặc định. Chỉ chạy khi có chủ ý tạo môi trường thử.

```powershell
python -m scripts.run_e2e_acceptance prepare
python -m scripts.run_e2e_acceptance run --manifest <đường-dẫn-manifest-được-in-ra>
```

`prepare` sẽ từ chối nếu database `HospitalBedForecastV2_E2E` đã tồn tại. Vì database lần này được giữ lại, không chạy lại lệnh này và không tự xóa database để vượt qua kiểm tra. Cần thống nhất một môi trường mới hoặc quy trình dọn môi trường thử trước lần nghiệm thu kế tiếp.

Lệnh `verify-fixture` phục vụ kiểm tra lại workbook của lần nghiệm thu đầu, chỉ chấp nhận manifest đã hoàn tất và chưa thực hiện bước này. Nó không huấn luyện lại hoặc thay artifact.

Kiểm tra guard mà không ghi SQL:

```powershell
python -m pytest tests/test_e2e_acceptance_guards.py -q
python -m pytest -q
```

## Chưa bao phủ

- Luồng trực tiếp từ HIS hoặc nguồn dữ liệu bệnh viện khác Excel.
- Tải đồng thời nhiều người dùng, vận hành kéo dài và khôi phục sau mất điện/mất SQL ở môi trường thật.
- Mọi kiểu dữ liệu đầu vào lỗi, mọi nhánh rollback hoặc thay mô hình đồng thời trong lần nghiệm thu này; một số nhánh có bộ kiểm thử giả lập riêng.
- Độ chính xác trên dữ liệu thực tế ngoài mẫu thử và chất lượng trải nghiệm trình duyệt trong tải lớn.
