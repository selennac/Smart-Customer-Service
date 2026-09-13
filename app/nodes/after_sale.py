"""受控售后子图：工单、用户确认退款和主管审批。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.db.models import Refund, RefundStatus, Thread, ThreadStatus, TicketType
from app.nodes.common import build_tool_context, text_content
from app.services import refund_service, ticket_service
from app.state import CustomerServiceState


def _result_message(result: dict[str, Any], fallback: str) -> str:
    return str(result.get("message") or fallback)


def _with_answer(result: dict[str, Any], fallback: str) -> dict[str, Any]:
    answer = _result_message(result, fallback)
    return {
        "after_sale_result": result,
        "answer": answer,
        "last_message": answer,
        "messages": [AIMessage(content=answer)],
    }


def create_ticket_node(state: CustomerServiceState, config: RunnableConfig = None) -> dict[str, Any]:
    ctx = build_tool_context(state, config)
    action = state.get("after_sale_action") or "complaint"
    ticket_type = TicketType.EXCHANGE if action == "exchange" else TicketType.COMPLAINT
    description = (state.get("reason") or text_content(state.get("messages", [])[-1])).strip()
    try:
        with ctx.db_factory() as session:
            with session.begin():
                result = ticket_service.create_ticket(
                    session,
                    user_id=ctx.user_id,
                    ticket_type=ticket_type,
                    description=description,
                    order_id=state.get("order_id") or None,
                )
        return _with_answer(result, "售后工单处理失败，请稍后再试。")
    except Exception:
        return _with_answer({"ok": False, "code": "INTERNAL_ERROR", "message": "工单创建失败，请稍后再试"}, "工单创建失败，请稍后再试。")


def create_refund_draft_node(state: CustomerServiceState, config: RunnableConfig = None) -> dict[str, Any]:
    ctx = build_tool_context(state, config)
    reason = (state.get("reason") or "用户申请退款").strip()
    try:
        with ctx.db_factory() as session:
            with session.begin():
                result = refund_service.create_refund_draft(
                    session,
                    user_id=ctx.user_id,
                    thread_id=ctx.thread_id,
                    order_id=state.get("order_id", ""),
                    reason=reason,
                    now=ctx.now(),
                    approval_threshold=ctx.threshold(),
                )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if result.get("ok") and data.get("refund_id"):
            answer = _result_message(result, "退款申请已准备，请确认。")
            pending_kind = result.get("next_action")
            if pending_kind not in {"refund_confirmation", "supervisor_approval"}:
                raise ValueError(f"unsupported refund next_action: {pending_kind}")
            return {
                "refund_id": data["refund_id"],
                "refund": data,
                "after_sale_result": result,
                "answer": answer,
                "last_message": answer,
                "pending_action": {
                    "kind": pending_kind,
                    "refund_id": data["refund_id"],
                    "order_id": data.get("order_id"),
                    "amount": data.get("amount"),
                    "reason": data.get("reason"),
                },
                "messages": [AIMessage(content=answer)],
            }
        return _with_answer(result, "退款申请创建失败，请稍后再试。")
    except Exception:
        return _with_answer({"ok": False, "code": "INTERNAL_ERROR", "message": "退款申请创建失败，请稍后再试"}, "退款申请创建失败，请稍后再试。")


def request_refund_order_id_node(state: CustomerServiceState) -> dict[str, Any]:
    """退款意图明确但缺少订单号时，在售后子图内补充收集订单号。"""
    answer = "请提供需要办理退款的订单号。"
    return {
        "answer": answer,
        "last_message": answer,
        "messages": [AIMessage(content=answer)],
    }


def _draft_route(state: CustomerServiceState) -> str:
    result = state.get("after_sale_result") or {}
    if not result.get("ok"):
        return "done"
    if not state.get("refund_id"):
        return "done"
    if result.get("next_action") == "supervisor_approval":
        return "approval"
    if result.get("next_action") == "refund_confirmation":
        return "confirm"
    return "done"


def user_confirmation_node(state: CustomerServiceState) -> dict[str, Any]:
    pending_action = state.get("pending_action") or {}
    if pending_action.get("kind") != "refund_confirmation":
        raise ValueError("user confirmation requires kind=refund_confirmation")

    decision = interrupt(pending_action)
    if not isinstance(decision, dict) or decision.get("kind") != "refund_confirmation":
        raise ValueError("refund confirmation resume must include kind=refund_confirmation")

    value = decision.get("decision")
    if value not in {"confirm", "cancel"}:
        raise ValueError("refund confirmation decision must be confirm or cancel")
    return {"confirmation": value}


def cancel_refund_node(state: CustomerServiceState, config: RunnableConfig = None) -> dict[str, Any]:
    ctx = build_tool_context(state, config)
    try:
        with ctx.db_factory() as session:
            with session.begin():
                result = refund_service.cancel_refund(session, user_id=ctx.user_id, refund_id=state["refund_id"])
        return {"pending_action": {}, **_with_answer(result, "已取消退款申请。")}
    except Exception:
        return {"pending_action": {}, "answer": "退款取消失败，请稍后再试。", "last_message": "退款取消失败，请稍后再试。"}


def confirm_refund_node(state: CustomerServiceState, config: RunnableConfig = None) -> dict[str, Any]:
    ctx = build_tool_context(state, config)
    try:
        with ctx.db_factory() as session:
            with session.begin():
                result = refund_service.confirm_refund(
                    session,
                    user_id=ctx.user_id,
                    thread_id=ctx.thread_id,
                    refund_id=state["refund_id"],
                    now=ctx.now(),
                    approval_threshold=ctx.threshold(),
                )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if result.get("code") == "APPROVAL_REQUIRED":
            return {
                "refund": data,
                "after_sale_result": result,
                "answer": _result_message(result, "退款已提交，等待主管审批。"),
                "last_message": _result_message(result, "退款已提交，等待主管审批。"),
                "pending_action": {
                    "kind": "supervisor_approval",
                    "refund_id": state["refund_id"],
                    "amount": data.get("amount"),
                },
                "messages": [AIMessage(content=_result_message(result, "退款已提交，等待主管审批。"))],
            }
        return {"pending_action": {}, "refund": data, **_with_answer(result, "退款确认失败，请稍后再试。")}
    except Exception:
        return {"pending_action": {}, "answer": "退款确认失败，请稍后再试。", "last_message": "退款确认失败，请稍后再试。"}


def supervisor_interrupt_node(state: CustomerServiceState) -> dict[str, Any]:
    pending_action = state.get("pending_action") or {}
    if pending_action.get("kind") != "supervisor_approval":
        raise ValueError("supervisor approval requires kind=supervisor_approval")
    interrupt(pending_action)
    return {}


def supervisor_resume_node(state: CustomerServiceState, config: RunnableConfig = None) -> dict[str, Any]:
    ctx = build_tool_context(state, config)
    try:
        with ctx.db_factory() as session:
            with session.begin():
                row = session.get(Refund, state["refund_id"])
                if row is None:
                    result = {"ok": False, "code": "NOT_FOUND", "message": "未找到该退款申请"}
                else:
                    status = getattr(row.status, "value", str(row.status))
                    if status == RefundStatus.COMPLETED.value:
                        message = "主管已批准退款。"
                        ok = True
                    elif status == RefundStatus.REJECTED.value:
                        message = "主管已拒绝退款。"
                        ok = True
                    else:
                        message = "退款仍在等待主管审批。"
                        ok = False
                    result = {"ok": ok, "code": "OK" if ok else "APPROVAL_REQUIRED", "message": message, "data": refund_service.refund_data(row)}
                    if ok and row.thread_id:
                        thread = session.get(Thread, row.thread_id)
                        if thread is not None:
                            thread.status = ThreadStatus.ACTIVE
                            thread.last_message = message
        return {"pending_action": {}, **_with_answer(result, "退款审批状态已更新。")}
    except Exception:
        return {"pending_action": {}, "answer": "读取审批结果失败，请稍后刷新。", "last_message": "读取审批结果失败，请稍后刷新。"}


def _confirm_route(state: CustomerServiceState) -> str:
    return "cancel" if state.get("confirmation") == "cancel" else "confirm"


def _approval_route(state: CustomerServiceState) -> str:
    result = state.get("after_sale_result") or {}
    return "approval" if result.get("code") == "APPROVAL_REQUIRED" else "done"


def build_after_sale_graph():
    builder = StateGraph(CustomerServiceState)
    builder.add_node("create_ticket", create_ticket_node)
    builder.add_node("create_refund_draft", create_refund_draft_node)
    builder.add_node("request_refund_order_id", request_refund_order_id_node)
    builder.add_node("user_confirmation", user_confirmation_node)
    builder.add_node("cancel_refund", cancel_refund_node)
    builder.add_node("confirm_refund", confirm_refund_node)
    builder.add_node("supervisor_interrupt", supervisor_interrupt_node)
    builder.add_node("supervisor_resume", supervisor_resume_node)
    builder.add_conditional_edges("create_ticket", lambda state: "done", {"done": END})
    builder.add_conditional_edges("create_refund_draft", _draft_route, {"done": END, "confirm": "user_confirmation", "approval": "supervisor_interrupt"})
    builder.add_conditional_edges("user_confirmation", _confirm_route, {"cancel": "cancel_refund", "confirm": "confirm_refund"})
    builder.add_edge("cancel_refund", END)
    builder.add_conditional_edges("confirm_refund", _approval_route, {"done": END, "approval": "supervisor_interrupt"})
    builder.add_edge("supervisor_interrupt", "supervisor_resume")
    builder.add_edge("supervisor_resume", END)
    builder.add_conditional_edges(
        START,
        lambda state: (
            "refund_missing_order_id"
            if state.get("after_sale_action") == "refund" and not state.get("order_id")
            else "refund" if state.get("after_sale_action") == "refund" else "ticket"
        ),
        {
            "refund_missing_order_id": "request_refund_order_id",
            "refund": "create_refund_draft",
            "ticket": "create_ticket",
        },
    )
    builder.add_edge("request_refund_order_id", END)
    return builder.compile()


__all__ = ["build_after_sale_graph"]
