# Haven 运行时层架构文档

> 生成日期: 2026-06-07 | Haven v3.0.0

## 一、架构总览

Haven 运行时层 (`src/haven/runtime/`) 是整个框架的执行核心，实现了 **Coordinator + 专业 Agent + 工作流引擎** 的三层调度模型。

```
                         用户输入
                            │
                            ▼
                   ┌─────────────────┐
                   │   Coordinator   │  ← 任务规划 + Agent 调度
                   │   (coordinator) │
                   └───────┬─────────┘
                           │ plan() → ExecutionPlan
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌──────────┐   ┌────────────┐   ┌──────────┐
    │ Workflow │   │ Multi-Step │   │  Direct  │
    │  Graph   │   │  拓扑排序   │   │  Agent   │
    └────┬─────┘   └─────┬──────┘   └────┬─────┘
         │               │               │
         └───────────────┼───────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │   prepare_agent()   │  ← 统一执行前钩子
              │  (skill 合并 +      │
              │   tool 绑定 +       │
              │   system_prompt)    │
              └─────────┬───────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │     BaseAgent       │  ← LangGraph ReAct Agent
              │  (run / astream)    │
              └─────────────────────┘
```

**三条执行路径（按优先级）：**

| 优先级 | 路径 | 触发条件 | 说明 |
|--------|------|----------|------|
| 1 | Workflow Graph | `ExecutionPlan.workflow` 非空 | DAG 工作流引擎，节点化执行 |
| 2 | Multi-Step | `ExecutionPlan.steps` 非空 | 拓扑排序 → 逐步执行 |
| 3 | Direct Agent | 以上皆空 | 单轮 ReAct Agent 直通 |

---

## 二、目录结构

```
src/haven/runtime/
├── __init__.py           # 公开 API 导出
├── coordinator.py        # Coordinator — 任务规划 + 调度
├── factory.py            # create_coordinator() — 系统装配入口
├── context.py            # ContextBuilder — 统一 system prompt 构建
├── state.py              # AgentState TypedDict (LangGraph 兼容)
├── registry.py           # WorkflowRegistry — 工作流注册中心
├── agents/
│   ├── __init__.py       # BaseAgent 重导出
│   └── base.py           # BaseAgent — 专业 Agent 基类
└── graphs/
    ├── __init__.py       # create_checkpointer()
    ├── _helpers.py       # 工作流节点共享辅助函数
    ├── dev.py            # DevAgentState + 5 步开发工作流
    ├── research.py       # ResearchAgentState + 3 步调研工作流
    └── diagnosis.py      # DiagnosisAgentState + 3 步诊断工作流
```

---

## 三、核心组件详解

### 3.1 Coordinator (`coordinator.py`)

**职责：** 运行时层大脑。一次 LLM 调用完成意图分类、Agent 选择、Skill 选择、步骤拆解、Workflow 匹配。

#### Pydantic 数据模型

```python
class PlanStep(BaseModel):
    order: int                    # 步骤编号 (从 1 开始)
    description: str              # 自然语言步骤描述
    skill: str | None = None      # 此步骤需要的 skill 名称
    depends_on: list[int] = []    # 依赖的前置步骤编号
    expected_output: str = ""     # 期望输出描述

class ExecutionPlan(BaseModel):
    goal: str                     # 一句话目标
    intent: str                   # 意图分类标签
    agent_type: str               # "coder" | "researcher" | "diagnosis" | "general"
    complexity: str               # "simple" | "medium" | "complex"
    skills: list[str] = []        # 要激活的 skill 名称
    workflow: str | None = None   # 匹配的预定义工作流名称
    steps: list[PlanStep] = []    # 执行步骤
    reasoning: str = ""           # 规划理由
```

#### 构造方法

```python
class Coordinator:
    def __init__(
        self,
        agents: dict[str, BaseAgent],         # {"coder": ..., "researcher": ..., ...}
        llm: BaseChatModel,                   # 规划用 LLM
        *,
        workflow_registry: type = None,       # WorkflowRegistry 类引用
        state: RuntimeState = None,           # 所有 Agent 共享的会话状态
        context_builder: ContextBuilder = None,
        tool_resolver: ToolResolver = None,   # 动态 tool 解析
        fact_store: FactStore = None,         # 长期记忆 (SQLite)
        checkpointer: AsyncSqliteSaver = None,# LangGraph checkpointer
        use_memory: bool = True,
    )
```

