# AGENTS.md

Haven（健健）— 个人高血压管理 Managed Deep Agent。基于
[managed-deepagents](https://github.com/langchain-ai/managed-deepagents-sdk) 构建。

---

## 开发路线

当前阶段使用 **MDA（Managed Deep Agents）** 快速开发与部署，快速验证产品形态。
后续将逐步用 **LangChain + LangGraph** 替代 MDA，自己掌控 agent 运行时、工具注入、
中间件链与部署流程，减少对 MDA 托管层的依赖。

迁移原则：

- 业务逻辑（`tools/`、`application/`、`safety/`、`storage/`）保持纯函数/SQLAlchemy，
  不依赖 MDA 运行时，确保可直接迁移。
- 中间件链需改造为 LangGraph 原生中间件机制，保持执行顺序不变。
- `mda dev` / `mda build` / `mda deploy` 逐步替换为自建开发/构建/部署流程。

---

## 核心约束

- **单租户**：一个部署 = 一个人（[ADR-006](.docs/adr/ADR-006-单租户身份模型.md)）。
  本人 id 由 `HAVEN_OWNER_ID` 配置（默认 `owner`），**不从平台注入身份推导**。
  要服务另一个人 = 再部署一个实例（不同 `HAVEN_OWNER_ID` + 不同库）。
- **不做医疗诊断**：只记录与转达。血压分级、趋势、紧急判定全部由确定性函数计算，
  LLM 绝不自行判断。
- **无 `memory.py`**：MDA 记忆是部署级共享的，健康数据绝不写入。
  记忆注入 = `middleware/memory_context.py`，确定性只读组装用户数据摘要，
  追加到 system prompt，不落库、不进线程历史。
- **无 `sandbox/`**：纯对话 + 确定性工具，不需要文件系统或 shell。

---

## 命令

```bash
uv sync                         # 安装依赖
mda dev                         # 本地开发（LangGraph dev server）
mda build                       # 构建部署产物
mda deploy                      # 部署到 LangSmith
mda logs                        # 查看部署日志
mda delete                      # 删除部署
mda evals init -i               # 初始化评测工作区
```

> 无传统测试框架（pytest/mypy/ruff 均未接入）。质量验证走 `mda evals`。

---

## 项目结构

```text
haven/
  agent.py             # define_deep_agent(…) — 工具/中间件/interrupt_on 装配入口
  instructions.md      # 中文系统提示（健健的行为规范完整脚本）
  identity.py          # 准入认证（LangSmith API key）
  pyproject.toml       # 依赖声明（版本锁定见注释）
  config/              # settings.py (.env 单源) + mcp.py (纯标准库) + mcp.json + model.py
  storage/             # 异步 SQLAlchemy（database.py 懒初始化 + models.py ORM + audit.py）
  middleware/          # 中间件链：emergency → command → output_safety → memory_context → mcp_policy
  tools/               # 11 个确定性工具（consent / onboarding / vitals / trends / account）
  application/         # 业务逻辑（校验/确认/趋势/记忆组装/消息/建档）
  safety/              # 紧急词表/免责声明/输出过滤/降级文案
  connectors/          # 外部 MCP 连接器（仅远程 HTTP/SSE）
  .docs/               # ADR + 需求文档
```

---

## 中间件执行顺序（不可变更）

1. `emergency_input` — 急救词优先于一切（LLM 前拦截）
2. `command` — `/hello` `/help` `/consent` `/cancel` 确定性路由
3. `output_safety` — 输出安全过滤 + 降级兜底
4. `memory_context` — 只追加 system prompt 内容块，不重写
5. `mcp_policy` — 外部 MCP 白名单/审计/降级（只挂工具调用钩子）

---

## 技术栈

| 领域   | 选型                                                                    |
| ------ | ----------------------------------------------------------------------- |
| 运行时 | `managed-deepagents==0.6.1`                                             |
| 语言   | Python ≥3.11（本地 dev 3.14、`mda build` 用 3.12）                      |
| 包管理 | `uv`（`uv sync` / `uv.lock`）                                           |
| LLM    | `langchain==1.4.0` + `deepagents==0.7.13`（经 MDA 托管）                |
| 模型   | `langchain-deepseek`，`.env` 的 `HAVEN_MODEL` 切换                      |
| 数据库 | SQLAlchemy 异步 + SQLite（dev）→ PostgreSQL（prod），首笔工具调用懒建表 |
| 配置   | `pydantic-settings`，`.env` 可调项唯一入口                              |

---

## 编码规范

- 注释、文档字符串、面向用户文案：**中文**。变量/函数/类名：英文。
- 工具函数用 `Annotated` + `Field(description=…)` 声明参数。
- 工具返回固定文案，模型只负责转达。数据库异常捕获 `DatabaseUnavailable`，返回降级文案。
- 使用 `from __future__ import annotations` + Pydantic v2 + SQLAlchemy 2.0 `Mapped`。
- **绝不**在日志中输出健康数据明文；**绝不**硬编码密钥（走 `.env`）。
- 紧急词表、血压阈值、免责声明是**产品语义**，不允许被环境变量改写。
- 设计功能或修改逻辑时，先思考整体方案、影响范围与边界条件，然后再动手实现。
- 每个关键路径都要有**保底方案**：工具调用失败、模型输出异常、外部依赖不可用时，
  必须有降级兜底逻辑（降级文案 / 默认值 / 安全退出），不允许静默失败或裸抛异常。

---

## 依赖版本约束

`pyproject.toml` 中的版本组合是端到端验证通过的。关键坑位：

- **`langchain==1.4.0` / `langchain-core==1.6.2` / `deepagents==0.7.13`**：
  升到 1.4.1/1.6.3/0.7.15 后，注入工具的 `runtime` 参数会被 pydantic 校验拦下。
- `requires-python` 保持 `>=3.11`：`mda build` 用 Python 3.12，提到 3.14 会让构建环境装不上。
- `asyncpg>=0.31.0`：0.30.0 无 cp314 轮子，会退化成源码编译。
- `mcp_policy` 中间件在调用 handler 前将 `_ManagedRuntime` 代理还原为底层 `ToolRuntime`（代理只用于审计）。

---

## 部署要点

- `.env` 需 `DEEPSEEK_API_KEY`。代码不直接读取，由 langchain-deepseek 从进程环境读取。
  `mda deploy` 将 `.env` 非保留变量转发为部署环境变量。
- **`HAVEN_OWNER_ID`**：本机 `mda dev` 与云端部署必须是同一个值，否则看到两份数据。
- **数据库**：部署前必须在 `.env` 设置 PostgreSQL URL（`postgresql+asyncpg://...`）。
  SQLite 仅限本地 dev，不要带去部署。
- `interrupt_on`（异常血压确认、数据删除）仅在持久线程 + 管理运行时下生效。
- 工具内建 SQL 去标识审计（`audit_logs.subject_key`），删除数据时仅保留审计事件本身。

---

## 外部 MCP

- 声明在 `connectors/mcp.py`，配置在 `config/mcp.json`（`${VAR}` 插值，从进程环境 → `.env` 解析）。
- 仅支持远程 HTTP/SSE（MDA 拒绝 stdio）。空/缺失 = 完全关闭。
- 双保险：① `include_tools` 白名单（留空则服务器不启用）；② `mcp_policy` 默认拒绝 + 审计 + 降级。
- 工具名格式 `{服务器名}__{远端工具名}`。`instructions.md` §四 有使用规则。
- **`connectors/*` import 链必须纯标准库**：`config/__init__.py` 保持为空，
  `config/mcp.py` 纯标准库，避免构建/运行环境导入失败。

---

## 相关文档

| 文档                                       | 用途                             |
| ------------------------------------------ | -------------------------------- |
| [instructions.md](instructions.md)         | 健健系统提示（行为规范完整脚本） |
| [agent.py](agent.py)                       | Agent 装配入口                   |
| [.docs/adr/](.docs/adr/)                   | 架构决策记录（ADR-001 ~ 008）    |
| [.docs/requirements/](.docs/requirements/) | 需求文档（SPRINT-0.0.1 ~ 0.0.3） |
