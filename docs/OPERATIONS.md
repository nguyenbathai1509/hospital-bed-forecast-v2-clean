# Quy trình vận hành

Đối chiếu mã nguồn ngày 13/09/2026. Tài liệu này mô tả hành vi hiện tại, không thay đổi quy tắc nghiệp vụ. Xem [hướng dẫn Windows](WINDOWS_QUICKSTART.md) để cài đặt và kết nối.

## 1. Trước khi thao tác

- Kiểm tra API đích ở thanh bên và database backend theo hướng dẫn Windows. Không dùng database `HospitalBedForecastV2_E2E` chứa dữ liệu giả lập để vận hành.
- Lưu bản sao nguồn Excel trước khi thay; với thao tác bảo trì/nâng cấp, chuẩn bị bản sao database và artifact mô hình tương ứng. Có thư mục backup không đồng nghĩa đã kiểm chứng khôi phục thành công.
- Để `V2_DEMO_RESET_ENABLED=false`. Đặt lại trình diễn không phải cách làm mới màn hình hay sửa lỗi dữ liệu.

## 2. Khi có dữ liệu mới

### Chuẩn bị Excel

Nguồn API hiện cố định tại `data/HSNoi.xlsx` và `data/hsNgoai.xlsx` của project chạy backend. Giao diện chưa có tải lên file, chọn đường dẫn hoặc kết nối trực tiếp HIS. Giữ dữ liệu lịch sử, bổ sung ngày mới cho cả hai khoa và kiểm tra ngày cuối khớp nhau; không chỉ thay bằng một file chứa riêng ngày mới.

Sheet phải là `Export Worksheet`, với 16 cột theo thứ tự trong [source contract](../src/contracts.py):

```text
NGAY
THU
THANG
ID_KHOA
MA_KHOA
TEN_KHOA
SO_GIUONG_KE_HOACH
BN_DAU_NGAY
SO_BN_NHAP_VIEN
SO_BN_CHUYEN_DEN
SO_BN_RA_VIEN
SO_BN_CHUYEN_DI
BN_CUOI_NGAY
SO_GIUONG_DANG_SU_DUNG
TRANG_THAI_CAN_DOI
CONG_SUAT_GIUONG
```

Kiểm tra thiếu ngày, trùng khoa/ngày, kiểu dữ liệu và cân đối số bệnh nhân. Không tự đổi số liệu để làm biến mất cảnh báo; xác minh với nguồn rồi mới sửa. Nếu workbook dùng công thức, cần lưu kết quả đã tính bằng Excel trước khi nhập: thư viện openpyxl không tự tính lại công thức, cache trống có thể làm giá trị đọc bị thiếu.

### Chạy pipeline và kiểm tra kết quả

1. Mở trang **Dữ liệu**, kiểm tra hướng dẫn/xác nhận rồi chạy pipeline.
2. Đọc kết quả và lịch sử lần chạy mới nhất; kiểm tra ngày nghiệp vụ, số dòng, lỗi và cảnh báo chất lượng.
3. Chỉ tiếp tục với ngày mong muốn đã đạt `DATA_READY`. Khi `WAITING` hoặc `FAILED`, xử lý nguyên nhân trước, không xem trạng thái sẵn sàng cũ là bằng chứng dữ liệu mới đã được nhận.

`/data/status` lấy lần **DATA_READY gần nhất**, nên có thể vẫn hiển thị ngày cũ sau một lần chạy mới thất bại. Luôn đối chiếu với lịch sử pipeline và ngày nguồn.

Pipeline xử lý RAW → kiểm tra chất lượng → CLEAN → đặc trưng/mẫu học; đồng thời xử lý mô hình đã lên lịch đến kỳ và đối chiếu dự báo chính thức với actual nếu đủ dữ liệu. Pipeline **không tự huấn luyện, tạo bản nháp hoặc xác nhận dự báo chính thức**. Không có bộ theo dõi file/lịch tự động chạy các bước này.

Chạy lại cùng nguồn có thể thêm lịch sử/audit của lần chạy, nhưng không được hiểu là phải sinh thêm các bản ghi nghiệp vụ trùng. Không bấm chạy liên tục khi giao diện timeout: xem trạng thái và lịch sử trước.

## 3. Huấn luyện và đọc kết quả

