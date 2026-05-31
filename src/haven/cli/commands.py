"""Slash-command handlers for the Haven CLI REPL.

All handlers return ``(output: str, should_exit: bool)``.
"""

from __future__ import annotations

from typing import Any


def handle(agent: Any, text: str) -> tuple[str, bool] | None:
    mcp_manager = getattr(agent, "mcp_manager", None)
    """Parse and dispatch a slash command.

    Returns ``(output, should_exit)``, or ``None`` if *text* is not a command.
    """
    if not text.startswith("/"):
        return None

    parts = text.strip().split()
    cmd = parts[0].lower()

    if cmd in ("/exit", "/quit", "/q"):
        return ("再见.", True)

    if cmd == "/help":
        return (_cmd_help(), False)

    if cmd == "/skills":
        return (_cmd_skills(agent), False)

    if cmd == "/clear":
        return (_cmd_clear(agent), False)

    if cmd == "/model":
        return (_cmd_model(agent, parts), False)

    if cmd == "/models":
        return (_cmd_models(agent), False)

    if cmd == "/mcp":
        return (_cmd_mcp(mcp_manager), False)

    if cmd == "/tools":
        return (_cmd_tools(agent), False)

    return (f"未知命令: {cmd}  (输入 /help 查看帮助)", False)


# ------------------------------------------------------------------
# individual handlers
# ------------------------------------------------------------------

def _cmd_help() -> str:
    return (
        "命令列表:\n"
        "  /help       显示帮助\n"
        "  /models     列出可用模型\n"
        "  /model      显示当前模型  |  /model <名称> 切换模型\n"
        "  /skills     列出已加载的 skill\n"
        "  /tools      列出可用工具 (含 MCP)\n"
        "  /mcp        显示 MCP 服务器状态\n"
        "  /clear      清空对话历史\n"
        "  /exit, /q   退出\n"
        "\n输入任何其他内容将发送给 agent。"
    )


def _cmd_skills(agent: Any) -> str:
    # aggregate skills from orchestrator sub-agents when applicable
    sub_agents = getattr(agent, "sub_agents", None)

    if sub_agents:
        lines = ["Agents 及已加载 Skill:"]
        for name, sub in sorted(sub_agents.items()):
            defaults = [s for s in sub.skills.values() if s.default]
            ondemands = [s for s in sub.skills.values() if not s.default]
            lines.append(f"  [{name}] — {len(sub.skills)} skill(s)")
            if defaults:
                for s in defaults:
                    lines.append(f"    [默认] {s.name} — {s.description}")
            if ondemands:
                for s in ondemands:
                    lines.append(f"    [按需] {s.name} — {s.description}")
        return "\n".join(lines)

    if not agent.skills:
        return "(未加载任何 skill)"

    defaults = [s for s in agent.skills.values() if s.default]
    ondemands = [s for s in agent.skills.values() if not s.default]
    lines = [f"已加载 {len(agent.skills)} 个 skill:"]
    if defaults:
        lines.append("  [默认]")
        for s in defaults:
            lines.append(f"    {s.name} — {s.description}")
    if ondemands:
        lines.append("  [按需]")
        for s in ondemands:
            lines.append(f"    {s.name} — {s.description}")
    return "\n".join(lines)


def _cmd_clear(agent: Any) -> str:
    agent.reset()
    return "对话历史已清空。"


def _cmd_model(agent: Any, parts: list[str]) -> str:
    if len(parts) > 1:
        target = parts[1]
        valid = _list_model_names()
        match = None
        for name in valid:
            if name == target:
                match = name
                break
            if target in name:
                match = name
                break
        if match:
            try:
                # switch model on orchestrator and all sub-agents
                actual = agent.switch_model(match)
                for sub in getattr(agent, "sub_agents", {}).values():
                    try:
                        sub.switch_model(match)
                    except Exception:
                        pass
                return f"已切换到模型: {actual}"
            except Exception as exc:
                return f"切换失败: {exc}"
        else:
            return f"未知模型: {target}\n可用模型: {', '.join(valid)}"

    from haven.config import get_default_model
    current = getattr(agent.llm, "model_name", None) or get_default_model()
    return f"当前模型: {current}  (使用 /model <名称> 切换, /models 查看列表)"


def _cmd_models(agent: Any) -> str:
    from haven.config import get_default_model
    valid = _list_model_names()
    current = getattr(agent.llm, "model_name", None) or get_default_model()
    lines = ["可用模型:"]
    for name in valid:
        mark = " ← 当前" if name == current else ""
        lines.append(f"  {name}{mark}")
    return "\n".join(lines)


def _cmd_mcp(mcp_manager: Any) -> str:
    if mcp_manager is None:
        return "MCP 未启用或未配置。"
    lines = [
        "MCP 服务器状态:",
        mcp_manager.get_status_summary(),
        f"可用工具: {len(mcp_manager.tools)}",
    ]
    return "\n".join(lines)


def _cmd_tools(agent: Any) -> str:
    sub_agents = getattr(agent, "sub_agents", None)

    if sub_agents:
        all_tools: dict[str, tuple[str, str]] = {}  # name → (desc, agent_name)
        for a_name, sub in sorted(sub_agents.items()):
            for t_name, tool in sorted(sub.tools.items()):
                desc = getattr(tool, "description", "") or ""
                if t_name not in all_tools:
                    all_tools[t_name] = (desc, a_name)
        lines = [f"已加载 {len(all_tools)} 个工具 (来自 {len(sub_agents)} 个 Agent):"]
        for t_name, (desc, a_name) in sorted(all_tools.items()):
            if desc:
                lines.append(f"  {t_name} [{a_name}] — {desc}")
            else:
                lines.append(f"  {t_name} [{a_name}]")
        return "\n".join(lines)

    if not agent.tools:
        return "(未加载任何工具)"
    lines = [f"已加载 {len(agent.tools)} 个工具:"]
    for name, tool in sorted(agent.tools.items()):
        desc = getattr(tool, "description", "") or ""
        if desc:
            lines.append(f"  {name} — {desc}")
        else:
            lines.append(f"  {name}")
    return "\n".join(lines)


def _list_model_names() -> list[str]:
    from haven.config import load_models_config
    return list(load_models_config().keys())
