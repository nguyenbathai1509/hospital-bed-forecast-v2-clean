"""Show advisory intervals without changing or confirming any forecast."""
import hashlib
import json

import streamlit as st

from app.api_client import ApiClientError
from app.components import technical_details


def render_uncertainty(rows: list[dict], client, *, scope: str) -> None:
    if not rows:
        return
    with st.expander("Khoảng bất định của dự báo — tham khảo", expanded=False):
        st.caption(
            "Dựa trên ít nhất 30 dự báo chính thức đã đối chiếu thực tế, cùng mô hình, khoa và mốc dự báo "
            "trong 90 ngày gần nhất. Mức bao phủ mục tiêu 90% không phải cam kết chính xác 90%. "
            "Không thay đổi dự báo chính thức hoặc cảnh báo công suất."
        )
        for index, row in enumerate(rows):
            fields = {key: row.get(key) for key in (
                "candidate_id", "department_id", "horizon", "origin_date", "prediction_raw", "issued_at", "created_at",
            )}
            identity = hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()
            slot = f"uncertainty_result_{scope}_{index}"
            st.write(f"Khoa {row.get('department_id')} · H+{row.get('horizon')} · Ngày {row.get('target_date')}")
            if st.button("TÍNH KHOẢNG THAM KHẢO", key=f"uncertainty_{scope}_{identity}"):
                # Remove stale output first: failed refresh must not leave a success visible.
                st.session_state.pop(slot, None)
                try:
                    result = client.forecast_uncertainty(row)
                    st.session_state[slot] = {"identity": identity, "result": result}
                except ApiClientError as exc:
                    st.warning(f"Chưa tính được khoảng tham khảo: {exc.message}. Dự báo điểm vẫn giữ nguyên.")
            stored = st.session_state.get(slot, {})
            if stored.get("identity") != identity:
                continue
            result = stored["result"]
            if result.get("status") == "AVAILABLE":
                st.metric("Khoảng tham khảo", f"{result['lower_beds']}–{result['upper_beds']} giường")
                st.caption(
                    f"Từ {result['sample_count']} quan sát · {result['calibration_start']} → {result['calibration_end']}. "
                    "Không giới hạn cận trên theo số giường kế hoạch."
                )
            else:
                st.info(f"Chưa đủ dữ liệu: {result.get('sample_count', 0)}/{result.get('minimum_samples', 30)} quan sát hợp lệ.")
            st.caption(result.get("reason", ""))
            technical_details(result, label="Cách tính và thời điểm dữ liệu dùng cho khoảng tham khảo")
