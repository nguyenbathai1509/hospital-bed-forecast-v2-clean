from __future__ import annotations

SOURCE_COLUMNS = [
    "NGAY",
    "THU",
    "THANG",
    "ID_KHOA",
    "MA_KHOA",
    "TEN_KHOA",
    "SO_GIUONG_KE_HOACH",
    "BN_DAU_NGAY",
    "SO_BN_NHAP_VIEN",
    "SO_BN_CHUYEN_DEN",
    "SO_BN_RA_VIEN",
    "SO_BN_CHUYEN_DI",
    "BN_CUOI_NGAY",
    "SO_GIUONG_DANG_SU_DUNG",
    "TRANG_THAI_CAN_DOI",
    "CONG_SUAT_GIUONG",
]

SOURCE_TO_NORMALIZED = {
    "NGAY": "business_date",
    "THU": "source_weekday",
    "THANG": "source_month",
    "ID_KHOA": "department_id",
    "MA_KHOA": "department_code",
    "TEN_KHOA": "department_name",
    "SO_GIUONG_KE_HOACH": "planned_beds",
    "BN_DAU_NGAY": "occupied_start",
    "SO_BN_NHAP_VIEN": "admissions",
    "SO_BN_CHUYEN_DEN": "transfer_in",
    "SO_BN_RA_VIEN": "discharges",
    "SO_BN_CHUYEN_DI": "transfer_out",
    "BN_CUOI_NGAY": "occupied_end",
    "SO_GIUONG_DANG_SU_DUNG": "occupied_beds",
    "TRANG_THAI_CAN_DOI": "balance_status",
    "CONG_SUAT_GIUONG": "occupancy_rate",
}

REQUIRED_NORMALIZED = [
    "business_date",
    "department_id",
    "department_code",
    "department_name",
    "planned_beds",
    "occupied_start",
    "admissions",
    "transfer_in",
    "discharges",
    "transfer_out",
    "occupied_end",
    "occupied_beds",
]

COUNT_FIELDS = [
    "planned_beds",
    "occupied_start",
    "admissions",
    "transfer_in",
    "discharges",
    "transfer_out",
    "occupied_end",
    "occupied_beds",
]
