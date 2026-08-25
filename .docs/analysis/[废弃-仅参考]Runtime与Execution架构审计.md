# Runtime ↔ Execution 架构审计报告

> 日期: 2026-06-16
> 方法: 纯代码分析，零修改
> 范围: `runtime/` vs `execution/` 职责边界

---

## 1. 实际目录结构

### runtime/ （2 个源文件 + `__init__.py`）

```
runtime/
├── __init__.py    — 公开 API：re-export Runtime, create_runtime, ContextBuilder；
│                    同时 re-export ExecutionPlan / PlanStep（从 execution 层）
├── factory.py     — create_runtime() 工厂函数 + Runtime 容器类
└── context.py     — ContextBuilder：system_prompt 组装（6 级优先级 + token budget）
```

### execution/ （6 个源文件 + `__init__.py`）

```
execution/
├── __init__.py    — 公开 API：re-export 全部 execution 类型
├── request.py     — ExecutionRequest / ExecutionPlan / PlanStep（Pydantic 数据模型）
├── response.py    — ExecutionResponse（Pydantic 响应模型）
├── state.py       — ExecutionState（dataclass，跟踪单次执行生命周期）
├── planner.py     — Planner（LangGraph StateGraph: classify→select_skills→build_plan→validate）
├── pipeline.py    — ExecutionPipeline（三条执行路径：workflow / 多步编排 / 直接对话）
└── executor.py    — Executor（统一执行入口，持有 Planner + Pipeline）
```

---

## 2. 真实调用链

以下调用链根据实际 `import` 语句和代码路径绘制，未做任何推测。

### 2.1 CLI 路径（`interface/cli/repl.py`）

```
main_cli()
  │
  └─ run_repl()
       │
       ├─ runtime = await create_runtime(channel="cli")   ← haven.runtime.factory
       │    │
       │    └─ Runtime(executor, llm, registry, checkpointer, session_manager, agents, ...)
       │         │
       │         └─ executor = Executor(planner, pipeline, session_manager)
       │              │
       │              ├─ planner = Planner(llm, workflow_registry, capability_registry)
       │              └─ pipeline = ExecutionPipeline(agents, workflow_registry, ...)
       │
       └─ for each user input:
            runtime.execute_stream(user_input)             ← Runtime 实例方法
              │
              ├─ request = ExecutionRequest(task, session_id)
              ├─ async for chunk in self.executor.execute_stream(request):
              │    │
              │    ├─ session = session_manager.get_or_create(session_id)
              │    ├─ plan = await planner.plan(request)         ← Planner (LangGraph)
              │    ├─ yield StreamChunk(kind="plan", ...)
              │    └─ async for chunk in pipeline.run_stream(plan, task, session):
              │         │
              │         ├─ [Path 1: workflow] → WorkflowEngine.run()
              │         ├─ [Path 2: multi-step] → agent.run() per step (独立 UUID)
              │         └─ [Path 3: direct] → agent.astream()
              │
              └─ _trigger_memory(task, collected_text)     ← 异步后台写入
```

### 2.2 HTTP 路径（`interface/http_server.py`）

```
HTTPServer._handle()
  │
  └─ result = await self._runtime.execute(task)            ← Runtime 实例方法
       │
       └─ self.executor.execute(request)                   ← 同步（非流式）
            │
            ├─ plan = await planner.plan(request)
            └─ result = await pipeline.run(plan, task, session)
```

### 2.3 Daemon 路径（`interface/daemon.py`）

```
HavenDaemon._init_runtime()
  │
  └─ self.runtime = await create_runtime(session_id="daemon", ...)

FeishuChannel._handle_event()
  │
  └─ response = await self._session.execute(text)          ← self._session == Runtime 实例
```

### 2.4 依赖方向图

