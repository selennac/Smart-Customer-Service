"""SQLAlchemy 引擎与会话辅助工具。

应用程序从本模块导入 ``engine``/``SessionLocal``，而独立的建表初始化命令也可以复用相同的配置。
"""

from __future__ import annotations

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()


def get_database_url() -> str:
    """返回业务数据库 URL，若未设置则抛出包含操作指引的错误信息。"""

    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL 未设置；请先将 .env.example 复制为 .env 并配置 PostgreSQL")
    return url


# pool_pre_ping=True: 在从连接池获取连接前进行健康检查，避免使用已断开的连接
# future=True: 启用 SQLAlchemy 2.0 风格的行为
engine = create_engine(get_database_url(), pool_pre_ping=True, future=True)

# autoflush=False: 禁用自动刷新，需手动调用 flush()
# autocommit=False: 禁用自动提交，需显式管理事务
# expire_on_commit=False: 提交后不使实例属性过期，避免后续访问时触发隐式查询
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """生成一个请求级别的同步 SQLAlchemy 会话。"""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["engine", "SessionLocal", "get_db", "get_database_url"]