# Haven

代号：**健健**（出自《灵笼》）— 多智能体交互框架

基于 Python 3.14+、LangChain 1.x + LangGraph 构建。
人格与领域能力通过 Markdown 技能文件注入，零代码扩展。
外部工具通过 MCP 协议集成。

## 快速开始

```bash
uv sync                   # 安装依赖
uv run haven              # 交互式 REPL
uv run haven --task "..." # 单轮问答
uv run pytest             # 运行测试 (200+)
```

## V2 架构

```
Interface  →  Runtime  →  Execution  →  Agent  →  Capability  →  Memory
                ↓            ↓             ↓          ↓
           Infrastructure ← Kernel ← Config / Model
```

| 层 | 职责 |
|---|------|
| **Kernel** | 事件系统、Trace、异常体系、生命周期 |
| **Infrastructure** | 公共类型、日志、MCP 连接 |
| **Config** | 配置加载（YAML → env → runtime override） |
| **Model** | LLM 客户端抽象（OpenAI/DeepSeek 兼容） |
| **Session** | 会话生命周期管理 |
| **Execution** | Planner（LangGraph Flow）+ Pipeline + Executor |
| **Agent** | LangChain create_agent 封装 |
| **Capability** | 统一 Skill + Tool 注册表 |
| **Memory** | MemoryManager（Fact + Vector + Conflict） |
| **Workflow** | LangGraph StateGraph 工作流引擎 |
| **Interface** | CLI / HTTP / WebSocket |

## 项目结构

```
src/haven/
├── kernel/           # 内核基础设施
├── infrastructure/   # 跨层类型
├── config/           # 配置系统
├── model/            # LLM 抽象
├── session/          # 会话管理
├── execution/        # 执行引擎
├── agent/            # Agent 封装
├── capability/       # 统一能力管理
├── memory/           # 记忆系统
├── workflow/         # 工作流引擎
├── interface/        # 用户入口
└── runtime/          # 运行时装配
```
