"""ChatSession — 可复用的单轮对话处理器。

封装 system-prompt 组装、记忆和持久化。
CLI REPL 和 socket 通道共用。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from haven.core.base_agent import BaseAgent

logger = logging.getLogger("haven.session")


class ChatSession:
    """通过共享 agent 处理一轮对话。

    构建完整消息列表（system prompt + skills + 历史 + 用户输入），
    委托 agent 调用 LLM，然后更新记忆并持久化。

    用法::

        session = ChatSession(agent)
        response = await session.process("你好")
        # 可选：触发后台事实提取
        await agent.extract_facts_async()
    """

    def __init__(self, agent: BaseAgent) -> None:
        self.agent = agent

    async def process(
        self,
        user_input: str,
        history: list[Any] | None = None,
        persist: bool = True,
    ) -> str:
        """处理单条用户消息并返回 agent 的响应。

        Args:
            user_input: 用户消息文本。
            history: 可选的对话历史覆盖（用于 socket 通道中的按连接会话隔离）。
                     为 ``None`` 时使用 ``agent.memory.get_history()``。
            persist: 是否将本轮对话保存到长期记忆。
        """
        on_demand = self.agent.match_skills(user_input)

        try:
            content = await self.agent.run(
                user_input,
                history=history or self.agent.memory.get_history(),
                on_demand_skills=on_demand,
                use_rag=True,
            )
        except Exception as exc:
            logger.warning("ChatSession LLM error: %s", exc)
            content = f"[错误] {exc}"

        self._update_memory(user_input, content, history)

        if persist:
            self.agent.save_turn(user_input, content)

        return content

    def _update_memory(
        self, user_input: str, content: str, history: list[Any] | None
    ) -> None:
        """更新短期记忆（仅当使用 agent 自身历史时）。"""
        if history is None:
            self.agent.memory.add_message(HumanMessage(content=user_input))
            self.agent.memory.add_message(AIMessage(content=content))

    async def process_no_persist(self, user_input: str) -> str:
        """处理消息但不持久化到长期记忆。"""
        return await self.process(user_input, persist=False)