#### 公共方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `plan` | `async plan(task: str) -> ExecutionPlan` | 分析任务，返回结构化执行计划。短问候语走缓存。 |
| `execute` | `async execute(task: str) -> str` | plan + dispatch，3 条路径自动选择 |
| `execute_stream` | `async execute_stream(task: str) -> AsyncIterator[str]` | 流式版 execute，逐 token 产出 |
| `prepare_agent` | `async prepare_agent(agent, skill_names, *, task="") -> str` | 统一执行前钩子：合并 skill → 解析 tool → 绑定 → 构建 system_prompt |
| `switch_model` | `def switch_model(model_name: str) -> str` | 热替换所有 Agent 的 LLM |
| `reset_session` | `async reset_session() -> None` | 清空 turn 状态 + checkpointer 线程历史 |
| `reset` | `def reset() -> None` | 同步重置 turn 状态 (兼容旧版) |

#### 内部方法

| 方法 | 说明 |
|------|------|
| `_is_trivial(task)` | 常见问候语类方法检测，命中则走缓存免 LLM 调用 |
| `_cache_key(task)` | MD5 哈希，用于 plan 缓存 (LRU, 128 项) |
| `_llm_plan(task)` | 调用 LLM `with_structured_output(ExecutionPlan)`，DeepSeek 模型关闭 thinking 模式 |
| `_build_skill_menu()` | 从 SkillRegistry 格式化可用 skill 菜单 |
| `_get_workflow_menu()` | 从 WorkflowRegistry 格式化可用工作流菜单 |
| `_validate_plan(plan)` | 过滤不存在的 skill 名称 |
| `_pick_agent_for_step(step, default_type)` | 根据 skill 名称启发式选择步骤 Agent |
| `_execute_via_workflow(plan, task)` | 编译 LangGraph StateGraph 并执行 |
| `_execute_steps(plan, task)` | Kahn 拓扑排序 → 顺序执行 |
| `_topological_sort(steps)` | 静态 Kahn 算法，处理步骤依赖 |

#### 缓存机制

- `_plan_cache`: LRU 字典 (max 128)，key = MD5(task)，value = ExecutionPlan
- `_is_trivial()`: 类变量 `_TRIVIAL_GREETINGS` 预设常见问候语，命中后直接返回预设 plan，完全跳过 LLM

---

### 3.2 BaseAgent (`agents/base.py`)

**职责：** 专业 Agent 基类，封装 LangGraph `create_react_agent`。每个 Agent 持有特定的 tool 子集 + skill 子集 + system_prompt。

```python
class BaseAgent:
    def __init__(
        self,
        name: str,                           # "coder" | "researcher" | "diagnosis" | "general"
        llm: BaseChatModel,                  # Agent 使用的 LLM
        tools: list[BaseTool],               # 基础工具集
        checkpointer: AsyncSqliteSaver,      # 共享的 checkpointer
        state: RuntimeState,                 # 共享的轮次状态
        *,
        agent_prompt: str = "",              # Agent 专属 prompt
        default_skills: list[str] = None,    # Agent 始终携带的 skill
        max_iterations: int = None,          # ReAct 循环上限
    )
```

**公共方法：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `run` | `async run(task, *, system_prompt="") -> str` | 同步执行：构建 Agent → `ainvoke` → 返回结果 |
| `astream` | `async astream(task, *, system_prompt="") -> AsyncIterator[str]` | 流式执行：`astream_events(v2)` → 过滤 `on_chat_model_stream` → yield 文本块 |
| `set_tools` | `def set_tools(tools: list[BaseTool]) -> None` | 动态替换工具集，触发 Agent 重建 |
| `restore_base_tools` | `def restore_base_tools() -> None` | 恢复到初始工具集 |
| `reset` | `def reset() -> None` | 重置轮次状态 |

**核心机制：**
- **惰性 Agent 构建**：`_agent` 通过 `_get_agent()` 惰性创建，工具集变化时通过哈希对比自动重建 (`_agent_tools_hash`)
- **pre_model_hook**：每次 LLM 调用前注入 `system_prompt`，并通过 `trim_messages()` 裁剪消息确保不超 context window
- **turn_count 递增**：每次 `run()` / `astream()` 调用自动递增 `state.turn_count`

---

### 3.3 工厂函数 (`factory.py`)

**职责：** 系统装配的唯一入口。按固定顺序实例化所有组件并注入 Coordinator。

