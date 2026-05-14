from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from forest.config import settings, get_model_config
from forest.core.memory import AgentMemory


class BaseAgent(ABC):
    def __init__(self, name: str, llm: BaseChatModel | None = None):
        self.name = name
        self.llm = llm
        self.tools: dict[str, Any] = {}
        self.memory = AgentMemory()
        self.max_iterations = settings.agent_max_iterations
        self.max_execution_time = settings.agent_max_execution_time

        self._role: str = ""
        self._goal: str = ""
        self._backstory: str = ""

    def register_tool(self, name: str, tool: Any) -> None:
        self.tools[name] = tool

    def _init_llm(self, model_name: str | None = None) -> BaseChatModel:
        if self.llm is not None:
            return self.llm

        model_name = model_name or settings.agent_default_model
        cfg = get_model_config(model_name)
        provider = cfg["provider"]

        if provider == "deepseek":
            from langchain_deepseek import ChatDeepSeek
            self.llm = ChatDeepSeek(
                model=cfg["name"],
                api_key=cfg["api_key"],
                api_base=cfg["base_url"],
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
            )
        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(
                model=cfg["name"],
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

        return self.llm

    def _build_system_prompt(self) -> str:
        parts = []
        if self._role:
            parts.append(f"你是 {self._role}。")
        if self._goal:
            parts.append(f"你的目标是：{self._goal}")
        if self._backstory:
            parts.append(f"背景：{self._backstory}")
        return "\n".join(parts) if parts else ""

    async def _invoke_llm(self, task: str, system_prompt: str = "") -> str:
        if self.llm is None:
            self._init_llm()

        messages: list[BaseMessage] = []
        full_system = self._build_system_prompt()
        if system_prompt:
            full_system = f"{full_system}\n{system_prompt}" if full_system else system_prompt
        if full_system:
            messages.append(SystemMessage(content=full_system))
        messages.append(HumanMessage(content=task))

        response = await self.llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content

    def _load_agent_config(self) -> None:
        from forest.config import load_agents_config
        agents_cfg = load_agents_config()
        if self.name in agents_cfg:
            agent_cfg = agents_cfg[self.name]
            self._role = str(agent_cfg.get("role", ""))
            self._goal = str(agent_cfg.get("goal", ""))
            self._backstory = str(agent_cfg.get("backstory", ""))
            model_name = str(agent_cfg.get("llm_model", ""))
            if model_name and self.llm is None:
                self._init_llm(model_name)

    @abstractmethod
    async def run(self, task: str, **kwargs: Any) -> str:
        ...

    @abstractmethod
    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        ...

    def reset(self) -> None:
        self.memory.clear()
