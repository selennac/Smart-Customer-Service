"""Generate demo users, orders, products, and logistics events.

Run from the project root after the business tables have been created::

    python data/generate_mock_data.py
    python data/generate_mock_data.py --users 8 --orders-per-user 6 --replace

The generated records use stable ``DEMO-*`` identifiers.  This makes it safe to
run the script repeatedly; use ``--replace`` to remove the previous demo set
before inserting the requested set again.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.models import LogisticsEvent, Order, OrderStatus, Product, User, VipLevel  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


DEMO_USER_PREFIX = "DEMO-USR-"
DEMO_ORDER_PREFIX = "DEMO-ORD-"
DEMO_TRACKING_PREFIX = "DEMO-TRK-"

# 管理员用户 ID（固定，方便登录测试）
DEMO_ADMIN_USER_ID = f"{DEMO_USER_PREFIX}ADMIN"

PRODUCTS: tuple[dict[str, Any], ...] = (
    {"sku_id": "DEMO-SKU-001", "name": "无线降噪耳机", "category": "数码", "price": Decimal("399.00")},
    {"sku_id": "DEMO-SKU-002", "name": "智能手环", "category": "数码", "price": Decimal("249.00")},
    {"sku_id": "DEMO-SKU-003", "name": "便携咖啡机", "category": "家电", "price": Decimal("599.00")},
    {"sku_id": "DEMO-SKU-004", "name": "保温杯", "category": "家居", "price": Decimal("89.00")},
)

LOCATIONS = ("深圳仓", "广州转运中心", "长沙分拨中心", "武汉转运中心", "北京配送站")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _user_name(index: int) -> str:
    # Keep the first four names aligned with the project specification's A-D demo users.
    suffix = chr(ord("A") + index) if index < 26 else str(index + 1)
    return f"测试用户{suffix}"


def _status_plan(orders_per_user: int) -> list[tuple[OrderStatus, int | None]]:
    """Return one in-transit order and delivered orders with the requested ages."""
    plan: list[tuple[OrderStatus, int | None]] = [
        (OrderStatus.IN_TRANSIT, None),
        (OrderStatus.DELIVERED, 3),
        (OrderStatus.DELIVERED, 2),
        (OrderStatus.DELIVERED, 15),
    ]
    # A fifth order is required by the demo contract; repeat the 3-day scenario.
    while len(plan) < orders_per_user:
        plan.append((OrderStatus.DELIVERED, 3))
    return plan[:orders_per_user]


def _logistics_rows(
    tracking_no: str,
    created_at: datetime,
    status: OrderStatus,
    delivered_at: datetime | None,
) -> list[LogisticsEvent]:
    events: list[tuple[datetime, str, str]] = [
        (created_at + timedelta(hours=1), LOCATIONS[0], "已揽收，商品离开仓库"),
        (created_at + timedelta(days=1), LOCATIONS[1], "运输中，已到达转运中心"),
    ]
    if status is OrderStatus.DELIVERED and delivered_at is not None:
        events.extend(
            [
                (delivered_at - timedelta(days=1), LOCATIONS[4], "派送中"),
                (delivered_at, LOCATIONS[4], "已签收"),
            ]
        )
    else:
        events.extend(
            [
                (created_at + timedelta(hours=12), LOCATIONS[2], "运输中，已完成干线装车"),
                (_utcnow() - timedelta(hours=2), LOCATIONS[2], "运输中，预计 1-2 天送达"),
            ]
        )

    # Make timestamps strictly increasing even when a caller supplies unusual dates.
    events.sort(key=lambda item: item[0])
    return [
        LogisticsEvent(
            tracking_no=tracking_no,
            event_time=event_time,
            location=location,
            status=description,
        )
        for event_time, location, description in events
    ]


def _remove_demo_data(session: Session) -> None:
    session.execute(delete(LogisticsEvent).where(LogisticsEvent.tracking_no.like(f"{DEMO_TRACKING_PREFIX}%")))
    session.execute(delete(Order).where(Order.order_id.like(f"{DEMO_ORDER_PREFIX}%")))
    session.execute(delete(User).where(User.user_id.like(f"{DEMO_USER_PREFIX}%")))


def generate_demo_data(
    session: Session,
    *,
    user_count: int = 4,
    orders_per_user: int = 5,
    seed: int = 20260908,
    replace: bool = False,
) -> dict[str, int]:
    """插入演示数据集并返回已插入实体的数量。

    该函数有意基于 session 实现，这样测试可以传入内存中的
    SQLite session，而无需依赖命令行环境。
    """
    if user_count < 1:
        raise ValueError("user_count must be at least 1")
    if orders_per_user < 5:
        raise ValueError("orders_per_user must be at least 5")

    if replace:
        _remove_demo_data(session)

    rng = random.Random(seed)
    now = _utcnow()
    products: list[Product] = []
    for product_data in PRODUCTS:
        product = session.get(Product, product_data["sku_id"])
        if product is None:
            product = Product(**product_data)
            session.add(product)
        products.append(product)
    session.flush()

    # 先创建管理员用户（不参与普通用户的循环，避免命名/编号冲突）
    admin = session.get(User, DEMO_ADMIN_USER_ID)
    if admin is None:
        admin = User(user_id=DEMO_ADMIN_USER_ID, name="管理员")
        session.add(admin)
    admin.name = "管理员"
    admin.vip_level = VipLevel.GOLD
    admin.is_admin = True
    session.flush()
    # ─────────────────────────────────────────────────────

    status_plan = _status_plan(orders_per_user)
    order_count = 0
    event_count = 0
    for user_index in range(user_count):
        user_id = f"{DEMO_USER_PREFIX}{user_index + 1:03d}"
        user = session.get(User, user_id)
        if user is None:
            user = User(user_id=user_id, name=_user_name(user_index))
            session.add(user)
        user.name = _user_name(user_index)
        user.vip_level = (VipLevel.REGULAR, VipLevel.SILVER, VipLevel.GOLD)[user_index % 3]
        user.is_admin = False
        session.flush()

        for order_index, (status, age_days) in enumerate(status_plan, start=1):
            order_id = f"{DEMO_ORDER_PREFIX}{user_index + 1:03d}-{order_index:02d}"
            tracking_no = f"{DEMO_TRACKING_PREFIX}{user_index + 1:03d}-{order_index:02d}"
            existing = session.get(Order, order_id)
            if existing is not None:
                session.execute(delete(LogisticsEvent).where(LogisticsEvent.tracking_no == tracking_no))
                session.delete(existing)
                session.flush()

            selected = rng.choice(products)
            quantity = rng.randint(1, 2)
            amount = selected.price * quantity
            delivered_at = now - timedelta(days=age_days) if age_days is not None else None
            created_at = (
                delivered_at - timedelta(days=4, hours=2)
                if delivered_at is not None
                else now - timedelta(days=2, hours=3)
            )
            order = Order(
                order_id=order_id,
                user_id=user_id,
                items=[
                    {
                        "sku_id": selected.sku_id,
                        "name": selected.name,
                        "quantity": quantity,
                        "unit_price": str(selected.price),
                    }
                ],
                total_amount=amount,
                status=status,
                tracking_no=tracking_no,
                delivered_at=delivered_at,
                created_at=created_at,
                updated_at=now,
            )
            session.add(order)
            logistics_rows = _logistics_rows(tracking_no, created_at, status, delivered_at)
            session.add_all(logistics_rows)
            order_count += 1
            event_count += len(logistics_rows)

    session.commit()
    return {"users": user_count, "products": len(products), "orders": order_count, "logistics_events": event_count}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate demo customer-service data.")
    parser.add_argument("--users", type=int, default=4, dest="user_count", help="number of test users (default: 4)")
    parser.add_argument(
        "--orders-per-user", type=int, default=5, help="orders per user, minimum 5 (default: 5)"
    )
    parser.add_argument("--seed", type=int, default=20260908, help="random seed for product/quantity choices")
    parser.add_argument("--replace", action="store_true", help="delete the previous DEMO-* dataset first")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with SessionLocal() as session:
        counts = generate_demo_data(
            session,
            user_count=args.user_count,
            orders_per_user=args.orders_per_user,
            seed=args.seed,
            replace=args.replace,
        )
    print(
        "Generated demo data: "
        + ", ".join(f"{key}={value}" for key, value in counts.items())
    )


if __name__ == "__main__":
    main()
