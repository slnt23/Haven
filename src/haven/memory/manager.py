"""MemoryManager — 四层记忆统一编排。

生命周期:
    record_turn():   每轮对话后调用，存储到各层 + 触发批量语义提取
    retrieve():      每次 LLM 调用前调用，四路并行检索 → MemoryContext
    consolidate():   后台整合（每 10 轮触发），压缩 + 衰减 + 清理

批量语义提取:
    每轮记录后检查未处理对话数 ≥ BATCH_MIN_SIZE(5) → 异步触发
    辅助 LLM 通读旧知识 + 新对话 → 生成自然语言事实 → 全量替换
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

    # 批量提取参数
    _BATCH_MIN_SIZE = 1       # 未处理对话不少于此时触发 LLM 调用
    _BATCH_GATHER_DELAY = 2.0 # 不足 5 条时的聚集等待时间（秒），让更多消息攒批
    _BATCH_MAX_EPISODES = 20  # 每次最多发送给 LLM 的对话数（控制 prompt 长度）

    def __init__(
        self,
        session_id: str = "default",
        entity_name: str = "user",
        channel: str = "cli",
        *,
        enable_vector: bool = False,
        max_working_messages: int = 100,
    ):
        self.session_id = session_id
        self.entity_name = entity_name
        self.channel = channel
        self.turn_count: int = 0

        # 四层记忆
        self.working = WorkingMemory(max_messages=max_working_messages)
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.vector = VectorMemory() if enable_vector else None

        # LLM 由外部注入（factory.py 注入辅助模型）
        self._llm: BaseChatModel | None = None
        self._consolidation_counter: int = 0
        # 并发锁：防止多个批量提取任务同时执行
        self._extraction_lock = asyncio.Lock()

    def set_llm(self, llm: BaseChatModel) -> None:
        """注入 LLM 实例。通常传入辅助模型，用于记忆提取、摘要等后台任务。"""
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
        """记录一轮完整对话到所有 Memory 层。

        写入顺序:
        1. Working  — 立即追加到滑动窗口（同步）
        2. Episodic — 持久化到 SQLite（await）
        3. Vector   — embedding 后写入 ChromaDB（await）
        4. Semantic — 异步检查是否触发批量提取（fire-and-forget）
        5. 摘要检查 — 工作记忆溢出时异步压缩
        6. 周期整合 — 每 10 轮触发一次
        """
        self.turn_count += 1

        # 如果外部未指定重要性，用关键词启发式估算
        if importance is None:
            importance = self._estimate_importance(user_message, assistant_message)

        # 1. Working — 立即追加，不持久化
        self.working.add_message(HumanMessage(content=user_message))
        self.working.add_message(AIMessage(content=assistant_message))

        if not persist:
            return

        # 配置级记忆开关：关闭后只保留 Working，不写持久层
        try:
            from haven.config import settings

            if not settings.memory_enabled:
                return
        except Exception:
            pass  # 配置不可用时继续写入（宽松策略）

        # 2. Episodic — SQLite 持久化完整对话
        await self.episodic.store_turn(
            session_id=self.session_id,
            turn_number=self.turn_count,
            user_message=user_message,
            assistant_response=assistant_message,
            importance=importance,
        )

        # 3. Vector — 嵌入后写入 ChromaDB
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

        # 4. Semantic — 检查未处理对话数，达标则异步批量提取
        asyncio.create_task(self._check_and_extract())

        # 5. Working 摘要 — 溢出消息 ≥ 10 条时异步压缩，并回填到 Episodic
        if self.working.needs_summarization() and self._llm:
            asyncio.create_task(self._summarize_and_bridge())

        # 6. 周期整合 — 每 10 轮触发一次（清理旧数据、衰减、压缩）
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
        """四路并行检索，合并为 MemoryContext。

        检索策略:
        - Working:  始终返回最近 20 条消息
        - Semantic: 按 entity_name 过滤，匹配 task 关键词
        - Episodic: hybrid 模式（重要性 60% + 时间衰减 40%），30 天内
        - Vector:   embedding 相似度检索（仅 task 非空时）

        任一路失败不影响其他路（graceful degradation）。
        """
        tasks: list[asyncio.Task] = []

        # Working — 最近消息（不注入 prompt，直接追加到 messages）
        tasks.append(
            asyncio.create_task(self.working.retrieve(query="", top_k=20))
        )
        # Semantic — 自然语言事实
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
        # Episodic — 历史对话
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
        # Vector — 语义相似片段
        tasks.append(
            asyncio.create_task(
                self.vector.retrieve(
                    query=task, top_k=top_k, min_importance=0.3
                )
                if (search_vector and self.vector and task)
                else self._empty()
            )
        )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        def _ok(r):
            """异常降级为空列表。"""
            return [] if isinstance(r, (Exception, BaseException)) else r

        return MemoryContext(
            working=_ok(results[0]),
            semantic=_ok(results[1]),
            episodic=_ok(results[2]),
            vector=_ok(results[3]),
        )

    async def get_long_term_context(self, entity_name: str = "") -> str:
        """获取格式化的长期记忆上下文（兼容 ContextManager 旧接口）。

        委托给 retrieve()，调用 format_for_prompt() 格式化。
        """
        ctx = await self.retrieve(task=entity_name or self.entity_name)
        return ctx.format_for_prompt()

    # ==================================================================
    # Consolidation
    # ==================================================================

    async def consolidate(
        self, llm: BaseChatModel | None = None
    ) -> dict[str, int]:
        """后台整合所有持久化层。

        - Episodic: 为旧对话生成 LLM 摘要
        - Semantic: 清理 90 天前的过期事实
        - Vector:   超过 10000 条时删除最旧的
        """
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

    @property
    def is_vector_available(self) -> bool:
        """向量记忆是否实际可用（配置开启 + chromadb 已安装 + 初始化成功）。"""
        if self.vector is None:
            return False
        return self.vector._available

    def get_working_messages(self) -> list[Any]:
        """获取当前工作记忆的消息列表。用于构建 LLM 调用前的 messages。"""
        return self.working.get_messages()

    def get_working_summary(self) -> str:
        """获取工作记忆的溢出摘要。"""
        return self.working.summary

    async def get_entity_profile(
        self, entity_name: str | None = None
    ) -> list[MemoryItem]:
        """获取某个实体的所有已知事实。"""
        return await self.semantic.retrieve_entity_facts(
            entity_name or self.entity_name
        )

    async def _summarize_and_bridge(self) -> None:
        """Working 摘要生成 + 回填 Episodic 桥接。

        Working 压缩溢出消息后，将生成的摘要回写到 Episodic
        中最近的无摘要 episodes，避免 Episodic 重复 LLM 摘要。
        """
        if self._llm is None:
            return
        try:
            prev_summary = self.working.summary
            await self.working.summarize(self._llm)
            new_summary = self.working.summary
            # 只有摘要确实更新了才回填
            if new_summary and new_summary != prev_summary:
                n = await self.episodic.backfill_summary_from_working(
                    self.session_id, new_summary
                )
                if n > 0:
                    logger.debug(
                        "Working summary backfilled to %d episodic rows", n
                    )
        except Exception:
            pass

    # ==================================================================
    # 批量语义提取
    # ==================================================================

    async def extract_semantic_facts_async(
        self, force: bool = False
    ) -> None:
        """供外部调用的语义提取入口。

        force=True 时忽略批次大小阈值，立即处理所有未处理对话。
        用于会话结束、守护进程停止等场景，确保不丢失未处理数据。
        """
        if self._llm is None:
            return
        await self._batch_extract_semantic_facts(force=force)

    async def _check_and_extract(self) -> None:
        """record_turn() 后的异步检查：未处理对话达标则触发批量提取。

        小批次（< 5 条）时等待 gather_delay 秒，让更多消息攒批后一起处理。
        """
        try:
            count = await self.episodic.count_unprocessed(self.session_id)
            if count < self._BATCH_MIN_SIZE:
                return
            # 不足 5 条时等待聚集，减少高频小批次 LLM 调用
            if count < 5:
                await asyncio.sleep(self._BATCH_GATHER_DELAY)
                count = await self.episodic.count_unprocessed(self.session_id)
                if count < self._BATCH_MIN_SIZE:
                    return
            await self._batch_extract_semantic_facts()
        except Exception:
            pass

    async def _batch_extract_semantic_facts(
        self, force: bool = False
    ) -> None:
        """批量从情节记忆中提取自然语言事实。

        流程:
        1. 获取未处理对话（最多 BATCH_MAX_EPISODES 条）
        2. 获取已有知识文本
        3. 组装 prompt（旧知识 + 新对话文本）
        4. 调辅助 LLM 提取 + 去重
        5. 全量替换 semantic_facts 表
        6. 标记对话为已处理

        并发锁 _extraction_lock 防止多个提取任务同时执行导致数据不一致。
        """
        async with self._extraction_lock:
            # 1. 获取待处理的对话
            episodes = await self.episodic.get_unprocessed(
                self.session_id, limit=self._BATCH_MAX_EPISODES
            )
            if not episodes:
                return
            if not force and len(episodes) < self._BATCH_MIN_SIZE:
                return

            # 2. 获取已有知识
            existing_text = await self.semantic.get_all_facts_text(
                self.entity_name
            )
            existing_str = existing_text if existing_text else "（暂无已有知识）"

            # 3. 构建对话文本（每轮截断到 500 字符，控制 prompt 长度）
            transcript_parts = []
            for ep in episodes:
                transcript_parts.append(
                    f"[第{ep['turn_number']}轮]\n"
                    f"用户: {ep['user_message'][:500]}\n"
                    f"AI: {ep['assistant_response'][:500]}"
                )
            transcript = "\n\n".join(transcript_parts)

            # 4. 组装 prompt 并调用辅助 LLM
            # prompt 设计要点:
            #   - 包含"已有知识"，让 LLM 做增量合并而非从零提取
            #   - 明确要求"保留旧知识"，防止遗忘
            #   - "新旧冲突以最新为准"，保证信息时效性
            #   - 输出 JSON 结构，便于解析
            prompt = (
                f'你是一个信息提取助手。阅读以下对话记录，'
                f'提取关于"{self.entity_name}"的事实，'
                f"与已有知识合并去重。\n\n"
                f"## 规则\n"
                f"1. 只提取明确陈述的事实，不推测\n"
                f"2. 用自然中文句子表述，每句独立完整\n"
                f"3. 新旧冲突以最新对话为准\n"
                f"4. 旧知识在新对话中没提到也要保留\n"
                f"5. importance: high(明确个人信息)"
                f"/medium(偏好观点)/low(临时需求)\n\n"
                f"## 已有知识\n{existing_str}\n\n"
                f"## 新对话\n{transcript}\n\n"
                f"## 输出\n"
                f"只返回一个 JSON 对象（不要 markdown 代码块）:\n"
                f'{{"facts":['  # 避免 f-string 中的 {} 被解析
                f'{{"text":"用户叫张三，住在北京","importance":"high"}}'
                f']}}\n'
                f'无事实返回: {{"facts":[]}}'
            )

            try:
                response = await self._llm.ainvoke(
                    [HumanMessage(content=prompt)]
                )
                raw = (
                    response.content
                    if hasattr(response, "content")
                    else str(response)
                )
                facts = self._parse_extraction_response(raw)
            except Exception as exc:
                logger.warning(
                    "Batch semantic extraction failed: %s", exc
                )
                return

            if not facts:
                return

            # 5. 全量替换事实
            episode_ids = [ep["id"] for ep in episodes]
            await self.semantic.store_facts(
                entity_name=self.entity_name,
                facts=facts,
                source_episode_ids=episode_ids,
            )

            # 6. 标记已处理
            await self.episodic.mark_processed(episode_ids)

            # 7. 回填情节重要性（从提取的事实推断）
            if facts:
                self._backfill_episodic_importance(episode_ids, facts)

            logger.info(
                "Semantic batch: %d episodes → %d facts for '%s'",
                len(episodes),
                len(facts),
                self.entity_name,
            )

    @staticmethod
    def _parse_extraction_response(raw: str) -> list[dict]:
        """解析 LLM 返回的 JSON 响应。

        处理常见的格式问题：
        - markdown 代码块包裹
        - 响应中包含 JSON 之外的文本
        - 中文 JSON 编码
        """
        import json

        raw = raw.strip()
        # 去除 markdown 代码块
        if raw.startswith("```"):
            raw = (
                raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
            )
            if raw.endswith("```"):
                raw = raw[:-3]
        # 从第一个 { 开始解析
        brace = raw.find("{")
        if brace == -1:
            return []
        try:
            data = json.loads(raw[brace:])
            return data.get("facts", [])
        except json.JSONDecodeError:
            return []

    # ==================================================================
    # 内部工具
    # ==================================================================

    def _backfill_episodic_importance(
        self, episode_ids: list[str], facts: list[dict]
    ) -> None:
        """根据 LLM 提取的事实重要性，回填 episodic 记录的 importance 字段。

        high 事实 → importance 0.9
        medium 事实 → importance 0.6
        low 事实 → importance 0.4
        多条事实取最高值。
        """
        importance_map = {"high": 0.9, "medium": 0.6, "low": 0.4}
        best_imp = 0.4  # 默认值
        for f in facts:
            imp = importance_map.get(f.get("importance", "low"), 0.4)
            if imp > best_imp:
                best_imp = imp

        # 回填到来源 episodes
        placeholders = ",".join("?" * len(episode_ids))
        self.episodic._conn.execute(
            f"UPDATE episodes SET importance = MAX(importance, ?) "
            f"WHERE id IN ({placeholders})",
            [best_imp] + episode_ids,
        )
        self.episodic._conn.commit()

    @staticmethod
    def _estimate_importance(user: str, assistant: str) -> float:
        """基于多维度信号的对话重要性估算。

        四个信号维度：
        1. 个人信息（姓名、联系方式、地址等）
        2. 偏好声明（喜欢/不喜欢/总是/从不）
        3. 任务请求（帮我/写一下/生成等）
        4. 情感表达（紧急/重要/必须等）
        范围 0.3-0.9。
        """
        combined = (user + " " + assistant).lower()
        score = 0.3

        # 个人信息信号（权重 0.12 每个）
        personal = [
            "我叫", "我是", "我住在", "我的电话", "我的邮箱",
            "我的地址", "我今年", "我的工作是", "我在",
            "名字是", "联系电话", "email", "出生",
        ]
        score += sum(0.12 for kw in personal if kw in combined)

        # 偏好声明信号（权重 0.10 每个）
        preference = [
            "我喜欢", "我讨厌", "我不喜欢", "偏好", "总是",
            "从不", "习惯", "倾向", "宁愿", "最爱",
        ]
        score += sum(0.10 for kw in preference if kw in combined)

        # 任务请求信号（权重 0.08 每个）
        task = [
            "帮我", "请帮我", "帮我写", "生成", "分析一下",
            "能不能", "可以帮我", "实现", "修复",
        ]
        score += sum(0.08 for kw in task if kw in combined)

        # 情感/紧迫信号（权重 0.15 每个）
        urgency = [
            "紧急", "重要", "必须", "尽快", "立即",
            "过敏", "危险", "严重", "关键",
        ]
        score += sum(0.15 for kw in urgency if kw in combined)

        return min(0.9, score)

    @staticmethod
    async def _empty() -> list[MemoryItem]:
        """返回空列表的协程。用于检索时的降级占位。"""
        return []
