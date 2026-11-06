from __future__ import annotations

from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("V2_DB_HOST", "localhost")
    db_port: int = int(os.getenv("V2_DB_PORT", "1433"))
    db_name: str = os.getenv("V2_DB_NAME", "HospitalBedForecastV2")
    db_schema: str = os.getenv("V2_DB_SCHEMA", "dbo")
    db_user: str = os.getenv("V2_DB_USER", "sa")
    db_password: str = os.getenv("V2_DB_PASSWORD", "")
    db_driver: str = os.getenv("V2_DB_DRIVER", "pymssql")
    sql_echo: bool = _as_bool(os.getenv("V2_SQL_ECHO"), False)
    feature_version: str = os.getenv("V2_FEATURE_VERSION", "v2.0")
    timezone: str = os.getenv("V2_TIMEZONE", "Asia/Ho_Chi_Minh")

    def validate_for_database(self) -> None:
        if self.db_driver != "pymssql":
            raise ValueError(
                "V2-11 bootstrap currently supports V2_DB_DRIVER=pymssql. "
                "A pyodbc adapter can be added later without changing repositories."
            )
        if not self.db_host:
            raise ValueError("V2_DB_HOST is required")
        if not self.db_name:
            raise ValueError("V2_DB_NAME is required")
        if not self.db_user:
            raise ValueError("V2_DB_USER is required")
        if not self.db_password:
            raise ValueError(
                "V2_DB_PASSWORD is empty. Put the SQL password in your local .env file; "
                "do not send the password to ChatGPT or commit it to Git."
            )


settings = Settings()
