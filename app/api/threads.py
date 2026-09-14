"""会话管理接口。"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, get_current_user
from app.api.dependencies import get_conversation_service
from app.api.schemas import (
    MessageItem,
    ThreadCreatedResponse,
    ThreadItem,
    ThreadListResponse,
    ThreadMessagesResponse,
)
from app.db.models import Refund, Thread, ThreadStatus
from app.db.session import get_db
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/threads", tags=["threads"])
logger = logging.getLogger(__name__)


def _thread_item(row: Thread) -> ThreadItem:
    return ThreadItem(
        thread_id=row.thread_id,
        title=row.title,
        status=row.status,
        last_message=row.last_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _encode_cursor(row: Thread) -> str:
    payload = json.dumps(
        {"updated_at": row.updated_at.isoformat(), "thread_id": row.thread_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        return datetime.fromisoformat(payload["updated_at"]), str(payload["thread_id"])
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="无效的分页游标",
        ) from exc


@router.get("", response_model=ThreadListResponse)
def list_threads(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ThreadListResponse:
    statement = select(Thread).where(Thread.user_id == user.user_id)
    if cursor:
        updated_at, thread_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                Thread.updated_at < updated_at,
                and_(Thread.updated_at == updated_at, Thread.thread_id < thread_id),
            )
        )
    rows = db.scalars(
        statement.order_by(Thread.updated_at.desc(), Thread.thread_id.desc()).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1]) if has_more and page else None
    return ThreadListResponse(items=[_thread_item(row) for row in page], next_cursor=next_cursor)


@router.post("", response_model=ThreadCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_thread(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ThreadCreatedResponse:
    thread_id = f"TH-{uuid.uuid4().hex[:12].upper()}"
    row = Thread(thread_id=thread_id, user_id=user.user_id, status=ThreadStatus.ACTIVE)
    db.add(row)
    db.commit()
    return ThreadCreatedResponse(thread_id=thread_id, status=row.status)


@router.get("/{thread_id}", response_model=ThreadItem)
def get_thread(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ThreadItem:
    row = db.scalar(
        select(Thread).where(Thread.thread_id == thread_id, Thread.user_id == user.user_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return _thread_item(row)


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: ConversationService = Depends(get_conversation_service),
) -> None:
    """Delete a user's conversation and its LangGraph checkpoints.

    Refund records are business records, so they are retained but detached from the
    deleted conversation before the thread index is removed.
    """
    row = db.scalar(
        select(Thread).where(Thread.thread_id == thread_id, Thread.user_id == user.user_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    try:
        db.execute(update(Refund).where(Refund.thread_id == thread_id).values(thread_id=None))
        db.delete(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to delete thread row: thread_id=%s", thread_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除会话失败，请稍后重试",
        ) from exc

    # The SQL row is the user's visible conversation index. Checkpoint cleanup is
    # best-effort because it is stored outside the database transaction.
    try:
        await service.delete_thread(thread_id=thread_id)
    except Exception:
        logger.exception("Failed to clean up thread checkpoints: thread_id=%s", thread_id)


@router.get("/{thread_id}/messages", response_model=ThreadMessagesResponse)
async def get_thread_messages(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: ConversationService = Depends(get_conversation_service),
) -> ThreadMessagesResponse:
    """返回指定会话的用户与客服消息，供前端打开会话时恢复界面。"""
    row = db.scalar(
        select(Thread).where(Thread.thread_id == thread_id, Thread.user_id == user.user_id)
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    messages = await service.get_messages(user_id=user.user_id, thread_id=thread_id)
    pending_action = await service.get_pending_action(user_id=user.user_id, thread_id=thread_id)
    title = await service.ensure_title(user_id=user.user_id, thread_id=thread_id, messages=messages)
    return ThreadMessagesResponse(
        thread_id=thread_id,
        title=title or row.title,
        pending_action=pending_action,
        messages=[
            MessageItem(
                message_id=message.message_id,
                role=message.role,
                content=message.content,
                sources=message.sources,
            )
            for message in messages
        ],
    )


__all__ = ["router"]