```
Interface (CLI / HTTP / Daemon / FeishuChannel)
  │
  ├─ import haven.runtime.factory → create_runtime()
  ├─ 调用 runtime.execute() / runtime.execute_stream()
  │
  ▼
Runtime (runtime/factory.py)
  │
  ├─ import haven.execution.executor → Executor
  ├─ import haven.execution.planner → Planner
  ├─ import haven.execution.pipeline → ExecutionPipeline
  ├─ import haven.execution.request → ExecutionRequest
  │
  ▼
Executor (execution/executor.py)
  │
  ├─ import Planner, ExecutionPipeline
  ├─ import ExecutionRequest, ExecutionResponse
  │
  ▼
Planner (execution/planner.py)
  │
  └─ LangGraph StateGraph → LLM Structured Output → ExecutionPlan

ExecutionPipeline (execution/pipeline.py)
  │
  ├─ import haven.runtime.context → ContextBuilder   ← ⚠️ 反向依赖！
  ├─ import haven.workflow.engine → WorkflowEngine
  └─ 调用 agent.run() / agent.astream()
```

### 2.5 关键发现：反向依赖

```
runtime/factory.py  →  execution/executor.py     ✅ 正常（上层依赖下层）
runtime/factory.py  →  execution/planner.py      ✅ 正常
runtime/factory.py  →  execution/pipeline.py     ✅ 正常
execution/pipeline.py → runtime/context.py       ⚠️ 反向（下层依赖上层）
```

`ExecutionPipeline._build_sp()` 需要 `ContextBuilder` 来构建 system prompt，但 `ContextBuilder` 位于 `runtime/` 层。这是唯一的层级违规。

---

## 3. Runtime 模块职责分析

### 3.1 `runtime/factory.py` — `create_runtime()` 工厂函数

| 维度 | 内容 |
|------|------|
| **职责** | 组装完整 Haven 运行时：Config → LLM → CapabilityLoader → SessionManager → MemoryManager → Agents → ExecutionPipeline → Executor → Runtime |
| **输入** | `session_id`, `entity_name`, `channel`, `load_skills`, `load_mcp`, `use_memory` |
| **输出** | `Runtime` 实例（完全装配） |
| **依赖** | Config, ModelFactory, CapabilityLoader, SessionManager, Agent, Planner, ExecutionPipeline, Executor, MemoryManager, ContextBuilder, WorkflowRegistry |
| **被谁调用** | `interface/cli/repl.py:42`, `interface/daemon.py:101` |

> **如果删除该函数：** 系统无法启动。所有 Interface 入口直接依赖它。但可以移到 Interface 层或新建 `bootstrap.py`。

### 3.2 `runtime/factory.py` — `Runtime` 类

| 维度 | 内容 |
|------|------|
| **职责** | 运行时容器：持有 Executor + 所有子系统引用；提供 `execute()` / `execute_stream()` 入口；管理 Session 生命周期、Model 切换、Memory 触发、资源清理 |
| **输入** | executor, llm, registry, checkpointer, session_manager, agents, memory_manager, model_factory |
| **输出** | `execute()` → `str`, `execute_stream()` → `AsyncIterator[StreamChunk]` |
| **依赖** | Executor, SessionManager, Agent, MemoryManager, ModelFactory, CapabilityRegistry |
| **被谁调用** | `interface/cli/repl.py`, `interface/http_server.py`, `interface/channels/feishu.py` |

#### 方法分析

| 方法 | 逻辑复杂度 | 是否薄封装 | 说明 |
|------|:---:|:---:|------|
| `execute()` | 低 | ✅ 薄封装 | 创建 ExecutionRequest → executor.execute() → trigger memory. 实际 4 行有效代码 |
| `execute_stream()` | 低 | ✅ 薄封装 | 同 execute()，流式版。收集 text chunks 用于 memory |
| `reset_session()` | **高** | ❌ | UUID 切换、旧 session close、checkpointer 清理、新 session 创建、Agent reset。约 25 行有效逻辑 |
| `switch_model()` | **中** | ❌ | 遍历所有 Agent 替换 LLM、清除 _agent 缓存。约 8 行有效逻辑 |
| `flush_memory()` | 低 | ✅ 薄封装 | await memory task（5s timeout） |
| `reset()` | 低 | ✅ 薄封装 | 遍历 agents 调用 reset() |
| `close()` | **中** | ❌ | CapabilityLoader.stop_all() + SQLite connection close |

