"""会话管理接口。"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
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
from app.db.models import Thread, ThreadStatus
from app.db.session import get_db
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/threads", tags=["threads"])


def _thread_item(row: Thread) -> ThreadItem:
    return ThreadItem(
        thread_id=row.thread_id,
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
    return ThreadMessagesResponse(
        thread_id=thread_id,
        messages=[
            MessageItem(
                message_id=message.message_id,
                role=message.role,
                content=message.content,
            )
            for message in messages
        ],
    )


__all__ = ["router"]
