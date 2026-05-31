# Haven（健健）— 多智能体 AI 对话框架

## 项目概述

Haven 是一个基于 Python 3.14+ 的**多智能体 AI 对话框架**。V2 架构将 Agent 重构为纯执行引擎（Runtime），领域能力由 Skill `.md` 文件零代码注入，任务规划由 PlannerAgent 驱动（LLM Structured Output），工具统一由 Provider 架构管理，记忆升级为四层体系，工作流升级为 DAG 引擎。CLI 基于 Typer + Rich，通过 RuntimeService 桥梁与 Runtime 交互。

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.14+ |
| LLM 框架 | LangChain + LangChain-DeepSeek + LangChain-OpenAI |
| 大模型 | DeepSeek V4、GPT-4o、Qwen Max 等，支持 OpenAI 兼容 API |
| CLI | Typer + Rich（三级命令树 + 终端渲染 + 流式输出） |
| 协议集成 | MCP（Model Context Protocol）多传输协议 |
| 消息通道 | TCP Socket、IMAP/SMTP 邮件、飞书 WebSocket 长连接 |
| 记忆存储 | 四层记忆：Working (deque) + Episodic (SQLite) + Semantic (SQLite) + Vector (ChromaDB) |
| RAG | OpenAI Embeddings + 内存向量库 |
| 工作流 | DAG 执行引擎 + 条件路由 + 失败重试 + Checkpoint 持久化 |
| 构建工具 | Hatchling + uv |

## 架构亮点

### 1. Runtime + Skill 分离架构

V2 将 Agent 拆分为两个正交概念：

- **AgentRuntime**：纯执行引擎。负责 LLM + Tool + Memory + State + Prompt，零业务逻辑。
- **Skill `.md` 文件**：全部领域知识。通过 YAML frontmatter（`tags`/`tools`/`dependencies`）声明能力。

新增领域能力只需创建一个 `.md` 文件，零 Python 代码。

### 2. LLM 驱动 Skill 选择

替代 V1 的关键词匹配（`str.lower()` 子串），采用三阶段 Pipeline：

```
Phase 0: 快速路径 → 简单对话跳过选择
Phase 1: 标签过滤 → 同义词集缩减候选（12→3个）
Phase 2: LLM Structured Output → 语义匹配 + 依赖解析
```

支持多 Skill 组合 + 依赖传递闭包。

### 3. PlannerAgent — LLM 驱动任务规划

一次 LLM 调用完成：意图分类 + 任务拆解 + Skill 选择 + Workflow 匹配。

```json
{
  "goal": "编写爬虫并分析数据",
  "intent": "development",
  "complexity": "complex",
  "skills": ["coder", "data_analysis", "summarization"],
  "workflow": "research_flow",
  "steps": [
    {"order": 1, "description": "编写爬虫", "skill": "coder", "depends_on": []},
    {"order": 2, "description": "分析数据", "skill": "data_analysis", "depends_on": [1]}
  ]
}
```

### 4. DAG 工作流引擎

三个预定义工作流，支持条件路由 + 失败重试 + Checkpoint 恢复：

```
dev_flow:      planner → architect → coder → reviewer → tester
                                                ↑           │
                                                └── fail ────┘ (retry ≤3)

research_flow: searcher → analyst → synthesizer
                    ▲          │
                    └── 缺口 ──┘

diagnosis_flow: collector → analyzer → adviser
```

### 5. 四层记忆系统

| 层 | 存储 | 用途 |
|----|------|------|
| Working | 内存 deque | 当前上下文窗口 + 滚动摘要 |
| Episodic | SQLite episodes | 完整对话记录 + 时间衰减检索 |
| Semantic | SQLite memory_facts | 结构化事实 + 变更历史 + 置信度衰减 |
| Vector | ChromaDB | embedding 语义检索 + 跨 session 匹配 |

### 6. Provider 统一工具架构

四种 Provider 接入工具源：

| Provider | 来源 | 发现方式 |
|----------|------|---------|
| BuiltinProvider | 内置工具 | 自动扫描 HavenTool 子类 |
| MCPProvider | MCP 服务器 | 连接 → discover → 适配 |
| OpenAPIProvider | REST API | 解析 OpenAPI 3.x spec |
| CustomProvider | 用户定义 | `@provider.register()` 装饰器 |

### 7. CLI V2 — Typer + Rich 命令体系

```
haven chat             交互式 REPL [默认]
haven run -t "..."     单轮任务
haven workflow list     工作流管理
haven skill list        Skill 管理
haven doctor            环境诊断
```

**CLI → Service → Runtime 三层隔离：**

```
commands/chat.py ─→ RuntimeService.chat() ─→ PlannerAgent.execute()
commands/run.py  ─→ RuntimeService.run_task() ─→ PlannerAgent + Runtime.run()
commands/skill.py ─→ SkillRegistry（轻量查询，不启动 LLM）
```

CLI 层禁止直接导入 `haven.runtime`。

### 8. MCP 协议全集成

支持 stdio / HTTP SSE / WebSocket 三种传输，`${VAR}` 环境变量解析，单服务器故障不影响其他服务器。

## 核心指标

| 指标 | 数值 |
|------|------|
| 代码行数 | ~12,000+ |
| Python 模块 | 55+ |
| 内置 Skill | 9 个（1 人格 + 8 领域） |
| 内置工具 | 6 个（code_exec / file_ops / web_search / email / medical / rag） |
| 预定义工作流 | 3 个（dev / research / diagnosis） |
| Memory 层 | 4 层（Working / Episodic / Semantic / Vector） |
| Tool Provider | 4 种（Builtin / MCP / OpenAPI / Custom） |
| CLI 命令 | 5 个顶级命令 + 12 个子命令 |
| 消息通道 | 3 种（TCP Socket / Email / 飞书） |
| 支持 LLM | DeepSeek V4 / GPT-4o / Qwen-Max 等 OpenAI 兼容模型 |