> **如果删除该类：** `execute()` / `execute_stream()` 的薄封装可移至 Executor；`reset_session()` / `switch_model()` / `close()` 是真正的跨切面逻辑，需要找到新家。

### 3.3 `runtime/context.py` — `ContextBuilder`

| 维度 | 内容 |
|------|------|
| **职责** | 按 6 级优先级 + token budget 组装 system_prompt：①Personality ②Agent prompt ③Skills ④Project files ⑤Memory/History ⑥Channel hint |
| **输入** | `agent_prompt`, `skills`, `task`, `history_summary`, `memory_items`, `channel` |
| **输出** | `BuildResult(system_prompt, token_usage)` |
| **依赖** | Config (token_budget, memory_token_budget), MemoryItem |
| **被谁调用** | `execution/pipeline.py:_build_sp()` — **唯一调用者** |

> **如果删除该文件：** Pipeline 无法构建 system prompt。所有 Agent 调用将缺少人格/技能/记忆上下文。但注意：它是 `execution/` 的唯一 `runtime/` 依赖。

---

## 4. Execution 模块职责分析

### 4.1 `execution/request.py` — 数据模型

| 维度 | 内容 |
|------|------|
| **职责** | 定义 ExecutionRequest（用户输入）、ExecutionPlan（规划输出）、PlanStep（步骤） |
| **输入** | Pydantic 模型定义 |
| **输出** | Pydantic BaseModel 类 |
| **依赖** | 仅 pydantic |
| **被谁调用** | Executor, Planner, Pipeline, Runtime factory, Runtime `__init__.py`（re-export） |

> **如果删除该文件：** 整个 execution 层的数据流断裂。Executor/Planner/Pipeline 全部依赖它。

### 4.2 `execution/response.py` — 响应模型

| 维度 | 内容 |
|------|------|
| **职责** | ExecutionResponse：result + events + trace_id + plan_summary + errors |
| **输入** | Pydantic 模型定义 |
| **输出** | Pydantic BaseModel 类 |
| **依赖** | kernel.event.AgentEvent |
| **被谁调用** | Executor（构造返回值） |

> **如果删除该文件：** Executor 无法返回结构化响应。

### 4.3 `execution/state.py` — 运行时状态

| 维度 | 内容 |
|------|------|
| **职责** | ExecutionState dataclass：跟踪单次执行生命周期（task, session_id, trace_id, plan, status） |
| **输入** | 无 |
| **输出** | dataclass 类 |
| **依赖** | execution.request.ExecutionPlan |
| **被谁调用** | `execution/__init__.py` re-export；实际业务代码中**零使用** |

> **如果删除该文件：** 系统正常运行。该 dataclass 定义了但未被任何业务逻辑引用（仅在 `__init__.py` 中 re-export）。

### 4.4 `execution/planner.py` — 任务规划器

| 维度 | 内容 |
|------|------|
| **职责** | 基于 LangGraph 的任务规划：classify → select_skills → build_plan → validate；LLM Structured Output 生成 ExecutionPlan |
| **输入** | `ExecutionRequest` |
| **输出** | `ExecutionPlan` |
| **依赖** | LangGraph, LLM (BaseChatModel), CapabilityRegistry, WorkflowRegistry |
| **被谁调用** | Executor.plan() — **唯一调用者** |

> **如果删除该文件：** Planner 需要重写。目前已有 LangGraph flow，是执行链的核心环节。

### 4.5 `execution/pipeline.py` — 执行管道

