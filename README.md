# Forest — 多智能体协作框架

代号：**健健**（出自《灵笼》），英文名 **Haven**

基于 Python 3.12+、LangChain 与 pydantic-settings 构建的多 Agent 协作框架。采用 **Orchestrator + 专精 Agent** 架构，核心设计理念是 **数据驱动**——通过 Markdown 技能文件注入人格与领域知识，无需编写代码即可扩展 Agent 能力。

## 快速开始

```bash
# 1. 创建环境变量文件并填入 API Key
cp .env.example .env

# 2. 安装依赖
uv sync

# 3. 运行（三种模式）
uv run haven                       # 交互式 REPL
uv run haven --task "你的问题"      # 单轮问答
uv run haven serve                 # 常驻守护进程（多渠道并行）
```

## 架构概览

```
用户输入 → OrchestratorAgent（意图分类）
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼           ▼
CoderAgent  MedicalAgent  CompanionAgent  PracticalAgent
(软件工程)   (医疗健康)     (日常陪伴)      (工科实用)
    │           │           │           │
    └───────────┴───────────┴───────────┘
                │
            统一响应
```

### 专精 Agent

| Agent | 职责 | 工具 |
|-------|------|------|
| `OrchestratorAgent` | LLM 意图分类 → 路由 → 聚合 | — |
| `CoderAgent` | 代码生成、审查、调试、架构 | `code_exec` `file_ops` `web_search` |
| `MedicalAgent` | 症状分析、健康咨询（Haven 医疗形态） | `medical_kb` `web_search` `rag_search` |
| `CompanionAgent` | 日常聊天、情感陪伴（Haven 陪伴形态） | `web_search` |
| `PracticalAgent` | 硬件排障、DIY、效率工具、网络通信 | `web_search` `file_ops` `rag_search` |

所有 Agent 共享同一个长期记忆实例，对话历史跨 Agent 无缝衔接。

## 配置说明

分层配置：`app.yaml`（默认值） → `.env`（覆盖） → `models.yaml`（模型定义） → `mcp.json`（MCP 服务器）。

### 1. `.env` — API Key 与环境变量（必须配置）

```bash
# ─── 模型 API Key ───
DEEPSEEK_API_KEY=sk-your-key-here
OPENAI_API_KEY=sk-your-key-here
DASHSCOPE_API_KEY=sk-your-key-here

# ─── 网页搜索 ───
WEB_SEARCH_API_KEY=your-search-api-key

# ─── 邮箱（可选） ───
EMAIL_SMTP_USERNAME=your-email@qq.com
EMAIL_SMTP_PASSWORD=your-smtp-password
EMAIL_IMAP_USERNAME=your-email@qq.com
EMAIL_IMAP_PASSWORD=your-imap-password
```

### 2. `src/forest/config/models.yaml` — 模型定义

```yaml
default_model: deepseek-v4-pro

models:
  deepseek-v4-pro:
    provider: deepseek
    api_key_env: DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com
    temperature: 0.5
    max_tokens: 4096

  gpt-4o:
    provider: openai
    api_key_env: OPENAI_API_KEY
    base_url: https://api.openai.com/v1
    temperature: 0.5
    max_tokens: 8192
```

支持 `deepseek`、`openai` 及任何兼容 OpenAI 接口的 provider。

### 3. `src/forest/config/app.yaml` — 框架参数

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `agent.max_iterations` | 最大工具调用轮次 | `20` |
| `agent.max_execution_time` | 最大执行时间（秒） | `300` |
| `web_search.engine` | 搜索引擎 | `bing` |
| `email.smtp_host` / `smtp_port` | SMTP 发件服务器 | `smtp.qq.com:587` |
| `email.imap_host` / `imap_port` | IMAP 收件服务器 | `imap.qq.com:993` |
| `rag.embedding_model` | RAG 嵌入模型 | `text-embedding-3-small` |
| `rag.chunk_size` / `chunk_overlap` | 文档分块 | `1000` / `200` |
| `rag.top_k` | 检索条数 | `5` |
| `mcp.enabled` | MCP 开关 | `true` |
| `daemon.channels.socket` | TCP 渠道 | `enabled: true, 127.0.0.1:9020` |
| `daemon.channels.email` | 邮件渠道 | `enabled: false` |
| `memory.enabled` | 长期记忆 | `true` |
| `memory.min_confidence` | 注入最低置信度 | `0.5` |
| `skill.directory` | Skill 文件目录 | `skills` |

### 4. `mcp.json` — MCP 服务器配置

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "enabled": true
    },
    "remote_api": {
      "type": "sse",
      "url": "http://localhost:8000/mcp",
      "enabled": false
    }
  }
}
```

MCP 工具会自动注册到所有专精 Agent，LLM 可按需调用。

## CLI 交互命令

进入 REPL 后，输入 `/help` 查看完整命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/models` | 列出所有可用模型 |
| `/model` | 显示当前模型（Orchestrator + 所有子 Agent） |
| `/model <名称>` | 切换模型（同步切换所有 Agent，支持模糊匹配） |
| `/skills` | 按 Agent 分组列出已加载的 skill |
| `/tools` | 列出所有工具（标注所属 Agent） |
| `/mcp` | MCP 服务器连接状态 |
| `/clear` | 清空所有 Agent 的对话历史 |
| `/exit` `/quit` `/q` | 退出 |

