"""使用统一公开结构的全局异常处理器。"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.services.conversation_service import ConversationRunError

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or uuid4().hex


def _response(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={"X-Request-ID": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求失败"
        response = _response(
            request,
            status_code=exc.status_code,
            code=f"HTTP_{exc.status_code}",
            message=message,
        )
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        print(exc)
        print(type(exc))
        return _response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="VALIDATION_ERROR",
            message="请求参数不合法",
        )

    @app.exception_handler(ConversationRunError)
    async def conversation_error_handler(request: Request, exc: ConversationRunError) -> JSONResponse:
        return _response(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="CONVERSATION_RUN_FAILED",
            message="客服服务暂时不可用，请稍后再试。",
        )

    @app.exception_handler(OperationalError)
    async def database_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
        logger.exception("Database operation failed")
        return _response(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="DATABASE_UNAVAILABLE",
            message="数据服务暂时不可用，请稍后再试。",
        )


__all__ = ["register_exception_handlers"]
