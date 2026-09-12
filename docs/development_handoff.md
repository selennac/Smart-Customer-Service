# 智能客服系统开发交接文档

> 本文用于新建会话后的快速上下文恢复。开始后续开发前，优先阅读本文，其次阅读 `docs/project_spec.md` 和目标模块源码。

## 1. 项目目标与技术选型

这是一个本地模拟数据驱动的智能客服学习项目。系统不仅回答 FAQ，还要支持订单/物流查询、工单创建、退款处理、人工审批、多轮会话和流式输出。

已确定的技术方案：

- 后端：FastAPI + Uvicorn + SSE。
- Agent 编排：LangChain + LangGraph。
- 大模型：阿里云百炼 OpenAI 兼容接口，默认 `qwen-plus`。
- 向量模型：`text-embedding-v4`。
- 业务数据库：PostgreSQL 16 + SQLAlchemy 2.0 + psycopg。
- 图状态持久化：`PostgresSaver`。
- 向量库：本地持久化 Chroma。
- 前端：Vue 3 + Vite + TypeScript + Pinia。

环境变量模板位于 `.env.example`，本地配置位于 `.env`。关键变量包括：

```text
DATABASE_URL
CHECKPOINT_DATABASE_URL
CHECKPOINT_POOL_MIN_SIZE=1
CHECKPOINT_POOL_MAX_SIZE=10
CHECKPOINT_POOL_TIMEOUT_SECONDS=5
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
EMBEDDING_MODEL
CHROMA_PERSIST_DIRECTORY
KNOWLEDGE_BASE_PATH
REFUND_APPROVAL_THRESHOLD=500
DEMO_AUTH_ENABLED=true
```

Windows 下使用项目启动入口，以确保 psycopg 异步连接运行在兼容的事件循环上：

```powershell
.\.venv\Scripts\python.exe -m app.server
```

## 2. 已完成模块

### 2.1 领域模型和数据库会话

已完成：

- `app/db/models.py`
- `app/db/session.py`
- `scripts/create_tables.py`

主要实体：

| 实体 | 用途 |
|---|---|
| `User` | 用户、VIP 等级及管理员标识 `is_admin` |
| `Product` | 商品基础数据 |
| `Order` | 订单、商品明细 JSON、订单状态、物流单号、签收时间 |
| `LogisticsEvent` | 物流轨迹 |
| `Ticket` | 退款/换货/投诉工单 |
| `Refund` | 退款金额、原因、状态、审批人和审批时间 |
| `Thread` | 业务会话索引，用于展示和定位挂起会话 |

关键枚举：

```text
OrderStatus:
pending_shipment / in_transit / delivered / refunding / completed

TicketStatus:
open / in_progress / resolved / closed

RefundStatus:
pending_user / pending_supervisor / approved / rejected / completed

ThreadStatus:
active / pending_user / pending_supervisor / closed
```

### 2.2 模拟数据

已完成：`data/generate_mock_data.py`。

脚本会生成稳定的 `DEMO-*` 标识，重复运行安全；传入 `--replace` 会清理并重新生成模拟数据。每个演示用户至少有：运输中、签收 3 天、小额订单；签收 2 天、大额订单；签收 15 天、超期订单。

常用命令：

```powershell
python scripts/create_tables.py
python data/generate_mock_data.py --replace
```

### 2.3 RAG 知识库

已完成：

- `app/rag/ingest.py`：读取 Markdown、按 H2 与句子边界切分、附加元数据。
- `app/rag/retriever.py`：DashScope embedding、Chroma 建库和检索器创建。
- `scripts/ingest_knowledge.py`：知识库入库脚本。
- `data/knowledge/`：退款、退换货、物流、会员、常见问题五类文档。

每个块具有 `source`、`document_title`、`section_title`、`section_path`、`topic`、`document_type`、`chunk_index` 等元数据。`topic` 包括：

```text
refund / return_exchange / logistics / membership / faq
```

常用命令：

```powershell
python scripts/ingest_knowledge.py --recreate
```

## 3. Tools 与服务层设计

### 3.1 当前架构原则

1. `services` 是业务规则和事务的唯一真相来源。
2. `tools` 仅负责将 LangChain 的结构化调用适配到 service，不直接承载复杂 SQL 或状态迁移。
3. 统一客服 Agent 只获得 FAQ 检索和订单、物流、工单、退款状态查询工具。
4. 售后写操作工具保留在 `action_tools`，当前不绑定到通用客服 Agent，待售后子图接入后由受控节点调用。
5. 管理员审批不是 Agent tool，而是 FastAPI 管理端直接调用 service。
6. `user_id`、`thread_id`、管理员身份不允许模型填写，必须由认证和运行时上下文注入。

### 3.2 工具基础设施

