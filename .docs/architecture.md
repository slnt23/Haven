# Haven V2 项目架构

基于 Python 3.14+、LangChain 与 pydantic-settings 构建的多智能体交互框架。

**V2 核心变化：** Agent = 纯执行引擎（Runtime），领域能力由 Skill `.md` 文件注入（零代码），任务规划由 PlannerAgent 驱动（LLM Structured Output），工具统一由 Provider 架构管理，记忆升级为四层体系，工作流升级为 DAG 引擎。

## 目录结构

```
haven/
├── pyproject.toml                    # 项目元信息，haven 命令入口
├── mcp.json                          # MCP Provider 配置
├── haven.yaml                        # 用户配置覆盖（deep-merge app.yaml）
├── models.yaml                       # 用户模型定义（可选）
├── CLAUDE.md                         # Claude Code 项目指令
│
├── skills/                           # 【零代码扩展】Skill 定义 (.md)
│   ├── code_review.md                #   代码审查 — 按需激活
│   ├── data_analysis.md              #   数据分析 — 按需激活
│   ├── summarization.md              #   摘要总结 — 按需激活
│   └── translation.md                #   翻译 — 按需激活
│
├── .data/                            #   运行时数据（自动创建）
│   ├── memory.db                     #   SQLite (episodic + semantic + checkpoints)
│   ├── chroma/                       #   Vector store (ChromaDB)
│   └── haven.pid                     #   守护进程 PID
│
└── src/haven/                        #   源码
    │
    ├── config/                       # 1. 配置层
    │   ├── __init__.py               #   导出 settings + loader
    │   ├── settings.py               #   Pydantic BaseSettings 单例
    │   ├── loader.py                 #   OmegaConf YAML 加载 + deep-merge
    │   ├── app.yaml                  #   框架默认参数
    │   ├── models.yaml               #   LLM 模型定义（内置默认）
    │   └── haven.md                  #   核心人格 Skill（随包分发，default: true）
    │
    ├── core/                         # 2. 核心基础设施
    │   ├── __init__.py               #
    │   ├── llm.py                    #   LLM 生命周期（init / switch / bind）
    │   ├── prompt.py                 #   PromptBuilder + TokenBudget
    │   ├── state.py                  #   RuntimeState 会话状态
    │   ├── registry.py               #   通用 Registry 基类
    │   ├── memory.py                 #   AgentMemory（V1 facade，委托 V2 MemoryManager）
    │   └── pidfile.py                #   守护进程 PID 文件管理
    │
    ├── runtime/                      # 3. 运行时层 ★ 核心 ★
    │   ├── __init__.py               #   统一导出
    │   ├── runtime.py                #   AgentRuntime — 纯执行引擎
    │   ├── planner.py                #   PlannerAgent + ExecutionPlan + PlanStep
    │   └── factory.py                #   create_agent() 系统装配
    │
    ├── skills/                       # 4. Skill 系统
    │   ├── __init__.py               #
    │   ├── base_skill.py             #   BaseSkill dataclass (V2 Schema)
    │   ├── loader.py                 #   SkillLoader — .md 扫描 + YAML 解析
    │   └── registry.py               #   SkillRegistry — 查询 + 依赖解析
    │
    ├── memory/                       # 5. Memory 系统
    │   ├── __init__.py               #
    │   ├── base.py                   #   BaseMemory ABC + MemoryItem + MemoryContext
    │   ├── working.py                #   WorkingMemory — 滑动窗口 + 摘要
    │   ├── episodic.py               #   EpisodicMemory — SQLite 对话记录
    │   ├── semantic.py               #   SemanticMemory — 结构化事实 + 变更历史
    │   ├── vector.py                 #   VectorMemory — ChromaDB 语义检索
    │   └── manager.py                #   MemoryManager — 四层编排
    │
    ├── tools/                        # 6. Tool 系统 (Provider Architecture)
    │   ├── __init__.py               #
    │   ├── base.py                   #   HavenTool + ToolMetadata + ToolCategory
    │   ├── manager.py                #   ToolManager — Provider 编排
    │   ├── mcp_config.py             #   MCPServerConfig + load_mcp_servers()
    │   │
    │   ├── providers/                #   Provider 实现层
    │   │   ├── __init__.py           #
    │   │   ├── base.py               #   ToolProvider ABC
    │   │   ├── builtin.py            #   BuiltinProvider — 自动发现内置工具
    │   │   └── mcp.py                #   MCPProvider — MCP 服务器适配
    │   │
    │   ├── code_exec.py              #   Python/Shell 沙箱执行
    │   ├── file_ops.py               #   文件读写
    │   ├── web_search.py             #   网络搜索
    │   ├── email_tool.py             #   邮件发送
    │   ├── medical.py                #   医学知识查询
    │   └── rag_search.py             #   RAG 知识库检索
    │
    ├── workflows/                    # 7. Workflow 引擎
    │   ├── __init__.py               #
    │   ├── graph.py                  #   WorkflowGraph — DAG 执行引擎
    │   ├── state.py                  #   WorkflowState + 领域特化 States
    │   ├── nodes.py                  #   WorkflowNode 基类 + 12 个内置节点
    │   ├── edges.py                  #   Edge + ConditionalEdge + Router 函数
    │   ├── checkpoint.py             #   Checkpointer + SQLiteCheckpointer
    │   ├── registry.py               #   WorkflowRegistry
    │   │
    │   └── graphs/                   #   预定义工作流图
    │       ├── __init__.py           #
    │       ├── dev.py                #   软件开发工作流 (5 节点)
    │       ├── research.py           #   调研工作流 (3 节点)
    │       └── diagnosis.py          #   诊断工作流 (3 节点)
    │
    ├── cli/                          # 8. CLI 交互层 (Typer + Rich)
    │   ├── __init__.py               #   模块导出
    │   ├── main.py                   #   Typer 入口 + 命令注册 + global callback
    │   ├── validators.py             #   validate_task / validate_model_name
    │   │
    │   ├── commands/                 #   命令实现
    │   │   ├── __init__.py           #   命令注册表
    │   │   ├── chat.py               #   haven chat — REPL (RuntimeService.chat)
    │   │   ├── run.py                #   haven run  — 单轮 (RuntimeService.run_task)
    │   │   ├── skill.py              #   haven skill {list,info,search,add,remove,reload}
    │   │   ├── tool.py               #   haven tool {list,info}
    │   │   ├── workflow.py           #   haven workflow {list,info,run,resume,history}
    │   │   └── doctor.py             #   haven doctor — 环境诊断
    │   │
    │   ├── ui/                       #   终端渲染 (Rich)
    │   │   ├── __init__.py           #
    │   │   ├── console.py            #   render_table / render_json / render_kv / render_status
    │   │   ├── banner.py             #   print_banner() — V2 启动横幅
    │   │   └── progress.py           #   spinner / StreamRenderer / NodeWatcher
    │   │
    │   └── services/                 #   CLI 服务
    │       ├── __init__.py           #
    │       ├── cli_service.py        #   CLIContext / HistoryManager / TabCompleter
    │       └── runtime_service.py    #   RuntimeService — CLI ↔ Runtime 唯一桥梁
    │
    └── services/                     # 9. 服务层 (Daemon + Channels)
        ├── __init__.py               #
        ├── base_channel.py           #   BaseChannel 渠道抽象
        ├── daemon.py                 #   HavenDaemon 守护进程
        ├── socket_channel.py         #   SocketChannel TCP REPL
        ├── email_channel.py          #   EmailChannel IMAP/SMTP
        ├── email_service.py          #   EmailService 邮件收发核心
        └── feishu_channel.py         #   FeishuChannel 飞书/Lark
```

