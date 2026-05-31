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
    """将用户请求路由至最合适的 specialist agent。

    1. 轻量级 LLM 调用分类用户意图。
    2. 路由到匹配的 specialist。
    3. 返回 specialist 的响应。

    分类模糊时回退到 companion agent。
    """

    def __init__(self, name: str = "orchestrator", llm: Any = None) -> None:
        super().__init__(name, llm)
        self.sub_agents: dict[str, BaseAgent] = {}
        self._default_agent = "companion"

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        """向编排器注册子 agent。"""
        self.sub_agents[name] = agent

    # ------------------------------------------------------------------
    # skill 聚合
    # ------------------------------------------------------------------

    def match_skills(self, task: str) -> list["BaseSkill"]:
        """聚合全部子 agent 的按需 skill 匹配结果。"""
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
        logger.info("意图: %s → 路由到 %s", intent, ROUTE_MAP.get(intent, self._default_agent))

        agent_name = ROUTE_MAP.get(intent, self._default_agent)
        agent = self.sub_agents.get(agent_name)

        if agent is None:
            agent = self.sub_agents.get(self._default_agent)
            logger.warning("Agent '%s' 未找到，回退到 '%s'", agent_name, self._default_agent)

        if agent is None:
            return "[错误] 没有可用的 Agent"

        return await agent.run(task, **kwargs)

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        msg = messages[-1]
        return msg

    def reset(self) -> None:
        """清空编排器及全部子 agent 的记忆。"""
        super().reset()
        for agent in self.sub_agents.values():
            agent.reset()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _classify_intent(self, task: str) -> str:
        """用 LLM 将用户意图分类到对应类别。"""
        if self.llm is None:
            self._init_llm()

        prompt = CLASSIFY_PROMPT.format(task=task)

        try:
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            raw = (response.content if hasattr(response, "content") else str(response)).strip().lower()
        except Exception as exc:
            logger.warning("意图分类失败: %s，回退到 chat", exc)
            return "chat"

        for category in ("chat", "code", "medical", "practical"):
            if category in raw:
                return category

        logger.debug("无法识别的分类输出: %r，回退到 chat", raw)
        return "chat"
