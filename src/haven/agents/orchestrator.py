"""OrchestratorAgent — 分类用户意图并路由到最合适的 specialist。"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage

from haven.core.base_agent import BaseAgent

if TYPE_CHECKING:
    from haven.skills.base_skill import BaseSkill

logger = logging.getLogger("haven.orchestrator")

CLASSIFY_PROMPT = """\
Classify the user's request into exactly ONE category. Reply with only the category name, nothing else.

Categories and their scope:
- code: programming, debugging, code review, software architecture, git, deployment, algorithms
- medical: health questions, symptoms, medication, first aid, medical knowledge, wellness advice
- practical: tech troubleshooting, hardware, electronics, DIY, home repair, tools, productivity, networking, system optimization
- chat: casual conversation, companionship, daily chat, small talk, emotional support, general questions

Examples:
"写一个排序算法" → code
"头疼怎么办" → medical
"路由器连不上网" → practical
"今天心情不好" → chat
"Python 的装饰器怎么用" → code
"推荐一把电钻" → practical
"感冒吃什么药" → medical
"讲个笑话" → chat

User request: {task}

Category:"""

ROUTE_MAP: dict[str, str] = {
    "code": "coder",
    "medical": "medical",
    "practical": "practical",
    "chat": "companion",
}


class OrchestratorAgent(BaseAgent):
    """Routes user requests to the most suitable specialist agent.

    1. Classify user intent with a lightweight LLM call.
    2. Route to the matching specialist.
    3. Return the specialist's response.

    Falls back to the companion agent when classification is ambiguous.
    """

    def __init__(self, name: str = "orchestrator", llm: Any = None) -> None:
        super().__init__(name, llm)
        self.sub_agents: dict[str, BaseAgent] = {}
        self._default_agent = "companion"

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        """Register a sub-agent with the orchestrator."""
        self.sub_agents[name] = agent

    # ------------------------------------------------------------------
    # skill 聚合
    # ------------------------------------------------------------------

    def match_skills(self, task: str) -> list["BaseSkill"]:
        """Aggregate on-demand skill matches from all sub-agents."""
        seen: set[str] = set()
        matched: list["BaseSkill"] = []
        for agent in self.sub_agents.values():
            for skill in agent.match_skills(task):
                if skill.name not in seen:
                    seen.add(skill.name)
                    matched.append(skill)
        return matched

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def run(self, task: str, **kwargs: Any) -> str:
        intent = await self._classify_intent(task)
        logger.info("Intent: %s → routing to %s", intent, ROUTE_MAP.get(intent, self._default_agent))

        agent_name = ROUTE_MAP.get(intent, self._default_agent)
        agent = self.sub_agents.get(agent_name)

        if agent is None:
            agent = self.sub_agents.get(self._default_agent)
            logger.warning("Agent '%s' not found, falling back to '%s'", agent_name, self._default_agent)

        if agent is None:
            return "[错误] 没有可用的 Agent"

        return await agent.run(task, **kwargs)

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        msg = messages[-1]
        return msg

    def reset(self) -> None:
        """Clear memory for the orchestrator and all sub-agents."""
        super().reset()
        for agent in self.sub_agents.values():
            agent.reset()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _classify_intent(self, task: str) -> str:
        """Use LLM to classify the user's intent into a category."""
        if self.llm is None:
            self._init_llm()

        prompt = CLASSIFY_PROMPT.format(task=task)

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            raw = (response.content if hasattr(response, "content") else str(response)).strip().lower()
        except Exception as exc:
            logger.warning("Intent classification failed: %s, defaulting to chat", exc)
            return "chat"

        for category in ("chat", "code", "medical", "practical"):
            if category in raw:
                return category

        logger.debug("Unrecognized classification output: %r, defaulting to chat", raw)
        return "chat"