| 维度 | 内容 |
|------|------|
| **职责** | 根据 ExecutionPlan 路由到三条执行路径；构建 system prompt（通过 ContextBuilder）；拓扑排序多步编排；调用 Agent/WorkflowEngine |
| **输入** | `ExecutionPlan`, `task: str`, `Session` |
| **输出** | `str` (run) / `AsyncIterator[StreamChunk]` (run_stream) |
| **依赖** | ContextBuilder (runtime!), WorkflowEngine, Agent, SessionManager, CapabilityRegistry, MemoryManager |
| **被谁调用** | Executor.execute() / Executor.execute_stream() — **唯一调用者** |

> **如果删除该文件：** 执行管道需要重写。三条路径（workflow/steps/direct）都在此类中。

### 4.6 `execution/executor.py` — 执行编排器

| 维度 | 内容 |
|------|------|
| **职责** | 统一执行入口：持有 Planner + Pipeline；管理 TraceContext；提供 execute() / execute_stream() |
| **输入** | `ExecutionRequest` |
| **输出** | `ExecutionResponse` (execute) / `AsyncIterator[StreamChunk]` (execute_stream) |
| **依赖** | Planner, ExecutionPipeline, SessionManager, TraceContext, ExecutionResponse |
| **被谁调用** | `Runtime.execute()` / `Runtime.execute_stream()` — **唯一调用者** |

> **如果删除该文件：** Runtime 必须直接持有 Planner + Pipeline。但这是有意设计的——Architecture 规范要求 "Runtime 只能通过 Executor 执行任务"。

---

## 5. 职责重叠分析

| 职责 | Runtime 负责 | Execution 负责 | 是否重复 |
|------|:---:|:---:|:---:|
| **调度** (dispatch) | ❌ | ✅ Planner 决定 agent_type/workflow | 不重复 |
| **编排** (orchestration) | ❌ | ✅ Pipeline 三条路径 + 拓扑排序 | 不重复 |
| **Agent 调用** | ❌ | ✅ Pipeline._via_steps / 直接对话路径 | 不重复 |
| **Workflow 调用** | ❌ | ✅ Pipeline._via_workflow → WorkflowEngine | 不重复 |
| **Request 处理** | ✅ 创建 ExecutionRequest | ✅ 消费 ExecutionRequest | 补充关系 |
| **Response 处理** | ✅ 触发 Memory 后处理 | ✅ 构造 ExecutionResponse | 补充关系 |
| **Streaming** | ✅ 收集 chunks 用于 memory | ✅ 产生 & yield chunks | 补充关系 |
| **Event 分发** | ❌ | ❌（均未处理 AgentEvent） | ⬜ 空白 |
| **System Prompt 构建** | ✅ ContextBuilder (在 runtime/) | ✅ Pipeline._build_sp() 调用 ContextBuilder | **位置异常** |
| **Session 生命周期** | ✅ reset_session / close | ❌ | 不重复 |
| **Model 管理** | ✅ switch_model / llm 引用 | ❌（Planner 持有自己的 llm） | 不重复 |
| **Memory 集成** | ✅ trigger + flush | ❌（Pipeline 仅调用 retrieve） | 不重复 |
| **资源清理** | ✅ CapabilityLoader + SQLite | ❌ | 不重复 |
| **Trace 管理** | ❌ | ✅ Executor 创建/设置 TraceContext | 不重复 |

### 重叠结论

**零实质性职责重叠。** Runtime 和 Execution 是补充关系，不是竞争关系。

- Execution = **执行引擎**（如何执行一个任务）
- Runtime = **容器 + 横切面**（组装、生命周期、Memory 集成、Session 管理）

唯一的架构异味是 `ContextBuilder` 的物理位置：它位于 `runtime/` 但被 `execution/pipeline.py` 使用。这是反向依赖。

---

## 6. 架构合理性判断

### 当前更接近 **A**（分层的 Pipeline）

```
Interface (CLI / HTTP / Daemon)
  │
  ▼
Runtime (容器 + 横切面)
  │
  ▼
Executor (执行入口 + Trace)
  │
  ▼
Planner ──► ExecutionPipeline
  │             │
  │             ├─ WorkflowEngine ──► Agent
  │             ├─ Multi-Step ──────► Agent
  │             └─ Direct ──────────► Agent
  │
  ▼
Agent (LangChain create_agent)
```

