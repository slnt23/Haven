# Forest — 多智能体交互框架

代号：**健健**（出自《灵笼》），英文名 **Haven**

基于 Python 3.14+、LangChain 与 pydantic-settings 构建的多 Agent 协作框架。核心设计理念是 **数据驱动**——通过 Markdown 技能文件注入人格与领域知识，无需编写 Python 代码即可扩展 Agent 能力。

## 快速开始

```bash
# 1. 创建环境变量文件并填入 API Key
cp .env.example .env   # 或直接创建 .env

# 2. 安装依赖
uv sync

# 3. 运行（三种模式）
uv run haven                       # 交互式 REPL
uv run haven --task "你的问题"      # 单轮问答
uv run haven serve                 # 常驻守护进程（多渠道并行）
```

## 配置说明

项目使用 **分层配置**：`app.yaml`（默认值） → `.env`（覆盖） → `models.yaml`（模型定义） → `mcp.json`（MCP 服务器）。

### 1. `.env` — API Key 与环境变量（必须配置）

位于项目根目录，配置格式：

```bash
# ─── 模型 API Key ───
# 变量名必须与 models.yaml 中的 api_key_env 一致
DEEPSEEK_API_KEY=sk-your-key-here
OPENAI_API_KEY=sk-your-key-here
DASHSCOPE_API_KEY=sk-your-key-here

# ─── 网页搜索 ───
WEB_SEARCH_API_KEY=your-search-api-key
# WEB_SEARCH_ENGINE=bing       # 默认值在 app.yaml 中

# ─── 邮箱（可选） ───
EMAIL_SMTP_USERNAME=your-email@qq.com
EMAIL_SMTP_PASSWORD=your-smtp-password
EMAIL_IMAP_USERNAME=your-email@qq.com
EMAIL_IMAP_PASSWORD=your-imap-password

# ─── Agent 行为（可选，覆盖 app.yaml） ───
# AGENT_MAX_ITERATIONS=20
# AGENT_MAX_EXECUTION_TIME=300
```

### 2. `src/forest/config/models.yaml` — 模型定义

定义所有可用模型，每个模型指定 provider、API endpoint、参数等：

```yaml
default_model: deepseek-v4-pro   # 启动时默认使用的模型

models:
  deepseek-v4-pro:
    provider: deepseek
    api_key_env: DEEPSEEK_API_KEY    # 从环境变量读取 Key
    base_url: https://api.deepseek.com
    temperature: 0.5
    max_tokens: 4096

  gpt-4o:
    provider: openai
    api_key_env: OPENAI_API_KEY
    base_url: https://api.openai.com/v1
    temperature: 0.5
    max_tokens: 8192

  qwen-max:                          # 通义千问兼容 OpenAI 接口
    provider: aliyun
    api_key_env: DASHSCOPE_API_KEY
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    temperature: 0.7
    max_tokens: 2000
```

添加新模型只需在此文件中新增一个条目 + 在 `.env` 中设置对应的 Key。支持 `deepseek`、`openai` 及任何兼容 OpenAI 接口的 provider（如通义千问、Moonshot 等）。

### 3. `src/forest/config/app.yaml` — 框架默认参数

框架级配置，所有值均可被同名的环境变量覆盖：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `agent.max_iterations` | Agent 最大工具调用轮次 | `20` |
| `agent.max_execution_time` | Agent 最大执行时间（秒） | `300` |
| `web_search.engine` | 搜索引擎 | `bing` |
| `email.smtp_host` / `smtp_port` | SMTP 发件服务器 | `smtp.qq.com:587` |
| `email.imap_host` / `imap_port` | IMAP 收件服务器 | `imap.qq.com:993` |
| `email.poll_interval` | 邮件轮询间隔（秒） | `60` |
| `email.digest_time` | 每日邮件摘要时间 | `08:00` |
| `rag.embedding_model` | RAG 嵌入模型 | `text-embedding-3-small` |
| `rag.chunk_size` / `chunk_overlap` | 文档分块参数 | `1000` / `200` |
| `rag.top_k` | 检索返回条数 | `5` |
| `mcp.enabled` | 是否启用 MCP | `true` |
| `daemon.channels.socket` | 守护进程 TCP 渠道 | `enabled: true, 127.0.0.1:9020` |
| `daemon.channels.email` | 守护进程邮件渠道 | `enabled: false` |
| `memory.enabled` | 长期记忆开关 | `true` |
| `memory.extract_after_turn` | 每轮对话后自动提取事实 | `true` |
| `memory.min_confidence` | 注入上下文的最低置信度 | `0.5` |
| `skill.directory` | Skill 文件目录（相对于项目根目录） | `skills` |

