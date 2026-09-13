"""API 服务与资源归属校验共用的 FastAPI 依赖。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, get_current_user
from app.api.schemas import ChatRequest
from app.db.models import Thread, ThreadStatus
from app.db.session import get_db
from app.services.conversation_service import ConversationService


def get_conversation_service(request: Request) -> ConversationService:
    service = getattr(request.app.state, "conversation_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务尚未准备就绪",
        )
    return service


def get_owned_thread(
    thread_id: str,
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Thread:
    thread = db.scalar(
        select(Thread).where(Thread.thread_id == thread_id, Thread.user_id == user.user_id)
    )
    if thread is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    if thread.status == ThreadStatus.CLOSED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="会话已经关闭")
    if thread.status in {ThreadStatus.PENDING_USER, ThreadStatus.PENDING_SUPERVISOR} and body.resume is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前会话正在等待售后操作，请先完成待处理操作")
    return thread


__all__ = ["get_conversation_service", "get_owned_thread"]