## V2 核心架构

```
                         User Input
                              │
                     ┌────────▼────────┐
                     │  PlannerAgent    │  1 次 LLM Structured Output
                     │  plan(task)      │  → ExecutionPlan
                     │  execute(task)   │     {goal, skills, workflow, steps}
                     └────────┬────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
     (有workflow)     (有steps)        (简单对话)
              │               │               │
     ┌────────▼────────┐ ┌───▼────┐  ┌───────▼──────┐
     │ WorkflowGraph   │ │顺序执行│  │ Runtime.run() │
     │ (DAG + Router)  │ │        │  │ (默认人格)    │
     └────────┬────────┘ └───┬────┘  └──────────────┘
              │               │
              └───────┬───────┘
                      │
              ┌───────▼───────┐
              │ AgentRuntime  │  纯执行引擎
              │               │
              │ LLM + Tool    │
              │ Memory + State│
              │ Prompt        │
              └───────┬───────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
  ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
  │ Skill     │ │ Memory    │ │ Tool      │
  │ Registry  │ │ Manager   │ │ Manager   │
  │           │ │           │ │           │
  │ 注册/查询 │ │ Working   │ │ Builtin   │
  │ 依赖解析  │ │ Episodic  │ │ MCP       │
  │           │ │ Semantic  │ │           │
  │           │ │ Vector    │ │           │
  └───────────┘ └───────────┘ └───────────┘
```

