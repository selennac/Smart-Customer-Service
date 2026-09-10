# 智能客服系统（LangChain + LangGraph 实战项目）

> 一个不仅回答问题、还能执行操作的 AI 客服：查询订单、创建工单、处理退款，
> 支持人工审批介入、多轮对话记忆与流式输出。所有业务数据为本地模拟。

---

## 1. 项目概述

### 1.1 项目定位

| 维度 | 说明 |
|---|---|
| 性质 | 个人学习项目（覆盖 LangChain / LangGraph 核心知识点） |
| 形态 | 前后端分离的完整系统：Vue3 前端 + FastAPI 服务 + LangGraph 编排 |
| 数据 | 全部模拟（Faker 生成业务数据 + 手写知识库文档） |
| 总周期 | 业余时间每天 8 小时，约 1-2 周 |

### 1.2 核心功能

| 能力 | 用户示例 | 背后技术 |
|---|---|---|
| FAQ 知识问答 | "退货政策是什么？" | RAG 全链路 |
| 订单/物流查询 | "我的订单到哪了？" | 工具调用 + 只读查库 |
| 创建工单 | "我要投诉物流太慢" | 结构化输出 + 写库 |
| 处理退款（小额） | "订单 ORD-xxx 退款" | 工具调用 + 用户确认（interrupt） |
| 处理退款（大额 >¥500） | — | 双重确认 + 主管审批（HITL） |
| 多轮对话记忆 | 跨轮次上下文 | Checkpointer + thread_id |
| 流式输出 | 打字机效果 | SSE 多事件协议 |

### 1.3 学习目标：知识点覆盖矩阵

| 模块 | 覆盖知识点 |
|---|---|
| RAG | DocumentLoader / TextSplitter / Embeddings / Chroma / Retriever / LCEL |
| 工具调用 | @tool / Pydantic args_schema / docstring 设计 / ReAct Agent |
| LangGraph 核心 | StateGraph / TypedDict State / add_messages / 条件边路由 |
| HITL | interrupt() / Command(resume=) / 挂起-恢复机制 |
| 持久化 | AsyncPostgresSaver / thread_id 会话隔离 / checkpoint 恢复 |
| 工程化 | FastAPI lifespan / SSE 流式 / 异步架构 / 事务 / 越权校验 |
| 进阶（选修） | Supervisor 多 Agent / 时间旅行 / 意图分类评测 |

**刻意设计的学习路径**：ReAct Agent（LLM 自主决策）→ 显式图路由（人控制流程）→ 多 Agent，
完成后可真正理解三种范式的适用场景差异。

---

## 2. 技术选型（已敲定）

| 项 | 选型 | 说明 |
|---|---|---|
| LLM | qwen-plus | 阿里云百炼，OpenAI 兼容模式接入 |
| Embedding | text-embedding-v4 | 同在百炼，兼容模式接入 |
| 业务数据库 | PostgreSQL 16 (虚拟机中已有此服务) | 业务数据 + LangGraph checkpoint 统一存放 |
| Checkpointer | PostgresSaver | 官方包 langgraph-checkpoint-postgres |
| 向量库 | Chroma | 持久化到本地磁盘 |
| ORM | SQLAlchemy 2.0 + psycopg3 | 同步访问业务表 |
| 后端 | FastAPI + uvicorn | SSE 流式接口 |
| 前端 | Vue3 + Vite + TS + Pinia | 聊天页 + 管理员审批台 |


---

## 3. 系统架构

### 3.1 架构图

```
                ┌────────────────────────────────┐
                │  Vue3 前端                      │
                │  /login 登录 │ /chat 聊天   │
                │  /admin 主管审批台               │
                └───────────────┬────────────────┘
                                │ HTTP + SSE (fetch stream)
                ┌───────────────▼────────────────┐
                │  FastAPI                       │
                │  lifespan 管理 graph 与连接池    │
                │  REST + SSE 事件协议            │
                └───────────────┬────────────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │  LangGraph 主图                     │
              │  意图识别 → 条件路由 → 业务节点      │
              │  + PostgresSaver 持久化        │
              └────┬─────────┬─────────┬───────────┘
                   │         │         │
            ┌──────▼───┐ ┌───▼─────┐ ┌─▼─────────────┐
            │ FAQ/RAG  │ │ 订单查询 │ │ 售后/退款      │
            │ 检索问答  │ │ Agent  │ │ (interrupt子图) │
            └──────┬───┘ └───┬─────┘ └─┬─────────────┘
                   │         │         │
            ┌──────▼─────────▼─────────▼─────────────┐
            │  Tools: 查订单/查物流/建工单/执行退款   │
            │  (写操作校验归属 + 事务)               │
            └──────┬────────────────────┬────────────┘
                   │                    │
        ┌──────────▼─────────┐  ┌───────▼──────────────┐
        │  PostgreSQL        │  │  Chroma 向量库        │
        │  业务表 + checkpoint│  │  (知识库文档检索)      │
        └────────────────────┘  └──────────────────────┘
```