工具目录和文件：

| 文件 | 职责 |
|---|---|
| `app/tools/context.py` | `ToolContext`：当前用户、会话、角色、数据库工厂、检索器、当前时间和审批阈值 |
| `app/tools/result.py` | 统一 `ToolResult`、`success()`、`failure()` 返回格式 |
| `app/tools/schemas.py` | 暴露给模型的 Pydantic 参数模型 |
| `app/tools/query_tools.py` | 面向统一客服 Agent 的订单、物流、工单和退款状态只读工具 |
| `app/tools/faq_tools.py` | 面向统一客服 Agent 的 FAQ 知识库检索工具 |
| `app/tools/policy_tools.py` | 退款资格评估 |
| `app/tools/action_tools.py` | 面向受控售后节点的轻量工具适配层 |
| `app/tools/__init__.py` | 公共工具构造函数导出 |

`ToolResult` 返回格式：

```python
{
    "ok": bool,
    "code": "OK | NOT_FOUND | FORBIDDEN | POLICY_REJECTED | ...",
    "message": "给节点和前端展示的说明",
    "data": {},
    "next_action": "none | user_confirm | supervisor_approval",
    "event": None,
}
```

统一客服 Agent 将工具调用结果以精简摘要追加到 LangGraph state 的 `tool_events`，FAQ 来源写入 `sources`。

### 3.3 查询与策略工具

`build_query_tools(ctx)` 创建以下只读 LangChain tools：

| 工具 | 参数 | 说明 |
|---|---|---|
| `list_orders` | `status?`, `limit` | 仅列出当前用户订单 |
| `get_order` | `order_id` | 查询当前用户订单详情 |
| `get_logistics` | `order_id` | 根据订单查询物流轨迹，不直接接受运单号 |
| `list_tickets` | `status?`, `limit` | 查询当前用户工单 |
| `get_refund_status` | `refund_id` | 查询当前用户退款状态 |

所有订单与退款查询都按 `ToolContext.user_id` 做数据隔离，不能通过模型参数越权查询其他用户记录。

`build_policy_tools(ctx)` 创建：

| 工具 | 用途 |
|---|---|
| `evaluate_refund` | 根据确定性规则评估订单是否可退款，不写库 |

FAQ 知识库检索由统一客服 Agent 调用 `search_faq` 工具完成。`policy_tools` 只保留确定性的退款资格评估能力，当前未绑定到通用客服 Agent。

### 3.4 退款规则

规则实现位于 `app/services/policy_service.py`：

- 仅 `delivered` 状态订单可申请退款。
- 必须有 `delivered_at`。
- 签收超过 7 天拒绝退款。
- 退款金额使用订单总额，使用 `Decimal`，不使用 float。
- 金额严格大于 `REFUND_APPROVAL_THRESHOLD` 时，需要管理员审批。

`evaluate_refund_order()` 返回资格、原因、签收天数、金额、审批阈值和是否需要审批。RAG 文档用于解释政策，但资格判定必须始终以此确定性代码为准。

### 3.5 工单和退款事务服务

当前服务：

| 文件 | 函数 | 调用方 |
|---|---|---|
| `app/services/ticket_service.py` | `create_ticket()` | 售后受控节点或 `action_tools` |
| `app/services/refund_service.py` | `create_refund_draft()` | 售后受控节点或 `action_tools` |
| `app/services/refund_service.py` | `confirm_refund()` | 用户确认后的 LangGraph 恢复节点 |
| `app/services/refund_service.py` | `list_pending_refunds()` | FastAPI 管理端 |
| `app/services/refund_service.py` | `approve_refund()` | FastAPI 管理端 |

所有写服务都接收已有的 SQLAlchemy `Session`，并要求调用方使用：

```python
with SessionLocal() as session:
    with session.begin():
        result = refund_service.confirm_refund(...)
```

这样 Graph 节点和 FastAPI 路由能复用相同事务边界；service 内部不会自行提交事务。

退款状态流程：

```text
create_refund_draft
  -> pending_user
  -> 用户确认后 confirm_refund
       -> 小额：completed
       -> 大额：pending_supervisor，线程状态改为 pending_supervisor
  -> 管理端 approve_refund
       -> approve：completed
       -> reject：rejected，订单恢复 delivered
```

幂等约束：

- 同一订单只允许一个活跃退款申请。
- 相同未完成工单重复提交时返回已有工单。
- 已完成或已拒绝退款再次审批时返回 `IDEMPOTENT_REPLAY`。
- `confirm_refund()` 会再次读取订单并校验政策，不能信任中断前状态。
- 退款确认和审批查询采用 `with_for_update()` 进行行锁保护。

管理员审批 service 会再次查询 `User.is_admin`，不只依赖 FastAPI 路由层鉴权。

