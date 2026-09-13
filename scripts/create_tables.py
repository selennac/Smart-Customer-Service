"""创建业务数据表和 LangGraph 检查点（checkpoint）数据表。

在配置好 ``.env`` 文件后，从项目根目录运行：

    python scripts/create_tables.py

该命令设计为追加式操作，多次运行是安全的。它不会删除或修改已有的数据表。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import inspect, text

# 允许从项目根目录执行 ``python scripts/create_tables.py``。
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from app.db.models import Base  # noqa: E402
from app.db.session import engine  # noqa: E402


def _checkpoint_url() -> str:
    url = os.getenv("CHECKPOINT_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("CHECKPOINT_DATABASE_URL 或 DATABASE_URL 未设置")
    # PostgresSaver 需要 libpq 格式的 URL；psycopg 的 SQLAlchemy 驱动前缀
    # 并非被所有版本的 checkpointer 包所接受。
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def create_business_tables() -> list[str]:
    Base.metadata.create_all(bind=engine)
    # 为已有项目数据库补充售后会话关联字段；新库由 create_all 直接创建。
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE refunds ADD COLUMN IF NOT EXISTS thread_id VARCHAR(128) "
            "REFERENCES threads(thread_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_refunds_thread_id ON refunds (thread_id)"
        ))
    return sorted(inspect(engine).get_table_names())


def create_checkpoint_tables() -> None:
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_checkpoint_url()) as checkpointer:
        checkpointer.setup()


def main() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    tables = create_business_tables()
    print(f"业务数据表已就绪 ({len(tables)}): {', '.join(tables)}")

    create_checkpoint_tables()
    print("LangGraph 检查点数据表已就绪。")


if __name__ == "__main__":
    main()
