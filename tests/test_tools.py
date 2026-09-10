"""Agent tools 的手动测试用例。

运行这些测试前，请准备好测试数据库配置；本文件默认使用内存 SQLite，
不会访问项目中的 PostgreSQL 数据库或 Chroma 持久化目录。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    LogisticsEvent,
    Order,
    OrderStatus,
    Refund,
    RefundStatus,
    TicketType,
    Thread,
    ThreadStatus,
    User,
)
from app.tools import (
    ToolContext,
    build_action_tools,
    build_query_tools,
)
from app.tools.policy_tools import build_policy_tools
from app.services import refund_service


@pytest.fixture()
def session_factory():
    """为每个测试创建独立的内存数据库。"""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        session.add_all(
            [
                User(user_id="USR-001", name="测试用户甲"),
                User(user_id="USR-002", name="测试用户乙"),
                User(user_id="ADM-001", name="管理员", is_admin=True),
                Thread(thread_id="thread-test", user_id="USR-001"),
                Order(
                    order_id="ORD-SMALL",
                    user_id="USR-001",
                    items=[{"name": "保温杯", "quantity": 1}],
                    total_amount=Decimal("89.00"),
                    status=OrderStatus.DELIVERED,
                    tracking_no="TRK-SMALL",
                    delivered_at=now - timedelta(days=3),
                    created_at=now - timedelta(days=7),
                    updated_at=now,
                ),
                Order(
                    order_id="ORD-LARGE",
                    user_id="USR-001",
                    items=[{"name": "笔记本电脑", "quantity": 1}],
                    total_amount=Decimal("1299.00"),
                    status=OrderStatus.DELIVERED,
                    tracking_no="TRK-LARGE",
                    delivered_at=now - timedelta(days=2),
                    created_at=now - timedelta(days=6),
                    updated_at=now,
                ),
                Order(
                    order_id="ORD-OLD",
                    user_id="USR-001",
                    items=[{"name": "耳机", "quantity": 1}],
                    total_amount=Decimal("399.00"),
                    status=OrderStatus.DELIVERED,
                    tracking_no="TRK-OLD",
                    delivered_at=now - timedelta(days=15),
                    created_at=now - timedelta(days=19),
                    updated_at=now,
                ),
                Order(
                    order_id="ORD-OTHER",
                    user_id="USR-002",
                    items=[{"name": "鼠标", "quantity": 1}],
                    total_amount=Decimal("199.00"),
                    status=OrderStatus.DELIVERED,
                    tracking_no="TRK-OTHER",
                    delivered_at=now - timedelta(days=2),
                    created_at=now - timedelta(days=6),
                    updated_at=now,
                ),
                LogisticsEvent(
                    tracking_no="TRK-SMALL",
                    event_time=now - timedelta(days=4),
                    location="深圳仓",
                    status="已发货",
                ),
                LogisticsEvent(
                    tracking_no="TRK-SMALL",
                    event_time=now - timedelta(days=3),
                    location="北京站",
                    status="已签收",
                ),
            ]
        )
        session.commit()
    yield factory
    engine.dispose()


def _context(factory, user_id: str = "USR-001", role: str = "customer") -> ToolContext:
    return ToolContext(
        user_id=user_id,
        thread_id="thread-test",
        actor_role=role,
        db_factory=factory,
        refund_approval_threshold=Decimal("500"),
    )


def _tools_by_name(tools):
    return {item.name: item for item in tools}


def test_query_tools_enforce_order_ownership(session_factory):
    """客户不能通过订单号读取其他客户的订单。"""
    tools = _tools_by_name(build_query_tools(_context(session_factory)))

    own_result = tools["get_order"].invoke({"order_id": "ORD-SMALL"})
    other_result = tools["get_order"].invoke({"order_id": "ORD-OTHER"})

    assert own_result["ok"] is True
    assert own_result["data"]["order_id"] == "ORD-SMALL"
    assert other_result["ok"] is False
    assert other_result["code"] == "NOT_FOUND"


def test_logistics_tool_returns_ordered_timeline(session_factory):
    """物流工具返回按时间升序排列的轨迹。"""
    tool = _tools_by_name(build_query_tools(_context(session_factory)))["get_logistics"]

    result = tool.invoke({"order_id": "ORD-SMALL"})

    assert result["ok"] is True
    assert [event["status"] for event in result["data"]["events"]] == ["已发货", "已签收"]


def test_create_ticket_is_idempotent(session_factory):
    """重复提交同一工单时返回已有工单。"""
    tool = _tools_by_name(build_action_tools(_context(session_factory)))["create_ticket"]
    payload = {
        "ticket_type": TicketType.COMPLAINT.value,
        "order_id": "ORD-SMALL",
        "description": "物流更新太慢",
    }

    first = tool.invoke(payload)
    second = tool.invoke(payload)

    assert first["ok"] is True
    assert second["code"] == "DUPLICATE_REQUEST"
    assert first["data"]["ticket_id"] == second["data"]["ticket_id"]


def test_small_refund_requires_confirmation_then_completes(session_factory):
    """小额退款先进入待确认，确认后完成。"""
    action_tools = _tools_by_name(build_action_tools(_context(session_factory)))

    draft = action_tools["create_refund_draft"].invoke(
        {"order_id": "ORD-SMALL", "reason": "商品不需要了"}
    )
    refund_id = draft["data"]["refund_id"]
    with session_factory() as session:
        with session.begin():
            confirmed = refund_service.confirm_refund(
                session,
                user_id="USR-001",
                thread_id="thread-test",
                refund_id=refund_id,
                now=datetime.now(timezone.utc),
                approval_threshold=Decimal("500"),
            )

    assert draft["next_action"] == "user_confirm"
    assert confirmed["ok"] is True
    assert confirmed["data"]["status"] == RefundStatus.COMPLETED.value

    with session_factory() as session:
        refund = session.get(Refund, refund_id)
        assert refund is not None
        assert refund.status == RefundStatus.COMPLETED


def test_old_order_is_rejected_by_refund_policy(session_factory):
    """签收超过七天的订单不能创建退款草稿。"""
    tools = _tools_by_name(build_policy_tools(_context(session_factory)))

    result = tools["evaluate_refund"].invoke({"order_id": "ORD-OLD", "reason": "超过期限"})

    assert result["ok"] is False
    assert result["code"] == "POLICY_REJECTED"
    assert result["data"]["delivered_days"] >= 15


def test_large_refund_requires_admin_approval(session_factory):
    """大额退款确认后挂起，管理员批准后完成。"""
    customer_tools = _tools_by_name(build_action_tools(_context(session_factory)))
    draft = customer_tools["create_refund_draft"].invoke(
        {"order_id": "ORD-LARGE", "reason": "商品存在质量问题"}
    )
    refund_id = draft["data"]["refund_id"]
    with session_factory() as session:
        with session.begin():
            waiting = refund_service.confirm_refund(
                session,
                user_id="USR-001",
                thread_id="thread-test",
                refund_id=refund_id,
                now=datetime.now(timezone.utc),
                approval_threshold=Decimal("500"),
            )

    assert waiting["code"] == "APPROVAL_REQUIRED"
    assert waiting["next_action"] == "supervisor_approval"

    with session_factory() as session:
        thread = session.get(Thread, "thread-test")
        assert thread is not None
        assert thread.status == ThreadStatus.PENDING_SUPERVISOR

    with session_factory() as session:
        with session.begin():
            approved = refund_service.approve_refund(
                session,
                admin_user_id="ADM-001",
                refund_id=refund_id,
                decision="approve",
                now=datetime.now(timezone.utc),
            )

    assert approved["ok"] is True
    assert approved["data"]["status"] == RefundStatus.COMPLETED.value


def test_non_admin_cannot_approve_refund(session_factory):
    """服务层也会拒绝普通客户发起的审批。"""
    with session_factory() as session:
        with session.begin():
            result = refund_service.approve_refund(
                session,
                admin_user_id="USR-001",
                refund_id="RFD-NOT-EXIST",
                decision="approve",
                now=datetime.now(timezone.utc),
            )

    assert result["ok"] is False
    assert result["code"] == "FORBIDDEN"
