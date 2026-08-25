# Haven V2 架构设计

> 版本: 2.0.0
> 日期: 2026-06-12
> 状态: 设计阶段，禁止实现

---

## 目录

1. [总体架构](#1-总体架构)
2. [模块职责](#2-模块职责)
3. [最终目录结构](#3-最终目录结构)
4. [核心接口设计](#4-核心接口设计)
5. [数据流](#5-数据流)
6. [生命周期](#6-生命周期)
7. [官方组件映射](#7-官方组件映射)
8. [迁移计划](#8-迁移计划)

---

## 1. 总体架构

### 1.1 分层模型

```
┌──────────────────────────────────────────────────────────────────┐
│                        Interface Layer                           │
│   CLI REPL  │  TCP Daemon  │  Feishu WebSocket  │  HTTP API     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                      Infrastructure Layer                        │
│   Logging  │  MCP Connections  │  SQLite  │  Async Primitives   │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                        Kernel Layer                              │
│   Config  │  Model Factory  │  DI Container  │  Lifecycle        │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                       Runtime Layer                              │
│   Process Manager  │  Session Manager  │  Event Bus             │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                      Execution Layer                             │
│   Planner  │  Router  │  Step Executor  │  Execution Context     │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
┌───────────────────────┐  ┌───────────────────────┐
│     Agent Layer       │  │    Workflow Layer      │
│  Agent Runner         │  │  DAG Engine            │
│  ReAct Loop           │  │  Workflow Registry     │
│  Tool Calling         │  │  Node Executor         │
└───────────┬───────────┘  └───────────┬───────────┘
            │                          │
            └──────────┬───────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Capability Layer                              │
│   Skill Registry  │  Skill Loader  │  Tool Registry              │
│   Tool Provider (Builtin)  │  Tool Provider (MCP)                │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                       Memory Layer                                │
│   Fact Store  │  Vector Memory  │  Context Builder               │
│   Message History (LangGraph Checkpointer)                        │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 各层一句话职责

| 层 | 职责 |
|---|------|
| **Kernel** | 配置加载、模型工厂、DI 容器、进程生命周期 |
| **Runtime** | 进程管理、会话管理、事件总线 |
| **Execution** | 单次请求的规划→路由→执行全流程 |
| **Session** | 多轮对话状态、checkpointer、上下文窗口管理 |
| **Agent** | 封装 LangChain `create_agent`，管理 ReAct 循环与工具调用 |
| **Capability** | Skill + Tool 的发现、注册、生命周期管理 |
| **Memory** | 长期事实记忆 + 向量语义记忆 + 上下文组装 |
| **Workflow** | 基于 LangGraph StateGraph 的 DAG 工作流引擎 |
| **Infrastructure** | 日志、MCP 连接池、SQLite、异步原语、类型定义 |
| **Interface** | 用户入口：CLI REPL / TCP Daemon / Feishu WebSocket |

### 1.3 依赖方向

```
Interface → Runtime → Execution → Agent → Capability → Memory
                ↓            ↓          ↓
           Infrastructure ← Kernel
```

- **严格单向依赖**：上层依赖下层，下层绝不引用上层
- **Kernel 无依赖**（仅依赖标准库 + 第三方基础库）
- **Infrastructure 仅依赖标准库**
- **Capability 与 Memory 是平层**，互不依赖

---

## 2. 模块职责

### 2.1 Kernel

| 维度 | 说明 |
|------|------|
| **职责** | 配置加载（YAML + env vars deep-merge）、LLM 模型工厂（按 models.yaml 创建 ChatModel 实例）、DI 容器（组件注册与解析）、进程生命周期管理（启动/关闭钩子） |
| **不负责** | 会话管理、Agent 创建、工具加载、请求处理 |
| **输入** | `haven.yaml`、`models.yaml`、环境变量 |
| **输出** | `AppConfig` 实例、`BaseChatModel` 实例、DI 容器 |
| **依赖方向** | 无上层依赖，仅依赖标准库 + OmegaConf + pydantic-settings + LangChain |

**关键差异（对比当前）**：当前 factory.py 混合了创建逻辑与配置加载。V2 中 Kernel 只提供"零件"，Runtime 负责"装配"。

### 2.2 Runtime

| 维度 | 说明 |
|------|------|
| **职责** | 持有进程级单例（配置、事件总线、Provider 连接池）、创建/销毁 Session、启动/停止 Interface 通道 |
| **不负责** | 单次请求处理、Agent 调用、任务规划 |
| **输入** | `AppConfig`、`EventBus`、组件注册信息 |
| **输出** | `Session` 实例、运行状态报告 |
| **依赖方向** | Kernel → Infrastructure |

**关键差异（对比当前）**：当前 `Runtime` 类是 Coordinator/Dispatcher/Agent 的容器。V2 中 Runtime 只管理进程与会话生命周期，不直接持有执行组件。

### 2.3 Execution

| 维度 | 说明 |
|------|------|
| **职责** | 接收用户输入 → 创建 ExecutionContext → Planner 生成 ExecutionPlan → Router 选择路径（直接/多步/工作流）→ StepExecutor 逐步执行 → 聚合 Response |
| **不负责** | Agent 内部实现、Skill 加载、长期记忆写入（通过 Event 触发） |
| **输入** | 用户文本 + Session + 可选的 channel metadata |
| **输出** | `ExecutionResponse`（含文本 + 事件流） |
| **依赖方向** | Session → Agent → Capability（通过 Router 间接依赖）|

**关键差异（对比当前）**：当前 Coordinator 和 Dispatcher 是两个独立类且与 Runtime 紧耦合。V2 中合并为一个 Execution 模块，通过 Planner → Router → StepExecutor 管道处理。

### 2.4 Session

| 维度 | 说明 |
|------|------|
| **职责** | 管理单个会话的状态：thread_id（LangGraph checkpointer key）、turn_count、active_skills、entity_name、channel、上下文窗口（消息裁剪）、长期记忆引用 |
| **不负责** | 消息持久化（由 LangGraph SqliteSaver 负责）、事实提取（由 Memory 负责）、请求执行 |
| **输入** | session_id、entity_name、channel |
| **输出** | SessionState 快照、消息历史（需要时） |
| **依赖方向** | Kernel |

**关键差异（对比当前）**：当前 `RuntimeState` 只是一个薄 dataclass，session 管理散落在 Runtime/Dispatcher/Agent 中。V2 中 Session 是一等模块，封装所有会话级状态。

### 2.5 Agent

| 维度 | 说明 |
|------|------|
| **职责** | 封装 LangChain `create_agent`：持有 LLM + tools + checkpointer，提供 `run()` / `astream()` 执行接口，处理 tool_call 中断恢复，管理 ReAct 循环超时 |
| **不负责** | Tool 注册/发现（由 Capability 负责）、system_prompt 组装（由 Memory ContextBuilder 负责）、任务规划（由 Execution Planner 负责） |
| **输入** | `AgentRequest`（task + system_prompt + thread_id） |
| **输出** | `AgentResponse`（文本 + token 用量） |
| **依赖方向** | Capability → Memory → Kernel |

**关键差异（对比当前）**：当前 `BaseAgent` 概念正确，但创建方式散落在 factory.py 中。V2 中 Agent 由 AgentFactory 创建，通过 DI 获取 tools 和 LLM。

### 2.6 Capability

| 维度 | 说明 |
|------|------|
| **职责** | **Skill**：从 `.md` 文件加载 YAML frontmatter → 注册到 SkillRegistry → 提供按标签/名称/依赖查询。**Tool**：管理 ToolProvider 生命周期（Builtin 扫描 + MCP 连接）→ 注册到 ToolRegistry → 返回 `list[BaseTool]`。 |
| **不负责** | 决定使用哪个 skill/tool（由 Execution Planner + LLM Function Calling 决定）、system_prompt 拼装（由 Memory ContextBuilder 负责） |
| **输入** | Skill 目录路径、`mcp.json` 配置 |
| **输出** | `list[BaseSkill]`、`list[BaseTool]` |
| **依赖方向** | Kernel（配置）→ Infrastructure（MCP 连接） |

**关键差异（对比当前）**：当前 Skill 和 Tool 是两个独立模块。V2 中合并为 Capability 层，因为它们都是"Agent 的能力来源"，只是形态不同（Skill = prompt 注入，Tool = 函数调用）。

### 2.7 Memory

| 维度 | 说明 |
|------|------|
| **职责** | **FactStore**：SQLite 语义事实 CRUD。**FactExtractor**：LLM 从对话中提取结构化事实。**MemoryPipeline**：编排提取→存储（后台异步）。**ContextBuilder**：按优先级组装 system_prompt（Personality > Agent > Skills > Files > History）。 |
| **不负责** | 消息持久化（LangGraph SqliteSaver 自动完成）、决定何时触发记忆（通过订阅 Event 实现） |
| **输入** | 用户消息 + Agent 响应（after-turn hook）、实体名称 |
| **输出** | 提取的事实、组装好的 system_prompt 字符串 |
| **依赖方向** | Kernel（LLM 工厂） |

**关键差异（对比当前）**：当前 Memory 通过 Runtime._trigger_memory() 手动调用。V2 中通过订阅 Execution 层的 Event，解耦触发逻辑。

### 2.8 Workflow

| 维度 | 说明 |
|------|------|
| **职责** | 定义、注册、构建、执行基于 LangGraph `StateGraph` 的 DAG 工作流。提供共享节点辅助函数（`run_agent_node`）。管理工作流级状态（AgentState 子类）。 |
| **不负责** | 选择工作流（由 Execution Planner 选择）、Agent 内部逻辑 |
| **输入** | workflow_name + task + plan_skills + Session |
| **输出** | 工作流执行结果（final_output + errors） |
| **依赖方向** | Agent → Capability → Session |

**关键差异（对比当前）**：当前 Workflow 散落在 runtime/workflows/ 中，通过 import side-effect 注册。V2 中 Workflow 是独立模块，注册由 WorkflowRegistry 的装饰器完成，无需 import side-effect。

### 2.9 Infrastructure

| 维度 | 说明 |
|------|------|
| **职责** | 日志配置、MCP 连接池管理、SQLite 连接管理、异步原语（超时、重试、并发控制）、公共类型定义（Event、StreamChunk 等） |
| **不负责** | 任何业务逻辑 |
| **输入** | 日志级别配置、MCP 服务器配置 |
| **输出** | logger 实例、MCP session、SQLite connection |
| **依赖方向** | 仅标准库 + 第三方基础库 |

### 2.10 Interface

| 维度 | 说明 |
|------|------|
| **职责** | 接收外部输入 → 转化为内部 Request → 调用 Runtime.execute() → 格式化输出返回给用户。支持 CLI REPL (Rich)、TCP Socket Daemon、Feishu WebSocket。 |
| **不负责** | 任何业务逻辑、请求处理、Agent 调用 |
| **输入** | 用户原始输入（文本 / WebSocket 消息 / TCP 数据） |
| **输出** | 格式化后的响应文本 / 流式 chunk |
| **依赖方向** | Runtime |

---

## 3. 最终目录结构

```
src/haven/
│
├── kernel/                         # 内核层：配置 + 模型 + DI + 生命周期
│   ├── __init__.py
│   ├── config.py                   # AppConfig 数据类 + 加载逻辑（OmegaConf + pydantic-settings）
│   ├── container.py                # DI 容器（组件注册/解析）
│   ├── lifecycle.py                # 进程生命周期钩子（startup / shutdown）
│   └── model_factory.py            # LLM 模型工厂（从 models.yaml 创建 ChatModel）
│
├── infrastructure/                 # 基础设施层：日志 + 连接 + 类型
│   ├── __init__.py
│   ├── logging.py                  # 日志配置
│   ├── mcp_pool.py                 # MCP 连接池管理
│   ├── sqlite.py                   # SQLite 连接工厂
│   └── types.py                    # 公共类型：Event, StreamChunk, ExecutionPlan 等
│
├── runtime/                        # 运行时层：进程 + 会话 + 事件
│   ├── __init__.py
│   ├── process.py                  # ProcessManager：进程级单例管理
│   ├── session.py                  # Session + SessionManager
│   └── events.py                   # EventBus：发布/订阅事件系统
│
├── execution/                      # 执行层：规划 → 路由 → 执行
│   ├── __init__.py
│   ├── planner.py                  # Planner：LLM 结构化输出 → ExecutionPlan
│   ├── router.py                   # Router：根据 plan 选择执行路径
│   ├── executor.py                 # StepExecutor：逐步执行 task
│   ├── context.py                  # ExecutionContext：单次执行的上下文
│   └── response.py                 # ExecutionResponse + ResponseBuilder
│
├── agent/                          # Agent 层：LLM Agent 封装
│   ├── __init__.py
│   ├── base.py                     # BaseAgent：LangChain create_agent 包装
│   ├── factory.py                  # AgentFactory：按 agent_type 创建 Agent
│   └── runner.py                   # AgentRunner：run() / astream() 统一入口
│
├── capability/                     # 能力层：Skill + Tool
│   ├── __init__.py
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── loader.py               # SkillLoader：扫描 .md 文件
│   │   ├── registry.py             # SkillRegistry：注册 + 查询 + 依赖解析
│   │   └── models.py               # Skill 数据类
│   └── tools/
│       ├── __init__.py
│       ├── loader.py               # ToolLoader：编排 Provider 生命周期
│       ├── registry.py             # ToolRegistry：全局工具注册表
│       ├── models.py               # ToolMetadata
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py             # ToolProvider ABC + ProviderStatus
│       │   ├── builtin.py          # BuiltinProvider：扫描内置工具目录
│       │   └── mcp.py              # MCPProvider：MCP 服务器连接
│       └── builtin/
│           ├── __init__.py
│           └── web_search.py       # WebSearchTool
│
├── memory/                         # 记忆层：事实 + 向量 + 上下文
│   ├── __init__.py
│   ├── fact_store.py               # FactStore：SQLite 语义事实存储
│   ├── extractor.py                # FactExtractor：LLM 提取结构化事实
│   ├── pipeline.py                 # MemoryPipeline：extract → store 编排
│   ├── context_builder.py          # ContextBuilder：system_prompt 组装
│   └── vector_memory.py            # VectorMemory：ChromaDB 向量语义检索（可选）
│
├── workflow/                       # 工作流层：DAG 引擎 + 预定义流程
│   ├── __init__.py
│   ├── engine.py                   # WorkflowEngine：编译 + 执行 StateGraph
│   ├── registry.py                 # WorkflowRegistry：注册 + 查询
│   ├── helpers.py                  # 共享节点辅助函数
│   ├── state.py                    # AgentState 基类
│   └── definitions/                # 预定义工作流定义
│       ├── __init__.py
│       ├── dev.py                  # 软件开发工作流
│       ├── diagnosis.py            # 诊断工作流
│       └── research.py             # 研究工作流
│
├── model/                          # 模型层：Pydantic 数据模型
│   ├── __init__.py
│   ├── request.py                  # ExecutionRequest, AgentRequest
│   ├── response.py                 # ExecutionResponse, AgentResponse
│   ├── plan.py                     # ExecutionPlan, PlanStep
│   ├── session.py                  # SessionState
│   └── events.py                   # Event 及其子类型
│
├── config/                         # 默认配置文件（YAML + Markdown）
│   ├── __init__.py
│   ├── haven.yaml                  # 框架默认参数
│   ├── models.yaml                 # 内置模型定义
│   └── haven.md                    # 系统人格 prompt
│
└── interface/                      # 用户界面层
    ├── __init__.py
    ├── cli/
    │   ├── __init__.py
    │   ├── main.py                 # CLI 入口点
    │   └── repl.py                 # 交互式 REPL 循环
    ├── daemon.py                   # 守护进程管理
    └── channels/
        ├── __init__.py
        ├── base.py                 # BaseChannel ABC
        └── feishu.py               # 飞书 WebSocket 通道
```

### 3.1 关键变化 vs 当前

| 当前路径 | V2 路径 | 变化说明 |
|---------|---------|---------|
| `core/state.py` | `model/session.py` | RuntimeState → SessionState，移入 model 层 |
| `core/registry.py` | 删除 | 各 Registry 自行实现，不共享基类 |
| `core/llm.py` | `kernel/model_factory.py` | 移入 Kernel |
| `core/pidfile.py` | `infrastructure/` 或 `kernel/lifecycle.py` | 归类到基础设施 |
| `config/settings.py` | `kernel/config.py` | 合并配置逻辑 |
| `config/loader.py` | `kernel/model_factory.py` | 合并模型加载 |
| `config/mcp.py` | `infrastructure/mcp_pool.py` | MCP 连接管理独立 |
| `runtime/factory.py` | **删除** | 拆分为 kernel/container.py + runtime/process.py |
| `runtime/coordinator.py` | `execution/planner.py` | 职责不变，增加接口 |
| `runtime/dispatcher.py` | `execution/router.py` + `execution/executor.py` | 拆分路由与执行 |
| `runtime/agents/base.py` | `agent/base.py` | 移出 runtime |
| `runtime/context.py` | `memory/context_builder.py` | 上下文构建属于记忆层 |
| `runtime/state.py` | `workflow/state.py` | 工作流状态独立 |
| `runtime/registry.py` | `workflow/registry.py` | 工作流注册独立 |
| `runtime/workflows/` | `workflow/definitions/` | 移出 runtime |
| `runtime/stream.py` | `infrastructure/types.py` | StreamChunk 是基础设施类型 |
| `skills/` | `capability/skills/` | 并入 Capability 层 |
| `tools/` | `capability/tools/` | 并入 Capability 层 |
| `memory/` | `memory/` | 增加 vector_memory.py |
| `channels/` | `interface/channels/` | 移入 Interface 层 |
| `cli/` | `interface/cli/` | 移入 Interface 层 |
| `middleware/` | **删除** | 已废弃的死代码 |
| — | `model/` | **新增**：集中管理所有 Pydantic 数据模型 |
| — | `execution/` | **新增**：从 runtime 中拆出执行管道 |
| — | `agent/` | **新增**：Agent 从 runtime 独立 |

---

## 4. 核心接口设计

### 4.1 Runtime

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

from haven.model.request import ExecutionRequest
from haven.model.response import ExecutionResponse
from haven.model.session import SessionState
from haven.infrastructure.types import StreamChunk


class Runtime(ABC):
    """进程级运行时。

    管理 Session 生命周期、事件总线、Interface 通道。
    不直接处理请求——请求委托给 Execution 层。
    """

    @abstractmethod
    async def start(self) -> None:
        """启动 Runtime：初始化所有组件，启动 Interface 通道。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """优雅关闭：停止通道 → 等待进行中的请求完成 → 释放资源。"""
        ...

    @abstractmethod
    async def create_session(
        self,
        session_id: str,
        *,
        entity_name: str = "user",
        channel: str = "default",
    ) -> SessionState:
        """创建新会话或返回已有会话。"""
        ...

    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """同步执行：规划 → 路由 → 执行 → 响应。"""
        ...

    @abstractmethod
    async def execute_stream(
        self, request: ExecutionRequest,
    ) -> AsyncIterator[StreamChunk]:
        """流式执行：逐步 yield StreamChunk。"""
        ...
```

### 4.2 ExecutionRequest

```python
from pydantic import BaseModel, Field


class ExecutionRequest(BaseModel):
    """用户请求的标准化输入模型。

    由 Interface 层创建，传递给 Runtime.execute()。
    """

    task: str = Field(description="用户输入文本")
    session_id: str = Field(default="default")
    entity_name: str = Field(default="user")
    channel: str = Field(default="cli")
    metadata: dict = Field(default_factory=dict, description="渠道元数据")
```

### 4.3 ExecutionResponse

```python
from pydantic import BaseModel, Field


class ExecutionResponse(BaseModel):
    """Execution 层的统一响应模型。"""

    text: str = Field(default="", description="响应文本")
    plan_summary: str | None = Field(default=None, description="规划摘要")
    agent_type: str | None = Field(default=None, description="使用的 Agent 类型")
    skills_used: list[str] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    turn_count: int = Field(default=0)
    token_usage: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
```

### 4.4 Session

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver


@dataclass
class SessionState:
    """会话级状态快照。

    贯穿整个对话生命周期，由 SessionManager 管理。
    """

    session_id: str = "default"
    entity_name: str = "user"
    channel: str = "cli"

    # 运行时状态
    turn_count: int = 0
    active_skills: list[str] = field(default_factory=list)
    active_tools: list[str] = field(default_factory=list)
    last_plan: dict | None = None

    # 上下文管理
    context_window_tokens: int = 8000


class SessionManager(ABC):
    """会话管理器。

    管理所有活跃 Session。每个 Session 对应一个 LangGraph thread_id。
    """

    @abstractmethod
    async def get_or_create(
        self,
        session_id: str,
        *,
        entity_name: str = "user",
        channel: str = "default",
    ) -> SessionState:
        ...

    @abstractmethod
    async def get(self, session_id: str) -> SessionState | None:
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        ...

    @abstractmethod
    async def get_checkpointer(self, session_id: str) -> BaseCheckpointSaver:
        """获取该 Session 关联的 LangGraph checkpointer。"""
        ...

    @abstractmethod
    async def trim_context(
        self, session_id: str, messages: list[Any],
    ) -> list[Any]:
        """按 token 预算裁剪消息历史。"""
        ...
```

### 4.5 Agent

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

from pydantic import BaseModel, Field

from haven.infrastructure.types import StreamChunk


class AgentRequest(BaseModel):
    """Agent 层输入。"""

    task: str
    system_prompt: str = ""
    thread_id: str = "default"
    max_iterations: int = 20
    timeout_seconds: int = 300


class AgentResponse(BaseModel):
    """Agent 层输出。"""

    text: str
    tool_calls_count: int = 0
    iterations: int = 0


class Agent(ABC):
    """Agent 抽象。

    封装 LLM + tools + checkpointer。
    不负责 system_prompt 组装（由 Memory ContextBuilder 负责）。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 类型名称：coder / researcher / diagnosis / general。"""
        ...

    @property
    @abstractmethod
    def agent_prompt(self) -> str:
        """Agent 专属 system prompt 片段。"""
        ...

    @abstractmethod
    async def run(self, request: AgentRequest) -> AgentResponse:
        """非流式执行。"""
        ...

    @abstractmethod
    async def astream(
        self, request: AgentRequest,
    ) -> AsyncIterator[StreamChunk]:
        """流式执行，逐 token yield。"""
        ...

    @abstractmethod
    def bind_tools(self, tools: list) -> None:
        """绑定/更新工具集。"""
        ...
```

### 4.6 Capability

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Skill:
    """技能数据模型——纯数据，零代码。

    LLM 通过 description 字段判断是否激活此 skill。
    """

    name: str
    description: str = ""
    prompt: str = ""                 # Markdown 正文
    tags: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    version: str = "1.0"
    default: bool = False
    source_file: Path = field(default_factory=Path)


class SkillRegistry(ABC):
    """技能注册表。"""

    @abstractmethod
    def register(self, skill: Skill) -> None: ...

    @abstractmethod
    def get(self, name: str) -> Skill: ...

    @abstractmethod
    def list_all(self) -> dict[str, Skill]: ...

    @abstractmethod
    def get_by_tag(self, tag: str) -> list[Skill]: ...

    @abstractmethod
    def get_by_tags(self, tags: list[str]) -> list[Skill]: ...

    @abstractmethod
    def resolve_dependencies(self, names: list[str]) -> list[str]: ...

    @abstractmethod
    def get_default_skill(self) -> Skill | None: ...


class SkillLoader(ABC):
    """技能加载器。"""

    @abstractmethod
    def load_from_dir(self, directory: Path) -> list[Skill]: ...

    @abstractmethod
    def load_single(self, filepath: Path) -> Skill | None: ...
```

### 4.7 Tool

```python
from abc import ABC, abstractmethod
from enum import Enum, auto

from langchain_core.tools import BaseTool  # 直接使用 LangChain 官方


class ProviderStatus(str, Enum):
    """ToolProvider 状态机。"""
    UNINITIALIZED = "uninitialized"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class ToolProvider(ABC):
    """工具提供者。子类实现 discover() + health_check()。

    生命周期由 ToolLoader 编排：start → discover → (running) → stop。
    """

    @abstractmethod
    async def discover(self) -> list[BaseTool]:
        """发现该 Provider 提供的所有工具。"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查。"""
        ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def list_tools(self) -> list[BaseTool]: ...


class ToolRegistry(ABC):
    """全局工具注册表。"""

    @abstractmethod
    def register(self, tool: BaseTool, provider: str) -> None: ...

    @abstractmethod
    def get(self, name: str) -> BaseTool: ...

    @abstractmethod
    def list_all(self) -> list[BaseTool]: ...

    @abstractmethod
    def list_by_provider(self, provider: str) -> list[BaseTool]: ...

    @abstractmethod
    def clear(self) -> None: ...
```

### 4.8 Memory

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MemoryFact:
    """一条语义事实。"""
    content: str
    entity_name: str
    importance: float = 0.5
    source: str = "conversation"
    created_at: float = 0.0


class FactStore(ABC):
    """长期事实存储。"""

    @abstractmethod
    def add(self, entity: str, content: str, *, importance: float = 0.5) -> None: ...

    @abstractmethod
    def search(self, entity: str, query: str) -> list[MemoryFact]: ...

    @abstractmethod
    def get_all(self, entity: str) -> list[MemoryFact]: ...

    @abstractmethod
    def clear(self, entity: str) -> None: ...


class FactExtractor(ABC):
    """从对话中提取结构化事实。"""

    @abstractmethod
    async def extract(
        self, user_input: str, agent_response: str,
    ) -> list[dict]:
        """返回 [{"content": ..., "importance": ...}]。"""
        ...


class ContextBuilder(ABC):
    """按优先级组装 LLM system_prompt。"""

    @abstractmethod
    def build(
        self,
        *,
        agent_prompt: str = "",
        skills: list[Skill] | None = None,
        task: str = "",
        history_summary: str = "",
    ) -> str:
        """返回组装好的 system_prompt 字符串。"""
        ...
```

### 4.9 Event

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Awaitable, Callable


class EventType(str, Enum):
    """系统事件类型。"""

    # 进程级
    STARTUP = "startup"
    SHUTDOWN = "shutdown"

    # 会话级
    SESSION_CREATED = "session.created"
    SESSION_DESTROYED = "session.destroyed"

    # 执行级
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"

    # Agent 级
    AGENT_TURN_STARTED = "agent.turn.started"
    AGENT_TURN_COMPLETED = "agent.turn.completed"
    TOOL_CALL_STARTED = "tool.call.started"
    TOOL_CALL_COMPLETED = "tool.call.completed"

    # Memory 级
    FACTS_EXTRACTED = "memory.facts.extracted"


@dataclass
class Event:
    """系统事件。"""

    type: EventType
    source: str = ""                    # 事件来源组件名
    session_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


# 事件处理器签名
EventHandler = Callable[[Event], Awaitable[None]]


class EventBus(ABC):
    """进程内事件总线。发布/订阅模式。"""

    @abstractmethod
    async def publish(self, event: Event) -> None:
        """发布事件。同步等待所有 handler 完成。"""
        ...

    @abstractmethod
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """订阅事件类型。"""
        ...

    @abstractmethod
    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """取消订阅。"""
        ...
```

---

## 5. 数据流

### 5.1 主流程（用户输入 → 响应输出）

```
用户输入 (plain text)
    │
    ▼
┌──────────────────────────────────────────────┐
│ Interface                                     │
│  接收原始输入 → 创建 ExecutionRequest         │
│  调用 runtime.execute(request)                │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ Runtime                                       │
│  获取/创建 Session                            │
│  发布 Event(EXECUTION_STARTED)                │
│  委托给 Execution.execute()                   │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ Execution                                     │
│  1. Planner.plan(task) → ExecutionPlan        │
│     ├─ LLM Structured Output                  │
│     ├─ Skill 选择（语义匹配）                  │
│     └─ Workflow 选择（若有匹配）              │
│                                                │
│  2. Router.route(plan) → 执行路径              │
│     ├─ 路径 A: plan.workflow → WorkflowEngine │
│     ├─ 路径 B: plan.steps → StepExecutor      │
│     └─ 路径 C: 直接 → Agent                   │
│                                                │
│  3. StepExecutor / WorkflowEngine              │
│     └─ 每步调用 Agent.run()                   │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ Agent                                         │
│  1. ContextBuilder.build() → system_prompt    │
│     ├─ Personality (haven.md)                 │
│     ├─ Agent prompt                           │
│     ├─ Skills prompt                          │
│     ├─ Project files                          │
│     └─ History summary                        │
│                                                │
│  2. LangChain create_agent                    │
│     ├─ Input: system_prompt + task + messages │
│     ├─ ReAct loop (LLM ↔ Tool calling)        │
│     └─ Output: AgentResponse                  │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ Capability                                    │
│  ToolRegistry → list[BaseTool]                │
│  SkillRegistry → Skill prompt fragments       │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ Execution                                     │
│  聚合结果 → 构建 ExecutionResponse            │
│  发布 Event(EXECUTION_COMPLETED)              │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ Memory (后台异步)                              │
│  订阅 Event(AGENT_TURN_COMPLETED)             │
│  FactExtractor.extract() → FactStore.add()    │
└──────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ Interface                                     │
│  格式化 ExecutionResponse → 输出给用户         │
└──────────────────────────────────────────────┘
```

### 5.2 事件流（订阅驱动）

```
Execution 发布                  Memory 订阅
─────────────────────────      ─────────────────────
EXECUTION_COMPLETED  ──────►   MemoryPipeline.after_turn()
                                ├─ FactExtractor.extract()
                                └─ FactStore.add()

Agent 发布                      Logging 订阅
─────────────────────────      ─────────────────────
TOOL_CALL_STARTED      ──────►  logger.info("tool: ...")
TOOL_CALL_COMPLETED    ──────►  logger.info("done: ...")
AGENT_TURN_COMPLETED   ──────►  TokenUsageTracker.record()

Runtime 发布                    Interface 订阅
─────────────────────────      ─────────────────────
SHUTDOWN               ──────►  各 Channel.close()
```

---

## 6. 生命周期

### 6.1 Process Scope（进程级）

```
启动:
  1. Kernel.startup()
     ├─ 加载配置 (haven.yaml + models.yaml)
     ├─ 初始化日志
     └─ 创建 DI 容器
  2. Capability.ToolLoader.start_all()
     ├─ BuiltinProvider.start()
     └─ MCPProvider × N .start()
  3. Runtime.start()
     ├─ 创建 EventBus
     ├─ 初始化 SessionManager + Checkpointer
     ├─ 创建 AgentFactory
     └─ 启动 Interface 通道
  4. Event(STARTUP) → 各组件就绪

运行:
  ┌─→ Interface 等待输入
  │   └─→ Runtime.execute() → 返回响应
  └─── 循环

关闭:
  1. Event(SHUTDOWN) → 各组件收到通知
  2. Interface 通道关闭
  3. 等待进行中的请求完成
  4. MCPProvider × N .stop()
  5. SQLite 连接关闭
  6. 进程退出
```

### 6.2 Session Scope（会话级）

```
创建:
  SessionManager.get_or_create(session_id)
    ├─ 分配 Checkpointer (thread_id = session_id)
    ├─ 初始化 SessionState
    └─ Event(SESSION_CREATED)

活跃:
  每次 execute():
    ├─ Session.turn_count += 1
    ├─ Session.active_skills = plan.skills
    └─ Checkpointer 自动持久化 messages

销毁:
  SessionManager.delete(session_id)
    ├─ Checkpointer.delete_thread(session_id)
    ├─ FactStore.clear(entity_name)  # 可选
    └─ Event(SESSION_DESTROYED)
```

### 6.3 Execution Scope（执行级）

```
单次 Execution 生命周期:

  1. 创建 ExecutionContext(task, session)
  2. Event(EXECUTION_STARTED)
  3. Planner.plan(task)
     ├─ 快速路径（琐碎输入 → 默认 plan）
     └─ LLM 路径（Structured Output → ExecutionPlan）
  4. Router.route(plan)
     ├─ 路径 A: WorkflowEngine.run(workflow_name, task)
     │   ├─ 编译 StateGraph
     │   ├─ 逐节点执行 (每个节点 = Agent.run())
     │   └─ 聚合 final_output
     ├─ 路径 B: StepExecutor.run(steps, task)
     │   ├─ 拓扑排序
     │   ├─ 逐步执行 (每步 = Agent.run())
     │   └─ 聚合结果
     └─ 路径 C: Agent.run(task)
         └─ 直接对话
  5. 构建 ExecutionResponse
  6. Event(EXECUTION_COMPLETED | EXECUTION_FAILED)
  7. 返回响应
```

---

## 7. 官方组件映射

### 7.1 直接采用官方能力（不重复实现）

| 官方组件 | 来源 | 用法 |
|---------|------|------|
| **BaseTool** | `langchain_core.tools` | Tool 基类，所有工具继承此类 |
| **create_agent** | `langchain.agents` | 创建 ReAct Agent，替代自定义 Agent 运行时 |
| **StateGraph** | `langgraph.graph` | DAG 工作流引擎，Workflow 层直接使用 |
| **CompiledStateGraph** | `langgraph.graph.state` | 编译后的工作流，.ainvoke() / .astream() |
| **SqliteSaver / AsyncSqliteSaver** | `langgraph.checkpoint.sqlite` | Checkpointer，Session 层直接使用 |
| **trim_messages** | `langchain_core.messages` | 消息裁剪（pre_model_hook），Session 层使用 |
| **with_structured_output** | `langchain_core.language_models` | LLM 结构化输出，Planner 使用 |
| **RunnableConfig** | `langchain_core.runnables` | LangGraph 节点配置传递 |
| **SystemMessage / HumanMessage / AIMessage / ToolMessage** | `langchain_core.messages` | 消息类型，全程使用 |
| **BaseChatModel** | `langchain_core.language_models` | LLM 抽象基类 |
| **BaseCheckpointSaver** | `langgraph.checkpoint.base` | Checkpointer 抽象基类 |
| **VectorStore** | `langchain_core.vectorstores` | 向量存储抽象（ChromaDB 集成时使用） |
| **CallbackHandler** | `langchain_core.callbacks` | LangChain 回调系统（日志、监控） |
| **ChatOpenAI / ChatDeepSeek** | `langchain_openai` / `langchain_deepseek` | 模型适配器，Kernel 直接使用 |

### 7.2 项目自定义（官方无对应能力）

| 自定义组件 | 位置 | 原因 |
|-----------|------|------|
| **Runtime** | `runtime/process.py` | 进程级编排 + Session 管理 + EventBus，LangChain 不涉及进程模型 |
| **Planner** | `execution/planner.py` | 任务规划 + Skill/Workflow 选择的领域逻辑 |
| **Router** | `execution/router.py` | 3 条执行路径的调度逻辑 |
| **StepExecutor** | `execution/executor.py` | 多步拓扑排序执行 |
| **SessionManager** | `runtime/session.py` | 会话生命周期 + 多 Session 管理 |
| **AgentFactory** | `agent/factory.py` | 按 agent_type 创建不同 system_prompt 的 Agent |
| **SkillRegistry** | `capability/skills/registry.py` | Skill 依赖解析 + 标签匹配（领域特有） |
| **SkillLoader** | `capability/skills/loader.py` | YAML frontmatter 解析 + .md 文件扫描 |
| **ToolLoader** | `capability/tools/loader.py` | 多 Provider 编排 + 生命周期管理 |
| **ToolProvider (ABC)** | `capability/tools/providers/base.py` | Provider 状态机 + 抽象契约 |
| **MCPProvider** | `capability/tools/providers/mcp.py` | MCP 协议适配 + 工具命名空间隔离 |
| **BuiltinProvider** | `capability/tools/providers/builtin.py` | 内置工具目录自动扫描 |
| **FactStore** | `memory/fact_store.py` | SQLite 语义事实存储（领域特有 schema） |
| **FactExtractor** | `memory/extractor.py` | LLM 驱动的结构化事实提取 |
| **ContextBuilder** | `memory/context_builder.py` | 5 级优先级 prompt 组装 + token 预算管理 |
| **EventBus** | `runtime/events.py` | 进程内发布/订阅事件系统 |
| **WorkflowRegistry** | `workflow/registry.py` | 工作流注册 + LLM 选择菜单构建 |
| **AppConfig** | `kernel/config.py` | YAML deep-merge + pydantic-settings 单例 |

---

## 8. 迁移计划

### 8.0 前置原则

- **每步迁移后项目必须可运行**：`uv run haven` 不报错
- **每次只改一个模块**：不跨模块同时修改
- **先测试后迁移**：每步先为要迁移的模块写测试
- **不允许兼容层**：删除旧代码，放入新代码

### 8.1 Step 1: Kernel + Config

**目标**：建立新的配置与内核基础设施。

**修改范围**：
- 新建 `kernel/` 目录：`config.py`、`container.py`、`lifecycle.py`、`model_factory.py`
- 将 `config/settings.py` 逻辑移入 `kernel/config.py`
- 将 `config/loader.py` 逻辑移入 `kernel/model_factory.py`
- 将 `core/llm.py` 逻辑移入 `kernel/model_factory.py`
- 删除旧的 `config/settings.py`、`config/loader.py`、`core/llm.py`

**风险**：低。Kernel 无上层依赖，所有引用单向。
**测试要求**：`kernel/config.py` 加载配置测试、`kernel/model_factory.py` 创建模型测试。

### 8.2 Step 2: Model（数据模型层）

**目标**：集中管理所有 Pydantic/数据类。

**修改范围**：
- 新建 `model/` 目录：`request.py`、`response.py`、`plan.py`、`session.py`、`events.py`
- 将 `ExecutionPlan`、`PlanStep` 从 `runtime/coordinator.py` 移入 `model/plan.py`
- 将 `RuntimeState` 从 `core/state.py` 移入 `model/session.py`
- 将 `StreamChunk` 从 `runtime/stream.py` 移入 `model/events.py`（或保留在 infrastructure/types.py）
- 创建 `ExecutionRequest`、`ExecutionResponse`、`AgentRequest`、`AgentResponse`
- 更新所有 import 引用

**风险**：低。纯数据模型迁移，不涉及逻辑变更。
**测试要求**：所有 Pydantic model 的序列化/反序列化测试。

### 8.3 Step 3: Infrastructure

**目标**：抽取跨层基础设施。

**修改范围**：
- 新建 `infrastructure/` 目录：`logging.py`、`mcp_pool.py`、`sqlite.py`、`types.py`
- 将 `config/mcp.py` 中的 MCP 连接管理移入 `infrastructure/mcp_pool.py`
- 将 `core/pidfile.py` 移入 `infrastructure/` 或 `kernel/lifecycle.py`
- 创建 `infrastructure/types.py` 放置 Event、StreamChunk 等公共类型
- 删除 `middleware/` 目录（死代码）

**风险**：低-中。MCP 连接逻辑移动需要仔细测试。
**测试要求**：MCPProvider 连接/断开测试、日志配置测试。

### 8.4 Step 4: Capability（Skill + Tool 合并）

**目标**：Skill 和 Tool 统一为 Capability 层。

**修改范围**：
- 新建 `capability/skills/` 和 `capability/tools/` 目录
- 将 `skills/` → `capability/skills/`（保持内部结构）
- 将 `tools/` → `capability/tools/`（保持内部结构）
- 更新所有 import 路径
- 创建 `capability/__init__.py` 统一导出

**风险**：中。大量 import 路径变更。
**测试要求**：Skill 加载/注册/依赖解析测试、Tool 加载/Provider 生命周期测试。

### 8.5 Step 5: Session

**目标**：独立的 Session 管理模块。

**修改范围**：
- 新建 `session/` 目录（或放入 `runtime/session.py`）
- 从 `runtime/factory.py` 中移出 Session 创建逻辑
- 从 `runtime/dispatcher.py` 中移出 Session 状态管理逻辑
- 封装 Checkpointer 管理到 SessionManager

**风险**：中。Session 创建逻辑分散在多处。
**测试要求**：Session 创建/销毁测试、Checkpointer thread 隔离测试、消息裁剪测试。

### 8.6 Step 6: Execution

**目标**：从 Runtime 中拆出执行管道。

**修改范围**：
- 新建 `execution/` 目录：`planner.py`、`router.py`、`executor.py`、`context.py`
- 从 `runtime/coordinator.py` → `execution/planner.py`
- 从 `runtime/dispatcher.py` → `execution/router.py` + `execution/executor.py`
- 删除旧的 `runtime/coordinator.py` 和 `runtime/dispatcher.py`

**风险**：**高**。这是最核心的执行逻辑，必须保证全部三条路径正常工作。
**测试要求**：
- Planner：快速路径 / LLM 路径 / 缓存 / 回退
- Router：工作流路径 / 多步路径 / 直接对话路径
- Executor：拓扑排序 / 多步执行 / 错误处理

### 8.7 Step 7: Agent

**目标**：Agent 从 Runtime 中独立。

**修改范围**：
- 新建 `agent/` 目录：`base.py`、`factory.py`
- 从 `runtime/agents/base.py` → `agent/base.py`
- 从 `runtime/factory.py` 中移出 Agent 创建逻辑到 `agent/factory.py`
- 删除 `runtime/agents/` 目录

**风险**：中。Agent 是执行的核心，创建逻辑的迁移需要精确。
**测试要求**：Agent.run() / astream() 测试、工具绑定测试、中断恢复测试。

### 8.8 Step 8: Memory

**目标**：Memory 通过 Event 驱动而非手动调用。

**修改范围**：
- 新建 `memory/context_builder.py`（从 `runtime/context.py` 迁移）
- `memory/pipeline.py` 改为订阅 Event(AGENT_TURN_COMPLETED) 而非被 Runtime 手动调用
- 删除 `runtime/context.py`

**风险**：低-中。Memory 逻辑本身不变，只改变触发方式。
**测试要求**：FactStore CRUD 测试、ContextBuilder 组装测试、事件驱动触发测试。

### 8.9 Step 9: Workflow

**目标**：Workflow 从 Runtime 中独立。

**修改范围**：
- 新建 `workflow/` 目录：`engine.py`、`registry.py`、`helpers.py`、`state.py`、`definitions/`
- 从 `runtime/workflows/` → `workflow/definitions/`
- 从 `runtime/registry.py` → `workflow/registry.py`
- 从 `runtime/state.py` → `workflow/state.py`
- 删除 `runtime/workflows/` 和 `runtime/registry.py` 和 `runtime/state.py`

**风险**：中。工作流注册方式变化（不再用 import side-effect）。
**测试要求**：每个工作流的端到端测试（dev / diagnosis / research）。

### 8.10 Step 10: Interface

**目标**：Interface 层独立 + Runtime 重构完成。

**修改范围**：
- 新建 `interface/` 目录：`cli/`、`channels/`、`daemon.py`
- 从 `cli/` → `interface/cli/`
- 从 `channels/` → `interface/channels/`
- 重构 `runtime/factory.py` → `runtime/process.py`（仅保留进程管理）
- 删除 `runtime/factory.py`
- 创建新的 `runtime/__init__.py` 统一入口

**风险**：**高**。这是最终组装步骤，所有模块在这里集成。
**测试要求**：完整的端到端测试（CLI 输入 → 响应输出）、守护进程启动/停止测试。

### 8.11 迁移后清理

完成所有步骤后：

- [ ] 删除 `core/` 目录（内容已迁移到 kernel / model / infrastructure）
- [ ] 删除 `config/haven.yaml` 之外的 `config/` 文件（逻辑已迁移到 kernel）
- [ ] 删除 `runtime/` 中的旧文件（coordinator / dispatcher / context / state / stream / registry / agents / workflows）
- [ ] 删除 `middleware/` 目录
- [ ] 更新 `pyproject.toml` 版本号至 `2.0.0`
- [ ] 更新 `CLAUDE.md` 中的架构说明
- [ ] 确保 `uv run haven` 可运行
- [ ] 确保所有测试通过
- [ ] 删除 `.docs/` 中的旧架构文档（或标记为历史参考）

---

## 附录 A：当前架构问题清单

| 问题 | 当前表现 | V2 解决方案 |
|------|---------|------------|
| Runtime 大杂烩 | `factory.py` 同时做配置/Agent/工具/工作流/Memory 的创建 | 拆分为 Kernel + Runtime + Agent + Capability + Workflow |
| 无 Session 抽象 | `RuntimeState` 太薄，会话管理散落各处 | `SessionManager` + `SessionState` 一等模块 |
| 无事件系统 | Memory 通过 `Runtime._trigger_memory()` 手动调用 | EventBus 发布/订阅，解耦 Memory 触发 |
| 无 Execution 抽象 | Coordinator + Dispatcher 紧耦合于 Runtime | Planner + Router + StepExecutor 独立管道 |
| Skill/Tool 分离 | 两个独立模块，但都是 Agent 的能力来源 | 统一到 Capability 层 |
| Workflow 耦合 | `runtime/workflows/` 通过 import side-effect 注册 | 独立 Workflow 模块，装饰器注册 |
| 死代码 | `middleware/` 模块未被使用 | 删除 |
| 类型分散 | Pydantic model 散落在各模块中 | 集中在 `model/` 目录 |
| 无 DI | `factory.py` 硬编码所有创建依赖 | Kernel DI 容器 + AgentFactory |
| 无接口契约 | 类之间直接依赖具体实现 | ABC / Protocol 定义接口 |