Không bắt buộc huấn luyện mỗi lần thêm ngày; có thể tiếp tục dùng mô hình đang hoạt động. Khi chủ động cần mô hình mới:

1. Mở **Huấn luyện mô hình**, kiểm tra `DATA_READY` và ngày dữ liệu, rồi nhấn **Bắt đầu huấn luyện**.
2. Theo dõi `job_id`, trạng thái và thông báo. Dùng **Cập nhật trạng thái** để đọc lại; không suy luận phần trăm tiến độ từ thời gian chờ.
3. Khi hoàn tất, mở **Kết quả huấn luyện** để kiểm tra đủ RF/XGBoost/SVR/LSTM cho H+1/H+3, ngày chia tập, chỉ số theo khoa và bằng chứng đánh giá.

Mốc cuối test lấy từ `max(target_date)` của mẫu đã có actual, không lấy ngày đồng hồ máy. Mặc định validation 28 ngày, test 37 ngày, phần trước đó dùng train; cùng một cách chia theo thời gian cho tám mô hình, không shuffle và không tự rút ngắn cửa sổ nếu thiếu dữ liệu. Xem [chia tập động](DYNAMIC_TRAINING_SPLIT.md) và [đánh giá chung cửa sổ](COMMON_WINDOW_BACKTEST.md).

Tác vụ còn hoạt động được tái sử dụng. Recovery chỉ chạy khi gửi yêu cầu bắt đầu huấn luyện: tác vụ PENDING hoặc RUNNING mất heartbeat quá 120 giây có thể được chuyển FAILED, lần thử lại có ID mới. Chỉ cập nhật trạng thái không kích hoạt recovery. Heartbeat mỗi 15 giây không chứng minh phép fit đang tiến triển; hiện chưa có timeout toàn bộ phép fit.

Xem log tại `reports/training_jobs/<job_id>.log` và [quy tắc recovery](TRAINING_JOB_RECOVERY.md). Không tự sửa trạng thái SQL hay xóa artifact để ép chạy lại. Nếu sửa dữ liệu trong cùng ngày đã có run hoàn tất, kiểm tra phản hồi/lineage: cơ chế tái sử dụng có thể trả `ALREADY_COMPLETED`, không mặc định coi đó là huấn luyện lại trên phiên bản dữ liệu vừa sửa.

## 4. Chọn mô hình sử dụng

Trong **Quản lý mô hình**, đọc khuyến nghị và kế hoạch trước khi xác nhận. Phân biệt mô hình được khuyến nghị, đang hoạt động, đã lên lịch và trạng thái khóa; một khuyến nghị không đồng nghĩa đã trở thành mô hình đang dùng.

- Đưa mô hình vào sử dụng: kiểm tra horizon, candidate, thời điểm có hiệu lực và nhập đúng `I_CONFIRM_PROMOTION` khi muốn xác nhận.
- Hạn mức thay mô hình được xét theo từng horizon/ngày. Nếu bị khóa, đọc kế hoạch để biết có thể lên lịch kỳ tiếp theo hay bị chặn; không liên tục gửi lại để vượt hạn mức.
- Hoàn tác khẩn cấp: xem kế hoạch và mô hình đích, chỉ xác nhận `I_CONFIRM_EMERGENCY_ROLLBACK` khi thực sự cần. Không dùng rollback như thao tác thử.

## 5. Lập dự báo

Trong **Dự báo**, kiểm tra ngày gốc, khoa, horizon và mô hình sử dụng. Ngày đích bằng ngày gốc cộng horizon.

| Thao tác | Ý nghĩa |
| --- | --- |
| Xem thử | Không lưu bản nháp/chính thức; không đưa vào giám sát |
| Tạo bản nháp dự báo | Tạo hoặc tái sử dụng bản nháp để kiểm tra |
| Xác nhận chính thức | Lưu dự báo chính thức bất biến, dùng cho đối chiếu actual |

**Xác nhận chính thức áp dụng cho toàn bộ bản nháp thuộc ngày gốc được chọn**, không chỉ khoa/horizon đang xem. Kiểm tra đầy đủ trước khi nhập `I_CONFIRM_OFFICIAL`. Không thể dùng việc tạo lại bản nháp để ghi đè dự báo chính thức.

