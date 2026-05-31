import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from haven.config import settings, get_model_config, get_default_model, find_user_path
from haven.core.memory import AgentMemory
from haven.skills.loader import SkillLoader

if TYPE_CHECKING:
    from haven.core.rag import RAGEngine
    from haven.skills.base_skill import BaseSkill

logger = logging.getLogger("haven.agent")


class BaseAgent(ABC):
    def __init__(self, name: str, llm: BaseChatModel | None = None):
        self.name = name
        self.llm = llm
        self.tools: dict[str, Any] = {}
        self._tool_instances: list[BaseTool] = []
        self.skills: dict[str, "BaseSkill"] = {}
        self.memory = AgentMemory()
        self.rag: RAGEngine | None = None
        self.max_iterations = settings.agent_max_iterations
        self.max_execution_time = settings.agent_max_execution_time

    def register_tool(self, name: str, tool: Any) -> None:
        self.tools[name] = tool

    def register_lc_tool(self, tool: BaseTool) -> None:
        """注册 LangChain ``BaseTool``，供 ``bind_tools()`` 使用。"""
        self._tool_instances.append(tool)
        self.tools[tool.name] = tool

    def register_mcp_tools(self, tools: dict[str, BaseTool]) -> None:
        """注册 MCP 发现的工具。"""
        for name, tool in tools.items():
            self.register_lc_tool(tool)

    def bind_tools_to_llm(self) -> None:
        """对 LLM 执行 ``bind_tools()``（如有已注册工具）。"""
        if self.llm is None:
            self._init_llm()
        if self._tool_instances:
            self.llm = self.llm.bind_tools(self._tool_instances)

    def switch_model(self, model_name: str) -> str:
        """切换到另一模型，如有工具则重新绑定。

        返回实际设置的模型名。若新模型初始化失败，保留原模型不变。
        """
        previous = self.llm
        self.llm = None
        try:
            self._init_llm(model_name=model_name)
            self.bind_tools_to_llm()
        except Exception:
            self.llm = previous
            raise
        return getattr(self.llm, "model_name", model_name)

    def enable_skill(self, skill: "BaseSkill") -> None:
        """将 skill 实例加载到当前 agent。"""
        self.skills[skill.name] = skill

    def load_skills_from_dir(self, directory: str | None = None) -> int:
        """从 *directory* 自动发现并加载所有 ``.md`` skill 文件。

        若未指定 *directory*，则通过 ``find_user_path()`` 解析技能目录。

        返回加载的 skill 数量。
        """

        if directory is None:
            directory = str(find_user_path(settings.skill_directory))

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
        """组装 system prompt：默认 skill + 长期记忆。"""
        parts: list[str] = []
        for skill in self.skills.values():
            if skill.default and skill.prompt_extension:
                parts.append(skill.prompt_extension)

        # 注入当前实体的长期记忆
        ltm = self.memory.get_long_term_context()
        if ltm:
            parts.append(ltm)

        return "\n".join(parts) if parts else ""

    def match_skills(self, task: str) -> list["BaseSkill"]:
        """返回触发关键词匹配 *task* 的按需 skill（非默认 skill）。"""
        matched: list["BaseSkill"] = []
        for skill in self.skills.values():
            if skill.default:
                continue
            if skill.matches(task):
                matched.append(skill)
        return matched

    def _build_rag_context(self, task: str) -> str:
        """构建注入 prompt 的 RAG 上下文。无检索结果时返回空字符串。"""
        if self.rag is None or self.rag.doc_count == 0:
            return ""
        retrieved = self.rag.retrieve(task, top_k=settings.rag_top_k)
        if not retrieved:
            return ""
        return self.rag.format_context(retrieved)

    def _build_messages(
        self, task: str, system_prompt: str = "", use_rag: bool = True,
    ) -> list[BaseMessage]:
        """组装 LLM 调用的消息列表（system + human）。"""
        full_system = self._build_system_prompt()
        if system_prompt:
            full_system = f"{full_system}\n{system_prompt}" if full_system else system_prompt

        if use_rag:
            rag_context = self._build_rag_context(task)
            if rag_context:
                full_system = (
                    f"{full_system}\n\n"
                    f"[参考知识 — 请优先基于以下资料回答]\n{rag_context}"
                )

        messages: list[BaseMessage] = []
        if full_system:
            messages.append(SystemMessage(content=full_system))
        messages.append(HumanMessage(content=task))
        return messages

    async def _invoke_llm(self, messages: list[BaseMessage]) -> str:
        if self.llm is None:
            self._init_llm()
        response = await self.llm.ainvoke(messages)
        return response.content if hasattr(response, "content") else str(response)

    async def _invoke_llm_with_tools(self, messages: list[BaseMessage]) -> str:
        """带工具调用循环的 LLM 调用。

        1. 调用 LLM（可能返回 ``tool_calls``）。
        2. 若有 ``tool_calls``：逐一执行，追加 ``ToolMessage``，循环（受 ``max_iterations`` 限制）。
        3. 返回最终文本响应。
        """
        if self.llm is None:
            self._init_llm()

        iteration = 0
        while iteration < self.max_iterations:
            response = await self.llm.ainvoke(messages)

            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls:
                return response.content if hasattr(response, "content") else str(response)

            messages.append(response)

            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")

                try:
                    result = await self._execute_tool_call(tool_name, tool_args)
                except Exception as exc:
                    result = f"Error executing tool '{tool_name}': {exc}"
                    logger.warning("Tool execution failed: %s — %s", tool_name, exc)

                messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

            iteration += 1

        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)

    async def _execute_tool_call(self, name: str, args: dict[str, Any]) -> str:
        """按名称查找工具并用 *args* 调用。"""
        tool = self.tools.get(name)
        if tool is None:
            return f"Error: tool '{name}' not found. Available: {list(self.tools.keys())}"
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(args)
        elif callable(tool):
            result = tool(**args)
            if asyncio.iscoroutine(result):
                result = await result
        else:
            return f"Error: tool '{name}' is not callable"
        return str(result)

    @abstractmethod
    async def run(self, task: str, **kwargs: Any) -> str:
        ...

    @abstractmethod
    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        ...

    def reset(self) -> None:
        self.memory.clear()

    # ------------------------------------------------------------------
    # 长期记忆
    # ------------------------------------------------------------------

    def save_turn(self, user_input: str, response: str) -> None:
        """将一轮对话持久化到长期存储。"""
        self.memory.save_message("human", user_input)
        self.memory.save_message("ai", response)

    async def extract_facts_async(self) -> None:
        """从最近一轮对话中提取关于当前实体的事实。"""
        if self.llm is None:
            return
        await self.memory.extract_facts(self.llm)
