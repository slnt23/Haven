# CWD 布局参考

> Haven V2 项目根目录下各目录与文件说明。

---

## 目录

| 路径 | 职责 | 说明 |
|------|------|------|
| `src/haven/` | 主包 | 全部 Python 源码，50 文件，8 个子包 |
| `tests/` | 测试 | pytest + asyncio，270 个测试 |
| `skills/` | 用户 Skill | `.md` 文件 (YAML frontmatter + Markdown body)，零代码扩展 |
| `.docs/` | 内部文档 | 架构、数据库、CLI、UML、CWD 布局等参考文档 |
| `.github/workflows/` | CI/CD | test.yml / quality.yml / release.yml |
| `.data/` | 运行时数据 | `memory.db` (SQLite) + `haven.pid` (守护进程) |
| `.claude/` | Claude Code 元数据 | memory/ plans/ worktrees/ 由 Claude Code 管理 |
| `dist/` | 构建产物 | `.whl` + `.tar.gz` |
| `htmlcov/` | 覆盖率报告 | `pytest --cov` HTML 输出 |

## 配置文件

| 文件 | 格式 | 职责 |
|------|------|------|
| `pyproject.toml` | TOML | 项目元数据、依赖、Ruff/Mypy/Pytest 配置 |
| `haven.yaml` | YAML | 用户配置覆盖 (deep-merge 到 `app.yaml`) |
| `mcp.json` | JSON | MCP 服务器声明 (标准 `mcpServers` 格式) |
| `uv.lock` | TOML | uv 依赖锁定文件 |
| `Makefile` | Make | `lint` / `format` / `typecheck` / `test` / `cov` / `check` |
| `.pre-commit-config.yaml` | YAML | ruff + mypy pre-commit hooks |
| `.coveragerc` | INI | 覆盖率排除规则 |
| `.gitignore` | — | Git 忽略规则 |

## 根目录文档

| 文件 | 面向 | 内容 |
|------|------|------|
| `README.md` | 外部 | 项目简介 + CI badges |
| `CLAUDE.md` | Claude Code | 开发指南、架构、行为准则 |

内部审计/分析文档位于 `.docs/` 目录下。详见 `.docs/` 内文件列表。

## 约定

- **用户扩展文件**统一放在 CWD 下：`skills/`、`mcp.json`、`haven.yaml`、`models.yaml`
- **运行时数据**写入 `.data/`，不提交到 git
- **构建产物**在 `dist/`，由 `uv build` 生成
- **IDE 配置**在 `.idea/` (PyCharm)，不提交
