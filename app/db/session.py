"""SQLAlchemy engine and session helpers.

The application imports ``engine``/``SessionLocal`` from this module, and the
standalone table-creation script can reuse the same configuration.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


def get_database_url() -> str:
    """Return the business database URL, raise a descriptive error if unset."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL 未设置；请先将 .env.example 复制为 .env 并配置 PostgreSQL")
    return url


# connect_timeout 限制 TCP 握手时间，使请求快速失败（例如 5 秒），
engine = create_engine(
    get_database_url(),
    pool_pre_ping=True,
    future=True,
    connect_args={"connect_timeout": 5},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped synchronous SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["engine", "SessionLocal", "get_db", "get_database_url"]