### 4. `mcp.json` — MCP 服务器配置（项目根目录）

采用标准 MCP `mcpServers` 格式，可直接从 MCP 市场复制粘贴。支持三种传输方式：

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "env": { "HOME": "${USERPROFILE}" },
      "enabled": true
    },
    "remote_api": {
      "type": "sse",
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer ${MCP_API_KEY}" },
      "enabled": false
    },
    "ws_server": {
      "type": "websocket",
      "url": "ws://localhost:9000/mcp",
      "enabled": false
    }
  }
}
```

- **`type: "stdio"`** — 本地子进程通信，需 `command` + `args`
- **`type: "sse"`** — 远程 HTTP SSE 连接，需 `url`
- **`type: "websocket"`** — 远程 WebSocket 连接，需 `url`
- `${VAR}` 语法在 `env` 和 `headers` 中自动解析为环境变量
- `"enabled": false` 的服务器不会被加载

## CLI 交互命令

进入 REPL 后，输入 `/help` 查看完整命令列表：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/models` | 列出所有可用模型 |
| `/model` | 显示当前模型 |
| `/model <名称>` | 切换模型（支持模糊匹配，如 `/model gpt-4o`） |
| `/skills` | 列出已加载的 skill（分默认/按需） |
| `/tools` | 列出可用工具（含 MCP 工具） |
| `/mcp` | 显示 MCP 服务器连接状态 |
| `/clear` | 清空对话历史 |
| `/exit` `/quit` `/q` | 退出 |

## 常驻守护进程 `haven serve`

启动后 Agent 常驻内存，多个渠道（Channel）并行接入同一个 Agent：

```bash
haven serve
# 启动后可通过以下方式对话：
#   1. TCP 连接：telnet 127.0.0.1 9020
#   2. 邮件对话：配置 SMTP/IMAP 后自动处理邮件
#   (未来: 微信、Slack 等)
```

守护进程架构：

```
haven serve
  └── HavenDaemon（常驻进程）
       ├── Agent（共享一份 GeneralAgent 实例）
       ├── SocketChannel     ← TCP telnet 式 REPL（127.0.0.1:9020）
       ├── EmailChannel      ← IMAP 邮件轮询 + Agent 处理 + SMTP 回复
       └── (future) WeChatChannel...
```

- 每个渠道实现统一接口 `BaseChannel`：`start(agent)` / `stop()`
- 所有渠道共享一个 Agent 实例（含 LLM、tools、skills、长期记忆）
- Socket 连接会话隔离（每条连接独立对话历史）
- 单个渠道故障不影响其他渠道

### 渠道启用/关闭

在 `app.yaml` 中控制：

```yaml
daemon:
  channels:
    socket:
      enabled: true           # TCP 本地 REPL
      host: "127.0.0.1"
      port: 9020
    email:
      enabled: false          # 邮件渠道，需额外配置 SMTP/IMAP
```

## 长期记忆系统

双层记忆架构，自动从对话中提取用户信息并持久化：

```
短期记忆（deque, 100条）←── 当前对话上下文
长期记忆（SQLite）      ←── 自动提取人物档案，跨会话持久化
```

### 数据模型

| 表 | 说明 |
|----|------|
| `entities` | 人物对象（name, type, ...） |
| `entity_facts` | 人物属性键值对（key, value, confidence），同 key 自动覆盖 |
| `conversations` | 对话日志（session_id, role, content） |

### 自动提取流程

```
用户对话 → Agent 回复
             │
             └──→ 后台 LLM 提取重要事实
                   │  提取规则：姓名、职业、健康、偏好、技能等
                   │  置信度自评（0.9=明确, 0.5=暗示）
                   ↓
              entity_facts（UPSERT，同 key 覆盖）
                   │
             下一轮对话 → _build_system_prompt()
                         注入 "[长期记忆] 已知信息：name=张三, job=工程师..."
```

### 记忆配置

```yaml
# app.yaml
memory:
  enabled: true               # 是否启用长期记忆
  extract_after_turn: true    # 每轮对话后自动提取
  min_confidence: 0.5         # 注入 system prompt 的最低置信度
```

数据库文件自动创建在 `.data/memory.db`，零运维开销。

## Skill 系统 — 零代码扩展 Agent 能力

Skill 是 `.md` 文件，放在 `skills/` 目录下（可在 `app.yaml` 中修改路径）。每个文件 = 一个技能，包含 YAML 元数据头 + Markdown 提示词正文。

