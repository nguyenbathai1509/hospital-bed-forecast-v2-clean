# Cài đặt và chạy trên Windows

Hướng dẫn hiện hành, đối chiếu mã nguồn ngày 13/09/2026. Chạy các lệnh PowerShell tại thư mục gốc project. Không cần kích hoạt môi trường ảo vì các lệnh gọi trực tiếp Python trong `.venv`.

## 1. Chuẩn bị môi trường

Môi trường đã dùng để kiểm chứng là Windows với Python 3.12 và SQL Server 2022. SQL Server phải được cài/chạy riêng; lệnh cài thư viện Python không cài SQL Server.

| Thành phần | Cấu hình mẫu |
| --- | --- |
| SQL Server | `localhost:1434` trong `.env.example` |
| Database vận hành | `HospitalBedForecastV2`, schema `dbo` |
| FastAPI | `127.0.0.1:8000` |
| Streamlit | `127.0.0.1:8501` |
| Database thử đã nghiệm thu | `HospitalBedForecastV2_E2E`, không dùng vận hành |

Cổng SQL phải khớp máy của bạn. Mẫu `.env.example` dùng 1434, trong khi mặc định của mã cấu hình khi thiếu biến là 1433.

Chỉ tạo môi trường ảo nếu chưa có; không nâng cấp thư viện trong lúc worker đang huấn luyện:

```powershell
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.12 -m venv .venv
}
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` đã gộp đầy đủ thư viện dữ liệu, SQL, API, giao diện, RF/XGBoost/SVR/LSTM và kiểm thử. Lệnh này cài cả TensorFlow; không cần cài lại môi trường đang hoạt động chỉ vì gộp file.

## 2. Cấu hình đúng database

Tạo `.env` từ mẫu nếu chưa có, không ghi đè cấu hình hiện hữu:

```powershell
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
notepad .env
```

Điền đúng host, port, tên database, tài khoản và mật khẩu SQL cục bộ. Không giữ mật khẩu mẫu `CHANGE_ME_LOCALLY`, không gửi nội dung `.env` cho người khác. Backend dùng `pymssql`; biến môi trường đã đặt trong terminal được ưu tiên hơn `.env`.

Kiểm tra đích kết nối mà không in mật khẩu:

```powershell
.venv\Scripts\python.exe -c "from src.config import settings; print({'host': settings.db_host, 'port': settings.db_port, 'database': settings.db_name})"
```

Nếu thấy database E2E hoặc cổng không mong muốn, sửa cấu hình trước khi chạy bất kỳ thao tác ghi nào.

## 3. Kiểm tra SQL và chuẩn bị schema

Nếu database đã tồn tại, lệnh sau chỉ đọc tên database thực tế; lỗi kết nối cần được xử lý trước:

```powershell
.venv\Scripts\python.exe -c "from src.db.engine import create_sql_engine; from sqlalchemy import text; e=create_sql_engine(); c=e.connect(); print(c.execute(text('SELECT DB_NAME()')).scalar()); c.close(); e.dispose()"
```

**Lệnh dưới có ghi database**, không phải lệnh chẩn đoán. Chỉ dùng khi chủ động khởi tạo/nâng cấp đúng môi trường: nó tạo database nếu thiếu và áp dụng các migration chưa được ghi nhận (hiện có 001–011). Với database đang sử dụng, sao lưu và để các worker kết thúc trước khi nâng cấp; không cần chạy lại mỗi lần mở ứng dụng.

```powershell
.venv\Scripts\python.exe -m scripts.setup_db
```

Nếu chỉ bổ sung heartbeat vào hệ thống cũ, xem [hướng dẫn migration 011](TRAINING_JOB_RECOVERY.md) và công cụ có kiểm tra tác vụ đang chạy. Không dùng `scripts.setup_db --help` để xem trợ giúp: script này không có bộ phân tích tùy chọn và vẫn thực thi.

## 4. Khởi động API và giao diện

Terminal 1, giữ cửa sổ này để theo dõi API:

```powershell
$env:V2_DEMO_RESET_ENABLED = 'false'
.venv\Scripts\python.exe -m scripts.run_api --host 127.0.0.1 --port 8000
```

Terminal 2, cũng tại thư mục gốc project:

```powershell
$env:V2_API_BASE_URL = 'http://127.0.0.1:8000'
$env:V2_UI_REQUEST_TIMEOUT_SECONDS = '30'
.venv\Scripts\python.exe -m scripts.run_dashboard
```

Mở `http://127.0.0.1:8501`. Không dùng `--reload` cho API trong vận hành có worker huấn luyện.

**Giao diện không tự đọc `.env`.** `app/config.py` chỉ đọc biến môi trường; muốn đổi API đích/timeout, đặt biến trong terminal chạy giao diện rồi khởi động lại. Giao diện gọi API, không tự chọn SQL database.

Nếu cần cổng khác, đổi `--port` khi chạy API và đặt `V2_API_BASE_URL` tương ứng. Script dashboard cố định cổng 8501; để đổi cổng giao diện, gọi Streamlit trực tiếp:

```powershell
.venv\Scripts\python.exe -m streamlit run app/dashboard.py --server.address 127.0.0.1 --server.port 8511
```

Không dùng `scripts.run_dashboard --help` như một lệnh kiểm tra: script vẫn khởi động giao diện. Hiện chưa triển khai phân quyền; giữ địa chỉ loopback như trên, không mở dịch vụ trực tiếp ra Internet.

## 5. Kiểm tra sau khởi động

Hai yêu cầu sau chỉ đọc; điều chỉnh cổng nếu đã đổi API:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/data/status'
```

`/health` chỉ chứng minh API phản hồi, không kiểm tra SQL. `/data/status` truy vấn database; `NO_DATA_READY` là trạng thái hợp lệ khi chưa có dữ liệu sẵn sàng. Xem cả lịch sử pipeline vì endpoint này lấy lần `DATA_READY` gần nhất, không nhất thiết là lần chạy gần nhất.

Đặt hai workbook trong thư mục `data` của project **đang chạy API**. Giao diện chưa có chức năng tải lên/chọn đường dẫn nguồn. Làm tiếp theo [quy trình vận hành](OPERATIONS.md).

## 6. Dừng, khởi động lại và kiểm thử

- Nhấn `Ctrl+C` trong terminal giao diện/API tương ứng để dừng chúng. Worker huấn luyện chạy riêng có thể vẫn tiếp tục sau khi API dừng; kiểm tra tác vụ và để worker kết thúc trước khi bảo trì database hoặc thay thư viện.
- Đổi `.env` backend cần khởi động lại API; đổi biến cấu hình giao diện cần khởi động lại giao diện. Chỉ đổi CSS/giao diện không cần chạy lại pipeline, huấn luyện hoặc reset database.
- Kiểm thử mặc định: `.venv\Scripts\python.exe -m pytest -q`. Không bật `TRAINING_SQL_TESTS=1` nếu không chủ định chạy kiểm thử SQL tùy chọn.
- Công cụ [nghiệm thu E2E](E2E_ACCEPTANCE.md) có tạo/ghi database thử, không phải lệnh kiểm tra sức khỏe hằng ngày. Không xóa database thử đã giữ lại chỉ để chạy lại công cụ.
- Các script `verify_v2_*` cũ có thể chứa ngày/số dòng cố định của thí nghiệm cũ; không dùng làm tiêu chí duy nhất cho dữ liệu mới.
