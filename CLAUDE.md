# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

## 项目

**Haven**（Python 包名：`forest`）— 基于 Python 3.14+、LangChain 与 pydantic-settings 构建的多智能体交互框架。人格与领域能力通过 Markdown 技能文件注入，零代码扩展；外部工具通过 MCP 协议集成。

## 常用命令

```bash
uv sync                   # 安装依赖
uv sync --group dev       # 安装含开发依赖（pytest）
uv run haven              # 交互式 REPL
uv run haven --task "..." # 单轮问答
uv run haven serve        # 启动守护进程（多通道：TCP + 邮件 + 飞书）
uv run haven stop         # 停止守护进程
uv run haven status       # 查看守护进程状态
uv run pytest             # 运行全部测试
```

## 架构

**两种 Agent 类型，无数种能力：**

```
Agent（管怎么跑）         Skill（管怎么想）            MCP（管外部能力）
─────────────────      ─────────────────────        ────────────────────
GeneralAgent    ←──    haven.md      （默认人格）    filesystem   ← stdio
OrchestratorAgent ←──  code_review.md（按需激活）    web_fetch    ← HTTP SSE
                        *.md          （零代码）     ...          ← WebSocket
```

- **人格** = 默认 Skill（`haven.md`）注入 system prompt
- **领域能力** = 按需 Skill，用户输入关键词触发匹配后临时注入
- **外部能力** = `mcp.json` 中配置的标准 MCP 服务器

**核心分层（自底向上）：**

| 层 | 目录 | 职责 |
|-------|-----------|------|
| Config | `src/forest/config/` | YAML + env vars，OmegaConf deep-merge |
| Core | `src/forest/core/` | `BaseAgent`、`AgentMemory`、`RAGEngine`、`SQLiteMemoryStore` |
| Skills | `src/forest/skills/` | `.md` 文件加载，YAML frontmatter 解析 |
| MCP | `src/forest/mcp/` | MCP 服务器生命周期管理 + 工具发现 |
| Agents | `src/forest/agents/` | `GeneralAgent`（单agent）+ `OrchestratorAgent`（编排） |
| Tools | `src/forest/tools/` | 内置工具（搜索、文件、代码执行、邮件、RAG） |
| Workflows | `src/forest/workflows/` | 多 agent 流水线（调研、开发、诊断） |
| CLI | `src/forest/cli/` | `main.py` 入口 + `HavenApp` REPL 循环 |
| Services | `src/forest/services/` | 守护进程 + 渠道（TCP socket、邮件、飞书） |

## 关键约定

- **包名与项目名**：pip 包名为 `haven`（命令：`haven`），但 Python 包名为 `forest`（导入：`from forest...`）。源码位于 `src/forest/`。
- **配置优先级**：内置 YAML < 用户 YAML（CWD 或 `HAVEN_CONFIG_DIR`）< 环境变量（`.env` / shell）。用户 YAML deep-merge 覆盖内置默认值。
- **模型 Key 解析**：`models.yaml` 中每模型声明 `api_key_env` 字段（如 `DEEPSEEK_API_KEY`），loader 从 `os.environ` 动态读取。`settings.py` 中不硬编码任何 Key。
- **Skill 文件**：`skills/` 下的 `.md` 文件，包含 YAML frontmatter（`name`、`trigger_keywords`、`default`、`prompt_extension`）。`default: true` = 始终激活的人格 skill，其余按关键词匹配按需激活。
- **Agent 工具绑定**：先 `register_lc_tool()` 注册，再调用 `bind_tools_to_llm()` 执行 `llm.bind_tools()`。`switch_model()` 切换模型后工具自动重绑。
- **记忆系统**：双层 —— 短期记忆（`deque[BaseMessage]`，max 100）+ 长期记忆（SQLite，`SQLiteMemoryStore`）。每轮对话后 LLM 自动提取事实信息。
- **MCP 工具**：从 `mcp.json`（标准 `mcpServers` 格式）加载。`${VAR}` 语法自动解析环境变量。`"enabled": false` 的服务器跳过不加载。单服务器故障不影响其他。

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
