"""WorkflowRegistry — 工作流注册与发现。

PlannerAgent 通过此注册表获取可用工作流列表，
供 LLM 规划和选择。
"""

from __future__ import annotations

from haven.core.registry import Registry


class WorkflowRegistry(Registry):
    """工作流注册表。

    用法::

        @WorkflowRegistry.register("dev_flow")
        def create_dev_workflow() -> WorkflowGraph:
            ...

        # 供 Planner LLM 选择
        menu = WorkflowRegistry.get_selection_context()
    """

    _label = "Workflow"

    @classmethod
    def get_selection_context(cls) -> str:
        """格式化可用工作流列表（供 Planner LLM 选择）。"""
        if not cls._items:
            return "(无可用工作流)"

        lines: list[str] = []
        for name, factory in cls._items.items():
            desc = ""
            use_cases = ""
            step_count = "?"
            if hasattr(factory, "description"):
                desc = factory.description
            elif hasattr(factory, "__doc__") and factory.__doc__:
                desc = factory.__doc__.strip().split("\n")[0]
            if hasattr(factory, "use_cases"):
                use_cases = factory.use_cases
            if hasattr(factory, "step_count"):
                step_count = str(factory.step_count)

            lines.append(f"- name: {name}")
            lines.append(f"  description: {desc}")
            if use_cases:
                lines.append(f"  use_cases: {use_cases}")
            lines.append(f"  steps: {step_count}")

        return "\n".join(lines)

    @classmethod
    def build(cls, name: str) -> Any:
        """调用注册的 factory 函数，返回 WorkflowGraph 实例。"""
        factory = cls.get(name)
        return factory()
