# Haven

代号：**健健**（出自《灵笼》）— 多智能体交互框架

基于 Python 3.14+、LangChain 与 pydantic-settings 构建。人格与领域能力通过 Markdown 技能文件注入，零代码扩展。

## 快速开始

```bash
cp .env.example .env    # 填入 API Key
uv sync
uv run haven            # 交互式 REPL
```

## 使用

```bash
uv run haven                        # 交互式 REPL
uv run haven --task "你的问题"       # 单轮问答
uv run haven serve                  # 常驻守护进程（TCP + 邮件渠道）
```

REPL 内可用命令：`/help` `/models` `/model <名称>` `/skills` `/tools` `/mcp` `/clear` `/exit`

## 配置

在项目根目录放置用户配置文件（CWD 优先，覆盖包内置默认值）：

| 文件 | 用途 | 包内置默认 |
|------|------|-----------|
| `.env` | API Key、邮箱密码等敏感信息 | — |
| `haven.yaml` | 框架参数（agent、RAG、email、memory 等） | `src/haven/config/app.yaml` |
| `models.yaml` | 自定义/追加 LLM 模型 | `src/haven/config/models.yaml` |
| `skills/` | 自定义 Skill 文件（`.md`，拖入即用） | `src/haven/user/skills/` |
| `mcp/mcp.json` | MCP 服务器配置 | `src/haven/user/mcp/mcp.json` |

优先级：**内置默认 < 用户 YAML < 环境变量**

## 扩展

| 目标 | 方式 | 代码量 |
|------|------|--------|
| 新增领域能力 / 人格 | `skills/` 下创建 `.md` 文件（CWD 优先） | 零代码 |
| 新增模型 | `models.yaml` + `.env` 设 Key | 两行配置 |
| 新增 MCP 服务 | `mcp.json` 添加条目（CWD 优先） | 一段 JSON |
| 新增 Agent / 工具 / 渠道 | 继承对应基类，注册到框架 | 一个文件 |

## 目录

```
├── .env
├── haven.yaml          # 可选：用户配置覆盖（CWD 优先）
├── models.yaml         # 可选：用户模型定义（CWD 优先）
├── skills/             # 可选：用户 Skill 文件（CWD 优先）
├── mcp.json            # 可选：用户 MCP 配置（CWD 优先）
├── src/haven/
│   ├── agents/         # Agent 实现
│   ├── cli/            # CLI 入口 & REPL
│   ├── config/         # 配置层（app.yaml + models.yaml + settings）
│   ├── core/           # 核心抽象（Agent / Memory / RAG）
│   ├── mcp/            # MCP 协议集成
│   ├── services/       # 守护进程 & 渠道
│   ├── skills/         # Skill 加载器
│   ├── tools/          # 内置工具
│   ├── user/           # 用户可扩展内容（Skills、mcp.json 等包内置默认）
│   └── workflows/      # 工作流组合
├── docs/
│   └── architecture.md # 详细架构文档
└── tests/
```

## 文档

完整架构、配置详解、扩展指南见 **[docs/architecture.md](docs/architecture.md)**。

## 开发

```bash
uv sync --group dev
uv run pytest
```

## 许可证

MIT
