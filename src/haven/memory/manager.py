"""MemoryManager — 四层记忆统一编排。

- record_turn(): 每轮对话后调用，存储到各层
- retrieve():   每次 LLM 调用前调用，返回 MemoryContext
- consolidate(): 后台整合，压缩 + 衰减 + 清理
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import uuid

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from haven.memory.base import MemoryContext, MemoryItem
from haven.memory.episodic import EpisodicMemory
from haven.memory.semantic import SemanticMemory
from haven.memory.vector import VectorMemory
from haven.memory.working import WorkingMemory

logger = logging.getLogger("haven.memory")


class MemoryManager:
    """统一记忆管理。编排 Working / Episodic / Semantic / Vector 四层。

    用法::

        mm = MemoryManager(session_id="s1", entity_name="user_1")

        # 每轮对话后
        await mm.record_turn("你好", "你好！有什么可以帮您？")

        # 每次 LLM 调用前
        ctx = await mm.retrieve(task="帮我写代码")
        system_prompt += ctx.format_for_prompt()

        # 后台
        await mm.consolidate(llm)
    """

    def __init__(
        self,
        session_id: str = "default",
        entity_name: str = "user",
        channel: str = "cli",
        *,
        enable_vector: bool = True,
        max_working_messages: int = 100,
    ):
        self.session_id = session_id
        self.entity_name = entity_name
        self.channel = channel
        self.turn_count: int = 0

        self.working = WorkingMemory(max_messages=max_working_messages)
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.vector = VectorMemory() if enable_vector else None

        self._llm: BaseChatModel | None = None
        self._consolidation_counter: int = 0

    def set_llm(self, llm: BaseChatModel) -> None:
        self._llm = llm

    # ==================================================================
    # 存储
    # ==================================================================

    async def record_turn(
        self,
        user_message: str,
        assistant_message: str,
        *,
        importance: float | None = None,
        persist: bool = True,
    ) -> None:
        """记录一轮完整对话到所有 Memory 层。"""
        self.turn_count += 1

        if importance is None:
            importance = self._estimate_importance(user_message, assistant_message)

        # 1. Working — 立即追加
        self.working.add_message(HumanMessage(content=user_message))
        self.working.add_message(AIMessage(content=assistant_message))

        if not persist:
            return

        # 2. Episodic — 持久化
        await self.episodic.store_turn(
            session_id=self.session_id,
            turn_number=self.turn_count,
            user_message=user_message,
            assistant_response=assistant_message,
            importance=importance,
        )

        # 3. Vector — embed
        if self.vector:
            await self.vector.store(
                [
                    MemoryItem(
                        id=f"vec_{self.session_id}_{self.turn_count}_{uuid.uuid4().hex[:8]}",
                        content=f"用户: {user_message}\nAI: {assistant_message}",
                        memory_type="episodic",
                        importance=importance,
                        metadata={
                            "session_id": self.session_id,
                            "turn_number": self.turn_count,
                            "entity_name": self.entity_name,
                        },
                    )
                ]
            )

        # 4. Semantic — 异步提取事实
        asyncio.create_task(self._extract_facts(user_message, assistant_message))

        # 5. 摘要检查
        if self.working.needs_summarization() and self._llm:
            asyncio.create_task(self.working.summarize(self._llm))

        # 6. 周期整合
        self._consolidation_counter += 1
        if self._consolidation_counter % 10 == 0:
            asyncio.create_task(self.consolidate())

    # ==================================================================
    # 检索
    # ==================================================================

    async def retrieve(
        self,
        task: str = "",
        *,
        top_k: int = 5,
        search_episodic: bool = True,
        search_semantic: bool = True,
        search_vector: bool = True,
    ) -> MemoryContext:
        """多路并行检索，合并去重。"""
        tasks: list[asyncio.Task] = []

        tasks.append(asyncio.create_task(self.working.retrieve(query="", top_k=20)))
        tasks.append(
            asyncio.create_task(
                self.semantic.retrieve(
                    query=task if task else self.entity_name,
                    top_k=10,
                    entity_name=self.entity_name,
                    min_confidence=0.3,
                )
                if search_semantic
                else self._empty()
            )
        )
        tasks.append(
            asyncio.create_task(
                self.episodic.retrieve(
                    query=task,
                    top_k=top_k,
                    time_range="30d",
                    min_importance=0.3,
                    search_mode="hybrid",
                )
                if search_episodic
                else self._empty()
            )
        )
        tasks.append(
            asyncio.create_task(
                self.vector.retrieve(query=task, top_k=top_k, min_importance=0.3)
                if (search_vector and self.vector and task)
                else self._empty()
            )
        )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        def _ok(r):
            return [] if isinstance(r, (Exception, BaseException)) else r

        return MemoryContext(
            working=_ok(results[0]),
            semantic=_ok(results[1]),
            episodic=_ok(results[2]),
            vector=_ok(results[3]),
        )

    # ==================================================================
    # Consolidation
    # ==================================================================

    async def consolidate(self, llm: BaseChatModel | None = None) -> dict[str, int]:
        """后台整合所有层。"""
        llm = llm or self._llm
        results: dict[str, int] = {}

        results["episodic"] = await self.episodic.consolidate(llm)
        results["semantic"] = await self.semantic.consolidate(llm)
        if self.vector:
            results["vector"] = await self.vector.consolidate(llm)

        logger.debug("Memory consolidation: %s", results)
        return results

    # ==================================================================
    # 便利方法
    # ==================================================================

    def get_working_messages(self) -> list[Any]:
        return self.working.get_messages()

    def get_working_summary(self) -> str:
        return self.working.summary

    async def get_entity_profile(self, entity_name: str | None = None) -> list[MemoryItem]:
        return await self.semantic.retrieve_entity_facts(entity_name or self.entity_name)

    # ==================================================================
    # 内部
    # ==================================================================

    async def _extract_facts(self, user_message: str, assistant_message: str) -> None:
        if self._llm is None:
            return

        prompt = (
            f'从对话中提取关于"{self.entity_name}"的结构化信息。\n'
            f"规则: 只提取明确陈述的事实。key用英文snake_case，value保留原始语言。\n"
            f"confidence: 0.9=明确, 0.5=暗示。tags: personal/preference/health/skill/contact/goal\n"
            f"无新事实返回空数组。\n\n"
            f"对话:\n用户: {user_message}\nAI: {assistant_message}\n\n"
            f'仅返回JSON: {{"facts":[{{"key":"...","value":"...","confidence":0.9,"tags":["..."]}}]}}'
        )

        try:
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            raw = response.content if hasattr(response, "content") else str(response)
            facts = self._parse_facts(raw)
        except Exception as exc:
            logger.warning("Fact extraction failed: %s", exc)
            return

        if not facts:
            return

        items = [
            MemoryItem(
                id=f"fact_{self.session_id}_{self.turn_count}_{i}",
                content=f"{f['key']}: {f['value']}",
                memory_type="semantic",
                importance=f.get("confidence", 0.9),
                metadata={
                    "entity_name": self.entity_name,
                    "key": f["key"],
                    "value": f["value"],
                    "confidence": f.get("confidence", 0.9),
                    "source_session": self.session_id,
                    "source_turn": self.turn_count,
                    "tags": f.get("tags", []),
                    "entity_type": "user",
                },
            )
            for i, f in enumerate(facts)
        ]
        await self.semantic.store(items)
        logger.info("Extracted %d fact(s) for '%s'", len(items), self.entity_name)

    @staticmethod
    def _parse_facts(raw: str) -> list[dict]:
        import json

        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:]) if len(lines) > 1 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
        brace = raw.find("{")
        if brace == -1:
            return []
        try:
            data = json.loads(raw[brace:])
            return data.get("facts", [])
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _estimate_importance(user: str, assistant: str) -> float:
        keywords = [
            "记住",
            "我叫",
            "我是",
            "我喜欢",
            "我住在",
            "我的电话",
            "偏好",
            "总是",
            "从不",
            "重要",
            "过敏",
            "紧急",
        ]
        combined = (user + " " + assistant).lower()
        hits = sum(1 for kw in keywords if kw in combined)
        return min(0.9, 0.3 + hits * 0.15)

    @staticmethod
    async def _empty() -> list[MemoryItem]:
        return []
