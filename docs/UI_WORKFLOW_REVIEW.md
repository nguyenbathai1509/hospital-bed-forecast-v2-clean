# Kiểm tra luồng thao tác giao diện

## Phạm vi

Đợt này kiểm tra và sửa lớp trình bày: Dữ liệu → Huấn luyện → Kết quả huấn luyện → Quản lý mô hình → Dự báo → Giám sát. Không đổi thuật toán, quy tắc nghiệp vụ ở API, phân quyền hay dữ liệu vận hành.

Các thao tác trong kiểm thử dùng một dịch vụ giả lập lưu trong bộ nhớ. Không chạy pipeline thật, worker huấn luyện, chọn/khôi phục mô hình thật hoặc xác nhận dự báo thật.

## Các điểm đã sửa

| Tình huống | Trước | Sau |
| --- | --- | --- |
| API hết thời gian chờ | Báo chung là không kết nối được | Phân biệt `API_TIMEOUT`; nhắc kiểm tra trạng thái trước khi gửi lại, không tự retry thao tác |
| API trả HTTP thành công nhưng nội dung không phải JSON | Lỗi đọc JSON có thể thoát ra màn hình | Chuyển thành lỗi `API_INVALID_RESPONSE` để giao diện hiển thị được |
| Pipeline trả `WAITING` hoặc `FAILED` | Vẫn dùng thông báo thành công | Chọn cảnh báo/lỗi đúng trạng thái; tải lại lịch sử và yêu cầu đánh dấu xác nhận lại |
| Khoảng ngày lịch sử không hợp lệ / bỏ trống ngày dự báo | Gửi yêu cầu không hợp lệ hoặc phát sinh lỗi | Hướng dẫn chọn lại ngày trước khi gọi API |
| Chưa có dữ liệu sẵn sàng / chưa có mô hình vận hành | Vẫn cho gửi một số thao tác không thể thực hiện | Khóa nút huấn luyện/tạo bản nháp tương ứng và chỉ rõ bước cần hoàn tất |
| Theo dõi huấn luyện | Chỉ xem trạng thái trong chi tiết kỹ thuật; có thể giữ trạng thái cũ khi cập nhật lỗi | Hiển thị đang chờ/đang chạy/thất bại/hoàn tất; đọc lại khi trang chạy lại và không trình bày trạng thái lưu cũ như vừa được xác minh |
| Kết quả huấn luyện có mô hình nhưng không có khoa hoạt động | Truy cập lựa chọn khoa rỗng gây lỗi | Giữ phần tổng hợp và giải thích vì sao chưa xem được đánh giá theo ngày |
| Đổi khoa, mốc, ngày, cách chọn hoặc mô hình xem thử | Kết quả xem thử cũ vẫn hiện | Xóa kết quả không còn khớp ngữ cảnh; cũng xóa trước khi thử lại để lỗi mới không đi kèm kết quả thành công cũ |
| Bản nháp trong phiên giao diện | Chỉ kiểm tra ngày | Kiểm tra ngữ cảnh và lọc đúng khoa/mốc; việc ẩn thẻ không xóa bản nháp trong hệ thống |
| Xác nhận chính thức khi không có kế hoạch hợp lệ | Chủ yếu dựa vào chuỗi xác nhận | Cần kế hoạch đọc được, đúng ngày, có bản nháp; thay đổi kế hoạch yêu cầu nhập lại chuỗi xác nhận |
| Đổi lựa chọn sau khi kiểm tra kế hoạch khôi phục | Có thể xác nhận với lựa chọn khác kế hoạch đã xem | Gắn kế hoạch với mốc, lý do và trạng thái mô hình; thay đổi thì phải kiểm tra lại |
| Kiểm tra lại kế hoạch mô hình thất bại | Có thể còn kế hoạch thành công trước đó | Bỏ kế hoạch cũ trước khi kiểm tra lại; khóa xác nhận khi yêu cầu/trạng thái không còn khớp |
| Sau xác nhận dự báo, đổi/khôi phục mô hình hoặc chạy giám sát | Một số phần vẫn hiện dữ liệu trước thao tác | Chạy lại trang để đọc trạng thái mới, giữ thông báo kết quả; không tự gửi lại thao tác |

Các thao tác chờ phản hồi có thông báo đang xử lý. Nút cập nhật huấn luyện chỉ đọc trạng thái, không khởi chạy lại huấn luyện. Không thêm vòng polling nền hay phần trăm tiến độ suy đoán.

## Giữ nguyên ranh giới nghiệp vụ

- Xác nhận dự báo chính thức vẫn áp dụng cho **tất cả bản nháp của ngày được chọn**, không chỉ khoa/mốc đang xem; giao diện nhắc rõ phạm vi này.
- Các chuỗi xác nhận bắt buộc vẫn giữ nguyên. API tiếp tục là nơi kiểm tra điều kiện, khóa, hạn mức và xung đột.
- Giao diện kiểm tra lại điều kiện cả trong nhánh xử lý nút, không chỉ đặt thuộc tính `disabled`. Điều này chặn sự kiện bấm từ màn hình cũ khi dữ liệu đọc ở lần chạy mới đã thay đổi.
- Kiểm tra ngữ cảnh ở giao diện **không phải giao dịch nguyên tử** với backend. Đợt này không bổ sung token phiên bản kế hoạch hay thay đổi cơ chế xử lý đồng thời của API.
- Timeout không chứng minh thao tác thất bại: máy chủ có thể vẫn tiếp tục xử lý. Cần kiểm tra lịch sử/trạng thái trước khi chủ động gửi lại.

## Kiểm thử

```powershell
python -m pytest tests/test_ui_workflow.py tests/test_ui_api_client.py -q
python -m pytest -q
```

- `tests/test_ui_workflow.py`: Streamlit AppTest tương tác với dịch vụ giả lập; chặn mọi lời gọi qua HTTP client thật. Kiểm tra luồng trọn vẹn, dữ liệu trống, lỗi kết nối, thất bại thao tác, thay đổi bộ lọc và kế hoạch thay đổi đúng lúc bấm xác nhận.
- `tests/test_ui_api_client.py`: HTTP MockTransport kiểm tra timeout, phản hồi JSON lỗi và bảo đảm không tự retry thao tác ghi.
- AppTest 1.49 có thể giữ delta giao diện cũ khi `st.rerun()` xảy ra ngay trong một lần chạy kiểm thử. Bộ kiểm thử tách lần chạy lại để kiểm tra khung hình cuối; đồng thời có smoke test dùng `st.rerun()` thật cho pipeline và xác nhận dự báo.
- Kiểm thử SQL tùy chọn chỉ chạy khi `TRAINING_SQL_TESTS=1`; không bật trong đợt kiểm tra luồng này.

Đây là kiểm thử luồng giao diện bằng dữ liệu giả lập, không thay thế nghiệm thu pipeline/huấn luyện toàn hệ thống trên một cơ sở dữ liệu thử nghiệm riêng.
