from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from forest.config import settings, get_model_config, get_default_model
from forest.core.memory import AgentMemory
from forest.skills.loader import SkillLoader

if TYPE_CHECKING:
    from forest.core.rag import RAGEngine
    from forest.skills.base_skill import BaseSkill


class BaseAgent(ABC):
    def __init__(self, name: str, llm: BaseChatModel | None = None):
        self.name = name
        self.llm = llm
        self.tools: dict[str, Any] = {}
        self.skills: dict[str, "BaseSkill"] = {}
        self.memory = AgentMemory()
        self.rag: RAGEngine | None = None
        self.max_iterations = settings.agent_max_iterations
        self.max_execution_time = settings.agent_max_execution_time

    def register_tool(self, name: str, tool: Any) -> None:
        self.tools[name] = tool

    def enable_skill(self, skill: "BaseSkill") -> None:
        """Load a skill instance into this agent."""
        self.skills[skill.name] = skill

    def load_skills_from_dir(self, directory: str | None = None) -> int:
        """Auto-discover and load all ``.md`` skill files from *directory*.

        If *directory* is not given, ``settings.skill_directory`` is resolved
        relative to ``settings.project_root``.

        Returns the number of skills loaded.
        """

        if directory is None:
            directory = str(settings.project_root / settings.skill_directory)

        loaded = SkillLoader.load_from_dir(directory)
        for skill in loaded:
            self.skills[skill.name] = skill
        return len(loaded)

    def disable_skill(self, name: str) -> None:
        self.skills.pop(name, None)

    def enable_rag(self, rag: "RAGEngine") -> None:
        self.rag = rag

    def _init_llm(self, model_name: str | None = None) -> BaseChatModel:
        if self.llm is not None:
            return self.llm

        model_name = model_name or get_default_model()
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
        """Assemble system prompt from default skills only."""
        parts: list[str] = []
        for skill in self.skills.values():
            if skill.default and skill.prompt_extension:
                parts.append(skill.prompt_extension)
        return "\n".join(parts) if parts else ""

    def match_skills(self, task: str) -> list["BaseSkill"]:
        """Return on-demand (non-default) skills whose trigger keywords match *task*."""
        matched: list["BaseSkill"] = []
        for skill in self.skills.values():
            if skill.default:
                continue
            if skill.matches(task):
                matched.append(skill)
        return matched

    async def _invoke_llm(
            self,
            task: str,
            system_prompt: str = "",
            use_rag: bool = True) -> str:

        if self.llm is None:
            self._init_llm()

        messages: list[BaseMessage] = []
        full_system = self._build_system_prompt()
        if system_prompt:
            full_system = f"{full_system}\n{system_prompt}" if full_system else system_prompt

        if use_rag and self.rag is not None and self.rag.doc_count > 0:
            retrieved = self.rag.retrieve(task, top_k=settings.rag_top_k)
            if retrieved:
                rag_context = self.rag.format_context(retrieved)
                full_system = (
                    f"{full_system}\n\n"
                    f"[参考知识 — 请优先基于以下资料回答]\n{rag_context}"
                )

        if full_system:
            messages.append(SystemMessage(content=full_system))
        messages.append(HumanMessage(content=task))

        response = await self.llm.ainvoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content

    @abstractmethod
    async def run(self, task: str, **kwargs: Any) -> str:
        ...

    @abstractmethod
    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        ...

    def reset(self) -> None:
        self.memory.clear()