```python
async def create_coordinator(
    session_id: str = "default",
    entity_name: str = "user",
    channel: str = "default",
    *,
    load_skills: bool = True,
    load_mcp: bool = True,
    use_memory: bool | None = None,
) -> Coordinator:
```

**装配序列：**

```
 1. RuntimeState 创建 (session_id, entity_name, channel)
 2. Skills 加载     → haven.md 人格 + skills/ 目录
 3. LLM 创建        → create_llm(default_model)
 4. ToolManager 初始化 → BuiltinProvider + MCPProvider(s)
 5. Checkpointer 创建 → AsyncSqliteSaver (resource/checkpoint.db)
 6. ContextBuilder 创建
 7. ToolResolver 创建
 8. FactStore 创建    → (如果 use_memory=True)
 9. BaseAgent ×4 创建 → coder, researcher, diagnosis, general
10. Workflow 注册     → side-effect import dev/research/diagnosis
11. Coordinator 组装  → 注入所有组件
```

---

### 3.4 ContextBuilder (`context.py`)

**职责：** 统一 system prompt 构建，按优先级 + token 预算组装。

```python
class ContextBuilder:
    def __init__(self, token_budget: int = None):
        # 默认 8000 tokens，从 settings.context_window_tokens 读取

    def build(
        self,
        *,
        agent_prompt: str = "",
        skills: list[str] = None,
        task: str = "",
        history_summary: str = "",
    ) -> BuildResult:
```

**组装优先级 (高→低)：**

| 优先级 | 组件 | 来源 | 预算策略 |
|--------|------|------|----------|
| 1 | Personality | `haven.md` 静态文本 | 全量保留 |
| 2 | Agent Prompt | Agent 专属指令 | 全量保留 |
| 3 | Skills Prompt | 匹配的 skill 描述 | 最多占用剩余预算的 60% |
| 4 | Project Files | 工作区文件列表 (.py/.md/.yaml/.json) | 最多 500 tokens / 50 个文件 |
| 5 | History Summary | 长期记忆事实摘要 | 填满剩余预算 |

**BuildResult：**
```python
@dataclass
class BuildResult:
    system_prompt: str            # 最终组装后的 prompt
    token_usage: dict[str, int]   # 各部分的 token 消耗
```

---

### 3.5 AgentState (`state.py`)

**职责：** LangGraph 工作流的基类状态定义。

```python
class AgentState(TypedDict, total=False):
    task: str
    session_id: str
    messages: Annotated[list[BaseMessage], add]               # 消息列表 (追加归约)
    errors: Annotated[list[str], add]                         # 错误列表 (追加归约)
    completed_steps: Annotated[list[str], add]                # 已完成步骤 (追加归约)
    current_step: str
    node_outputs: Annotated[dict[str, str], _merge_dict]      # 节点输出 (合并归约)
    node_retry_counts: Annotated[dict[str, int], _merge_dict] # 重试计数 (合并归约)
    max_retries_per_node: int
    status: str
    final_output: str
    started_at: float
```

三个工作流各定义自己的扩展状态（见第四节）。

---

### 3.6 WorkflowRegistry (`registry.py`)

**职责：** 继承 `Registry` 基类，管理 LangGraph 工作流的注册与构建。

```python
class WorkflowRegistry(Registry):
    _label = "Workflow"

    @classmethod
    def get_selection_context(cls) -> str:
        """格式化所有已注册工作流为 LLM 菜单 (名称、描述、用例、步骤数)"""

    @classmethod
    def build(cls, name: str) -> CompiledStateGraph:
        """按名称查找工厂函数并调用，返回编译后的 StateGraph"""
```

工作流注册通过装饰器模式：
```python
@WorkflowRegistry.register("dev_flow")
def _create_dev_workflow() -> StateGraph:
    ...
_create_dev_workflow.description = "..."
_create_dev_workflow.use_cases = "..."
_create_dev_workflow.step_count = 5
```

---

## 四、预定义工作流

### 4.1 开发工作流 (`graphs/dev.py`)

5 步 DAG：`planner → architect → coder → reviewer → tester`，失败自动重试 (最多 3 次)。

```
planner ──→ architect ──→ coder ──→ reviewer ──→ tester
                              ↑                        │
                              └── 重试 (test_passed=False & retries<3)
```

