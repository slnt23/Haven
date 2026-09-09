# haven

A Managed Deep Agent built with [`managed-deepagents`](https://github.com/langchain-ai/managed-deepagents-sdk).

## Project structure

```text
haven/                 # 健健 —— 0.0.1 高血压管理智能体
  agent.py             # define_deep_agent(...) — 工具 / 中间件 / interrupt_on 装配
  instructions.md      # 中文系统提示（流程脚本、红线、语气）
  safety/              # 紧急拦截词表、免责声明、输出过滤、降级文案（src 原值复刻）
  application/         # 血压校验权威表、异常确认、趋势统计、固定消息
  storage/             # 懒初始化 async SQLAlchemy（SQLite 开发 / PG 部署）
  middleware/          # 紧急扫描（LLM 前）→ 命令路由 → 输出安全过滤 + 降级兜底
  tools/               # 10 个确定性工具（同意→建档→血压→趋势→删除）
  config.py            # 集中环境配置 —— .env 可调项单一来源（HAVEN_MODEL / DATABASE_URL）
  identity.py          # 管理认证（LangSmith API key，单身份原型）
  pyproject.toml       # 依赖；.env 密钥（勿提交）；.gitignore 含 storage/、data/、.env
```

健健刻意**没有** `memory.py`（MDA 记忆为部署级共享，健康数据不进）与
`sandbox/`（纯对话，已 opt out）。

## Install

```bash
uv sync
```

## Evaluate

From the project root, initialize the Harbor eval workspace:

```bash
mda evals init -i
```

Follow the coding-agent prompt to author tasks directly under `evals/<task>/`. The CLI
creates `evals/harbor-job.json` once and preserves your edits; `.mda/evals/` is generated.

A task may include an authored `evals/<task>/identity.json` fixture. It requires a
non-empty `user.id`; `user.kind`, `user.email`, and top-level `groups`, `claims`, and
`source.provider` are optional. Keep the fixture with the task, not in generated
`.mda/evals/`.

Running evals requires `uv` and Docker. Export `LANGSMITH_API_KEY`,
`LANGSMITH_WORKSPACE_ID` when your credentials require it, and the model or tool
credential variables used by the agent. Then run the pinned two-plugin Harbor command
included at the end of the coding-agent prompt from the project root. It uses POSIX
syntax on macOS/Linux and PowerShell on native Windows. `MDAJobPlugin` compiles a fresh
eval artifact at every Harbor job start. From the same project root, inspect results:

```bash
uv run --python 3.12 --with 'harbor[langsmith]==0.21.0' harbor view .mda/evals/jobs
```

This POC keeps MDA's custom Harbor adapter. Migration to Harbor's built-in LangGraph
agent is deferred.

## Develop

Edit `agent.py` to configure your model, tools, and middleware, and edit
`instructions.md` to shape the system prompt.

Run the compiled app on the local LangGraph dev server:

```bash
mda dev
```

For Python projects, `mda dev` requires `uv` on `PATH`, but it resolves the local LangGraph dev server automatically; you do not need to install a global `langgraph` command.

## Identity

`identity.py` enables managed authentication: threads are owned
per caller. Set `auth` to one or more `auth.*` entries if browsers call
the deployment directly. Durable memory is declared separately.

## Memory

This project declares no memory, so nothing is kept between runs. Add
`memory.py` exporting `defineMemory({ scope: "agent" })` (or
`define_memory(scope="agent")`) to mount one deployment-shared tree at
`/memories/agent/`.

## Sandbox

`sandbox/__init__.py` declares a managed LangSmith sandbox. MDA only enables the
sandbox when this declaration is present — remove the `sandbox/` directory to
opt out (for example for chat-only agents). Add `sandbox/setup.sh` if you want
to provision a recipe snapshot; `mda deploy` / `mda dev` bake it once and new
threads clone that image without re-running the script.

## Optional Runtime Pieces

Add `connectors/mcp.py` to attach MCP servers. The file must export a named
`connector` declaration.

## Deploy

Compile and deploy the project to LangSmith:

```bash
mda deploy
```

This copies your files verbatim, generates a managed entry module, and writes a
deployable build (including `langgraph.json`) to `.mda/build`. The CLI uploads
that build to LangSmith to run your agent on the managed runtime.

Common options:

```bash
mda deploy --name haven-dev --deployment-type dev
mda deploy --workspace-id "$LANGSMITH_WORKSPACE_ID"
mda deploy --no-wait
```

Deploy prints both the Agent Server URL to call and the LangSmith dashboard URL
to inspect.

## Logs

Read the deployed agent's server logs:

```bash
mda logs
mda logs --lines 200 --level error
```

In a terminal this streams new output until you press Ctrl-C. When the output is
piped or redirected it prints the most recent lines (1000 by default) and exits.

## Delete

Remove the deployment and the LangSmith resources it created:

```bash
mda delete
```

This deletes the deployment, the tracing project created alongside it, the
Context Hub repo holding this agent's context and memory, and the managed
sandboxes this agent created. It asks first; pass `--yes` to skip the prompt.
Agent memory and thread history are not recoverable afterwards.

## Environment

`mda deploy` loads `.env`, uses `LANGSMITH_API_KEY` for LangSmith, and forwards
model provider keys such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` as deployment
secrets. Provider keys must be in `.env` or configured as LangSmith workspace
secrets — a value exported in your shell is not read. Set
`LANGSMITH_WORKSPACE_ID` or pass `--workspace-id` if your LangSmith API key
requires a workspace selection.

### 健健部署注意

- 模型走 DeepSeek：`.env` 需 `DEEPSEEK_API_KEY`；模型名由 `config.py`
  读取 `.env` 的 `HAVEN_MODEL`（默认 `deepseek:deepseek-v4-flash`，
  切换模型只改 `.env`，不动代码）。
- 模型/密钥链路（dev 与部署一致）：代码从不读取 `DEEPSEEK_API_KEY`，由
  langchain-deepseek 库在每次模型调用时从**进程环境**读取 —— `mda dev`
  来自本机 `.env`；`mda deploy` 时 mda 将 `.env` 非保留变量转发为部署环境变量
  （构建产物 `langgraph.json` 的 `"env": ".env"`），部署端自动连通 DeepSeek，
  无需额外联调。`DEEPSEEK_API_KEY` 与 `HAVEN_MODEL` 都是**服务器侧**凭证/配置
  （模型调用账单走部署者账户），与终端用户无关 —— 用户经身份认证访问部署的
  agent，不接触也不需要提供这些值。
- **数据库**：`config.py` 读取 `.env` 的 `DATABASE_URL`（`storage/database.py`
  引用同一配置）；开发默认
  `sqlite+aiosqlite:///./data/haven.db`（建表由首笔工具调用懒初始化）。
  部署前**必须**在 `.env` 设置托管 PostgreSQL，如
  `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/haven` ——
  SQLite 仅限本地 dev（`mda dev`），不要带去部署。
- 异常血压二次确认与数据删除依赖 `interrupt_on` 人工批准门，仅在
  持久线程 + 管理运行时下生效（Studio / resume）。
- 工具内建 SQL 去标识审计（`audit_logs.subject_key`），删除数据时
  仅保留审计事件本身。
