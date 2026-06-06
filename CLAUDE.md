# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

## 项目

**Haven**（Python 包名：`haven`）— 基于 Python 3.14+、LangChain 与 pydantic-settings 构建的多智能体交互框架。人格与领域能力通过 Markdown 技能文件注入，零代码扩展；外部工具通过 MCP 协议集成。

## 常用命令

```bash
uv sync                   # 安装依赖
uv sync --group dev       # 安装含开发依赖（pytest）
uv run haven              # 交互式 REPL
uv run haven --task "..." # 单轮问答
uv run haven serve        # 启动守护进程（多通道：TCP + 邮件 + 飞书）
uv run haven stop         # 停止守护进程
uv run haven status       # 查看守护进程状态
uv run haven restart      # 重启守护进程
uv run pytest             # 运行全部测试
uv run pytest tests/path  # 运行单个测试文件
```

## 架构

**入口**：`factory.create_agent()` 创建单个 `PlannerAgent`（持有 `AgentRuntime`），无子 agent。系统通过 LLM 结构化输出动态选择 Skill 和 Workflow，替代 V1 硬编码的 4 分类路由。

**V2 执行模型（3 条路径）：**

```
用户输入 → PlannerAgent.plan() → ExecutionPlan
  ├─ 路径 1: 简单对话 → AgentRuntime.run() 直通（无工具/单轮）
  ├─ 路径 2: 多步任务 → PlannerAgent._execute_steps() 顺序编排（拓扑排序）
  └─ 路径 3: 匹配工作流 → WorkflowGraph.run() DAG 引擎执行
```

- **PlannerAgent** = 任务规划层。一次 LLM 调用（`with_structured_output(ExecutionPlan)`）完成意图分类 + Skill 选择 + 步骤拆解 + Workflow 匹配。输出 `ExecutionPlan` Pydantic 模型（`goal`、`intent`、`complexity`、`skills`、`workflow`、`steps`）。
- **AgentRuntime** = 纯执行引擎。组合 LLM + Tool + State + Prompt。使用 LangGraph `SqliteSaver` checkpointer 自动持久化消息，`pre_model_hook` + `trim_messages()` 管理上下文窗口。
- **WorkflowGraph** = DAG 工作流引擎（LangGraph 风格）。`add_node()` / `add_edge()` / `add_conditional_edge()` 构建图，`graph.run(state, runtime)` 执行。内置 3 个工作流：`dev_flow`、`research_flow`、`diagnosis_flow`，定义在 `runtime/graphs/` 中。

**核心分层（自底向上）：**

| 层 | 目录 | 职责 |
|-------|-----------|------|
| Config | `src/haven/config/` | YAML + env vars，OmegaConf deep-merge |
| Core | `src/haven/core/` | `RuntimeState`、`Registry`、LLM 工厂 |
| Memory | `src/haven/memory/` | `FactStore`（SQLite 语义事实）+ `VectorMemory`（ChromaDB，可选）。消息持久化由 LangGraph `SqliteSaver` checkpointer 自动管理 |
| Skills | `src/haven/skills/` | `.md` 文件加载，YAML frontmatter 解析，`SkillRegistry` 依赖解析 |
| Tools | `src/haven/tools/` | `ToolManager` + Provider 架构（Builtin + MCP），MCP 配置解析 |
| Runtime | `src/haven/runtime/` | `PlannerAgent`（规划）+ `AgentRuntime`（执行）+ `WorkflowRegistry`（工作流引擎）+ `factory.create_agent()`（装配） |
| CLI | `src/haven/cli/` | `main.py` 入口 + REPL 循环 + `RuntimeService` 桥梁 |
| Services | `src/haven/services/` | 守护进程 + 渠道（TCP socket、邮件 IMAP/SMTP、飞书 WebSocket） |

## 关键约定