### 3.6 管理员审批边界

当前没有 `app/tools/approval_tools.py`，管理员审批不通过 Agent tool 暴露。

管理员在 `/admin` 的人工点击是明确的业务操作，不应通过 LLM tool call 触发。管理员审批应由 API 的管理员鉴权依赖确认身份后，直接调用 `refund_service`。

同时，`build_action_tools()` 不再提供 `confirm_refund`。该函数只能由用户确认 `interrupt()` 恢复后的 LangGraph 节点直接调用 `refund_service.confirm_refund()`。

## 4. Graph 与节点实现

主图由 FastAPI lifespan 调用 `app.graph.build_graph(checkpointer=...)` 编译一次，API
统一通过 `ConversationService` 调用，不应在路由中临时编译。服务内部仍通过
`configurable` 注入受信任的运行时配置：

```python
result = await conversation_service.run(
    user_id=current_user.user_id,
    thread_id=thread_id,
    message="我的订单到哪里了？",
)
```

身份字段以运行时配置为准，模型输出和普通 graph input 不能覆盖认证的 `user_id`、`thread_id`。未注入数据库工厂时，图不会主动连接默认数据库；提供 `db_factory` 或 `tool_context` 后，`update_thread` 才会更新已有线程的 `last_message` 和状态。

当前主图流程为：

```text
START -> hydrate_context -> customer_service_agent
  -> 直接回复问候、能力咨询和非客服请求
  -> search_faq / 只读 Query Tools（按需调用）
  -> route_agent_result
     -> finalize_response（正常回答）
     -> fallback（模型/编排异常或空回答）
  -> update_thread -> END
```

通用 Agent 绑定 `search_faq` 和订单、物流、工单、退款状态查询工具，不绑定 `create_ticket`、`create_refund_draft` 等写工具。问候、能力咨询和非客服请求由 Agent 依据 `SystemMessage` 直接回复；模型或工具编排异常、空回答才进入 `fallback`。售后写操作待子图接入后由受控节点负责用户确认、主管审批和状态转换。

当前实现文件：

| 文件 | 当前职责 |
|---|---|
| `app/llm.py` | 构造 OpenAI 兼容的 ChatOpenAI，也支持节点运行时注入模型 |
| `app/nodes/common.py` | 解析运行时配置并构造 `ToolContext` |
| `app/nodes/customer_service.py` | 统一客服 ReAct Agent；通过显式 `SystemMessage` 约束身份、范围和工具使用 |
| `app/tools/faq_tools.py` | 将知识库检索封装为 `search_faq` 只读工具，并返回证据和来源 |
| `app/tools/query_tools.py` | 当前用户的订单、物流、工单及退款状态只读查询工具 |
| `app/graph.py` | 主图组装、fallback、响应整理和线程索引更新 |
| `app/main.py` | FastAPI 应用入口；lifespan 管理 checkpoint 连接池、retriever 和已编译主图 |
| `app/api/auth.py` | JWT 登录和当前用户鉴权依赖 |
| `app/api/chat.py` | `/api/v1/threads/{thread_id}/runs` 普通调用和 `/stream` SSE 调用 |
| `app/api/threads.py` | `/api/v1/threads` 会话创建、游标分页、摘要详情和消息历史接口 |
| `app/api/schemas.py` | HTTP/SSE 的稳定 Pydantic 契约 |
| `app/services/conversation_service.py` | 统一图调用、同会话串行化和公开流式事件转换 |
| `graph_design/main.mmd` | 主图设计图 |

`build_policy_tools(ctx)` 目前只返回 `evaluate_refund`，用于确定性的退款资格评估；该工具暂未绑定到通用客服 Agent。`action_tools` 仅供未来售后受控节点使用。

### 4.7 会话摘要与消息历史 API

`ThreadItem` 是会话索引项，只用于列表和摘要详情，字段包括状态、最后一条摘要和更新时间。
前端打开某个会话时，使用独立接口读取 checkpoint 中的公开消息：

```text
GET /api/v1/threads/{thread_id}/messages
```

返回的 `messages` 只包含 `user` 和 `assistant` 两种角色；Agent 的 `ToolMessage`、工具参数和检索原文属于内部执行数据，不直接返回给前端。当前接口会返回该线程 checkpoint 中的完整公开消息历史。

## 5. 未完成模块和推荐接入方式

以下能力仍未接入当前主图，下一步应按此顺序开发：

| 文件 | 开发内容 |
|---|---|
| 售后子图 | `graph_design/after_sale.mmd` 已描述退款/工单分支；代码仍需创建退款草稿、调用 `interrupt()`、恢复后确认退款或创建工单 |
| `app/graph.py` | 后续接入真实售后子图；主图当前已由 lifespan 使用 AsyncPostgresSaver 编译 |
| 恢复与审批 API | 增加用户确认恢复、管理员待审批列表和审批决定接口 |
| 前端 | 对接登录、聊天 SSE、会话列表和售后确认/审批交互 |