### 默认 Skill（人格）

设置 `default: true` 后，该 skill 会**始终注入**到每次对话的 system prompt 中，用于定义 Agent 的基础人格。示例 `skills/haven.md`：

```markdown
---
name: haven
description: 默认人格——灯塔医疗助手机器人
category: persona
default: true
---

## 角色：健健 — 灯塔医疗助手机器人

你是《灵笼》中的医疗辅助机器人 **健健**，编号 000-AC-0019...

### 核心性格
- 温柔体贴、沉稳可靠、忠诚尽责...
```

### 按需 Skill（领域知识）

不设 `default: true`，仅当用户消息匹配 `trigger_keywords` 时才注入。示例 `skills/code_review.md`：

```markdown
---
name: code_review
description: 审查代码中的 bug、安全漏洞和最佳实践违规
category: development
trigger_keywords:
  - review
  - code review
  - 审查
  - 代码审查
---

## 角色：高级代码审查员

你是经验丰富的代码审查专家。审查代码时，按以下步骤：
1. **Bug 检测** — 识别逻辑错误、边界条件...
2. **安全审查** — 按 OWASP Top 10 检查...
...
```

### Skill 元数据字段

| 字段 | 必需 | 说明 |
|------|------|------|
| `name` | 是 | Skill 唯一标识 |
| `description` | 否 | 简短描述 |
| `category` | 否 | 分类标签（persona / development / ...） |
| `default` | 否 | 设为 `true` 则始终激活（默认 false） |
| `trigger_keywords` | 否 | 触发关键词列表，匹配时自动激活 |

## 扩展点

| 目标 | 方式 | 代码量 |
|------|------|--------|
| 新增领域能力 | 在 `skills/` 下创建 `.md` 文件 | 零代码 |
| 新增人格 | 创建 `default: true` 的 `.md` 文件 | 零代码 |
| 新增模型 | 在 `models.yaml` 中添加条目 + `.env` 设 Key | 两行配置 |
| 新增 MCP 服务 | 在 `mcp.json` 中添加服务器条目 | 一段 JSON |
| 新增对话渠道 | 实现 `BaseChannel` 接口，注册到 daemon | 一个文件 |
| 新增工具 | 创建类 + `@ToolRegistry.register("name")` | 一个文件 |
| 新增工作流 | 在 `workflows/` 下组合 `GeneralAgent` | 一个文件 |
| 新增 Agent 类型 | 继承 `BaseAgent`，实现 `run()` / `step()` | 一个类 |

## 目录结构

```
Forest/
├── .env                  # 环境变量（API Key 等）【必须配置】
├── mcp.json              # MCP 服务器配置
├── skills/               # Skill 文件目录（.md）
│   ├── haven.md          #   默认人格
│   ├── code_review.md    #   按需激活的领域 skill
│   └── ...
├── .data/                # 运行时数据（自动创建）
│   └── memory.db         #   长期记忆 SQLite 数据库
├── src/forest/
│   ├── agents/           # Agent 实现（GeneralAgent, OrchestratorAgent）
│   ├── cli/              # CLI 入口 & REPL（main, HavenApp）
│   ├── config/           # 配置层（app.yaml + models.yaml + settings + loader）
│   ├── core/             # 核心抽象（BaseAgent, memory_store, RAG, registry）
│   ├── mcp/              # MCP 协议集成（manager + config）
│   ├── services/         # 守护进程 & 渠道（Daemon, BaseChannel, SocketChannel, EmailChannel）
│   ├── skills/           # Skill 加载器
│   ├── tools/            # 内置工具（web_search, file_ops, email, RAG 等）
│   └── workflows/        # 工作流组合
└── tests/
```

## 配置文件速查

| 文件 | 位置 | 用途 |
|------|------|------|
| `.env` | 项目根目录 | API Key、邮箱密码等敏感信息 |
| `app.yaml` | `src/forest/config/` | 框架默认参数（可被 .env 覆盖） |
| `models.yaml` | `src/forest/config/` | 模型定义（provider、endpoint、参数） |
| `mcp.json` | 项目根目录 | MCP 服务器连接配置 |

配置优先级：`.env` 环境变量 > `app.yaml` 默认值

## 开发

```bash
uv sync --group dev
uv run pytest          # 运行测试
uv run pytest -v       # 详细输出
```

## 详细文档

参见 [docs/architecture.md](docs/architecture.md)。

## 许可证

MIT
