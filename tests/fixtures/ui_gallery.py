"""Synthetic presentation fixture; never imports backend or invokes real actions."""
import streamlit as st

from app.styles import apply_global_styles, sidebar_brand, sidebar_note
from app.components import page_header, dataframe, render_prediction_cards

st.set_page_config(layout="wide", initial_sidebar_state="expanded")
apply_global_styles()
with st.sidebar:
    sidebar_brand("DỰ BÁO GIƯỜNG BỆNH", "Bộ kiểm tra giao diện · dữ liệu minh họa")
    st.radio("Điều hướng", ["Tổng quan", "Huấn luyện", "Dự báo"], key="hb-navigation")
    sidebar_note("Chế độ hiện tại: Máy cục bộ / Nội bộ.")
    st.button("Kiểm tra kết nối hệ thống")
page_header("Kiểm tra giao diện", "Dữ liệu minh họa, không thực hiện huấn luyện hoặc thay đổi dự báo.")
with st.container(border=True, key="hb-panel-training-controls"):
    st.text_input("Người thực hiện", "streamlit")
    st.selectbox("Mô hình", ["RF", "XGBoost", "SVR", "LSTM"])
    a,b = st.columns(2)
    a.button("BẮT ĐẦU HUẤN LUYỆN", type="primary")
    b.button("TẠO BẢN NHÁP DỰ BÁO", type="primary", disabled=True)
    st.button("XEM THỬ DỰ BÁO")
    st.download_button("Tải dữ liệu minh họa", "sample", file_name="sample.txt")
with st.form("gallery-form"):
    st.form_submit_button("Gửi biểu mẫu", type="primary")
    st.form_submit_button("Biểu mẫu chưa sẵn sàng", type="primary", disabled=True)
st.caption("Chú thích và dòng giải thích phải dễ đọc trên nền sáng.")
st.info("Thông tin tham khảo")
st.warning("Cần kiểm tra dữ liệu")
st.error("Không đủ dữ liệu để tiếp tục")
st.success("Đã hoàn thành")
render_prediction_cards([dict(department_id=343, horizon=1, prediction_rounded=47,
    predicted_utilization_pct=94, model_family="RF", target_date="2026-09-15", candidate_id="DEMO_ONLY")], key_prefix="preview")
dataframe([{"model_family":"RF","mae":1.25},{"model_family":"LSTM","mae":2.5}])
with st.expander("Chi tiết kỹ thuật"):
    st.code("example = True")
