# Đo và tối ưu hiệu năng giao diện

## Phương pháp đo

Đo ngày 13/09/2026 trên máy phát triển, gọi FastAPI thật ở localhost và chỉ đọc dữ liệu đang có. Không chạy pipeline, huấn luyện, thay đổi mô hình, xác nhận dự báo hay đặt lại dữ liệu.

Công cụ `scripts/profile_ui.py` chạy từng trang bằng Streamlit AppTest. Mỗi trang có một lần tải đầu và ba lượt chạy lại; bảng dưới dùng **trung vị ba lượt chạy lại**. Thời gian bao gồm thực thi Python của trang, chuẩn bị client/kết nối, gọi API và tạo dữ liệu giao diện; **không bao gồm trình duyệt vẽ giao diện hoặc truyền WebSocket đến trình duyệt**. Không phải kiểm thử tải nhiều người dùng.

Đợt đo dùng lựa chọn mặc định của từng trang trên cùng bộ dữ liệu. Trang Dự báo đang có dự báo chính thức; trang Huấn luyện chưa chọn tác vụ trong phiên. Các nhánh khác có thể có số yêu cầu khác. Không suy rộng các con số này thành cam kết cho mọi máy, dữ liệu hoặc mạng.

## Kết quả trước/sau

| Trang | Trước (ms) | Sau (ms) | Giảm thời gian | Số yêu cầu API trước → sau |
| --- | ---: | ---: | ---: | ---: |
| Tổng quan | 1.149,35 | 323,10 | 71,9% | 6 → 6 |
| Dữ liệu | 1.001,48 | 346,32 | 65,4% | 5 → 5 |
| Huấn luyện | 376,67 | 221,19 | 41,3% | 2 → 2 |
| Kết quả huấn luyện | 894,44 | 391,47 | 56,2% | 4 → 4 |
| Quản lý mô hình | 511,44 | 232,39 | 54,6% | 2 → 2 |
| Dự báo | 953,77 | 282,10 | 70,4% | 5 → 4 |
| Giám sát | 379,67 | 219,10 | 42,3% | 2 → 2 |
| Đặt lại trình diễn (chỉ xem) | 219,49 | 214,92 | 2,1% | 1 → 1 |

Không thấy lời gọi trùng **cùng phương thức, đường dẫn và tham số trong một lượt tải mặc định**. Việc đọc lại trạng thái ở lượt tải tiếp theo là cần thiết để tránh thông tin lỗi thời, không được xem là lỗi gọi lặp.

Báo cáo mẫu lưu cục bộ tại `reports/ui_performance/before.json` và `after.json`; thư mục reports được bỏ qua bởi Git. Công cụ không ghi nội dung phản hồi, tham số truy vấn, ngày dữ liệu hay mã lần huấn luyện vào báo cáo.

## Điểm nghẽn và thay đổi

### 1. Chi phí tạo lại HTTP client

Trước đây mỗi lời gọi API tạo một `httpx.Client` mới. Phép đo cProfile riêng cho năm yêu cầu `/health` tốn khoảng 1,196 giây; trong đó khoảng 1,115 giây nằm ở khởi tạo HTTP client, phần lớn là nạp chứng chỉ vào SSL context.

`HospitalApiClient.request_scope()` nay tái sử dụng một HTTP client trong một lượt render trang. HTTPX có thể tái sử dụng kết nối cho các yêu cầu trong lượt đó. `dashboard.py` bao quanh phần render bằng scope này.

- Không cache phản hồi API, không giảm bước kiểm tra kế hoạch xác nhận.
- Không giữ kết nối hoặc cookie giữa các lượt render/người dùng. `ContextVar` tách client theo ngữ cảnh thực thi; `finally` đặt lại ngữ cảnh và context manager đóng client cả khi lỗi hoặc `st.rerun()`/`st.stop()` ngắt lượt chạy.
- Scope lồng nhau dùng cùng kết nối và chỉ scope ngoài đóng nó.
- Các lời gọi ngoài scope vẫn dùng client ngắn hạn như trước.
- Không tắt kiểm tra chứng chỉ TLS, không thay timeout và không thêm retry tự động cho thao tác ghi.

### 2. Không tải dữ liệu tùy chọn quá sớm

- Trang Dự báo chỉ gọi `/models` khi chọn **Tự chọn mô hình** để xem thử; gửi thêm bộ lọc `horizon` tới API. Chế độ khuyến nghị/đang sử dụng không cần tải danh sách này. Nếu danh sách mô hình lỗi, phần dự báo chính thức vẫn được giữ trên màn hình.
- Trang Kết quả huấn luyện chỉ tải danh sách khoa khi đã có lần huấn luyện hoàn tất cần hiển thị.
- Dữ liệu dự báo, trạng thái huấn luyện và kế hoạch xác nhận vẫn được đọc mới theo luồng hiện có.

## Chạy lại phép đo

Khởi động API riêng ở localhost, sau đó từ thư mục gốc dự án:

```powershell
python -m scripts.profile_ui --base-url http://127.0.0.1:8011 --output reports/ui_performance/latest.json
```

Có thể chọn số mẫu và trang:

```powershell
python -m scripts.profile_ui --base-url http://127.0.0.1:8011 --repeats 5 --pages overview forecast
```

Các đường dẫn đọc được liệt kê rõ trong công cụ. Mọi thao tác không nằm trong danh sách bị chặn trước khi gửi HTTP, kể cả huấn luyện, xem thử dự báo và xác nhận chính thức. Ngoại lệ POST duy nhất là yêu cầu đọc kế hoạch `/forecasts/official/confirm` **không có trường confirmation**, theo hợp đồng đọc của API hiện tại. Công cụ không bấm nút nghiệp vụ.

Công cụ trả mã thoát khác 0 nếu có lỗi API hoặc ngoại lệ trang. Nó không tự khởi động/dừng máy chủ. `api_ms` tính cả chi phí khởi tạo scope; báo cáo cũng tách riêng `scope_setup_ms` và thời gian từng lời gọi.

## Kiểm thử hồi quy

```powershell
python -m pytest tests/test_ui_request_scope.py tests/test_ui_profiler.py tests/test_ui_workflow.py tests/test_ui_api_client.py -q
python -m pytest -q
```

Kiểm thử bao phủ: một client mỗi lượt render, phản hồi luôn mới, đóng client khi ngắt render, scope lồng nhau, timeout không tự retry, cách ly cookie khi hai lượt render đồng thời, danh sách mô hình tải theo nhu cầu và chặn thao tác ghi trong công cụ đo. Các kiểm thử này dùng MockTransport hoặc dịch vụ giả lập, không ghi vào cơ sở dữ liệu vận hành.

Phần chưa đo ở đợt này: thời gian trình duyệt thực sự hiển thị, mạng từ máy người dùng tới máy chủ và tải đồng thời nhiều người dùng. Chỉ nên tối ưu thêm backend/cache sau khi có phép đo tương ứng.
