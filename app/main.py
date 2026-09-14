"""FastAPI 应用入口与基础设施生命周期。"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from functools import partial
from typing import AsyncIterator

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from starlette.concurrency import run_in_threadpool

from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.error_handlers import register_exception_handlers
from app.api.threads import router as threads_router
from app.config import Settings, get_settings
from app.db.session import SessionLocal, engine
from app.graph import build_graph
from app.rag.retriever import get_retriever
from app.services.conversation_service import ConversationService

# Windows 下 psycopg 异步连接需要 selector 事件循环。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """为每个应用进程创建并释放一次图基础设施。"""
    settings: Settings = app.state.settings
    app.state.ready = False

    checkpoint_pool = AsyncConnectionPool(
        conninfo=settings.checkpoint_dsn,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "connect_timeout": settings.checkpoint_pool_timeout_seconds,
        },
        min_size=settings.checkpoint_pool_min_size,
        max_size=settings.checkpoint_pool_max_size,
        open=False,
        name="langgraph-checkpoints",
    )
    try:
        await checkpoint_pool.open(wait=True, timeout=settings.checkpoint_pool_timeout_seconds)
        checkpointer = AsyncPostgresSaver(checkpoint_pool)
        await checkpointer.setup()
        retriever = await run_in_threadpool(
            partial(get_retriever, persist_directory=settings.chroma_persist_directory)
        )
        app.state.conversation_service = ConversationService(
            graph=build_graph(checkpointer=checkpointer),
            db_factory=SessionLocal,
            retriever=retriever,
        )
        app.state.ready = True
        yield
    finally:
        app.state.ready = False
        app.state.conversation_service = None
        await checkpoint_pool.close()
        await run_in_threadpool(engine.dispose)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Smart Customer Service",
        description="LangGraph-powered customer service backend",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.ready = False

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    register_exception_handlers(app)
    api_router = APIRouter(prefix="/api/v1")
    api_router.include_router(auth_router)
    api_router.include_router(admin_router)
    api_router.include_router(threads_router)
    api_router.include_router(chat_router)
    app.include_router(api_router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["system"], response_model=None)
    def readiness(request: Request):
        if not request.app.state.ready:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready"},
            )
        return {"status": "ready"}

    return app


app = create_app()


__all__ = ["app", "create_app", "lifespan"]
