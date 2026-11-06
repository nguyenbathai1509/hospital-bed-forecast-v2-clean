# Mô hình đối chiếu và khoảng bất định tham khảo

## Trên giao diện

- **Kết quả huấn luyện**: sau bảng backtest là bảng so sánh ML với ba phương pháp đơn giản: giữ nguyên giá trị gần nhất; cùng thứ tuần trước; trung bình 7 ngày gần nhất. Dùng đúng metrics đã lưu, cùng khoa/ngày/cửa sổ với ML. MAE/RMSE nhỏ hơn là tốt hơn; độ lệch dương nghĩa là dự báo thiếu giường. Không tự đưa baseline vào danh sách mô hình Production.
- **Dự báo**: bên dưới kết quả chính thức, bản nháp và xem thử có mục **Khoảng bất định của dự báo — tham khảo**. Nhấn **TÍNH KHOẢNG THAM KHẢO** để đọc dữ liệu và tính khoảng. Chỉ mở trang/expander không gọi tính toán. Thay mô hình, ngày hoặc dự báo điểm thì kết quả cũ không được dùng lại.
- Nếu snapshot huấn luyện cũ chưa có baseline, báo rõ chưa có, không huấn luyện lại hoặc sửa snapshot. Nếu lịch sử vận hành chưa đủ cho khoảng, chỉ báo số quan sát hợp lệ, không hiện một khoảng giả định.

## Khoảng tham khảo tính như thế nào?

Phiên bản `official-errors-90-v1`, mức bao phủ mục tiêu 90%, tối thiểu 30 ngày có quan sát hợp lệ trong 90 ngày lịch gần nhất. Đây là chính sách khởi đầu, không phải kết luận 30/90 là tối ưu cho mọi khoa.

Chỉ dùng dự báo **Official đã đối chiếu Actual** của đúng candidate_id, khoa và H+1/H+3. Không trộn sai số các khoa, các horizon, mô hình cũ/mới; không dùng sai số train hoặc backtest của các trọng số đã fit lại để gán cho artifact Production.

Điều kiện thời gian:

1. Ngày origin của từng quan sát phải nằm từ cuối dữ liệu huấn luyện của artifact trở đi; target phải sau origin đúng horizon và không muộn hơn ngày origin của dự báo đang xem.
2. Official phải được phát hành trước khi kết thúc ngày origin của chính nó theo giờ Việt Nam (UTC+7). Dự báo tạo bù cho ngày quá khứ không được coi là dự báo triển vọng hợp lệ.
3. Thời điểm cắt dữ liệu là thời điểm sớm nhất giữa hiện tại, cuối ngày origin theo giờ Việt Nam và thời điểm tạo/phát hành dự báo đang xem (nếu có). Timestamp không có múi giờ từ SQL Server được hiểu là UTC như các bảng hiện tại.
4. Bản Actual/match phải được ghi nhận/cập nhật trước thời điểm cắt; Actual phải có quality PASS. Bản sửa dữ liệu sau thời điểm dự báo bị loại vì hệ thống chưa có kho lịch sử mọi phiên bản match để tái dựng chính xác. Cách này thận trọng, có thể làm giảm số mẫu của dự báo cũ.
5. Mỗi ngày target chỉ được tính một lần; khóa ngày/horizon sai, giá trị không hữu hạn hay dòng trùng gây lỗi rõ ràng, không làm tăng giả số mẫu.

Với mỗi quan sát, tính `e = |actual − max(0, prediction_raw)|`. Sắp xếp n sai số; lấy sai số thứ `ceil((n+1) × 0.90)` làm bán kính q, không nội suy. Tâm khoảng là `max(0, prediction_raw)` của dự báo đang xem. Cận dưới là `floor(max(0, tâm − q))`, cận trên là `ceil(tâm + q)`. Không giới hạn cận trên theo số giường kế hoạch. Dự báo thô, giá trị đã làm tròn và cảnh báo công suất gốc không bị thay đổi.

Mức 90% là **mục tiêu**, không phải bảo đảm 90% cho dữ liệu chuỗi thời gian. Công thức dựa trên cách lấy phân vị sai số của split conformal; bảo đảm chuẩn phụ thuộc giả định trao đổi được, dễ vi phạm do tương quan theo thời gian, thay đổi phân phối hoặc việc phát hành Official có chọn lọc. Không gọi đây là “khoảng tin cậy 90%” và không dùng tự động để đổi mô hình hay lập cảnh báo. Cơ sở và giới hạn: [Barber, Candès, Ramdas & Tibshirani — Conformal Prediction Beyond Exchangeability](https://www.stat.berkeley.edu/~ryantibs/papers/nexcp.pdf).

Chưa có giám sát độ bao phủ thực nghiệm của khoảng theo thời gian, phương pháp conformal thích nghi hay xác nhận chất lượng vận hành toàn bộ. Cần theo dõi và kiểm chứng những phần này trước khi dùng khoảng cho quyết định vận hành quan trọng.

## API và bằng chứng

`POST /forecasts/uncertainty` là phép tính **chỉ đọc**, nhận `candidate_id`, `department_id`, `horizon`, `origin_date`, `prediction_raw` và tùy chọn `forecast_created_at`. Đây là khoảng cho dự báo điểm được gửi lên, không xác nhận rằng giá trị do client gửi là một Official. Giao diện gửi trực tiếp các trường từ bản ghi API đã trả về.

Trả về AVAILABLE hoặc INSUFFICIENT_DATA, số mẫu, cửa sổ dữ liệu, thời điểm cắt, bán kính, cận dưới/trên và SHA-256 của bằng chứng hiệu chỉnh. `coverage_guaranteed=false`, `persisted=false`. Preview API bổ sung `generated_at` (UTC, lấy trước lúc chạy dự báo) để giao diện gửi thời điểm cắt cả khi xem thử. Không thêm/sửa bảng, artifact, khuyến nghị, Draft/Official hoặc kết quả giám sát. Kết quả chỉ được giữ trong phiên giao diện; nhấn lại sẽ tính lại từ dữ liệu hiện có. Đây không phải snapshot khoảng bất biến đã phát hành cùng Official.

Mô hình mới chưa tích lũy đủ Official có Actual sẽ chưa có khoảng. Với bộ dữ liệu demo được nạp sau các ngày lịch sử, các bộ lọc thời gian có thể khiến số quan sát hợp lệ bằng 0 — đây là hành vi dự kiến, không phải lỗi và không được lấp bằng số liệu giả.

## Kiểm thử

```powershell
python -m pytest tests/test_forecast_uncertainty.py tests/test_ui_uncertainty.py tests/test_ui_backtest_view.py -q
python -m pytest -q
```

Kiểm tra công thức phân vị/làm tròn, H+1/H+3, thiếu mẫu, trùng mẫu, giá trị sai, sai mô hình/khoa, Actual tương lai, bản sửa muộn, thời điểm phát hành và múi giờ; hợp đồng API; giao diện không tính trước khi nhấn và không dùng khoảng cũ cho dự báo khác. Không yêu cầu thư viện ML mới ngoài requirements.txt.
