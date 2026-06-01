"""AgentRuntime — V2 纯执行引擎。

职责范围（仅 5 项）：
  1. LLM     — 模型初始化、切换、bind_tools
  2. Tool    — 工具注册/绑定/执行调度
  3. Memory  — 短期消息窗口 + 长期事实存储
  4. State   — 会话状态
  5. Context — 上下文收集与组装（委托 ContextManager）

明确排除：
  - 不分类用户意图（→ PlannerAgent）
  - 不决定激活哪些 skill（→ PlannerAgent）
  - 不含任何硬编码人格 prompt（→ Skills）
  - 不直接读取 MemoryManager / SkillRegistry / Workflow（→ ContextManager）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from haven.config import settings
from haven.core.context import ContextManager
from haven.core.llm import bind_tools, create_llm
from haven.core.memory import AgentMemory
from haven.core.prompt import PromptBuilder
from haven.core.retry import retry_async
from haven.core.state import RuntimeState

logger = logging.getLogger("haven.runtime")


class AgentRuntime:
    """纯执行引擎。组合 LLM + Tool + Memory + State + Prompt。

    用法::

        runtime = AgentRuntime()
        runtime.init_llm()
        runtime.register_tool(some_tool)
        runtime.bind_tools_to_llm()

        ctx = runtime.memory.get_long_term_context()
        system = runtime.prompt_builder.build(
            personality_skills=[haven_skill],
            domain_skills=[coder_skill],
            memory_context=ctx,
        )
        result = await runtime.run("帮我写代码")
    """

    def __init__(self, name: str = "runtime"):
        self.name = name

        # -- LLM --
        self.llm: BaseChatModel | None = None

        # -- Tools --
        self._tools: dict[str, BaseTool] = {}  # 全部已注册工具
        self._active_tools: list[BaseTool] = []  # 当前激活（已 bind 到 LLM）

        # -- Memory --
        self.memory = AgentMemory()

        # -- State --
        self.state = RuntimeState()

        # -- Prompt --
        self.prompt_builder = PromptBuilder()

        # -- Context --
        self.context_manager = ContextManager(memory=self.memory)

        # -- Cancellation --
        self._exec_ctx: Any = None

        # -- Config --
        self.max_iterations = settings.agent_max_iterations

    # ==================================================================
    # LLM
    # ==================================================================

    def init_llm(self, model_name: str | None = None) -> BaseChatModel:
        """延迟初始化 LLM。已初始化时直接返回。"""
        if self.llm is not None:
            return self.llm
        self.llm = create_llm(model_name)
        return self.llm

    def switch_model(self, model_name: str) -> str:
        """切换到另一模型，已激活的工具自动重新绑定。"""
        self.llm = create_llm(model_name)
        self.bind_tools_to_llm()
        return getattr(self.llm, "model_name", model_name)

    # ==================================================================
    # Tool
    # ==================================================================

    def register_tool(self, tool: BaseTool) -> None:
        """注册一个 LangChain BaseTool。"""
        self._tools[tool.name] = tool

    def register_tools(self, tools: dict[str, BaseTool]) -> None:
        """批量注册工具。MCP 工具通过此方法注入。"""
        for name, tool in tools.items():
            self._tools[name] = tool

    def activate_tools(self, names: list[str]) -> None:
        """激活指定工具子集。调用后需执行 ``bind_tools_to_llm()``。"""
        self._active_tools = [self._tools[n] for n in names if n in self._tools]

    def activate_all_tools(self) -> None:
        """激活全部已注册工具。"""
        self._active_tools = list(self._tools.values())

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def bind_tools_to_llm(self) -> None:
        """将当前激活的工具绑定到 LLM。"""
        if self.llm is None:
            self.init_llm()
        if self._active_tools:
            self.llm = bind_tools(self.llm, self._active_tools)

    def resolve_tools(
        self,
        skill_names: list[str],
        *,
        permissions: list[str] | None = None,
    ) -> list[BaseTool]:
        """通过 ToolResolver 根据 skill 列表动态解析工具。

        委托给 ToolResolver，支持多级匹配（名称 → 标签 → 类别 → 能力）。
        解析后的工具自动注册到 self._active_tools。

        Args:
            skill_names: skill 名列表。
            permissions: 授予的权限。

        Returns:
            解析后的 BaseTool 列表。
        """
        if not hasattr(self, "_tool_resolver") or self._tool_resolver is None:
            return self._active_tools

        result = self._tool_resolver.resolve(
            skill_names,
            channel=getattr(self.state, "channel", "cli"),
            permissions=permissions,
        )
        if result.warnings:
            for w in result.warnings:
                logger.warning("ToolResolver: %s", w)

        self._active_tools = list(result.tools)
        return self._active_tools

    # ==================================================================
    # Prompt
    # ==================================================================

    def build_system_prompt(
        self,
        personality_skills: list[Any] | None = None,
        domain_skills: list[Any] | None = None,
        use_memory: bool = True,
        **kwargs: Any,
    ) -> str:
        """统一组装 system prompt。委托 ContextManager 收集，PromptBuilder 格式化。

        Args:
            personality_skills: default=true 的人格 skill 列表。
            domain_skills: Planner 激活的领域 skill 列表。
            use_memory: 是否注入长期记忆上下文。
            **kwargs: 透传至 ContextManager.build()（rag_context, workflow_state, tool_results）。

        Returns:
            组装好的 system prompt 字符串。
        """
        bundle = self.context_manager.build(
            personality_skills=personality_skills,
            domain_skills=domain_skills,
            use_memory=use_memory,
            **kwargs,
        )
        return self.prompt_builder.build(bundle)

    # ==================================================================
    # Messages
    # ==================================================================

    def build_messages(
        self,
        task: str,
        *,
        system_prompt: str = "",
        history: list[BaseMessage] | None = None,
    ) -> list[BaseMessage]:
        """组装 LLM 调用的完整消息列表。

        RAG 上下文不再在此方法处理——由 ContextManager 统一注入 system_prompt。

        Args:
            task: 用户任务/输入文本。
            system_prompt: system prompt（通过 ``build_system_prompt()`` 预生成）。
            history: 对话历史。为 None 时使用 memory 中的历史。

        Returns:
            [SystemMessage?, ...HistoryMessages, HumanMessage(task)]
        """
        messages: list[BaseMessage] = []

        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        for msg in history or self.memory.get_history():
            messages.append(msg)

        messages.append(HumanMessage(content=task))

        return messages

    # ==================================================================
    # Execution
    # ==================================================================

    async def run(
        self,
        task: str,
        *,
        system_prompt: str = "",
        history: list[BaseMessage] | None = None,
        active_skills: list[Any] | None = None,
        active_tools: list[BaseTool] | None = None,
        rag_context: str = "",
        use_memory: bool = True,
        workflow_state: Any = None,
        tool_results: dict[str, str] | None = None,
    ) -> str:
        """执行一次完整的 LLM + Tool 调用循环。

        Args:
            task: 用户任务文本。
            system_prompt: 预生成的 system prompt（可选）。
            history: 对话历史覆盖（用于 socket 通道会话隔离）。
            active_skills: Planner 激活的领域 skill 列表（传入时覆盖 state）。
            active_tools: 本次执行可用的工具列表（传入时覆盖 state）。
            rag_context: RAG 上下文（通过 ContextManager 注入 system prompt）。
            use_memory: 是否注入长期记忆。
            workflow_state: WorkflowState（通过 ContextManager 注入 system prompt）。
            tool_results: 工具执行结果（通过 ContextManager 注入 system prompt）。

        Returns:
            LLM 最终响应文本。
        """
        if self.llm is None:
            self.init_llm()

        # 决定本次执行的 system prompt
        if not system_prompt:
            personality = [s for s in (active_skills or []) if getattr(s, "default", False)]
            domain = [s for s in (active_skills or []) if not getattr(s, "default", False)]
            system_prompt = self.build_system_prompt(
                personality_skills=personality or None,
                domain_skills=domain or None,
                use_memory=use_memory,
                rag_context=rag_context,
                workflow_state=workflow_state,
                tool_results=tool_results,
            )

        # 决定本次执行的工具
        tools = active_tools or self._active_tools

        # 临时 bind（如果传入了不同的工具集）
        llm = self.llm
        if tools and tools != self._active_tools:
            llm = bind_tools(self.llm, tools)

        # 组装消息
        messages = self.build_messages(
            task,
            system_prompt=system_prompt,
            history=history,
        )

        # 工具调用循环
        if tools:
            result = await self._invoke_with_tool_loop(llm, messages)
        else:
            result = await self._invoke_direct(llm, messages)

        self.state.turn_count += 1
        return result

    # ==================================================================
    # Streaming
    # ==================================================================

    async def astream(
        self,
        task: str,
        *,
        system_prompt: str = "",
        history: list[BaseMessage] | None = None,
        active_skills: list[Any] | None = None,
        active_tools: list[BaseTool] | None = None,
        rag_context: str = "",
        use_memory: bool = True,
        workflow_state: Any = None,
        tool_results: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """执行一次 LLM 调用，逐 token 流式输出。

        与 ``run()`` 相同的前置处理，但使用 ``llm.astream()`` 原生透传。
        带工具时：首轮流式输出文本，工具调用后的后续轮次非流式执行。

        Yields:
            逐 token 文本块。
        """
        if self.llm is None:
            self.init_llm()

        # system prompt（与 run() 相同逻辑）
        if not system_prompt:
            personality = [s for s in (active_skills or []) if getattr(s, "default", False)]
            domain = [s for s in (active_skills or []) if not getattr(s, "default", False)]
            system_prompt = self.build_system_prompt(
                personality_skills=personality or None,
                domain_skills=domain or None,
                use_memory=use_memory,
                rag_context=rag_context,
                workflow_state=workflow_state,
                tool_results=tool_results,
            )

        tools = active_tools or self._active_tools
        llm = self.llm
        if tools and tools != self._active_tools:
            llm = bind_tools(self.llm, tools)

        messages = self.build_messages(
            task,
            system_prompt=system_prompt,
            history=history,
        )

        if tools:
            async for chunk in self._invoke_with_tool_loop_stream(llm, messages):
                yield chunk
        else:
            async for chunk in self._invoke_direct_stream(llm, messages):
                yield chunk

        self.state.turn_count += 1

    # ==================================================================
    # 内部：LLM 调用
    # ==================================================================

    async def _invoke_direct_stream(
        self,
        llm: BaseChatModel,
        messages: list[BaseMessage],
    ) -> AsyncIterator[str]:
        """流式直调 LLM（无工具），逐 token yield。"""
        async for chunk in llm.astream(messages):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if content:
                yield content

    async def _invoke_with_tool_loop_stream(
        self,
        llm: BaseChatModel,
        messages: list[BaseMessage],
    ) -> AsyncIterator[str]:
        """流式 LLM 调用 + 工具循环。

        首轮流式输出 token，若 LLM 返回 tool_calls 则：
        1. 收集流式 chunks 构建完整消息
        2. 执行工具
        3. 后续轮次非流式执行（工具结果无需流式输出）
        """
        iteration = 0
        while iteration < self.max_iterations:
            if self.cancelled:
                logger.info("Stream tool loop cancelled at iteration %d", iteration)
                return

            if iteration == 0:
                # 首轮：流式输出 token
                collected_content: list[str] = []
                collected_chunks: list[Any] = []
                async for chunk in llm.astream(messages):
                    collected_chunks.append(chunk)
                    content = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if content:
                        collected_content.append(content)
                        yield content

                # 构建完整 response 以检查 tool_calls
                response = collected_chunks[0] if collected_chunks else None
                for c in collected_chunks[1:]:
                    response = response + c if response else c

                tool_calls = getattr(response, "tool_calls", None) if response else None
            else:
                # 后续轮次：非流式
                response = await retry_async(llm.ainvoke, messages)
                tool_calls = getattr(response, "tool_calls", None)

            if not tool_calls:
                return

            messages.append(response)

            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")

                try:
                    result = await self._execute_tool(tool_name, tool_args)
                except Exception as exc:
                    result = f"Error executing tool '{tool_name}': {exc}"
                    logger.warning("Tool execution failed: %s — %s", tool_name, exc)

                messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

            iteration += 1

        # 超过 max_iterations
        last = messages[-1]
        final = last.content if hasattr(last, "content") else str(last)
        if final:
            yield final

    async def _invoke_direct(
        self,
        llm: BaseChatModel,
        messages: list[BaseMessage],
    ) -> str:
        """直接调用 LLM（无工具）。"""
        response = await retry_async(llm.ainvoke, messages)
        return response.content if hasattr(response, "content") else str(response)

    async def _invoke_with_tool_loop(
        self,
        llm: BaseChatModel,
        messages: list[BaseMessage],
    ) -> str:
        """带工具调用循环的 LLM 调用。

        1. 调用 LLM（可能返回 tool_calls）。
        2. 若有 tool_calls：逐一执行，追加 ToolMessage，循环。
        3. 返回最终文本响应。
        """
        iteration = 0
        while iteration < self.max_iterations:
            if self.cancelled:
                logger.info("Tool loop cancelled at iteration %d", iteration)
                return "[已取消]"

            response = await retry_async(llm.ainvoke, messages)

            tool_calls = getattr(response, "tool_calls", None)
            if not tool_calls:
                return response.content if hasattr(response, "content") else str(response)

            messages.append(response)

            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")

                try:
                    result = await self._execute_tool(tool_name, tool_args)
                except Exception as exc:
                    result = f"Error executing tool '{tool_name}': {exc}"
                    logger.warning("Tool execution failed: %s — %s", tool_name, exc)

                messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

            iteration += 1

        # 超过 max_iterations
        last = messages[-1]
        return last.content if hasattr(last, "content") else str(last)

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
        """按名称查找工具并调用。"""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: tool '{name}' not found. Available: {list(self._tools.keys())}"
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(args)
        elif callable(tool):
            result = tool(**args)
            if asyncio.iscoroutine(result):
                result = await result
        else:
            return f"Error: tool '{name}' is not callable"
        return str(result)

    # ==================================================================
    # Memory 便捷方法
    # ==================================================================

    def save_turn(self, user_input: str, response: str) -> None:
        self.memory.save_message("human", user_input)
        self.memory.save_message("ai", response)

    async def extract_facts_async(self) -> None:
        if self.llm is None:
            return
        await self.memory.extract_facts(self.llm)

    def set_context(self, ctx: Any) -> None:
        """注入 ExecutionContext 以支持外部取消。"""
        self._exec_ctx = ctx

    @property
    def cancelled(self) -> bool:
        if self._exec_ctx is None:
            return False
        return self._exec_ctx.cancelled

    def reset(self) -> None:
        self.memory.clear()
        self.state.reset_turn()
