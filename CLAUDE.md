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

## 架构 (V2)

**入口**：`create_runtime()` 创建 `Runtime` → 通过 `Executor` 执行任务。
Runtime 不直接接触 Agent —— 所有执行必须经过 Executor。

**执行模型：**

```
Interface → Runtime.execute(task)
  → Executor.execute(request)
    → Planner.plan(task)              [LangGraph StateGraph: classify → select_skills → build_plan → validate]
    → ExecutionPipeline.run(plan)
      ├─ 路径 1: 工作流 → WorkflowEngine (LangGraph StateGraph)
      ├─ 路径 2: 多步编排 → 拓扑排序逐步执行
      └─ 路径 3: 直接对话 → Agent.run()
    → ExecutionResponse
```

**核心分层：**

| 层 | 目录 | 职责 |
|---|------|------|
| Kernel | `kernel/` | AgentEvent、TraceContext、异常体系、LifecycleManager |
| Infrastructure | `infrastructure/` | StreamChunk、日志、MCP 连接 |
| Config | `config/` | AppConfig、ConfigLoader（YAML → env → runtime override） |
| Model | `model/` | LLMClient + ModelFactory（OpenAI/DeepSeek 兼容） |
| Session | `session/` | Session + SessionManager |
| Execution | `execution/` | Planner（LangGraph Flow）+ Pipeline + Executor |
| Agent | `agent/` | Agent（LangChain create_agent 封装） |
| Capability | `capability/` | 统一 Skill + Tool 注册表（CapabilityRegistry） |
| Memory | `memory/` | MemoryManager（Fact + Vector + ConflictResolver） |
| Workflow | `workflow/` | WorkflowEngine + WorkflowRegistry + definitions |
| Interface | `interface/` | CLI REPL / HTTP API / WebSocket |
| Runtime | `runtime/` | Runtime 容器 + ContextBuilder + factory

## 关键约定

- **包名与项目名**：pip 包名为 `haven`（命令：`haven`），Python 包名也为 `haven`（导入：`from haven...`）。源码位于 `src/haven/`。
- **配置优先级**：内置 YAML < 用户 YAML（CWD）< 环境变量。用户 YAML deep-merge 覆盖内置默认值。`_find_user_config()` 在 CWD 中查找用户配置文件。
- **Config**：`config/` 目录包含默认 YAML 配置。优先级：内置 YAML < 用户 CWD YAML < 环境变量 < runtime override。模块不得直接读取 YAML，只能依赖 `AppConfig` 对象。
- **Model**：`ModelFactory` 按 `models.yaml` 创建 `LLMClient`。Agent 不直接接触 `BaseChatModel`。支持 OpenAI 兼容 + DeepSeek。
- **Capability**：`CapabilityRegistry` 统一管理 Tool 和 Skill，不分别维护独立注册表。Skill 通过 `skills/` 目录中的 `.md` 文件加载（YAML frontmatter）。
- **Memory**：`MemoryManager` 提供统一的 `remember()` / `recall()` / `forget()` 接口。短期记忆由 LangGraph checkpointer 自动管理。VectorMemory 可选（ChromaDB）。
- **Workflow**：`WorkflowRegistry.register()` 装饰器注册工作流工厂函数。`WorkflowEngine` 封装 LangGraph StateGraph 执行。
- **Session**：`SessionManager` 管理会话生命周期。`Session.id` 即 LangGraph thread_id。消息持久化由 checkpointer 自动处理。
- **Agent**：Agent 不持有 session/memory/CLI 状态。`AgentFactory` 从 `AppConfig` 批量创建 Agent。

## 已知问题

- **无 CI/CD**：无 `.github/` 目录，无 linting（ruff/flake8/mypy）或 pre-commit 配置。
- **pyproject.toml 版本**：声明 `1.0.1`。

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
