"""Haven 专业 Agent 定义。

每个 Agent 是 LangGraph ReAct Agent 的轻量包装：
  - 工具在创建时一次性绑定
  - LLM 通过 Function Calling 自行选择调用哪个工具
  - Agent 不做任何 Tool 解析/选择/推理
"""

from haven.runtime.agents.base import BaseAgent

__all__ = ["BaseAgent"]
