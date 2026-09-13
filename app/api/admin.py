"""管理员退款审批接口。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, require_admin
from app.api.dependencies import get_conversation_service
from app.api.schemas import AdminDecisionRequest
from app.db.models import Order, Refund, Thread, ThreadStatus
from app.db.session import get_db
from app.services import refund_service
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/admin/refunds", tags=["admin"])


@router.get("/pending")
def list_pending_refunds(
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    return refund_service.list_pending_refunds(db, admin_user_id=user.user_id)


@router.post("/{refund_id}/decision")
async def decide_refund(
    refund_id: str,
    body: AdminDecisionRequest,
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    with db.begin():
        result = refund_service.approve_refund(
            db,
            admin_user_id=user.user_id,
            refund_id=refund_id,
            decision=body.decision,
            now=datetime.now(timezone.utc),
        )
    if not result.get("ok"):
        code = result.get("code")
        http_status = status.HTTP_404_NOT_FOUND if code == "NOT_FOUND" else status.HTTP_409_CONFLICT
        if code == "FORBIDDEN":
            http_status = status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=http_status, detail=result.get("message", "审批失败"))

    data = result.get("data") or {}
    thread_id = data.get("thread_id")
    if not thread_id:
        return {"approval": result, "resume": None}
    owner_id = db.scalar(select(Order.user_id).join(Refund, Refund.order_id == Order.order_id).where(Refund.refund_id == refund_id))
    if not owner_id:
        return {"approval": result, "resume": None}
    thread = db.get(Thread, thread_id)
    if thread is None or thread.status != ThreadStatus.PENDING_SUPERVISOR:
        return {"approval": result, "resume": None}
    resume = await service.run(
        user_id=owner_id,
        thread_id=thread_id,
        resume={"kind": "supervisor_approval", "refund_id": refund_id, "decision": body.decision},
    )
    return {
        "approval": result,
        "resume": {
            "run_id": resume.run_id,
            "answer": resume.answer,
            "pending_action": resume.pending_action,
        },
    }


__all__ = ["router"]