## 分层详解

### 1. 配置层 `config/`

配置文件分层加载，优先级：**内置默认 < 用户 YAML（CWD）< 环境变量**。

| 文件 | 位置 | 职责 |
|------|------|------|
| `app.yaml` | `src/haven/config/` | 框架默认参数（runtime / RAG / email / MCP / memory / skill） |
| `models.yaml` | `src/haven/config/` | LLM 模型定义（内置默认） |
| `haven.yaml` | CWD | 用户覆盖框架参数（optional） |
| `models.yaml` | CWD | 用户追加/覆盖模型定义（optional） |
| `mcp.json` | CWD | MCP Provider 配置 |

### 2. 核心基础设施 `core/`

| 模块 | 职责 |
|------|------|
| `llm.py` | LLM 生命周期：`create_llm()`, `switch_llm()`, `bind_tools()` |
| `prompt.py` | `PromptBuilder` — 按优先级（人格 > 领域 > 记忆 > RAG）组装 system prompt；`TokenBudget` 控制 token 预算 |
| `state.py` | `RuntimeState` dataclass — 会话状态（session_id, active_skills, active_tools, turn_count） |
| `registry.py` | 通用 Registry 基类 — `register()` / `get()` / `list_all()` 类方法 |
| `memory.py` | `AgentMemory` — V1 facade，内部委托到 V2 `MemoryManager` |
| `pidfile.py` | 守护进程 PID 文件管理 |

### 3. 运行时层 `runtime/` ★ 核心 ★

| 模块 | 职责 |
|------|------|
| `runtime.py` | `AgentRuntime` — 纯执行引擎。五职责：LLM + Tool + Memory + State + Prompt。零业务逻辑 |
| `planner.py` | `PlannerAgent` — 一次 LLM 调用完成：意图分类 + 任务拆解 + Skill 选择 + Workflow 匹配。`ExecutionPlan` + `PlanStep` |
| `factory.py` | `create_agent()` — 创建 Runtime → 加载 Skills → 初始化 LLM → 装配 ToolManager → 创建 Planner → 返回 |

### 4. Skill 系统 `skills/`

| 模块 | 职责 |
|------|------|
| `base_skill.py` | `BaseSkill` dataclass：name, description, tags, tools, dependencies, version, prompt |
| `loader.py` | `SkillLoader` — 扫描 `skills/*.md`，解析 YAML frontmatter |
| `registry.py` | `SkillRegistry` — `get_defaults()`, `get_domain_skills()`, `resolve_dependencies()`, `get_selection_context()` |

Skill 选择由 `PlannerAgent.plan()` 内嵌完成：LLM 根据 Skill 的 `description` 和 `tags` 语义匹配，无需独立的 Selector 模块。`SkillRegistry.resolve_dependencies()` 自动补全传递依赖。

### 5. Memory 系统 `memory/`

四层记忆架构，由 `MemoryManager` 统一编排：

| 层 | 实现 | 存储 | 生命周期 | 用途 |
|----|------|------|----------|------|
| Working | `WorkingMemory` | 内存 deque | 会话 | 当前上下文窗口 + 摘要压缩 |
| Episodic | `EpisodicMemory` | SQLite `episodes` | 永久 | 完整对话记录 + 关键词检索 |
| Semantic | `SemanticMemory` | SQLite `memory_*` | 永久 | 结构化事实 + 变更历史 + 置信度衰减 |
| Vector | `VectorMemory` | ChromaDB | 永久 | 语义相似性检索 + 跨 session 模式匹配 |

