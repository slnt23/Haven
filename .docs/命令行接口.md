# Haven CLI

## 概述

CLI 入口为 `haven` 命令，支持交互式 REPL、单轮问答、守护进程三种运行模式。

## CLI 目录文件

```
src/haven/cli/
├── __init__.py      # 空
├── main.py          # CLI 入口，命令解析与分发
├── app.py           # HavenApp REPL 主循环，V1/V2 兼容
├── commands.py      # REPL 内 / 斜杠命令处理器
└── display.py       # 界面辅助：banner、加载动画、提示符
```

### `main.py` — CLI 入口

`haven` 命令的唯一入口，解析 `sys.argv` 并分发到三种运行模式：

| 模式 | 命令 | 函数 | 说明 |
|------|------|------|------|
| 管理命令 | `haven stop` | `_cmd_stop()` | 停止守护进程，清理 PID 文件 |
| 管理命令 | `haven status` | `_cmd_status()` | 查看守护进程运行状态 |
| 管理命令 | `haven restart` | `_cmd_restart()` | 停止后重新启动守护进程 |
| 守护进程 | `haven serve` | `_run_daemon()` | 启动 HavenDaemon，多通道常驻 |
| 单轮对话 | `haven --task "..."` | `HavenApp.start(greeting_task=...)` | 处理一次请求后退出 |
| 交互式 | `haven`（无参数） | `HavenApp.start()` | 进入 REPL 循环 |

管理命令通过 `_MANAGEMENT_COMMANDS` 字典注册，守护进程 PID 文件由 `core/pidfile.py` 管理。

### `app.py` — REPL 主循环

`HavenApp` 类负责交互式 REPL，支持两种后端：

| 后端 | 标志 | Agent 类型 | 处理方式 |
|------|------|-----------|---------|
| V2（默认） | `use_v2=True` | `PlannerAgent` | `agent.execute(user_input)` |
| V1（兼容） | `use_v2=False` | `OrchestratorAgent` | `ChatSession.process(user_input)` |

`_create_agent()` 优先尝试 V2 工厂（`haven.runtime.factory.create_agent`），失败时回退 V1（`haven.agents.factory.create_agent`）。

REPL 循环流程：打印 banner → 等待用户输入 → 命令或对话 → 后台事实提取 → 循环。

### `commands.py` — 斜杠命令

以 `/` 开头的输入被识别为命令，否则发送给 agent 处理。

`handle()` 函数统一解析并分发，自动检测 V1/V2 agent 类型适配不同 API。

| 命令 | 处理器 | 说明 |
|------|--------|------|
| `/help` | `_cmd_help()` | 显示所有可用命令 |
| `/models` | `_cmd_models()` | 列出可用模型，标注当前 |
| `/model [name]` | `_cmd_model()` | 无参数显示当前模型，带参数切换 |
| `/skills` | `_cmd_skills()` | 列出已加载的 skill（人格 + 领域） |
| `/tools` | `_cmd_tools()` | 列出可用工具及来源 |
| `/mcp` | `_cmd_mcp()` | MCP 服务器连接状态 |
| `/clear` | `_cmd_clear()` | 清空对话历史 |
| `/memory` | `_cmd_memory()` | 记忆系统状态（V2 only） |
| `/workflows` | `_cmd_workflows()` | 列出可用工作流（V2 only） |
| `/plan` | `_cmd_plan()` | 显示最近执行计划（V2 only） |
| `/exit`, `/quit`, `/q` | — | 退出 |

辅助函数：
- `_is_v2(agent)` — 检测是否为 V2 PlannerAgent
- `_get_runtime(agent)` — 从 V2 agent 获取 AgentRuntime
- `_list_model_names()` — 列出 models.yaml 中的模型名称

### `display.py` — 界面辅助

| 函数 | 说明 |
|------|------|
| `print_line(*args)` | 向 stdout 写入一行并立即刷新 |
| `show_loading(stop_event)` | 异步动画加载指示（"思考中..."） |
| `prompt_user()` | 读取 stdin 一行输入 |
| `print_banner(agent)` | 打印启动 banner，自动检测 V1/V2 格式 |

## REPL 完整命令参考

```
/help       显示帮助
/models     列出可用模型
/model      显示当前模型  |  /model <名称> 切换模型
/skills     列出已加载的 skill
/tools      列出可用工具
/mcp        显示 MCP 服务器状态
/memory     显示记忆系统状态       [V2]
/workflows  列出可用工作流         [V2]
/plan       显示最近一次执行计划   [V2]
/clear      清空对话历史
/exit, /q   退出
```

## 外部命令参考

```
haven                  # 交互式 REPL
haven --task "问题"     # 单轮问答
haven serve            # 启动守护进程（多通道：TCP + 邮件 + 飞书）
haven stop             # 停止守护进程
haven status           # 查看守护进程状态
haven restart          # 重启守护进程
```