### 5.1 LangGraph 售后接入伪代码

```python
# 创建退款草稿的确定性节点
with SessionLocal() as session, session.begin():
    result = refund_service.create_refund_draft(
        session,
        user_id=state["user_id"],
        order_id=state["order_id"],
        reason=reason,
        now=datetime.now(timezone.utc),
        approval_threshold=Decimal(os.environ["REFUND_APPROVAL_THRESHOLD"]),
    )

# 命中 user_confirm 后：
confirmed = interrupt({"kind": "refund_confirmation", "refund": result["data"]})
if confirmed:
    with SessionLocal() as session, session.begin():
        result = refund_service.confirm_refund(...)
```

注意：`interrupt()` 恢复时使用同一 `thread_id` 的图配置；不要把退款确认操作交给 ReAct Agent。

### 5.2 FastAPI 管理端接入伪代码

```python
@router.get("/admin/refunds/pending")
def pending_refunds(current_admin=Depends(require_admin)):
    with SessionLocal() as session:
        return refund_service.list_pending_refunds(
            session,
            admin_user_id=current_admin.user_id,
        )

@router.post("/admin/refunds/{refund_id}/decision")
def decide_refund(refund_id: str, body: DecisionBody, current_admin=Depends(require_admin)):
    with SessionLocal() as session, session.begin():
        result = refund_service.approve_refund(
            session,
            admin_user_id=current_admin.user_id,
            refund_id=refund_id,
            decision=body.decision,
            now=datetime.now(timezone.utc),
        )
    # 审批成功后使用对应 thread_id 执行 Command(resume=...) 恢复图。
    return result
```

当前 `Refund` 模型没有 `thread_id` 字段。管理员 API 恢复 LangGraph 时，需要从请求携带 thread_id、前端审批卡上下文或后续增加明确的退款-会话关联字段中获取。不要根据用户 ID 猜测唯一会话。

## 6. 状态与接口约束

`app/state.py` 已定义：

```text
messages, thread_id, user_id, answer, sources, tool_events,
last_message, error
```

`ToolContext` 应由 API/节点按当前认证用户构造，例如：

```python
context = ToolContext(
    user_id=current_user.user_id,
    thread_id=thread_id,
    actor_role="customer",
    retriever=retriever,
)
```

默认数据库工厂采用惰性导入，测试注入 SQLite session factory 时不会因为导入时读取 PostgreSQL 配置而失败。

## 7. 测试现状

当前工作区没有可由 pytest 收集的测试文件。本轮接口重构按要求未新增测试用例。
最近一次非测试类检查结果：

```text
python -m compileall -q app 通过
OpenAPI schema 生成通过，共 7 个公开路径
SSE 事件过滤与完成事件的内联冒烟检查通过
```

本机 PostgreSQL 5432 端口当前不可达，因此认证、真实 checkpoint 生命周期、聊天和知识库检索尚未进行端到端验证。

## 8. 继续开发时的注意事项

1. 所有新增注释和文档字符串使用中文。
2. 不要把 `user_id`、管理员标识、数据库 session 暴露为模型可填写的 tool 参数。
3. 不要让 Agent 自主调用用户确认退款或管理员审批。
4. 不要在 Graph 节点、API 路由和 tools 中复制退款规则；统一调用 `refund_service` 和 `policy_service`。
5. 写操作必须由调用方显式使用 `session.begin()` 管理事务。
6. 金额使用 `Decimal`；跨 API、SSE、Graph state 时使用字符串序列化。
7. RAG 检索结果仅作为政策解释与来源引用，不能替代确定性退款资格判断。
8. 管理员审批后恢复图前，必须可靠地获得原始 `thread_id`。
9. `user_id`、`thread_id` 和数据库工厂必须从运行时配置注入；不要从模型输出或普通 graph input 信任这些字段。

## 9. 快速阅读清单

新会话建议按下列顺序阅读：

1. `docs/development_handoff.md`（本文）。
2. `docs/project_spec.md`（完整需求和演示脚本）。
3. `app/state.py`、`app/db/models.py`（状态与领域模型）。
4. `app/services/refund_service.py`、`app/services/policy_service.py`（关键业务规则）。
5. `app/tools/`（Agent 工具边界）。
6. `tests/test_customer_service_agent.py`（统一客服 Agent 当前行为预期）。
7. 再进入 `app/nodes/customer_service.py`、`app/graph.py`、`app/api/` 和 `frontend/` 开发未完成模块。
