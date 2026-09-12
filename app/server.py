"""API 服务的开发与生产启动入口。"""

from __future__ import annotations

import asyncio

import uvicorn

from app.config import get_settings


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """返回 Windows 下兼容 psycopg 异步连接的事件循环。"""
    return asyncio.SelectorEventLoop()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.log_level.lower(),
        loop=selector_loop_factory,
    )


if __name__ == "__main__":
    main()


__all__ = ["main", "selector_loop_factory"]
