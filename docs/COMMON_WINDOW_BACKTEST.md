# Backtest chung cho khuyến nghị mô hình

Phần bổ sung: [bảng mô hình đối chiếu và khoảng bất định tham khảo](BASELINES_AND_UNCERTAINTY.md). Khoảng vận hành dùng sai số Official của đúng artifact, không lấy sai số cấu hình fit lại trong backtest.

Đợt sửa 2, ngày 12/09/2026. Phiên bản bằng chứng: `common-window-v1`.

## Luồng mới

Sau khi huấn luyện hoàn thành, bước tạo khuyến nghị tự thực hiện backtest cho từng horizon. Nó so sánh bốn cấu hình RF/XGBoost/SVR/LSTM của run mới với cấu hình champion đang dùng; khi chưa có Production, dùng mô hình tham chiếu bootstrap của run đó.

Các cấu hình (siêu tham số, số epoch LSTM) được giữ cố định. Mỗi cấu hình được fit lại trong bộ nhớ bằng cùng dữ liệu lịch sử trước từng cửa sổ đánh giá, với cùng seed của run mới. Đây là so sánh cấu hình khi được huấn luyện lại, **không phải đo trực tiếp chất lượng artifact Production hiện hành**. Không đọc/ghi đè artifact Production, không tạo Draft/Official, không cập nhật số liệu test gốc trong Model Registry.

## Thời gian và dữ liệu chưa được nhìn thấy

1. Cấu hình mới chỉ được xem là đã xác định sau ngày cuối validation của run mới.
2. Với champion thuộc run cũ, loại thêm mọi ngày cho đến hết dữ liệu của run cũ và hết test cũ, vì việc chọn champion có thể đã dùng kết quả test đó.
3. Target đầu tiên phải có origin không sớm hơn thời điểm xác định cấu hình. Với H+3, bỏ hai target nằm giữa mốc này và target đầu tiên hợp lệ.
4. Chừa **7 ngày cuối** làm kỳ kiểm chứng riêng; phần trước chia thành **3 cửa sổ liên tiếp**, mỗi cửa sổ ít nhất **7 ngày**.
5. Với mỗi cửa sổ, chỉ fit các nhãn `target_date <= first_target_date - horizon`. Lịch sử fit mở rộng giữa các cửa sổ, còn tham số/epoch không được điều chỉnh lại.
6. Mọi mô hình phải chấm đúng cùng ngày và cùng khoa. Dữ liệu thiếu, dòng trùng, phiên bản không khớp hoặc khoa không tương thích đều không được âm thầm bỏ qua.

Ví dụ run mới kết thúc **31/08/2026**, validation kết thúc **25/07/2026**, champion đã được xác định từ **30/06/2026**:

| Horizon | Cửa sổ 1 | Cửa sổ 2 | Cửa sổ 3 | Kiểm chứng riêng |
| --- | --- | --- | --- | --- |
| H+1 | 26/07–04/08 | 05/08–14/08 | 15/08–24/08 | 25/08–31/08 |
| H+3 | 28/07–06/08 | 07/08–15/08 | 16/08–24/08 | 25/08–31/08 |

Mô hình được fit một lần ở đầu mỗi cửa sổ, không fit lại mỗi ngày. Đặc trưng của từng dự báo vẫn lấy tại origin tương ứng. Thời điểm sẵn có của actual được giả định theo quy trình dữ liệu cuối ngày hiện tại của project.

## Khuyến nghị và kiểm chứng riêng

Xếp hạng dựa trên MAE gộp theo số mẫu của ba cửa sổ, với các quy tắc tie-break/guardrail hiện có. Champion cũng được chấm lại trên đúng tập này; `SAME_EVALUATION_WINDOW` và kiểm tra từng khoa tiếp tục áp dụng.

Quyết định được xác định **trước khi** đánh giá 7 ngày cuối. Kỳ này chỉ chấm cấu hình được khuyến nghị và champion, để báo cáo riêng; không đổi lựa chọn, không veto và không chọn lại theo MAE kiểm chứng. Nếu champion có MAE bằng 0, giữ champion và nêu rõ phần trăm cải thiện không xác định; không chia cho 0.

Nếu chưa có tối thiểu 28 ngày đánh giá chung hợp lệ (21 ngày so sánh + 7 ngày kiểm chứng), lưu `KEEP_INSUFFICIENT_COMMON_WINDOW`. Run huấn luyện vẫn có thể hoàn thành; không tuyên bố mô hình mới tốt hơn từ các cửa sổ khác nhau. Lỗi tính toán hoặc dữ liệu không hợp lệ khác vẫn báo lỗi để điều tra.

## Bằng chứng và tính tương thích

- Snapshot riêng nằm trong `model_recommendations.policy_json.comparison`, được lưu cùng recommendation/rankings trong transaction hiện có; không cần migration.
- Snapshot chứa mốc fit/chấm từng cửa sổ, seed, cấu hình, môi trường, code revision nếu có, data version/hash đầu vào, sai số tổng/theo khoa và dự báo từng dòng. Hash nhận diện snapshot đầu vào, không thay thế kho lưu trữ dữ liệu nguồn.
- Rankings của recommendation mới dùng backtest. Metrics test gốc của candidate và bảng `model_evaluation_predictions` giữ nguyên ý nghĩa lịch sử.
- Recommendation đã tồn tại được trả lại, không tự tính lại hoặc ghi đè. Vì vậy run cũ không tự xuất hiện báo cáo mới.
- Trước khi lưu, kiểm tra lại champion trong transaction có khóa để tránh công bố so sánh với một slot vừa thay đổi.
- Trang Kết quả huấn luyện hiển thị báo cáo backtest và kỳ kiểm chứng riêng, đồng thời ghi rõ các biểu đồ test gốc và bảng xếp hạng dùng nguồn nào.
- Khuyến nghị không tự kích hoạt Production; vẫn cần quy trình xác nhận đưa mô hình vào sử dụng.

## Giới hạn

Backtest dùng cấu hình cố định được chọn trước khoảng đánh giá; chưa triển khai nested tuning cho từng cửa sổ. Kỳ kiểm chứng là độc lập **trong một lần ra quyết định**, không phải tập holdout bị khóa vĩnh viễn qua tất cả lần huấn luyện. Ba cửa sổ và ngưỡng số ngày là chính sách ban đầu, không chứng minh khác biệt có ý nghĩa thống kê hoặc an toàn lâm sàng. Baseline đơn giản, khoảng bất định và giám sát chất lượng Production vẫn là các phần tiếp theo.

Chi phí huấn luyện tăng vì phải fit thêm các cấu hình đã chọn, đặc biệt với LSTM; không chạy lại grid search trong backtest. Dữ liệu/features hiện hành phải khớp data version của run mới. Không tạo snapshot nguồn hay sửa các hợp đồng kiến trúc LSTM đã tồn tại.

## Kiểm thử

`python -m pytest tests/test_common_window_backtest.py tests/test_ui_backtest_view.py tests/test_recommendation_engine.py -q`

Kiểm tra H+1/H+3, purge nhãn chưa có tại origin, champion quá mới, dữ liệu thiếu/trùng, audit không đổi quyết định, MAE bằng 0, giữ kết quả lịch sử, lưu quyết định/rankings theo backtest, thay champion giữa lúc chạy và phần hiển thị UI. RF được fit thực với cấu hình nhỏ; nhánh LSTM dùng mô hình/replay giả để kiểm tra ranh giới dữ liệu. Chưa huấn luyện đủ mọi cấu hình với database vận hành.