**不是 B**（Runtime ≈ Execution），因为 Runtime 不做任何执行/规划/路由逻辑。

**不是 C**（三层混乱），因为 Workflow 是 Execution 的子路径，不存在独立的一层。

### 判断理由

1. **Runtime 不参与执行决策。** `execute()` 仅创建 ExecutionRequest 然后转给 Executor。Planner 决定 agent_type/workflow/steps，Pipeline 决定走哪条路径，Runtime 对此一无所知。

2. **Runtime 的职责是横切面。** Session 生命周期、Model 切换、Memory 触发、资源清理——这些都是跨越执行边界的关注点，不属于 Execution 层。

3. **Executor 是真正的执行入口。** 如果删除 Runtime，Executor 可以直接暴露给 Interface。但 Interface 将失去 Session 管理、Memory 集成、Model 切换等横切面能力。

4. **唯一的层级违规：** `ContextBuilder` 在 `runtime/`，但只有 `execution/pipeline.py` 使用它。这意味着 ContextBuilder 的物理位置错了——它应该属于 `execution/` 或独立的 `context/` 层。

---

## 7. 三种方案分析

### 方案 1：保留现状（Runtime → Execution → Workflow）

```
Interface → Runtime → Executor → Planner/Pipeline → WorkflowEngine → Agent
```

| 优点 | 缺点 |
|------|------|
| ✅ 层级清晰：容器/横切面 vs 执行引擎 | ❌ ContextBuilder 反向依赖 |
| ✅ Interface 只需知道 Runtime | ❌ Runtime.execute() 薄封装增加了间接层 |
| ✅ 横切面（Session/Memory/Model）有明确归属 | ❌ ExecutionState 死代码未清理 |
| ✅ 零迁移成本 | ❌ Runtime.__init__.py re-export ExecutionPlan（层级泄露） |
| ✅ 208 测试全通过 | |

### 方案 2：删除 Runtime，Executor 直接暴露

```
Interface → Executor → Planner/Pipeline → WorkflowEngine → Agent
```

| 优点 | 缺点 |
|------|------|
| ✅ 消除一层间接 | ❌ Session 生命周期管理无处归属 |
| ✅ 消灭 runtime/ 包 | ❌ Memory 触发逻辑需要嵌入 Executor/Pipeline |
| | ❌ Model 切换无处归属 |
| | ❌ 资源清理（CapabilityLoader + SQLite）无处归属 |
| | ❌ 组装逻辑（create_runtime）需移至 Interface 层 |
| | ❌ Interface 需要直接了解 Executor/Planner/Pipeline |
| | ❌ **高迁移成本**：至少改动 5 个 Interface 文件 + 全部测试 |

### 方案 3：Runtime 降级为 Facade

```python
class Runtime:
    """仅暴露 execute() / execute_stream() + Session/Model 管理。"""
    
    def __init__(self, executor, session_manager, ...):
        self._executor = executor
        ...
    
    async def execute(self, task, session_id=""):
        # 仅做：创建 ExecutionRequest → 委托 Executor → 触发 Memory
        ...
```

| 优点 | 缺点 |
|------|------|
| ✅ Interface 保持简单（只依赖 Runtime） | ❌ 与现状几乎一样 |
| ✅ 横切面有明确归属 | ❌ 需要明确 Facade 的边界约束 |
| ✅ 迁移成本低（主要是清理） | ❌ ContextBuilder 位置问题仍需解决 |
| ✅ 符合 Facade 模式 | |

**实际上方案 3 与方案 1 在代码层面几乎等同。** Runtime 当前就是 Facade——它不参与执行逻辑，只做委托 + 横切面。差异在于我们需要**明确声明**这一点，并修复少数违规（ContextBuilder 位置、`__init__.py` re-export）。

---

## 8. 最终建议