**扩展状态 (DevAgentState)：**
```python
architecture_doc: str           # 架构设计文档
source_code: str                # 生成的代码
code_language: str              # 目标编程语言
review_feedback: str            # 审查反馈
review_score: float             # 审查评分 (0-100)
review_blockers: list[str]      # 阻塞项列表
test_report: str                # 测试报告
test_passed: bool               # 测试通过标志
test_failures: list[str]        # 测试失败项
```

### 4.2 调研工作流 (`graphs/research.py`)

3 步循环：`searcher → analyst → synthesizer`，知识缺口自动重搜 (最多 3 次)。

```
searcher ──→ analyst ──(知识缺口 & retries<3)──→ searcher (重搜)
                │
                └──(无缺口)──→ synthesizer
```

**扩展状态 (ResearchAgentState)：**
```python
research_topic: str             # 调研主题
raw_findings: list[str]         # 原始发现 (追加归约)
analyzed_insights: str          # 分析后的洞察
final_report: str               # 最终报告 (Markdown)
sources: list[str]              # 来源列表 (追加归约)
```

### 4.3 诊断工作流 (`graphs/diagnosis.py`)

3 步线性：`collector → analyzer → adviser`，无分支/重试。

```
collector ──→ analyzer ──→ adviser
```

**扩展状态 (DiagnosisAgentState)：**
```python
symptoms: str                   # 症状描述
collected_info: str             # 收集到的信息
possible_causes: str            # 可能病因 (含置信度)
diagnosis: str                  # 诊断结论
recommendations: str            # 分级建议 (自我护理/就医/紧急)
```

### 4.4 工作流辅助函数 (`graphs/_helpers.py`)

```python
def get_agent(config: dict, prefer: str = "general") -> BaseAgent:
    """从运行时配置中选择专业 Agent，prefer 不命中则回退到 config["agent"]"""

async def run_agent_node(
    config: dict,
    prompt: str,
    *,
    skill_names: list[str] = None,
    agent_type: str = "general",
    task: str = "",
) -> str:
    """工作流节点统一执行入口：获取 Agent → prepare_agent → agent.run()"""

def resolve_skills(names: list[str]) -> list[BaseSkill]:
    """从 SkillRegistry 按名称批量解析 skill"""
```

---

## 五、支撑层速览

### 5.1 Core 层

| 组件 | 文件 | 说明 |
|------|------|------|
| `RuntimeState` | `core/state.py` | 对话会话状态 dataclass (session_id, entity_name, channel, turn_count...) |
| `Registry` | `core/registry.py` | 所有注册中心的基类 (register/get/list_all/clear) |
| `create_llm` | `core/llm.py` | LLM 工厂函数，从 models.yaml 读取配置创建 LangChain 模型 |

### 5.2 Tools 层

```
ToolManager ──编排──→ ToolProvider(s)
    │                    ├── BuiltinProvider  (web_search)
    │                    └── MCPProvider(s)   (stdio/HTTP SSE/WebSocket)
    │
    └── ToolResolver ──→ 语义匹配 (名称 → 标签 → 类别 → 能力关键词)
```

| 组件 | 文件 | 说明 |
|------|------|------|
| `ToolManager` | `tools/manager.py` | 编排所有 Provider 生命周期，提供工具检索 API |
| `ToolResolver` | `tools/resolver.py` | 语义解析层，将 skill 声明的工具需求解析为具体工具实例 |
| `ToolProvider` | `tools/providers/base.py` | 提供者抽象基类 (状态机: UNINITIALIZED→CONNECTING→CONNECTED/DEGRADED/ERROR) |
| `BuiltinProvider` | `tools/providers/builtin.py` | 内置工具提供者 (web_search 等) |
| `MCPProvider` | `tools/providers/mcp.py` | MCP 协议提供者，支持 stdio/HTTP SSE/WebSocket |
| `HavenTool` | `tools/base.py` | 统一工具基类，带 ToolMetadata (category, permissions, cost...) |

### 5.3 Skills 层

| 组件 | 文件 | 说明 |
|------|------|------|
| `BaseSkill` | `skills/base_skill.py` | Skill dataclass: name, description, prompt, tags, tools, dependencies |
| `SkillLoader` | `skills/loader.py` | 扫描 `*.md` 文件，解析 YAML frontmatter → BaseSkill |
| `SkillRegistry` | `skills/registry.py` | 技能注册中心：分类查询、标签过滤、依赖传递闭包解析 |

### 5.4 Config 层

