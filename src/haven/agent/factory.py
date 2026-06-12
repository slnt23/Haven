"""AgentFactory + AgentRegistry —— Agent 创建与管理。

AgentFactory: 从 AppConfig 批量创建 Agent。
AgentRegistry: 运行时 Agent 注册与查询。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver

from haven.agent.base import Agent
from haven.config.schema import AppConfig


class AgentFactory:
    """从 AppConfig 批量创建 Agent。

    根据 haven.yaml 中的 agents 定义创建各专业 Agent。
    每个 Agent 绑定相同的 LLM + tools + checkpointer，
    但拥有独立的 system_prompt（agent_prompt）。

    Usage::

        factory = AgentFactory(config, llm=llm, tools=tools, checkpointer=cp)
        agents = factory.create_all()
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        llm: BaseChatModel,
        tools: list[BaseTool],
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        self._config = config
        self._llm = llm
        self._tools = tools
        self._checkpointer = checkpointer

    def create(self, name: str, *, agent_prompt: str = "") -> Agent:
        """创建单个 Agent。"""
        return Agent(
            name=name,
            llm=self._llm,
            tools=list(self._tools),
            checkpointer=self._checkpointer,
            agent_prompt=agent_prompt,
        )

    def create_all(self) -> dict[str, Agent]:
        """创建所有已定义的 Agent，返回 {name: Agent}。"""
        agents: dict[str, Agent] = {}
        for name, ad in self._config.agents.items():
            agents[name] = Agent(
                name=name,
                llm=self._llm,
                tools=list(self._tools),
                checkpointer=self._checkpointer,
                agent_prompt=ad.prompt,
            )
        return agents


class AgentRegistry:
    """Agent 运行时注册表。

    存储已创建的 Agent，按名称查询。

    Usage::

        registry = AgentRegistry()
        registry.register(agent)
        agent = registry.get("coder")
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not found. Available: {list(self._agents.keys())}")
        return self._agents[name]

    def list_all(self) -> dict[str, Agent]:
        return dict(self._agents)

    def clear(self) -> None:
        self._agents.clear()

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: str) -> bool:
        return name in self._agents
