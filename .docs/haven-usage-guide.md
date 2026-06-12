# Haven 使用指南

> 代号：健健（出自《灵笼》）— 多智能体交互框架

## 环境要求

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) 包管理器

## 安装

```bash
git clone <repo-url>
cd Haven
uv sync
```

开发依赖（pytest / ruff / mypy）：

```bash
uv sync --group dev
```

## 配置

### 1. 模型 API Key

在环境变量中设置模型 API Key。当前默认使用 DeepSeek：

```bash
# Windows
set OWL_DEEPSEEK_API_KEY=sk-your-key-here

# Linux / macOS
export OWL_DEEPSEEK_API_KEY=sk-your-key-here
```

可选的其他模型（在 `src/haven/config/models.yaml` 中定义）：

| 模型 | 环境变量 |
|------|---------|
| DeepSeek | `OWL_DEEPSEEK_API_KEY` |
| OpenAI GPT | `OPENAI_API_KEY` |
| 通义千问 | `DASHSCOPE_API_KEY` |

### 2. 切换模型

默认使用 `deepseek-v4-pro`。启动后通过 `/model` 查看当前模型，或修改配置文件切换。

### 3. 用户自定义配置

在项目根目录（CWD）下放置以下文件可覆盖默认配置：

| 文件 | 作用 |
|------|------|
| `haven.yaml` | 框架参数（agent 迭代数、memory、MCP 等） |
| `models.yaml` | 模型定义 |
| `mcp.json` | MCP 外部工具服务器 |
| `skills/*.md` | 自定义技能 |

### 4. 自定义 Skill

在 `skills/` 目录下创建 `.md` 文件：

```markdown
---
name: my_skill
description: 我的自定义技能描述
tags:
  - analysis
dependencies: []
---

## 角色：我的专属助手

你擅长...
- 能力1
- 能力2
```

### 5. MCP 外部工具

在 `mcp.json` 中配置 MCP 服务器：

```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "@some/mcp-server"],
      "transport": "stdio"
    }
  }
}
```

## 使用方式

### 交互式 REPL

```bash
uv run haven
```

启动后进入对话界面，输入消息开始对话。

#### 内建命令

| 命令 | 说明 |
|------|------|
| `/model` | 查看当前使用的模型 |
| `/tools` | 查看已加载的工具列表 |
| `/agents` | 查看可用 Agent（coder / researcher / diagnosis / general） |
| `/clear` | 清除当前会话记忆 |
| `/memory-clear` | 清除长期记忆 |
| `/log [on/off/debug]` | 查看或切换日志级别 |
| `/exit` | 退出 |

### 单轮问答

```bash
uv run haven --task "写一个 Python 快速排序"
```

### HTTP API 服务

```bash
uv run python -c "
import asyncio
from haven.runtime.factory import create_runtime
from haven.interface.http_server import HTTPServer

async def main():
    runtime = await create_runtime()
    server = HTTPServer(runtime, port=8420)
    await server.start()

asyncio.run(main())
"
```

- `GET http://127.0.0.1:8420/` — 聊天网页
- `POST http://127.0.0.1:8420/api/chat` — API 接口
- `GET http://127.0.0.1:8420/health` — 健康检查

### 守护进程模式（飞书机器人）

```bash
uv run haven serve     # 启动
uv run haven stop      # 停止
uv run haven status    # 查看状态
uv run haven restart   # 重启
```

需在 `haven.yaml` 中配置飞书应用的 `app_id` 和 `app_secret`。

## 可用 Agent

| Agent | 用途 |
|-------|------|
| `coder` | 代码生成、审查、调试 |
| `researcher` | 信息搜索、数据分析、报告生成 |
| `diagnosis` | 症状分析、健康咨询、故障排查 |
| `general` | 通用对话与问答 |

## 开发

### 运行测试

```bash
uv run pytest                 # 全部测试 (200+)
uv run pytest tests/agent/    # 单个模块
uv run pytest -v              # 详细输出
```

### 项目结构

```
src/haven/
├── kernel/           # 事件、Trace、生命周期
├── config/           # 配置系统
├── model/            # LLM 抽象
├── session/          # 会话管理
├── execution/        # 执行引擎
├── agent/            # Agent 封装
├── capability/       # Skill + Tool 统一
├── memory/           # 记忆系统
├── workflow/         # 工作流引擎
├── interface/        # 用户入口
└── runtime/          # 运行时装配
```

### 架构说明

详细设计见 `docs/architecture/v2-design.md`。
