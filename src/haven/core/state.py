"""RuntimeState — AgentRuntime 的会话级状态容器。

轻量 dataclass，可序列化，在节点间传递时可 snapshot。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuntimeState:
    """单次会话的运行时状态。

    Planner 通过修改此状态来控制 Runtime 行为：
    ``active_skills`` 和 ``active_tools`` 决定当前轮次的 prompt 和可用工具。
    """

    session_id: str = "default"
    entity_name: str = "user"
    channel: str = "cli"

    # Planner 注入
    active_skills: list[str] = field(default_factory=list)
    active_tools: list[str] = field(default_factory=list)

    # 执行追踪
    turn_count: int = 0
    current_node: str = ""  # workflow 当前节点名（单步执行时为空）

    # 临时上下文（跨步骤传递，不持久化）
    context: dict[str, str] = field(default_factory=dict)

    # 最近一次 Planner 的 plan
    last_plan: dict | None = None

    def reset_turn(self) -> None:
        """清空当前轮次的临时状态（保留会话标识）。"""
        self.active_skills = []
        self.active_tools = []
        self.current_node = ""
        self.context = {}

    def snapshot(self) -> dict:
        """返回可序列化的状态快照。"""
        return {
            "session_id": self.session_id,
            "entity_name": self.entity_name,
            "turn_count": self.turn_count,
            "current_node": self.current_node,
            "active_skills": list(self.active_skills),
            "active_tools": list(self.active_tools),
            "context": dict(self.context),
        }