| 组件 | 文件 | 说明 |
|------|------|------|
| `Settings` | `config/settings.py` | pydantic-settings 全局单例，内置 YAML < 用户 YAML < 环境变量 |
| `loader` | `config/loader.py` | models.yaml 加载与模型配置解析 |
| `mcp` | `config/mcp.py` | mcp.json 解析 (MCPServerConfig) |

---

## 六、典型执行流程

### 简单对话路径

```
用户: "你好"
  → Coordinator.plan("你好")
    → _is_trivial("你好") = True
    → 缓存命中，返回 ExecutionPlan(agent_type="general", complexity="simple")
  → Coordinator.execute()
    → plan.steps 为空, plan.workflow 为空
    → 路径 3: 直接发往 general Agent
    → prepare_agent(general, skills=[]) → 构建 system_prompt
    → general.run("你好", system_prompt=...)
    → 返回结果
```

### 复杂多步骤路径

```
用户: "帮我写一个 Flask API，包含用户认证"
  → Coordinator.plan(task)
    → LLM 结构化输出 →
      ExecutionPlan(
        agent_type="coder",
        complexity="complex",
        skills=["coder"],
        steps=[
          PlanStep(order=1, description="设计 API 结构", ...),
          PlanStep(order=2, description="实现认证逻辑", depends_on=[1], ...),
          PlanStep(order=3, description="编写测试", depends_on=[2], ...),
        ]
      )
  → Coordinator._execute_steps(plan, task)
    → _topological_sort(steps) → [1, 2, 3]
    → 逐步执行: 每个 step 调用对应 Agent.run()
    → 返回最终步骤结果
```

### 工作流路径

```
用户: "开发一个用户管理系统"
  → Coordinator.plan(task)
    → LLM 匹配 → ExecutionPlan(workflow="dev_flow", ...)
  → Coordinator._execute_via_workflow(plan, task)
    → WorkflowRegistry.build("dev_flow") → 编译 StateGraph
    → state = DevAgentState(task=...)
    → graph.ainvoke(state) 一次性跑完 planner→architect→coder→reviewer→tester
    → 如有测试失败自动重试 coder 节点
    → 返回 final_output
```

---

## 七、扩展点

### 添加新的专业 Agent

在 `haven.yaml` 的 `agents` 段添加定义：
```yaml
agents:
  translator:
    description: "多语言翻译专家"
    tools: [web_search]
    skills: [translation]
    prompt: "你是翻译专家，擅长中英日韩互译。"
```

`factory.py` 会自动读取并创建对应的 `BaseAgent` 实例。

### 添加新的工作流

1. 在 `graphs/` 下新建文件，定义 `XxxAgentState(AgentState)`
2. 实现节点函数（调用 `_helpers.run_agent_node`）
3. 创建 `_create_xxx_workflow() → StateGraph` 工厂函数
4. 用 `@WorkflowRegistry.register("xxx_flow")` 注册
5. 在 `factory.py` 中添加 side-effect import

### 添加新的工具提供者

1. 继承 `ToolProvider`，实现 `discover()` 和 `health_check()`
2. 在 `ToolManager` 初始化时 `add_provider(YourProvider())`
3. 工具自动以 `{provider_name}__{tool_name}` 命名接入

---

## 八、配置参考

| 配置项 | 默认值 | 环境变量 | 说明 |
|--------|--------|----------|------|
| `agent.max_iterations` | 20 | `AGENT_MAX_ITERATIONS` | ReAct 循环最大步数 |
| `agent.max_execution_time` | 300 | `AGENT_MAX_EXECUTION_TIME` | 单次执行超时 (秒) |
| `context.token_budget` | 8000 | - | system prompt token 预算 |
| `context.file_max_tokens` | 500 | - | 项目文件列表最大 token |
| `memory.enabled` | true | `MEMORY_ENABLED` | 是否启用长期记忆 |
| `memory.db_path` | `resource/memory.db` | `MEMORY_DB_PATH` | 事实存储路径 |
| `memory.context_window_tokens` | 8000 | `CONTEXT_WINDOW_TOKENS` | 上下文窗口大小 |
| `skill.directory` | `skills` | `SKILL_DIRECTORY` | 用户 skill 目录 |
| `mcp.enabled` | true | `MCP_ENABLED` | 是否启用 MCP 工具 |

模型的 `api_key_env` 在 `models.yaml` 中声明，CLI 层会自动从对应环境变量读取 API Key。