Khoảng dự báo tham khảo chỉ được tính khi yêu cầu; thiếu dữ liệu hiệu chỉnh là trạng thái có thể gặp. Không diễn giải khoảng này thành cam kết bao phủ 90% trên dữ liệu tương lai. Xem [baseline và uncertainty](BASELINES_AND_UNCERTAINTY.md).

## 6. Khi có actual và theo dõi chất lượng

Bổ sung Excel đến ngày đích, chạy lại pipeline rồi mở **Giám sát**. Chỉ dự báo chính thức được đối chiếu; `WAITING_FOR_ACTUAL` hợp lệ nếu chưa có thực tế tương ứng. Có thể chủ động chạy lại giám sát qua giao diện; thao tác này ghi/cập nhật kết quả giám sát, không chỉ làm mới màn hình.

Theo dõi sai số theo khoa/horizon và ngày dữ liệu. Hệ thống chưa tự kết luận suy giảm mô hình hoặc tự yêu cầu huấn luyện lại dựa trên drift. Không xem việc pipeline chạy thành công là bằng chứng mô hình dự báo chính xác.

## 7. Tra cứu sự cố

| Hiện tượng | Kiểm tra trước khi thử lại |
| --- | --- |
| Giao diện không kết nối | API đã chạy chưa, địa chỉ/cổng ở thanh bên có đúng không; UI đọc biến môi trường terminal, không tự đọc `.env` |
| `/health` tốt nhưng trang dữ liệu lỗi | `/health` không kiểm tra SQL; kiểm tra kết nối database, tên database và migration |
| Timeout hoặc phản hồi không phải JSON | Kiểm tra API đích, terminal API và lịch sử tác vụ; thao tác ghi có thể đã hoàn tất dù UI chưa nhận kết quả |
| `NO_DATA_READY` | Kiểm tra đúng database, nguồn Excel và kết quả pipeline; không reset để chữa trạng thái này |
| Ngày dữ liệu vẫn cũ | Đối chiếu lịch sử mới nhất, ngày cuối hai khoa và readiness; có thể đang hiển thị lần DATA_READY trước |
| Cột công suất thiếu sau sửa workbook | Kiểm tra cached value của công thức; tính/lưu bằng Excel, không tự thay bằng số suy đoán |
| Nút bị vô hiệu hóa | Đọc điều kiện trên trang: dữ liệu, trạng thái tác vụ, mô hình, kế hoạch hoặc nội dung xác nhận còn thiếu |
| Huấn luyện chờ lâu | Kiểm tra log/heartbeat; LSTM có thể lâu. Chỉ yêu cầu bắt đầu lại sau khi hiểu trạng thái; recovery không có nghĩa tiếp tục fit từ checkpoint |
| Không import được thư viện ML | Kiểm tra đủ hai nhóm requirements ML và API chạy bằng Python trong `.venv`; không cài đè khi worker còn chạy |

## 8. Bảo trì và giới hạn

Giữ đồng bộ bản sao database, nguồn Excel, cấu hình được bảo vệ và `models/registry` để có thể truy vết/khôi phục mô hình. Giữ log/evidence cần thiết trước khi dọn dung lượng; hiện chưa có luân chuyển log tự động. Không xóa mô hình cũ chỉ vì nó không còn được chọn: dự báo lịch sử có thể vẫn tham chiếu đến nó.

Trước nâng cấp, ngừng gửi tác vụ mới và để worker kết thúc. Dừng API không đảm bảo worker riêng đã dừng. Sao lưu/khôi phục đầy đủ, thử tải nhiều người dùng và vận hành dài hạn vẫn cần nghiệm thu riêng; tài liệu này không chứng nhận đã thực hiện chúng.

Chức năng **Đặt lại trình diễn có thể xóa dữ liệu vận hành**, mặc định tắt. Không bật để xử lý lỗi kết nối, làm mới CSS, cập nhật Excel hay chạy kiểm thử. Muốn thử toàn quy trình, dùng môi trường cách ly theo [báo cáo E2E](E2E_ACCEPTANCE.md); không dùng bản thử thay cho môi trường chính.

Các tài liệu `V2-11_*` và `README_V2_*` giữ lại lịch sử từng giai đoạn. Khi có mốc/count hoặc giới hạn khác với hướng dẫn này, đối chiếu mã nguồn và tài liệu kỹ thuật hiện hành, không tự sửa dữ liệu để khớp thí nghiệm cũ.