切换模型时，Orchestrator 和所有子 Agent 会同步切换。

## 常驻守护进程 `haven serve`

```bash
haven serve
#   1. TCP 连接：telnet 127.0.0.1 9020
#   2. 邮件对话：配置 SMTP/IMAP 后自动处理
```

守护进程同样使用多 Agent 架构，渠道共享同一个 Orchestrator 实例：

```
haven serve
  └── HavenDaemon
       └── OrchestratorAgent
            ├── CoderAgent
            ├── MedicalAgent
            ├── CompanionAgent
            └── PracticalAgent
       └── SocketChannel (tcp://127.0.0.1:9020)
       └── EmailChannel  (IMAP + SMTP)
```

## 长期记忆系统

双层记忆架构，所有 Agent 共享同一份记忆：

```
短期记忆（deque, 100条）←── 当前对话上下文
长期记忆（SQLite）      ←── 自动提取人物档案，跨会话、跨 Agent 持久化
```

| 表 | 说明 |
|----|------|
| `entities` | 人物对象 |
| `entity_facts` | 属性键值对（key, value, confidence），同 key 自动覆盖 |
| `conversations` | 对话日志（session_id, role, content） |

## Skill 系统 — 零代码扩展

Skill 是 `skills/` 目录下的 `.md` 文件，包含 YAML 元数据头 + Markdown 提示词正文。

### 系统人格

项目核心人格 `haven.md` 内置在 `src/forest/config/` 下，作为 CompanionAgent 和 MedicalAgent 的基础人格，随包分发。

### 默认 Skill（始终激活）

```markdown
---
name: my_persona
description: 自定义人格
category: persona
default: true
---

## 角色：你的自定义角色
...
```

### 按需 Skill（关键词匹配触发）

```markdown
---
name: code_review
description: 代码审查
category: development
trigger_keywords:
  - review
  - 审查
---

## 角色：高级代码审查员
...
```

| 字段 | 必需 | 说明 |
|------|------|------|
| `name` | 是 | 唯一标识 |
| `description` | 否 | 简短描述 |
| `category` | 否 | 分类 |
| `default` | 否 | `true` 则始终激活 |
| `trigger_keywords` | 否 | 触发关键词 |

## 扩展点

| 目标 | 方式 | 代码量 |
|------|------|--------|
| 新增领域能力 | `skills/` 下创建 `.md` 文件 | 零代码 |
| 新增人格 | 创建 `default: true` 的 `.md` 文件 | 零代码 |
| 新增模型 | `models.yaml` + `.env` 设 Key | 两行配置 |
| 新增 MCP 服务 | `mcp.json` 添加条目 | 一段 JSON |
| 新增专精 Agent | 继承 `GeneralAgent`，注册工具 → 在 factory 中挂载 | 一个文件 |
| 新增工具 | 创建类 → 在 Agent 中注册 | 一个文件 |
| 新增对话渠道 | 实现 `BaseChannel`，注册到 daemon | 一个文件 |

### 添加专精 Agent 步骤

1. 在 `agents/` 下新建文件，继承 `GeneralAgent`
2. 定义 `PROMPT` 系统提示词，注册专属工具
3. 在 `factory.py` 中实例化并注册到 orchestrator
4. 在 orchestrator 的 `ROUTE_MAP` 和分类 prompt 中添加新类别

## 目录结构

```
Forest/
├── .env                      # 环境变量（API Key 等）【必须配置】
├── mcp.json                  # MCP 服务器配置
├── skills/                   # Skill 文件目录（.md）
│   ├── code_review.md        #   代码审查 skill
│   ├── data_analysis.md      #   数据分析 skill
│   └── ...
├── .data/                    # 运行时数据（自动创建）
│   └── memory.db             #   长期记忆 SQLite 数据库
├── src/forest/
│   ├── agents/               # Agent 实现
│   │   ├── orchestrator.py   #   路由编排（意图分类 + 分发）
│   │   ├── general.py        #   通用 Agent 基类
│   │   ├── coder.py          #   软件工程专精
│   │   ├── medical.py        #   医疗健康专精
│   │   ├── companion.py      #   日常陪伴专精
│   │   ├── practical.py      #   工科实用专精
│   │   └── factory.py        #   Agent 工厂（组装多 Agent 系统）
│   ├── cli/                  # CLI 入口 & REPL
│   ├── config/               # 配置层（app.yaml + models.yaml + settings + haven.md）
│   ├── core/                 # 核心抽象（BaseAgent, memory, RAG, registry）
│   ├── mcp/                  # MCP 协议集成
│   ├── services/             # 守护进程 & 渠道
│   ├── skills/               # Skill 加载器
│   ├── tools/                # 内置工具
│   └── workflows/            # 工作流组合
└── tests/
```

## 配置文件速查

| 文件 | 位置 | 用途 |
|------|------|------|
| `.env` | 项目根目录 | API Key、邮箱密码 |
| `app.yaml` | `src/forest/config/` | 框架参数（可被 .env 覆盖） |
| `models.yaml` | `src/forest/config/` | 模型定义 |
| `mcp.json` | 项目根目录 | MCP 服务器配置 |
| `haven.md` | `src/forest/config/` | 系统核心人格 |

## 开发

```bash
uv sync --group dev
uv run pytest
uv run pytest -v
```

## 文档

- [docs/architecture.md](docs/architecture.md) — 详细架构文档

## 许可证

MIT
