"""由应用层图服务驱动的对话运行接口。"""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.auth import CurrentUser, get_current_user
from app.api.dependencies import get_conversation_service, get_owned_thread
from app.api.schemas import ChatRequest, ChatResponse, StreamEventEnvelope
from app.db.models import Thread
from app.services.conversation_service import ConversationEvent, ConversationService

router = APIRouter(prefix="/threads/{thread_id}/runs", tags=["chat"])


def _to_sse(event: ConversationEvent) -> str:
    envelope = StreamEventEnvelope(
        event_id=event.event_id,
        run_id=event.run_id,
        thread_id=event.thread_id,
        type=event.type,
        data=event.data,
    )
    return f"id: {event.event_id}\nevent: {event.type}\ndata: {envelope.model_dump_json()}\n\n"


@router.post("", response_model=ChatResponse)
async def run_conversation(
    thread_id: str,
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    _: Thread = Depends(get_owned_thread),
    service: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    result = await service.run(user_id=user.user_id, thread_id=thread_id, message=body.message, resume=body.resume)
    return ChatResponse(
        run_id=result.run_id,
        thread_id=result.thread_id,
        answer=result.answer,
        sources=result.sources,
        tool_events=result.tool_events,
        pending_action=result.pending_action,
    )


@router.post("/stream")
async def stream_conversation(
    thread_id: str,
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    _: Thread = Depends(get_owned_thread),
    service: ConversationService = Depends(get_conversation_service),
) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        async for event in service.stream(
            user_id=user.user_id,
            thread_id=thread_id,
            message=body.message,
            resume=body.resume,
        ):
            yield _to_sse(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router", "run_conversation", "stream_conversation"]
