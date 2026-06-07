"""RuntimeState — 单次会话的运行时状态容器。

Planner 通过修改此状态来控制 Runtime 行为：
``active_skills`` 和 ``active_tools`` 决定当前轮次注入的 prompt 和可用工具。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuntimeState:
    """会话级状态，贯穿单次对话生命周期。

    字段：
        session_id: 会话标识，用于 LangGraph checkpointer 的 thread_id。
        entity_name: 对话实体名（用户或渠道标识）。
        channel: 当前交互渠道（cli / tcp / feishu 等）。
        active_skills: 当前轮次激活的 Skill 名称列表。
        active_tools: 当前轮次激活的工具名称列表。
        turn_count: 累计对话轮次。
        current_node: 工作流当前所在节点名。
        context: Planner 或 Agent 写入的临时上下文。
        last_plan: 最近一次 ExecutionPlan 的序列化结果。
    """

    session_id: str = "default"
    entity_name: str = "user"
    channel: str = "cli"

    active_skills: list[str] = field(default_factory=list)
    active_tools: list[str] = field(default_factory=list)

    turn_count: int = 0
    current_node: str = ""
    context: dict[str, str] = field(default_factory=dict)
    last_plan: dict | None = None

    def reset_turn(self) -> None:
        """清空当前轮次的临时状态，保留会话标识和计数器。"""
        self.active_skills = []
        self.active_tools = []
        self.current_node = ""
        self.context = {}