**检索流程：** `MemoryManager.retrieve(task)` → 四路并行 → 合并为 `MemoryContext` → `format_for_prompt()` 注入 system prompt

### 6. Tool 系统 `tools/` — Provider Architecture

统一工具发现机制，所有工具来源通过 `ToolProvider` 接口接入：

| Provider | 工具来源 | 发现方式 |
|----------|---------|---------|
| `BuiltinProvider` | 内置工具 (code_exec, file_ops, web_search 等 6 个) | 自动扫描 `tools/` 目录 |
| `MCPProvider` | MCP 服务器 (stdio/HTTP/WebSocket) | 连接 → discover → 适配 |

`ToolManager` 编排 Provider 生命周期：注册 → start → discover → 全局注册表 → 按 skill/tag/category 检索 → stop。

Provider 状态机：UNINITIALIZED → CONNECTING → CONNECTED / DEGRADED / ERROR → DISCONNECTED。

MCP 工具以 `{server_name}__{tool_name}` 命名空间注册，避免冲突。MCP 配置从 CWD 下的 `mcp.json` 加载（标准 `mcpServers` 格式），`MCPServerConfig` Pydantic 模型校验。

### 7. Workflow 引擎 `workflows/`

DAG 执行引擎，支持条件路由 + 失败重试 + Checkpoint 持久化：

| 工作流 | 节点数 | 结构 | 用途 |
|--------|--------|------|------|
| `dev_flow` | 5 | planner → architect → coder → reviewer → tester（tester fail → coder 重试 ≤3） | 软件开发 |
| `research_flow` | 3 | searcher → analyst → synthesizer（analyst 缺口 → searcher 重试） | 调研报告 |
| `diagnosis_flow` | 3 | collector → analyzer → adviser | 症状诊断 |

### 8. CLI 层 `cli/` — Typer + Rich

**命令体系：**

```
haven                   交互式 REPL [默认]
haven run -t "..."      单轮任务执行
haven workflow          工作流管理 {list,info,run,resume,history}
haven skill             Skill 管理 {list,info,search,add,remove,reload}
haven tool              工具管理 {list,info}
haven doctor            环境诊断
```

**架构原则：CLI → RuntimeService → Runtime**

```
┌──────────────────────────────────────────────┐
│  CLI Layer (commands/)                       │
│  chat.py / run.py / skill.py / workflow.py   │
│        │           │          │              │
│        │  RuntimeService    │ 直接查询       │
│        │  (单点桥梁)        │ SkillRegistry  │
│        ▼           │       │ WorkflowReg.   │
│  ┌──────────┐      │       └──────┬─────────┘
│  │ Runtime  │      │              │
│  │ Service  │      │              │
│  │          │      │              │
│  │ chat()   │      │              │
│  │ run_task │      │              │
│  │ switch   │      │              │
│  └────┬─────┘      │              │
└───────┼────────────┼──────────────┼──────────┘
        │            │              │
┌───────▼────────────▼──────────────▼──────────┐
│  Runtime Layer                               │
│  PlannerAgent / AgentRuntime / Registries    │
└──────────────────────────────────────────────┘
```

**CLI 命令禁止直接 import `haven.runtime`** — 所有运行时操作通过 `RuntimeService` 完成。

**终端渲染：** Rich 库 —— `render_table()` / `render_json()` / `render_kv()` / `render_markdown()` / `Spinner` / `StreamRenderer`

**关键模块：**

| 模块 | 职责 |
|------|------|
| `main.py` | Typer 应用 + 命令注册 + 全局异常处理 |
| `commands/chat.py` | REPL 循环 + slash 命令（`/help /model /models /skills /tools /memory /workflows /clear /exit`） |
| `commands/run.py` | `--task` / `--file` / `--stream` / `--json` / `--no-plan` / `--no-memory` |
| `services/runtime_service.py` | `RuntimeService` — `start()` / `chat()` / `run_task()` / `chat_stream()` / `stop()` |
| `ui/console.py` | 统一输出渲染器（text / JSON / table / status / code / markdown） |
| `ui/progress.py` | `spinner()` async ctx mgr / `StreamRenderer` 逐 token / `NodeWatcher` 工作流节点 |

**REPL Slash 命令：**

