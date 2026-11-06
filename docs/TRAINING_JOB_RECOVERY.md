# Phục hồi tác vụ huấn luyện bị ngắt

## Luồng hoạt động

1. Khi nhận yêu cầu bắt đầu, hệ thống kiểm tra DATA_READY và phục hồi tác vụ hết hạn trong cùng giao dịch trước khi tìm tác vụ có thể tái sử dụng.
2. RUNNING mất heartbeat quá 120 giây được chuyển FAILED. PENDING chưa được worker nhận sau 120 giây cũng được chuyển FAILED. Nếu heartbeat chưa có (worker cũ), dùng started_at để kiểm tra.
3. Tác vụ còn hoạt động được tái sử dụng; tác vụ FAILED giữ nguyên để tra cứu và lần thử lại có job_id mới. Không sửa kết quả của tác vụ COMPLETED.
4. Worker nhận PENDING bằng cập nhật có điều kiện, khởi chạy heartbeat mỗi 15 giây trên luồng và kết nối riêng. Lỗi kết nối tạm thời được ghi log; vòng heartbeat tiếp tục thử ở nhịp sau.
5. Khi tạo training run, liên kết run_id với job ngay trong cùng giao dịch. Phục hồi chỉ chuyển run liên kết đang RUNNING sang FAILED, không thay đổi run đã COMPLETED.
6. Mỗi giao dịch ghi của Training, Recommendation và Evaluation phải kiểm tra job còn RUNNING bằng khóa UPDLOCK/HOLDLOCK. Khóa được giữ đến commit/rollback, không giữ trong quá trình fit mô hình. Tiến trình cũ trả kết quả muộn không được ghi thêm vào registry, khuyến nghị, evaluation hoặc đổi job FAILED thành COMPLETED.
7. Heartbeat được yêu cầu dừng trong finally khi tác vụ thành công hoặc thất bại. Nếu lời gọi DB còn bị chặn, chỉ chờ tối đa 5 giây khi thu dọn; luồng daemon không giữ worker sống khi tiến trình chính kết thúc.

Trạng thái job là căn cứ quyền ghi. Job FAILED không bao giờ được hồi sinh; thử lại luôn tạo ID khác. Huấn luyện gọi trực tiếp từ CLI không có job context, giữ hành vi cũ.

## Phạm vi và giới hạn

- Phục hồi chạy khi có yêu cầu **BẮT ĐẦU HUẤN LUYỆN**, không có bộ quét định kỳ. Chỉ nhấn **CẬP NHẬT TRẠNG THÁI** vẫn là đọc trạng thái, không tự phục hồi.
- Heartbeat phát hiện worker ngừng hoạt động/mất kết nối, không chứng minh mô hình đang tiến triển. Một phép fit bị kẹt nhưng luồng heartbeat còn chạy chưa được coi là hết hạn. Chưa có timeout cho toàn bộ phép fit.
- Không cưỡng bức giết tiến trình đang fit. Khi mất quyền ghi, phép tính đang chạy có thể hoàn tất trước khi bị chặn tại giao dịch tiếp theo. Artifact chưa đăng ký có thể còn trong thư mục riêng của run; không xóa tự động và không ghi đè artifact Production.
- Nếu DB mất kết nối kéo dài quá ngưỡng, một worker vẫn đang tính có thể bị thu hồi khi người dùng thử lại. Khóa ghi ngăn kết quả muộn được công bố.
- Run cũ không có liên kết job/run không được suy đoán để đánh dấu FAILED; cần kiểm tra thủ công nếu có bản ghi mồ côi.
- Không đổi phép chia dữ liệu, mô hình, chỉ số, backtest hoặc quy tắc đưa mô hình vào Production.

## Nhật ký

Mỗi worker ghi stdout/stderr và log theo giai đoạn vào `reports/training_jobs/<job_id>.log`. Dùng chế độ append và Python unbuffered để giữ thông báo khi worker bị ngắt; đường dẫn chỉ chấp nhận ID hợp lệ, không lấy đường dẫn tùy ý từ người dùng. Thư mục reports và file log đã nằm trong quy tắc bỏ qua Git.

Nhật ký phục vụ vận hành cục bộ, không có API tải log. Hạn chế quyền đọc thư mục này; log lỗi có thể chứa chi tiết kỹ thuật của dữ liệu. Chưa tự luân chuyển/xóa log; cần quản lý dung lượng theo nhu cầu sử dụng.

## Cập nhật cơ sở dữ liệu

Migration `011_training_job_heartbeat_recovery.sql` chỉ thêm cột nullable `heartbeat_at`. Trước khi nâng cấp, dừng nhận yêu cầu mới và để worker cũ kết thúc; khởi động lại API bằng mã mới sau khi cập nhật.

Chạy trong môi trường ảo của project:

```powershell
python -m scripts.apply_training_job_heartbeat
```

Script chỉ áp dụng migration 011, không chạy migration khác; từ chối khi có PENDING/RUNNING, dùng giao dịch và khóa bảng trong lúc cập nhật, ghi nhận schema_migrations và có thể chạy lại. Không tạo lại database hay sửa dữ liệu huấn luyện/dự báo.

## Kiểm thử

```powershell
python -m pytest -q
```

Kiểm thử SQL Server dùng bảng tạm trên một kết nối riêng, không sửa bản ghi vận hành:

```powershell
$previousTrainingSqlTests = $env:TRAINING_SQL_TESTS
try {
    $env:TRAINING_SQL_TESTS = '1'
    python -m pytest tests/test_training_worker_recovery.py -q
} finally {
    $env:TRAINING_SQL_TESTS = $previousTrainingSqlTests
}
```

Bao gồm vòng đời heartbeat, mất kết nối tạm thời, worker trùng, kết quả muộn, ghi nhật ký, đường dẫn không hợp lệ, liên kết run và kiểm tra tất cả giao dịch ghi có hàng rào bảo vệ. Câu lệnh T-SQL phục hồi/claim/finalize được chạy thật trên bảng tạm; thứ tự khóa cạnh tranh có kiểm thử mô phỏng, chưa kiểm chứng tải nhiều worker đồng thời trên SQL Server. Không chạy huấn luyện đầy đủ với dữ liệu vận hành trong đợt sửa này.
