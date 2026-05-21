# Haven 项目架构

基于 Python 3.14+、LangChain 与 pydantic-settings 构建的多智能体交互框架。人格由 Skill 定义（`.md` 文件），领域能力按需激活，外部能力通过 MCP 协议集成，长期记忆由 SQLite + LLM 自动提取维护。

## 目录结构

```
haven/
├── pyproject.toml                  # 项目元信息，haven 命令入口
├── .env                            # 环境变量（LLM Key、SMTP 凭证等）
├── mcp.json                        # MCP 服务器配置（标准 mcpServers 格式）
├── skills/                         # Skill 定义（.md 文件，拖入即用）
│   ├── code_review.md              # 代码审查
│   ├── translation.md              # 翻译
│   ├── summarization.md            # 摘要
│   └── data_analysis.md            # 数据分析
│
├── src/forest/
│   ├── config/                     # 配置层
│   │   ├── __init__.py             # 统一导出 settings + loader
│   │   ├── settings.py             # Pydantic BaseSettings 单例
│   │   ├── loader.py               # YAML 配置加载（OmegaConf）
│   │   ├── app.yaml                # 框架默认参数（agent/RAG/email/MCP/skill）
│   │   ├── models.yaml             # LLM 模型定义
│   │   └── haven.md                # 系统核心人格（随包分发）
│   │
│   ├── core/                       # 核心框架层
│   │   ├── base_agent.py           # BaseAgent 抽象基类 + skill/工具/MCP/记忆 集成
│   │   ├── registry.py             # 通用注册表
│   │   ├── tool_registry.py        # 工具注册中心（装饰器模式）
│   │   ├── memory.py               # AgentMemory 双层记忆（短期 deque + 长期 SQLite）
│   │   ├── memory_store.py         # SQLiteMemoryStore 长期记忆后端 + LLM 自动提取
│   │   └── rag.py                  # RAGEngine 检索增强生成
│   │
│   ├── skills/                     # Skill 系统
│   │   ├── base_skill.py           # BaseSkill 数据类
│   │   ├── loader.py               # SkillLoader — 扫描目录，解析 YAML frontmatter
│   │   └── registry.py             # SkillRegistry（装饰器模式）
│   │
│   ├── mcp/                        # MCP 协议集成
│   │   ├── config.py               # MCPServerConfig + load_mcp_servers()
│   │   └── manager.py              # MCPManager — 生命周期管理 + 工具发现
│   │
│   ├── agents/                     # Agent 层
│   │   ├── general.py              # GeneralAgent — 唯一通用 agent
│   │   └── orchestrator.py         # OrchestratorAgent — 多 agent 编排
│   │
│   ├── tools/                      # 工具层
│   │   ├── web_search.py           # 网络搜索
│   │   ├── file_ops.py             # 文件读写
│   │   ├── code_exec.py            # 代码执行
│   │   ├── email_tool.py           # 邮件发送
│   │   ├── medical.py              # 医学知识查询
│   │   └── rag_search.py           # RAG 知识库检索
│   │
│   ├── workflows/                  # 工作流层
│   │   ├── research_flow.py        # 调研 → 总结
│   │   ├── dev_flow.py             # 方案 → 编码
│   │   └── diagnosis_flow.py       # 症状分析 → 诊断
│   │
│   ├── cli/                        # CLI 交互层
│   │   ├── main.py                 # haven 命令入口
│   │   └── app.py                  # HavenApp REPL 循环
│   │
│   └── services/                   # 服务层 — 守护进程 & 渠道
│       ├── base_channel.py         #   BaseChannel 渠道抽象基类
│       ├── email_service.py        #   EmailService 邮件收发核心
│       ├── email_channel.py        #   EmailChannel 邮件渠道适配器
│       ├── socket_channel.py       #   SocketChannel TCP 本地 REPL 渠道
│       └── daemon.py               #   HavenDaemon 守护进程管理器
│
├── scripts/                        # 独立运行脚本
│   ├── run_agent.py
│   ├── run_email_service.py
│   └── eval.py
│
├── tests/                          # 测试
│   ├── test_agents/
│   ├── test_tools/
│   └── test_workflows/
│
└── docs/
    ├── architecture.md             # 本文档
    ├── haven_class.png             # 类图
    ├── haven_package.png           # 包图
    └── haven_sequence.png          # 时序图
```