### **建议保留 Runtime，但明确其 Facade 职责并修复架构违规。**

原因：

1. **Runtime 不是 V1 遗留。** 它在 V2 迁移中是重新设计的——删除了原有的 monolithic RuntimeState、Agent 直接持有、Middleware 管道等，改为通过 Executor 委托执行。

2. **Runtime 承担了 Execution 层不应承担的职责。** Session 生命周期、Memory 触发、Model 切换、资源清理——这些是容器/横切面关注点。如果删除 Runtime，这些职责会污染 Execution 层或 Interface 层。

3. **删除 Runtime 的收益远小于成本。** Runtime 只有 2 个源文件（factory.py 171 行有效代码，context.py 271 行），删除它需要重新分配 ~8 个方法到 3+ 个不同位置，改动至少 5 个 Interface 消费者。

4. **Runtime 已经是 Facade。** `execute()` 和 `execute_stream()` 是薄封装——创建 Request → 委托 Executor → 触发 Memory。这就是 Facade 模式的标准实现。

### 建议的优化（不改变架构，仅清理）

| 优先级 | 操作 | 原因 |
|:---:|------|------|
| 🔴 高 | **移动 `context.py` 到 `execution/`** | 消除唯一的反向依赖。ContextBuilder 只被 Pipeline 使用，应属于 execution 层 |
| 🟡 中 | **删除 `execution/state.py`** | ExecutionState 零业务引用，死代码 |
| 🟡 中 | **清理 `runtime/__init__.py` 的 re-export** | `ExecutionPlan`/`PlanStep` 不应从 runtime 层 re-export；Interface 如需使用应从 execution 导入 |
| 🟢 低 | **在 `Runtime` 类 docstring 中明确 Facade 角色** | "Runtime is a Facade: it delegates all execution to Executor and manages cross-cutting concerns" |
| 🟢 低 | **将 `_trigger_memory()` 改为 Pipeline 回调** | 减少 Runtime 的 Memory 耦合；但当前实现简洁可用，非必须 |

### 迁移成本评估

| 改动 | 影响文件数 | 风险 |
|------|:---:|:---:|
| `context.py` → `execution/context.py` | ~3 (pipeline.py, factory.py, `__init__.py`) | 低 |
| 删除 `execution/state.py` | 1 (`execution/__init__.py`) | 极低 |
| 清理 `runtime/__init__.py` re-export | 1 | 极低（确认无外部引用后） |
| 添加 Facade docstring | 1 | 零 |

---

## 9. 总结

```
┌─────────────────────────────────────────────────┐
│                  Interface 层                     │
│         (CLI / HTTP / Daemon / Feishu)            │
└──────────────────────┬──────────────────────────┘
                       │ create_runtime()
                       │ runtime.execute(task)
                       ▼
┌─────────────────────────────────────────────────┐
│               Runtime (Facade)                    │
│                                                   │
│  职责: 组装 • Session 生命周期 • Memory 集成      │
│        • Model 切换 • 资源清理                    │
│                                                   │
│  不参与: 规划 • 路由 • Agent 调用 • Workflow      │
└──────────────────────┬──────────────────────────┘
                       │ executor.execute(request)
                       ▼
┌─────────────────────────────────────────────────┐
│             Execution (Engine)                    │
│                                                   │
│  Executor → Planner → Pipeline                    │
│                │        │                         │
│                │        ├─ WorkflowEngine → Agent │
│                │        ├─ Multi-Step → Agent     │
│                │        └─ Direct → Agent         │
│                │                                  │
│                └─ ContextBuilder ← ⚠️ 在 runtime/ │
└─────────────────────────────────────────────────┘
```

**结论：Runtime 应该保留。** 它不是 V1 遗留，而是 Execution 引擎的必要容器层。删除它不会简化系统，只会将横切面关注点散布到 Execution 和 Interface 层。当前唯一需要修复的问题是 `ContextBuilder` 的物理位置（应从 `runtime/` 移至 `execution/`）。
