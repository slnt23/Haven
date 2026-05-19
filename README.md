# Forest — 多智能体开发框架

基于 Python 3.14+、LangChain 与 deepagents 构建，提供一套可扩展的多 Agent 协作开发脚手架。

代号：健健（灵感来自灵笼）
英文版：haven

## 快速开始

```bash
cp .env .env
# 编辑 .env，填入 LLM_API_KEY

uv sync
uv run python scripts/run_agent.py "调研 AI Agent 的最新进展"
uv run pytest
```

## 项目架构

详见 [docs/architecture.md](docs/architecture.md)。