## 核心设计理念

**两个 Agent 类型，无数种能力：**

```
Agent（管"怎么跑"）          Skill（管"怎么想"）         MCP（管"外部能力"）
─────────────────────      ─────────────────────      ─────────────────────
GeneralAgent        ←──    haven.md         （默认人格）  filesystem ←─ stdio
OrchestratorAgent   ←──    code_review.md   （按需激活）  web_fetch ←─ HTTP SSE
                            translation.md   （按需激活）  ...       ←─ WebSocket
                            *.md             （零代码）
```

- **人格** = 默认 Skill（`haven.md`）注入 system prompt
- **领域能力** = 按需 Skill，用户输入触发关键词时临时注入 prompt
- **外部能力** = 通过 `mcp.json` 配置标准的 MCP 服务器，工具自动注入 Agent
- **新能力** = 写一个 `.md` 文件（零代码）或配置一个 MCP 服务（零代码）

## 分层详解

### 1. 配置层 `config/`

配置文件分层加载，内置默认值可被用户 YAML 覆盖，环境变量优先级最高：

| 文件 | 位置 | 职责 |
|------|------|------|
| `app.yaml` | `src/forest/config/` | 框架默认参数（内置，随包分发） |
| `models.yaml` | `src/forest/config/` | LLM 模型默认定义（内置，随包分发） |
| `haven.yaml` | 项目根目录 | 用户覆盖框架参数（可选，只写要改的字段） |
| `models.yaml` | 项目根目录 | 用户追加/覆盖模型定义（可选） |
| `mcp.json` | 项目根目录 | MCP 服务器连接配置（标准 mcpServers 格式） |
| `.env` | 项目根目录 | API Key、邮箱密码等敏感信息 |

配置优先级：**内置默认 < 用户 YAML (CWD) < 环境变量 (.env / shell)**

用户 YAML 与内置 YAML 做 deep merge，未覆盖的字段继承内置默认值。可通过 `HAVEN_CONFIG_DIR` 环境变量指定用户配置目录。

**`settings.py`** — 使用 `pydantic-settings` 从 `.env` 和 `app.yaml` 读取，全局单例：

```
# 模型 API Key 通过 models.yaml 的 api_key_env 字段指定，无需在 settings 中硬编码

# Agent
AGENT_MAX_ITERATIONS=20            # 最大工具调用轮次
AGENT_MAX_EXECUTION_TIME=300       # 最大执行时间（秒）

# Web Search
WEB_SEARCH_API_KEY=xxx             # 搜索引擎 API Key
WEB_SEARCH_ENGINE=bing             # 搜索引擎

# Email
EMAIL_SMTP_HOST=smtp.qq.com        # SMTP 发件服务器
EMAIL_SMTP_PORT=587                # SMTP 端口
EMAIL_SMTP_USERNAME=xxx            # 发件邮箱
EMAIL_SMTP_PASSWORD=xxx            # SMTP 授权码
EMAIL_IMAP_HOST=imap.qq.com        # IMAP 收件服务器
EMAIL_IMAP_PORT=993                # IMAP 端口
EMAIL_IMAP_USERNAME=xxx            # 收件邮箱
EMAIL_IMAP_PASSWORD=xxx            # IMAP 密码
EMAIL_POLL_INTERVAL=60             # 邮件轮询间隔（秒）
EMAIL_USER_WHITELIST=xxx           # 用户白名单
EMAIL_DIGEST_TIME=08:00            # 每日摘要时间

# RAG
RAG_EMBEDDING_MODEL=text-embedding-3-small
RAG_EMBEDDING_API_BASE=https://api.openai.com/v1
RAG_CHUNK_SIZE=1000
RAG_CHUNK_OVERLAP=200
RAG_TOP_K=5

# MCP
MCP_ENABLED=true                   # 是否启用 MCP 集成

# Skills
SKILL_DIRECTORY=skills             # .md skill 文件目录
```

