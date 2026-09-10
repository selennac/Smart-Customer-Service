"""所有 Agent 工具共享的可序列化结果封装。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

NextAction = Literal["none", "user_confirm", "supervisor_approval"]


class ToolResult(BaseModel):
    """稳定的工具输出，可直接写入图状态并转换为 SSE 事件。"""

    ok: bool
    code: str
    message: str
    data: Any = None
    next_action: NextAction = "none"
    event: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def success(
    data: Any = None,
    *,
    message: str = "操作成功",
    code: str = "OK",
    next_action: NextAction = "none",
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return ToolResult(
        ok=True,
        code=code,
        message=message,
        data=data,
        next_action=next_action,
        event=event,
    ).as_dict()


def failure(
    code: str,
    message: str,
    *,
    data: Any = None,
    next_action: NextAction = "none",
) -> dict[str, Any]:
    return ToolResult(
        ok=False,
        code=code,
        message=message,
        data=data,
        next_action=next_action,
    ).as_dict()


__all__ = ["NextAction", "ToolResult", "success", "failure"]
