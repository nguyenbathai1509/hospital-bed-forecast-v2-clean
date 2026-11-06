from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from src.config import Settings, settings


def create_sql_engine(database: str | None = None, cfg: Settings = settings) -> Engine:
    cfg.validate_for_database()
    target_db = database or cfg.db_name
    url = URL.create(
        "mssql+pymssql",
        username=cfg.db_user,
        password=cfg.db_password,
        host=cfg.db_host,
        port=cfg.db_port,
        database=target_db,
        query={"charset": "UTF-8"},
    )
    return create_engine(url, future=True, pool_pre_ping=True, echo=cfg.sql_echo)