### 3.2 典型数据流

**小额退款（含 HITL）**：

```
用户："我要退 ORD-xxx"
→ POST /api/chat/stream
→ 意图识别(after_sale) → 退款子图
→ 查订单 → 校验政策 → 计算金额 ¥89
→ interrupt(user_confirm) 图挂起
→ SSE 推送 interrupt 事件 → 前端渲染确认卡片
→ 用户点击"确认" → POST /api/threads/{id}/resume
→ Command(resume=True) 恢复图 → 事务性落库 → SSE 推送结果
```

**大额退款**：金额 > ¥500 时，用户确认后再次 `interrupt(supervisor)`，
threads 表状态更新为 `pending_supervisor`，主管在 /admin 审批后 resume。

---

## 4. 模拟数据设计

### 4.1 业务表（PostgreSQL）

| 表 | 关键字段 |
|---|---|
| users | user_id, name, vip_level(普通/银卡/金卡) |
| products | sku_id, name, category, price |
| orders | order_id, user_id, items(**JSONB**), total_amount, status(待发货/运输中/已签收/退款中/已完成), tracking_no |
| logistics_events | tracking_no, 时间, 地点, 状态（使"查物流"能返回轨迹列表） |
| tickets | ticket_id, user_id, order_id, type(退款/换货/投诉), status, description |
| refunds | refund_id, order_id, amount, reason, status |
| threads | thread_id, user_id, status(active/pending_user/pending_supervisor/closed), last_message |

> threads 表是"管理员发现待审批会话"的业务索引（LangGraph 本身无列出所有
> thread 的 API）。

### 4.2 知识库文档（手写 Markdown，每篇 600~1000 字）

- `退换货政策.md`：7 天无理由、30 天质量问题、特殊商品除外
- `退款政策.md`：审核时效、原路退回时效、大额需主管审核
- `物流配送说明.md` / `会员权益.md` / `常见问题.md`

> ⚠️ 政策规则必须与退款工具的代码逻辑一致（如"签收超 7 天拒绝无理由退款"），
> 才能演示"模型依据检索到的政策正确拒绝用户"。

### 4.3 演示剧本用户（保证每个分支可触发）

| 用户 | 订单设计 | 预期演示 |
|---|---|---|
| A | "运输中"订单 | 查物流返回轨迹列表 |
| B | 已签收 3 天，¥89 | 小额退款：用户确认即完成 |
| C | 已签收 2 天，¥1299 | 大额退款：触发主管审批挂起 |
| D | 已签收 15 天 | 退款被政策拒绝 |

---

## 5. 项目目录结构

```
smart-customer-service/
├── .env
├── requirements.txt
├── app/
│   ├── main.py              # FastAPI 入口 + lifespan
│   ├── graph.py             # LangGraph 主图组装
│   ├── state.py             # State 定义
│   ├── nodes/
│   │   ├── classify.py      # 意图识别（结构化输出）
│   │   ├── faq.py           # RAG 问答节点
│   │   ├── order.py         # 订单 ReAct Agent 节点
│   │   └── after_sale.py    # 售后子图（退款/工单）
│   ├── tools/
│   │   ├── query_tools.py   # 只读：订单/物流查询
│   │   └── action_tools.py  # 写操作：工单/退款
│   ├── rag/
│   │   ├── ingest.py        # 文档入库脚本
│   │   └── retriever.py
│   └── db/
│       ├── models.py        # SQLAlchemy 模型
│       └── session.py
├── data/
│   ├── generate_mock_data.py
│   └── knowledge/           # 5 篇政策/FAQ Markdown
├── frontend/                # Vue3 + Vite
│   └── src/
│       ├── views/           # LoginView / ChatView / AdminView
│       ├── components/      # MessageItem / InterruptCard / OrderCard / ToolStatus
│       ├── stores/chat.ts   # Pinia
│       └── api/sse.ts       # fetch 流式解析封装

```