**`models.yaml`** — LLM 模型档。支持 `deepseek`、`openai` 及任何兼容 OpenAI 接口的 provider：

```yaml
default_model: deepseek-v4-pro

models:
  deepseek-v4-pro:
    provider: deepseek
    api_key_env: DEEPSEEK_API_KEY    # Key 从环境变量读取
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

**`loader.py`** — OmegaConf 加载 `models.yaml`，`get_model_config(name)` 将模型名解析为 `{name, provider, api_key, base_url, temperature, max_tokens}`。API Key 通过 `api_key_env` 字段从 `os.environ` 动态读取，新增模型无需改代码。

### 2. 核心框架层 `core/`

**`BaseAgent`（ABC）**

所有 Agent 的基类：

| 方法 | 说明 |
|------|------|
| `_init_llm(model_name)` | 根据 provider 实例化 `ChatDeepSeek` 或 `ChatOpenAI` |
| `_build_system_prompt()` | 组装默认 skill 的 prompt 为 system prompt |
| `_invoke_llm(task, prompt, use_rag)` | 调用 LLM，可选 RAG 上下文注入 |
| `_invoke_llm_with_tools(task, prompt, use_rag)` | 带工具调用循环的 LLM 调用 |
| `register_tool(name, tool)` | 注册普通 callable 工具 |
| `register_lc_tool(tool)` | 注册 LangChain `BaseTool` |
| `register_mcp_tools(tools)` | 批量注册 MCP 发现的工具 |
| `bind_tools_to_llm()` | 将已注册工具 `bind_tools()` 到 LLM |
| `switch_model(name)` | 运行时切换模型，自动重新绑定工具 |
| `enable_skill(skill)` | 加载一个 skill 实例 |
| `load_skills_from_dir(dir)` | 扫描 `skills/*.md` 并自动注册 |
| `match_skills(task)` | 返回匹配当前任务关键词的按需 skill |
| `reset()` | 清空对话历史 |

抽象方法：`run(task)` / `step(messages)`

**`ToolRegistry`** — 装饰器注册表，`@ToolRegistry.register("name")` 注册工具类。

**`AgentMemory`** — 基于 `deque(maxlen=100)` 的对话历史，支持 `add_message` / `get_history` / `clear`。

**`RAGEngine`** — OpenAI 兼容 embedding + `InMemoryVectorStore`，支持 `add_texts` / `add_files` / `add_directory` 导入，`retrieve(query)` 语义检索。

### 3. Skill 系统 `skills/`

**Skill 定位**：介于 Tool（原子操作）和 Agent（完整智能体）之间的可复用能力包。

**`.md` 文件格式：**

```markdown
---
name: code_review
description: 审查代码中的 bug 和安全漏洞
category: development
default: false              # true = 始终激活的人格 skill
trigger_keywords:
  - review
  - 审查
  - code review
---

## 角色：高级代码审查员
你是经验丰富的代码审查专家……
```

**`BaseSkill`** — 纯数据类，字段包括 `name`、`description`、`prompt`、`trigger_keywords`、`category`、`default`。

**`SkillLoader`** — 扫描目录下所有 `.md` 文件，解析 YAML frontmatter，实例化 `BaseSkill`。

**`SkillRegistry`** — 程序化注册（装饰器模式），与 `ToolRegistry` 同风格。

**激活机制：**

```
_build_system_prompt()
  └── 注入所有 default=true 的 skill.prompt     ← 人格（haven.md）

match_skills(task)
  └── 返回 trigger_keywords 匹配 task 的 skill   ← 领域能力（按需）
```

### 4. MCP 协议集成 `mcp/`

通过标准 MCP (Model Context Protocol) 协议集成外部工具服务，实现零代码工具扩展。

**`MCPServerConfig`** — 单服务器配置模型，支持三种传输方式：

| 传输方式 | 配置字段 | 说明 |
|----------|----------|------|
| `stdio` | `command` + `args` + `env` | 本地子进程通信（如 npx/uvx） |
| `http` (SSE) | `url` + `headers` | 远程 HTTP SSE 连接 |
| `websocket` | `url` | 远程 WebSocket 连接 |

配置模型自动将标准 MCP `mcpServers` 格式（`type: "sse"`）转换为内部传输类型（`transport: "http"`）。

**`mcp.json`** — 标准格式，可直接从 MCP 市场复制粘贴：

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "enabled": true
    },
    "remote_api": {
      "type": "sse",
      "url": "http://localhost:8000/mcp",
      "headers": { "Authorization": "Bearer ${MCP_API_KEY}" },
      "enabled": false
    }
  }
}
```

- `${VAR}` 语法自动解析为环境变量
- `"enabled": false` 的服务器不会被加载
- 单个服务器故障不影响其他服务器

**`MCPManager`** — 生命周期管理器：

```
await manager.start()    → 连接所有启用的服务器，发现工具
  ├── stdio:   启动子进程 → 初始化 MCP session → load_mcp_tools
  ├── http:    SSE 连接 → 初始化 MCP session → load_mcp_tools
  └── ws:      WebSocket 连接 → 初始化 MCP session → load_mcp_tools
agent.register_mcp_tools(tools)  → 注册到 agent.tools
agent.bind_tools_to_llm()        → 绑定到 LLM
await manager.stop()    → 优雅关闭所有会话
```

### 5. 长期记忆系统 `core/memory_store.py`

双层记忆架构，自动从对话中提取结构化人物信息，跨会话持久化：

```
AgentMemory
  ├── 短期记忆：deque[BaseMessage]（maxlen=100，进程内存）
  └── 长期记忆：SQLiteMemoryStore（SQLite 持久化）
       ├── entities       — 人物对象（name, type）
       ├── entity_facts    — 人物属性键值对（key, value, confidence）
       └── conversations   — 对话日志（session_id, channel, role, content）
```

**自动提取机制：**

```
对话结束 → save_turn(user_msg, ai_response)
           → asyncio.create_task(extract_facts_async())
              → get_last_conversation_pair()
              → LLM.ainvoke(EXTRACT_PROMPT)
              → 解析 JSON 提取结果
              → UPSERT entity_facts（同 key 自动覆盖）
```

**提取 Prompt 规则** — LLM 从对话中提取：
- 姓名、职业、位置、健康、偏好、技能、兴趣等
- 每条事实附带 `confidence`（0.9=明确, 0.5=暗示）
- 无新事实时返回空数组，避免浪费 token

**系统提示注入：**

```
_build_system_prompt()
  ├── 默认 Skill（人格）
  ├── 长期记忆上下文 ← get_long_term_context()
  │     "[长期记忆 — 以下是你已知的关于当前用户的信息]
  │      - name: 张三
  │      - occupation: 软件工程师
  │      - health_condition: 轻度高血压"
  └── 按需 Skill（领域知识，match_skills 触发）
```

### 6. Agent 层 `agents/`

| Agent | 职责 |
|-------|------|
| `GeneralAgent` | 唯一通用 agent。人格由默认 skill 定义，领域能力由按需 skill 匹配。无硬编码角色 |
| `OrchestratorAgent` | 维护 `sub_agents` 字典，`run(task)` 广播给所有子 agent 并聚合结果 |

```python
from forest.agents import GeneralAgent, OrchestratorAgent

# 单 agent 模式
agent = GeneralAgent()
agent.load_skills_from_dir()
await agent.run("帮我审查这段代码")    # 自动匹配 code_review skill

# 编排模式
orchestrator = OrchestratorAgent()
orchestrator.register_agent("a", GeneralAgent("general"))
orchestrator.register_agent("b", GeneralAgent("general"))
await orchestrator.run("实现一个 CLI 工具")
```

### 7. CLI 交互层 `cli/`

三种运行模式：

```bash
haven                        # 交互式 REPL
haven --task "你的问题"       # 单轮问答
haven serve                  # 常驻守护进程
```

**`HavenApp`** — 交互式 REPL，启动流程：

```
haven 命令
  → _init_agent()     → GeneralAgent 初始化，LLM 就绪，设置 session/entity
  → _load_skills()    → 扫描 skills/ 目录，区分默认/按需 skill
  → _init_mcp()       → 连接 MCP 服务器，发现并注册工具 → bind_tools_to_llm
  → _print_banner()   → 显示模型/MCP/skill 状态
  → REPL 循环
       ├── /help      → 显示命令帮助
       ├── /skills    → 列出已加载 skill（区分 [默认] / [按需]）
       ├── /tools     → 列出可用工具（含 MCP 工具）
       ├── /models    → 列出所有可用模型（标注当前）
       ├── /model     → 显示当前模型
       ├── /model <名>→ 切换模型（支持模糊匹配，自动重绑工具）
       ├── /mcp       → 显示 MCP 服务器连接状态
       ├── /clear     → 清空对话历史
       ├── /exit /q   → 退出
       └── 其他输入    → _chat()
            ├── _build_system_prompt()    ← 默认 skill + 长期记忆
            ├── match_skills(input)       ← 按需匹配
            ├── memory.get_history()
            ├── llm.ainvoke(messages)
            ├── tool-calling loop
            ├── save_turn() → 持久化到 SQLite
            └── extract_facts_async() → 后台提取长期记忆
```

每条消息都携带完整对话历史 + 动态 skill + MCP 工具 + 长期记忆上下文。

### 8. 守护进程与服务层 `services/`

**守护进程 `HavenDaemon`** — 常驻后台服务，多渠道并行：

```
haven serve
  → _init_agent()     → GeneralAgent 初始化（含 LLM / skills / MCP / 长期记忆）
  → _init_mcp()       → 连接 MCP 服务器
  → _build_channels() → 根据配置实例化启用的 Channel
  → _start_channels() → 并行启动所有 Channel
  → 信号处理（SIGINT/SIGTERM → 优雅退出）
```

**渠道抽象 `BaseChannel`：**

```python
class BaseChannel(ABC):
    name: str
    enabled: bool
    async def start(agent: BaseAgent) -> None  # 启动，接收共享 Agent
    async def stop() -> None                    # 停止，释放资源
    async def handle_message(message: str) -> str  # 通过 Agent 处理消息
```

**现有渠道：**

| 渠道 | 说明 |
|------|------|
| `SocketChannel` | TCP 服务器（默认 `127.0.0.1:9020`），telnet 式 REPL。每条连接独立会话（会话隔离），支持 `/exit` `/model` `/models` `/help` |
| `EmailChannel` | 包装 `EmailService`，IMAP 轮询未读邮件 → Agent 处理 → SMTP 自动回复。白名单过滤 + 去重 |
| `FeishuChannel` | 飞书 / Lark 即时通讯渠道，WebSocket 长连接接收消息，API 回复。无需公网 IP，支持自动重连 |

**渠道启用配置（`app.yaml`）：**

```yaml
daemon:
  channels:
    socket:
      enabled: true
      host: "127.0.0.1"
      port: 9020
    email:
      enabled: false    # 需 .env 配置 SMTP/IMAP 凭证
    feishu:
      enabled: false    # 需 .env 配置 DAEMON_FEISHU_APP_ID / DAEMON_FEISHU_APP_SECRET
      app_id: ""
      app_secret: ""
```

#### 飞书渠道配置步骤

1. 打开 [飞书开发者后台](https://open.feishu.cn/app)，创建**企业自建应用**
2. **添加应用能力** → 开启 **机器人（Bot）**
3. **凭证与基础信息** → 复制 **App ID** 和 **App Secret**
4. **事件订阅**（可选，WebSocket 模式无需配置回调 URL）
5. **发布** → 创建版本并发布（仅应用管理员和测试用户可见即可）
6. 在飞书客户端搜索机器人名称，开始对话

在 `.env` 或用户 `haven.yaml` 中启用：

```bash
DAEMON_FEISHU_ENABLED=true
DAEMON_FEISHU_APP_ID=cli_xxxxxxxx
DAEMON_FEISHU_APP_SECRET=xxxxxxxx
```

```
飞书用户 → 飞书服务器 → WebSocket 事件 → FeishuChannel → agent.run()
                                                              ↓
飞书用户 ← 飞书 API 回复 ← ← ← ← ← ← ← ← ← ← ← ← ← agent 返回结果
```

### 9. 工作流层 `workflows/`

### 7. 工作流层 `workflows/`

多个 `GeneralAgent` 实例串联执行：

| 工作流 | 流程 |
|--------|------|
| `ResearchFlow` | Agent A 研究 → Agent B 总结 |
| `DevFlow` | Agent A 方案 → Agent B 实现 |
| `DiagnosisFlow` | Agent A 医学调研 → Agent B 诊断 |

所有 agent 使用相同的 `GeneralAgent("general")`，差异化来自任务描述和按需 skill 匹配。

**`EmailService`** — 邮件收发核心（被 `EmailChannel` 复用）：

- **IMAP 轮询**：定时收取未读邮件，白名单过滤
- **Agent 回调**：邮件内容传递给 Agent 处理并自动回复
- **SMTP 发送**：TLS/SSL 发送邮件
- **日报摘要**：定时发送每日汇总
- **状态持久化**：`processed_ids` 保存至 `.data/`

## 分层依赖关系

```
config/  ←── 所有层读取配置（app.yaml + models.yaml + .env + mcp.json）
   ↑
 core/   ←── agents/、skills/、mcp/、tools/、workflows/、services/ 依赖
   │        含 memory_store（长期记忆 SQLite 后端）
   ↑
 skills/ ←── core/（BaseSkill）+ 外部 skills/*.md 文件
   ↑
 mcp/    ←── mcp.json（外部）+ langchain-mcp-adapters
   ↑
 agents/ ←── core/（BaseAgent + AgentMemory + SQLiteMemoryStore）
   │        + skills/（SkillLoader）+ mcp/（MCPManager）
   ↑
cli/     ←── agents/（GeneralAgent）+ skills/（SkillLoader）
   │        + mcp/（MCPManager）+ config/
   │        main.py: haven | haven --task | haven serve
   ↑
services/ ←── agents/（共享 GeneralAgent）+ core/（BaseChannel）
   │        daemon.py: 守护进程管理器
   │        socket_channel.py: TCP 本地 REPL
   │        email_channel.py: IMAP 邮件渠道
   ↑
workflows/ ←── agents/（GeneralAgent / OrchestratorAgent）
```

## 扩展方式

| 需求 | 做法 | 改动量 |
|------|------|--------|
| 新领域能力 | `skills/` 下新建 `.md` 文件 | 零代码 |
| 新人格 | 新建 `.md`，设 `default: true` | 零代码 |
| 新外部工具 | `mcp.json` 添加 MCP 服务器条目 | 一段 JSON |
| 新对话渠道 | 实现 `BaseChannel` 接口，注册到 daemon | 一个文件 |
| 新工具 | `tools/` 新建类 + `@ToolRegistry.register` | 一个文件 |
| 新模型 | `models.yaml` 加条目 + `.env` 设 Key | 两行配置 |
| 新工作流 | `workflows/` 编排 `GeneralAgent` 实例 | 一个文件 |
| 新 Agent 类型 | 继承 `BaseAgent`，实现 `run()` / `step()` | 一个类 |

## UML 图

- [类图](haven_class.png) — 所有类的属性/方法/关系
- [包图](haven_package.png) — 模块分层与依赖方向
- [时序图](haven_sequence.png) — 对话交互完整流程
