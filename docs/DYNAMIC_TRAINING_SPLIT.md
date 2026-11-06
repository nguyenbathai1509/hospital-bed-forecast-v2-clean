# Chia tập huấn luyện theo dữ liệu mới

Tiếp nối: [Backtest chung cho khuyến nghị mô hình](COMMON_WINDOW_BACKTEST.md) đã bổ sung so sánh trên cùng cửa sổ và kỳ kiểm chứng riêng. Các giới hạn bên dưới mô tả phạm vi của đợt sửa chia tập đầu tiên.

Đợt sửa 1 (12/09/2026): training contract `v2.1`.

## Quy tắc

- Mốc cuối test lấy từ `max(target_date)` của các mẫu đã có actual, không lấy ngày trên máy.
- Mặc định giữ test 37 ngày và validation 28 ngày như thí nghiệm V2 ban đầu; train gồm các mẫu trước validation.
- Chia theo ngày lịch, trên trục `target_date`, không shuffle; các cửa sổ liên tiếp và không chồng lấn.
- Toàn bộ mô hình và horizon trong một run sử dụng cùng một `TemporalSplitSpec`.
- Kiểm tra các tập không rỗng trước khi tạo training run và artifact. Không tự rút ngắn cửa sổ khi thiếu dữ liệu.

| Dữ liệu cuối | Train kết thúc | Validation | Test |
| --- | --- | --- | --- |
| 30/06/2026 | 26/04/2026 | 27/04–24/05/2026 | 25/05–30/06/2026 |
| 31/08/2026 | 27/06/2026 | 28/06–25/07/2026 | 26/07–31/08/2026 |

`TemporalSplitSpec.ending_at()` có thể nhận độ dài khác khi được cấu hình bằng mã. Giao diện hiện dùng mặc định trên; các độ dài này giữ tương thích thí nghiệm, không phải kết luận rằng đây là lựa chọn tối ưu cho mọi bộ dữ liệu.

## Lưu và tái lập

Mốc ngày thực tế được lưu trong `training_runs.split_spec_json`, metadata của các candidate và bundle LSTM mới. Replay đọc mốc đã lưu, không tính lại theo dữ liệu/ngày hiện tại. Các run cũ tiếp tục dùng mốc lịch sử; không tự huấn luyện lại hay thay artifact cũ. `SPLIT_SPEC` cố định còn được giữ làm mặc định tương thích cho hàm chia tập/replay cũ; luồng huấn luyện mới truyền spec đã tính tường minh.

Replay tính số ngày test từ spec đã lưu, kiểm tra đủ ngày cho mỗi khoa và từ chối dòng trùng. Việc tái sử dụng job kiểm tra số dòng đánh giá theo từng candidate/khoa so với `model_metrics_by_department.sample_count`, thay vì mặc định 592 dòng. Evidence đã có nhưng không đầy đủ sẽ báo lỗi và được giữ nguyên để điều tra.

Replay vẫn yêu cầu dữ liệu/features tương ứng với phiên bản của run. Cơ chế này không tạo kho snapshot lịch sử: nếu dữ liệu nguồn đã thay phiên bản mà evidence chưa được lưu, replay sẽ từ chối như trước.

## Giới hạn còn lại

- Đây là chia tập theo cửa sổ dịch theo thời gian, chưa phải backtest nhiều cửa sổ.
- Guardrail `SAME_EVALUATION_WINDOW` được giữ. Candidate và champion có mốc khác nhau không được coi là so sánh tương đương; cần đánh giá chung trong bước backtest tiếp theo.
- Các script `verify_v2_*` cũ là kiểm chứng bộ dữ liệu thí nghiệm gốc, có thể vẫn chứa mốc/count cố định; không dùng chúng làm tiêu chí duy nhất cho dữ liệu mới.
- Lượt sửa này không thay chính sách lựa chọn mô hình, phân quyền hoặc recovery worker.

## Kiểm thử

`python -m pytest tests/test_dynamic_training_split.py tests/test_training_split.py tests/test_evaluation_replay.py tests/test_training_job_evaluation_auto.py tests/test_acceptance_v2_21_evaluation_dynamic_departments.py -q`

Bao gồm mốc lịch sử, dữ liệu mới, năm nhuận, dữ liệu thiếu, cửa sổ sai, replay dài 30 ngày, train/replay RF thực với grid nhỏ, luồng service truyền/lưu cùng spec cho 8 mô hình, LSTM dùng model giả để kiểm tra ranh giới tập, và số dòng evidence theo khoa/candidate. Không chạy huấn luyện đầy đủ hoặc ghi vào cơ sở dữ liệu vận hành.