- **包名与项目名**：pip 包名为 `haven`（命令：`haven`），Python 包名也为 `haven`（导入：`from haven...`）。源码位于 `src/haven/`。
- **配置优先级**：内置 YAML < 用户 YAML（CWD）< 环境变量。用户 YAML deep-merge 覆盖内置默认值。`_find_user_config()` 在 CWD 中查找用户配置文件。
- **配置目录**：`src/haven/config/` 包含 `app.yaml`（框架默认参数）、`models.yaml`（内置模型定义）、`haven.md`（系统人格 prompt）。用户可在 CWD 下放置 `haven.yaml` 或 `models.yaml` 覆盖。
- **模型 Key 解析**：`models.yaml` 中每模型声明 `api_key_env` 字段（如 `DEEPSEEK_API_KEY`），`loader.py:get_model_config()` 从 `os.environ` 动态读取。`settings.py` 中不硬编码任何 Key。
- **Skill 文件**：Skill 通过 `skills/` 目录（CWD 相对，由 `app.yaml` 的 `skill_directory` 配置）中的 `.md` 文件加载，包含 YAML frontmatter（`name`、`description`、`tags`、`tools`、`dependencies`、`default`）。`default: true` = 系统人格 skill（`haven.md`），始终注入 system prompt。V2 中 PlannerAgent 通过 LLM 语义匹配选择领域 Skill（而非 V1 的 `trigger_keywords` 关键词匹配）。
- **工具绑定**：通过 `AgentRuntime.register_tool()` 注册，`activate_tools()` 选择子集，`bind_tools_to_llm()` 执行 `llm.bind_tools()`。`switch_model()` 切换模型后工具自动重绑。
- **ToolManager + Provider 架构**：`ToolManager` 编排所有 `ToolProvider` 生命周期。`BuiltinProvider` 扫描内置工具（6 个模块），`MCPProvider` 管理单个 MCP 服务器连接。支持 stdio / HTTP SSE / WebSocket 传输。MCP 工具以 `{server_name}__{tool_name}` 命名避免冲突。Provider 状态机：UNINITIALIZED → CONNECTING → CONNECTED / DEGRADED / ERROR → DISCONNECTED。
- **记忆系统**：基于 LangGraph 原生机制。`SqliteSaver` checkpointer 按 `thread_id` 自动持久化所有消息，`pre_model_hook` + `trim_messages()` 在 LLM 调用前裁剪消息确保不超 context window。可选组件：`FactStore`（SQLite 语义事实存储与检索）、`VectorMemory`（ChromaDB 向量语义检索，默认关闭）。
- **MCP 工具**：从 CWD 下的 `mcp.json` 加载，标准 `mcpServers` 格式。`${VAR}` 语法自动解析环境变量。`"enabled": false` 的服务器跳过不加载。单服务器故障不影响其他。
- **用户扩展**：所有用户可扩展内容统一放在 CWD 下（`skills/`、`mcp.json`、`haven.yaml`、`models.yaml`），拖入即用。
- **Registry 模式**：`Registry` 基类提供 `register()` / `get()` / `list_all()` 类方法。`SkillRegistry`、`WorkflowRegistry` 均继承自此基类。新建可注册组件时继承 `Registry` 并设置 `_label`。
- **运行时数据**：守护进程 PID 文件写入 `.data/haven.pid`，由 `core/pidfile.py` 管理。

## 已知问题

- **测试全部损坏**：`tests/` 下 3 个测试文件导入的 V1 模块（`haven.agents.GeneralAgent`、`haven.tools.WebSearchTool.search()`、`haven.workflows.ResearchFlow`（已废弃））在 V2 中不存在，需按新 API 重写。
- **无 CI/CD**：无 `.github/` 目录，无 linting（ruff/flake8/mypy）或 pre-commit 配置。
- **`pyproject.toml` 版本不一致**：文件声明 `0.1.0`，但 banner 和代码中硬编码 `"2.0.0"`。

---

## 行为准则

减少 LLM 编码常见错误的指南。与项目特定指令合并使用。

**权衡：** 这些准则偏向谨慎而非速度。对简单任务，自行判断。

### 1. 先想后写

**不要假设。不要隐藏困惑。明确列出权衡。**

实现之前：
- 明确陈述你的假设。如果不确定，询问。
- 如果有多种解释，全部列出——不要默默选择其中一种。
- 如果有更简单的方案，提出来。必要时 push back。
- 如果某事不清晰，停下来。明确指出困惑所在。提问。

### 2. 简单优先

**用最少的代码解决问题。不要写猜测性代码。**

- 不添加超出需求的功能。
- 不为单次使用创建抽象。
- 不添加未被要求的「灵活性」或「可配置性」。
- 不为不可能发生的场景添加错误处理。
- 如果写了 200 行但 50 行就能搞定，重写。

自问：「资深工程师会觉得这过度设计吗？」如果会，简化。

### 3. 精准修改

**只动必须动的。只清理你自己造成的混乱。**

编辑已有代码时：
- 不要「顺便优化」邻近的代码、注释或格式。
- 不要重构没有坏的东西。
- 匹配已有代码风格，即使你自己的做法不同。
- 如果发现无关的废弃代码，提出来——但不要删。

当你的修改产生孤儿代码时：
- 删除因你的修改而不再使用的 import / 变量 / 函数。
- 不要删除之前就存在的废弃代码，除非被要求。

检验标准：每个改动的行都应该能直接追溯到用户的请求。

### 4. 目标驱动执行

**定义成功标准。循环直到验证通过。**

将任务转化为可验证的目标：
- 「加校验」→「先为非法输入写测试，再让它们通过」
- 「修 bug」→「先写一个能复现的测试，再让它通过」
- 「重构 X」→「确保测试前后全部通过」

对多步骤任务，列出简要计划：
```
1. [步骤] → 验证: [检查项]
2. [步骤] → 验证: [检查项]
3. [步骤] → 验证: [检查项]
```

有力的成功标准让你可以独立循环推进。模糊的标准（「让它能跑」）需要不断澄清。

---

**这些准则有效的标志：** diff 中不必要的改动变少、因过度设计导致的重写变少、澄清性问题在实现前提出而非犯错之后。
