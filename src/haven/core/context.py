"""Context Layer — 统一上下文收集与组装。

ContextManager 从 Memory、Skill、Workflow、Tool Result、RAG 统一收集上下文，
ContextAssembler 按优先级组装成 system prompt 字符串。

PromptBuilder 不再直接访问各子系统，只接收 ContextManager.build() 的返回结果。

用法::

    # 初始化（注入 memory 引用）
    cm = ContextManager(memory=runtime.memory)

    # 一站式收集 + 组装
    system_prompt = cm.build(
        personality_skills=[haven_skill],
        domain_skills=[coder_skill],
        rag_context="[RAG 检索结果]",
    )

    # 分步：先收集原始 items，检查后再组装
    items = cm.collect(personality_skills=[...], domain_skills=[...])
    prompt = cm.assemble(items)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ============================================================================
# ContextSource — 上下文来源枚举
# ============================================================================


class ContextSource(Enum):
    """上下文来源类型。按优先级排序（枚举定义顺序即默认优先级）。"""

    PERSONALITY = "personality"  # 人格 skill（default=true）
    SKILL = "skill"  # 领域 skill（Planner 激活）
    MEMORY = "memory"  # 长期记忆（Semantic facts）
    WORKFLOW = "workflow"  # 工作流状态（node_outputs / current_node）
    TOOL_RESULT = "tool_result"  # 工具执行结果
    RAG = "rag"  # 外部知识检索


# 默认优先级映射：值越小越优先
_DEFAULT_PRIORITY: dict[ContextSource, int] = {
    ContextSource.PERSONALITY: 0,
    ContextSource.SKILL: 1,
    ContextSource.MEMORY: 2,
    ContextSource.WORKFLOW: 3,
    ContextSource.TOOL_RESULT: 4,
    ContextSource.RAG: 5,
}


# ============================================================================
# ContextItem — 单条上下文
# ============================================================================


@dataclass
class ContextItem:
    """单条上下文，携带来源、优先级和元数据。

    Attributes:
        content: 文本内容。
        source: 来源类型。
        priority: 优先级（越小越优先），默认从 source 推导。
        metadata: 附加元数据（如 skill_name、confidence 等）。
    """

    content: str
    source: ContextSource
    priority: int = field(default=-1)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.priority < 0:
            self.priority = _DEFAULT_PRIORITY.get(self.source, 5)


# ============================================================================
# ContextBundle — ContextManager.build() 的返回结果
# ============================================================================


@dataclass
class ContextBundle:
    """ContextManager.build() 的返回结果。

    Attributes:
        system_prompt: 组装后的 system prompt 字符串。
        items: 本次收集的所有 ContextItem。
        token_usage: 估算的 token 用量。
    """

    system_prompt: str
    items: list[ContextItem] = field(default_factory=list)
    token_usage: int = 0


# ============================================================================
# TokenBudget — token 估算器
# ============================================================================


class TokenBudget:
    """简单的 token 预算估算器。

    按 1 token ≈ 3 个字符估算（中文约 1 token ≈ 1.5 字符）。
    """

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars / 3)

    def fits(self, text: str) -> bool:
        return self.estimate(text) <= self.max_tokens


# ============================================================================
# ContextAssembler — 上下文组装器
# ============================================================================


class ContextAssembler:
    """按优先级组装 ContextItem 列表为最终 prompt 字符串。

    处理逻辑：
      1. 按 priority 升序排列（值越小越优先）
      2. 按 token 预算从低优先级开始裁剪
      3. 超出预算时截断当前段并停止
    """

    def __init__(self, max_tokens: int = 4000):
        self._budget = TokenBudget(max_tokens)

    def assemble(self, items: list[ContextItem]) -> str:
        """组装 context items 为 system prompt 字符串。

        Args:
            items: ContextItem 列表。

        Returns:
            组装后的 system prompt 字符串。
        """
        if not items:
            return ""

        sorted_items = sorted(items, key=lambda x: x.priority)

        parts: list[str] = []
        used = 0

        for item in sorted_items:
            content = item.content.strip()
            if not content:
                continue
            est = self._budget.estimate(content)
            if used + est <= self._budget.max_tokens:
                parts.append(content)
                used += est
            else:
                remaining = self._budget.max_tokens - used
                if remaining > 100:
                    truncated = content[: remaining * 3] + "\n...[已截断]"
                    parts.append(truncated)
                break

        return "\n\n".join(parts)

    @property
    def max_tokens(self) -> int:
        return self._budget.max_tokens


# ============================================================================
# ContextManager — 统一上下文管理器
# ============================================================================


class ContextManager:
    """统一上下文收集器。从各子系统收集 ContextItem 并组装为 system prompt。

    PromptBuilder 只调用 ``build()`` 获取最终结果，
    不再直接访问 MemoryManager / SkillRegistry / Workflow。

    用法::

        cm = ContextManager(memory=runtime.memory, max_system_tokens=4000)

        # 收集 + 组装
        bundle = cm.build(
            personality_skills=[haven_skill],
            domain_skills=[coder_skill],
            rag_context="[检索结果]",
        )
        system_prompt = bundle.system_prompt
    """

    def __init__(
            self,
            memory: Any = None,
            *,
            max_system_tokens: int = 4000,
    ):
        self._memory = memory
        self._assembler = ContextAssembler(max_tokens=max_system_tokens)
        self._extra_collectors: dict[ContextSource, Any] = {}

    # ==================================================================
    # 公开 API
    # ==================================================================

    def build(
            self,
            *,
            personality_skills: list[Any] | None = None,
            domain_skills: list[Any] | None = None,
            workflow_state: Any = None,
            tool_results: dict[str, str] | None = None,
            rag_context: str = "",
            use_memory: bool = True,
    ) -> ContextBundle:
        """一站式收集 + 组装，返回 ContextBundle。

        这是 PromptBuilder 调用的唯一入口。
        """
        items = self.collect(
            personality_skills=personality_skills,
            domain_skills=domain_skills,
            workflow_state=workflow_state,
            tool_results=tool_results,
            rag_context=rag_context,
            use_memory=use_memory,
        )
        prompt = self.assemble(items)
        return ContextBundle(
            system_prompt=prompt,
            items=items,
            token_usage=self._assembler._budget.estimate(prompt),
        )

    def collect(
            self,
            *,
            personality_skills: list[Any] | None = None,
            domain_skills: list[Any] | None = None,
            workflow_state: Any = None,
            tool_results: dict[str, str] | None = None,
            rag_context: str = "",
            use_memory: bool = True,
    ) -> list[ContextItem]:
        """收集所有来源的 ContextItem 列表。

        Args:
            personality_skills: default=true 的人格 skill 实例列表。
            domain_skills: Planner 激活的领域 skill 实例列表。
            workflow_state: WorkflowState 实例（可选）。
            tool_results: {tool_name: result_string} 映射（可选）。
            rag_context: RAG 检索上下文字符串（可选）。
            use_memory: 是否从长期记忆中收集。

        Returns:
            按收集顺序排列的 ContextItem 列表（未排序）。
        """
        items: list[ContextItem] = []

        # 1. 人格 skill（最高优先级）
        items.extend(
            self._collect_skills(
                personality_skills,
                ContextSource.PERSONALITY,
            )
        )

        # 2. 领域 skill
        items.extend(
            self._collect_skills(
                domain_skills,
                ContextSource.SKILL,
            )
        )

        # 3. 长期记忆
        if use_memory:
            items.extend(self._collect_memory())

        # 4. 工作流状态
        if workflow_state is not None:
            items.extend(self._collect_workflow(workflow_state))

        # 5. 工具结果
        if tool_results:
            items.extend(self._collect_tool_results(tool_results))

        # 6. RAG
        if rag_context and rag_context.strip():
            items.extend(self._collect_rag(rag_context))

        # 7. 扩展收集器
        for _source, collector in self._extra_collectors.items():
            try:
                result = collector()
                if isinstance(result, list):
                    items.extend(result)
                elif isinstance(result, ContextItem):
                    items.append(result)
            except Exception:
                pass

        return items

    def assemble(self, items: list[ContextItem]) -> str:
        """对已收集的 items 执行优先级组装。

        暴露此方法以便调用方在 collect() 和 assemble() 之间
        插入自定义过滤/排序逻辑。
        """
        return self._assembler.assemble(items)

    def register_collector(
            self,
            source: ContextSource,
            collector: Any,
    ) -> None:
        """注册扩展上下文收集器。

        Args:
            source: 上下文来源标签。
            collector: 可调用对象，返回 list[ContextItem] 或 ContextItem。
        """
        self._extra_collectors[source] = collector

    # ==================================================================
    # 收集器实现
    # ==================================================================

    @staticmethod
    def _collect_skills(
            skills: list[Any] | None,
            source: ContextSource,
    ) -> list[ContextItem]:
        if not skills:
            return []
        items: list[ContextItem] = []
        for skill in skills:
            prompt = getattr(skill, "prompt_extension", "") or getattr(skill, "prompt", "")
            if prompt.strip():
                items.append(
                    ContextItem(
                        content=prompt.strip(),
                        source=source,
                        metadata={"skill_name": getattr(skill, "name", "")},
                    )
                )
        return items

    def _collect_memory(self) -> list[ContextItem]:
        if self._memory is None:
            return []
        try:
            ctx = self._memory.get_long_term_context()
        except Exception:
            return []
        if not ctx or not ctx.strip():
            return []
        return [ContextItem(content=ctx, source=ContextSource.MEMORY)]

    @staticmethod
    def _collect_workflow(state: Any) -> list[ContextItem]:
        items: list[ContextItem] = []

        current = getattr(state, "current_node", "")
        if current:
            items.append(
                ContextItem(
                    content=f"[当前工作流阶段: {current}]",
                    source=ContextSource.WORKFLOW,
                    metadata={"current_node": current},
                )
            )

        outputs = getattr(state, "node_outputs", {})
        if outputs:
            for node_name, output in outputs.items():
                if output:
                    items.append(
                        ContextItem(
                            content=f"[工作流节点 '{node_name}' 输出]\n{str(output)[:600]}",
                            source=ContextSource.WORKFLOW,
                            metadata={"node_name": node_name},
                        )
                    )

        return items

    @staticmethod
    def _collect_tool_results(results: dict[str, str]) -> list[ContextItem]:
        items: list[ContextItem] = []
        for tool_name, result in results.items():
            if result:
                items.append(
                    ContextItem(
                        content=f"[工具 '{tool_name}' 执行结果]\n{str(result)[:800]}",
                        source=ContextSource.TOOL_RESULT,
                        metadata={"tool_name": tool_name},
                    )
                )
        return items

    @staticmethod
    def _collect_rag(rag_context: str) -> list[ContextItem]:
        content = rag_context.strip()
        if not content:
            return []
        # 如果 RAG 内容没有自带标签，添加前缀
        if not content.startswith("["):
            content = "[参考知识 — 请优先基于以下资料回答]\n" + content
        return [ContextItem(content=content, source=ContextSource.RAG)]
