# Forest — 多智能体开发框架

基于 Python 3.14+、LangChain 与 deepagents 构建，提供一套可扩展的多 Agent 协作开发脚手架。

代号：健健（灵感来自灵笼）

## 目录结构

```
forest/
├── pyproject.toml              # 项目元信息与依赖管理（uv）
├── .env.example                # 环境变量模板（LLM Key、模型等）
│
├── src/forest/
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py         # 全局配置（Pydantic BaseSettings）
│   │   └── agents.yaml         # Agent 角色定义（预留）
│   │
│   ├── core/
│   │   ├── base_agent.py       # BaseAgent 抽象基类
│   │   ├── tool_registry.py    # 工具注册中心（装饰器模式）
│   │   └── memory.py           # 对话记忆管理
│   │
│   ├── agents/
│   │   ├── researcher.py       # 调研 Agent
│   │   ├── coder.py            # 编码 Agent
│   │   └── orchestrator.py     # 编排 Agent（管理子 Agent）
│   │
│   ├── tools/
│   │   ├── web_search.py       # 网络搜索工具
│   │   ├── file_ops.py         # 文件读写工具
│   │   └── code_exec.py        # 代码执行工具
│   │
│   └── workflows/
│       ├── research_flow.py    # 调研 → 总结 工作流
│       └── dev_flow.py         # 方案 → 编码 工作流
│
├── tests/                      # 单元测试（pytest + pytest-asyncio）
├── scripts/                    # CLI 入口与评估脚本
└── README.md
```

---

## 核心模块逻辑

### config/settings.py — 全局配置

使用 `pydantic-settings` 从 `.env` 文件读取配置，自动类型校验：

```
# .env 示例
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-xxx
```

核心字段：LLM 连接参数（provider/model/key）、Agent 运行限制（max_iterations）、工具密钥。全局单例 `settings` 在各模块中直接 `from forest.config import settings` 引用。

### core/base_agent.py — Agent 抽象基类

所有 Agent 的父类，定义了两个必须实现的核心接口：

- `run(task: str)` — 接收一个任务字符串，返回执行结果（完整的一次调用）
- `step(messages: list[BaseMessage])` — 接收消息列表，返回下一步消息（逐步推理）

内置 `register_tool(name, tool)` 方法，子类可按需挂载工具。

### core/tool_registry.py — 工具注册中心

采用**装饰器模式**的工具注册表。工具类只需加上 `@ToolRegistry.register()` 即自动注册：

```python
# @ToolRegistry.register("web_search")
class WebSearchTool:
    async def search(self, query): ...
```

通过 `ToolRegistry.get("web_search")` 或 `ToolRegistry.list_tools()` 发现所有可用工具。这种设计使新增工具时无需修改 Agent 代码。

### agents/orchestrator.py — 编排 Agent

核心编排角色。内部维护 `sub_agents: dict[str, BaseAgent]`，通过 `register_agent()` 注册子 Agent。`run()` 方法将任务广播给所有子 Agent，汇总结果为扁平字符串。

典型用法：

```python
# orchestrator = OrchestratorAgent()
# orchestrator.register_agent("researcher", ResearcherAgent("r1"))
# orchestrator.register_agent("coder", CoderAgent("c1"))
# await orchestrator.run("实现一个 CLI 工具")
```

### workflows/research_flow.py — 工作流示例

展示了多 Agent 协同模式：**先调研后总结**。内部持有多个 Agent 实例，`run()` 方法按顺序编排调用：

1. `ResearcherAgent.run("Research: {topic}")` — 收集资料
2. `CoderAgent.run("Summarize: {research}")` — 生成总结

结果以 `dict` 返回，兼顾结构化与灵活扩展。`DevFlow` 遵循同样的 `plan → implement` 模式。

### tools/ 层

每个工具遵循 `@ToolRegistry.register` + `__call__` 规范，使 Agent 可以统一通过 `await tool(...)` 调用：

| 工具 | 能力 |
|---|---|
| `WebSearchTool` | 网络搜索（预留 Bing/Google API 接入） |
| `FileOpsTool` | 文件的读写 |
| `CodeExecTool` | 临时 Python 脚本执行 |

---

## 快速开始

```bash
cp .env .env
# 编辑 .env，填入 LLM_API_KEY

uv sync
uv run python scripts/run_agent.py "调研 AI Agent 的最新进展"
uv run pytest
```
