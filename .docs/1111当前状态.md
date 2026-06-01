# Haven V2 当前状态

> 快照日期: 2026-06-01  
> 分支: `dev`  
> 最新提交: `d6fd9fb` — "删除兼容代码，本项目是V2"

## 状态摘要

| 维度 | 状态 | 备注 |
|------|------|------|
| 核心引擎 | 功能完整 | AgentRuntime + PlannerAgent + 3 条执行路径 |
| 工作流引擎 | 功能完整 | WorkflowGraph DAG + 3 个预定义工作流 + Checkpoint |
| 记忆系统 | 功能完整 | 四层记忆 (Working/Episodic/Semantic/Vector) |
| 工具系统 | 功能完整 | Provider 架构 + Builtin (6 工具) + MCP + ToolResolver |
| 技能系统 | 功能完整 | 8 个 .md Skill (1 人格 + 7 领域) |
| CLI | 功能完整 | Typer + Rich + REPL + 6 个子命令 |
| 守护进程 | 功能完整 | 多通道 (TCP/Email/飞书) |
| 测试 | **缺失** | `tests/` 仅空 `__init__.py` |
| CI/CD | **缺失** | 无 GitHub Actions, 无 linting |
| 文档 | 部分 | CLAUDE.md + .docs/ + 代码 docstring |

## 版本信息

| 位置 | 声明的版本 |
|------|-----------|
| `pyproject.toml` | `0.1.0` |
| CLI banner | `v2.0.0` |
| Daemon banner | `v2.0.0` |
| `ARCHITECTURE_AUDIT.md` | `V2.0.0` |

**已知不一致:** `pyproject.toml` 版本应为 `2.0.0`。

## 模块完成度

```
Config     ████████████████████ 100%   (5/5 files)
Core       ████████████████████ 100%   (7/7 files)
Memory     ████████████████████ 100%   (6/6 files)
Skills     ████████████████████ 100%   (3/3 files)
Tools      ████████████████████ 100%   (13/13 files)
Runtime    ████████████████████ 100%   (4/4 files)
Workflows  ████████████████████ 100%   (10/10 files)
CLI        ████████████████████ 100%   (11/11 files)
Services   ████████████████████ 100%   (6/6 files)
Tests      ░░░░░░░░░░░░░░░░░░░░   0%   (1 placeholder)
CI/CD      ░░░░░░░░░░░░░░░░░░░░   0%   (无配置)
```

## 文件统计

| 指标 | 数量 |
|------|------|
| Python 源文件 | 50 |
| 总 Python 行数 | ~8,000 (估算) |
| Skill 文件 (.md) | 8 |
| 配置 YAML | 2 (app.yaml + models.yaml) |
| MCP 配置 | 1 (mcp.json) |
| 预定义工作流 | 3 |
| 内置工具 | 6 |
| 测试文件 | 0 (仅 __init__.py) |

## 依赖

```
Python          >= 3.14
LangChain       (langchain-core + langchain-deepseek + langchain-openai)
pydantic        (pydantic + pydantic-settings)
OmegaConf       (YAML deep-merge)
Typer + Rich    (CLI)
SQLite          (memory/checkpoint 持久化)
ChromaDB        (vector memory, 可选)
MCP             (外部工具集成)
```

## 分支与提交历史

```
dev (current)
  d6fd9fb — 删除兼容代码，本项目是V2
  6eb1515 — 引入新架构，重构1
  159343b — 用户自定义在CWD中配置
  731a8ad — 注释统一整理格式中文化
  794a0c4 — match1

master (main branch)
  (未检查分歧)
```

## Git 状态

```
Modified:
  .docs/architecture.md
  CLAUDE.md
  README.md
  skills/code_review.md
  skills/data_analysis.md
  skills/summarization.md
  skills/translation.md
  src/haven/config/haven.md

Deleted:
  hello.txt
  tests/test_agents/__init__.py
  tests/test_agents/test_general.py
  tests/test_tools/__init__.py
  tests/test_tools/test_web_search.py
  tests/test_workflows/__init__.py
  tests/test_workflows/test_research_flow.py

Renamed:
  tests/test_agents/__init__.py → src/haven/user/haven.yaml

New (untracked):
  skills/coder.md
  skills/companion.md
  skills/medical.md
  skills/practical.md
```

## 下一步行动

1. **P0**: 将 `pyproject.toml` 版本改为 `2.0.0`
2. **P0**: 添加 ruff/mypy/pre-commit 配置
3. **P0**: 重写测试文件以匹配 V2 API
4. **P1**: 标记 V1 API deprecated
5. **P1**: 拆分 `workflows/nodes.py`
6. **P2**: 添加 API 文档生成