| 命令 | 功能 |
|------|------|
| `/help` | 命令帮助 |
| `/model [name]` | 查看/切换模型 |
| `/models` | 列出可用模型 |
| `/skills` | 列出已加载 Skill（人格 + 领域） |
| `/tools` | 列出已加载工具 |
| `/memory` | 记忆状态 |
| `/workflows` | 工作流列表 |
| `/clear` | 清空对话历史 |
| `/exit` | 退出 REPL |

## 核心数据流

```
User: "帮我写一个房价爬虫并做趋势分析"
  │
  ├─ PlannerAgent.plan(task) ── 1 次 LLM 调用 ──→ ExecutionPlan
  │     intent: development
  │     skills: [coder, data_analysis, summarization]
  │     workflow: research_flow
  │     steps: [S1 爬虫, S2 分析, S3 报告]
  │
  ├─ SkillRegistry.resolve_dependencies(["coder", "data_analysis", "summarization"])
  │     → ["coder", "data_analysis", "summarization"]
  │
  ├─ WorkflowGraph.run(state, runtime)
  │     searcher → analyst ─┬→ synthesizer → END
  │                ▲         │
  │                └─────────┘ (知识缺口 + retry ≤ 3)
  │
  │     每个 Node: runtime.run(prompt, active_skills=[skill], active_tools=[tools])
  │       │
  │       ├─ MemoryManager.retrieve(task) → MemoryContext
  │       ├─ ToolManager.get_tools_for_skills(["coder"])
  │       │     → [code_exec, file_ops, web_search]
  │       ├─ PromptBuilder.build(personality, domain, memory_ctx)
  │       └─ LLM.ainvoke() + tool-calling loop
  │
  └─ return result to user
```

## V1 → V2 对照表

| 维度 | V1 | V2 |
|------|----|----|
| **Agent** | 6 个类 (Orchestrator + 4 Specialist + General) | 2 个类 (PlannerAgent + AgentRuntime) |
| **领域知识** | 硬编码在 Agent 类 PROMPT 常量 | `.md` Skill 文件（零代码） |
| **意图分类** | 硬编码 4 类 + 正则回退 | LLM Structured Output + 动态标签 |
| **Skill 选择** | `str.lower()` 子串匹配 | LLM 语义选择（内嵌于 PlannerAgent） |
| **Workflow** | 3 个串行类（A→B） | DAG 引擎 + 条件路由 + 重试 + Checkpoint |
| **Memory** | deque + SQLite KV | 四层（Working/Episodic/Semantic/Vector） |
| **Tool 注册** | 分散注册 (register_tool + register_lc_tool) | Provider 统一架构（ToolManager 单一入口） |
| **新增工具源** | 仅 MCP | MCP + Provider 接口（可扩展） |
| **CLI** | 简单入口 + HavenApp REPL | Typer + Rich 多级命令树 + RuntimeService 桥梁 |
| **MCP 集成** | 独立 `mcp/` 模块 | 集成在 `tools/providers/` 中，统一 Provider 接口 |

## 扩展方式

| 需求 | 做法 | 改动量 |
|------|------|--------|
| 新领域能力 | `skills/` 下新建 `.md` 文件 | 零代码 |
| 新人格 | 新建 `.md`，设 `default: true` | 零代码 |
| 新外部工具 | `mcp.json` 添加 MCP 条目 | 一段 JSON |
| 新对话渠道 | 实现 `BaseChannel` 接口，注册到 daemon | 一个文件 |
| 新内置工具 | `tools/` 下新建 HavenTool 子类 | 一个文件 |
| 新模型 | `models.yaml` 加条目 + 环境变量设 Key | 两行配置 |
| 新工作流 | `workflows/graphs/` 下定义 DAG | 一个文件 |
| 新 Provider | 实现 `ToolProvider` 接口 | 一个类 |
| 新 Memory 层 | 实现 `BaseMemory` 接口 | 一个类 |

## 依赖关系

```
config/
  ↓
core/
  ↓
skills/  memory/  tools/  workflows/
  ↓        ↓        ↓         ↓
  └────────┴────────┴─────────┘
               ↓
          runtime/
               ↓
          cli/  services/
```

依赖规则：上层依赖下层，不可反向。`skills/`、`memory/`、`tools/`、`workflows/` 互不依赖，通过 `runtime/` 组合。
