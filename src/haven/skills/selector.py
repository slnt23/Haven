"""SkillSelector — LLM 驱动的三阶段 Skill 选择器。

Phase 0: 快速路径 — 简单对话跳过选择
Phase 1: 标签过滤 — 基于 tag 同义词集缩减候选
Phase 2: LLM 结构化选择 — 语义匹配
Phase 3: 依赖解析 — 传递闭包

用法::

    selector = SkillSelector(llm)
    result = await selector.select(task, SkillRegistry.list_all())
    # result.skill_names → ["coder", "data_analysis"]
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from haven.skills.base_skill import BaseSkill

logger = logging.getLogger("haven.skill_selector")

# ============================================================================
# Structured Output Schema
# ============================================================================


class SelectedSkill(BaseModel):
    """LLM 返回的单个 skill 选择。"""
    name: str = Field(description="选中的 skill 名称")
    reason: str = Field(description="为什么选择这个 skill，一句话")


class SkillSelectionResult(BaseModel):
    """LLM structured output — skill 选择结果。"""
    skills: list[SelectedSkill] = Field(
        default_factory=list,
        description="选中的 skills。若无匹配则返回空列表",
    )


# ============================================================================
# 标签同义词集
# ============================================================================

_TAG_SYNSET: dict[str, list[str]] = {
    "development": [
        "code", "编程", "程序", "代码", "debug", "开发", "软件", "bug",
        "算法", "框架", "API", "接口", "重构", "架构", "爬虫",
    ],
    "data": [
        "数据", "分析", "统计", "图表", "可视化", "SQL", "pandas",
        "报表", "爬虫", "清洗", "ETL",
    ],
    "medical": [
        "病", "药", "症状", "治疗", "诊断", "健康", "医", "手术",
        "处方", "体检", "头痛", "感冒", "发烧",
    ],
    "devops": [
        "部署", "Docker", "K8s", "CI", "CD", "服务器", "运维",
        "容器", "Nginx", "域名", "环境变量",
    ],
    "writing": [
        "翻译", "摘要", "总结", "写", "文档", "报告", "文章",
        "翻译成", "润色", "改写", "概括",
    ],
    "companion": [
        "聊天", "陪伴", "心情", "笑话", "故事", "日常", "无聊",
        "你好", "推荐", "聊聊",
    ],
    "technical": [
        "硬件", "电路", "网络", "路由", "装机", "嵌入式",
        "3D打印", "DIY", "维修", "工具",
    ],
}

_SIMPLE_PATTERNS: set[str] = {
    "你好", "hi", "hello", "谢谢", "thanks", "再见", "bye", "拜拜",
    "在吗", "你是谁", "你能做什么", "help", "帮助",
}

# ============================================================================
# LLM 选择 Prompt
# ============================================================================

_SELECTION_SYSTEM_PROMPT = """\
You are a skill selector for an AI assistant. Pick the most relevant skills.

Rules:
- Select 0 to {max_skills} skills. Return an empty list for generic/chat requests.
- Only select a skill if it is GENUINELY relevant to the request.
- Order by relevance (most relevant first).
- If a request spans multiple domains (e.g. "write code AND analyze data"),
  select multiple skills.
- The user's message may be in Chinese; skill descriptions are bilingual.

Available skills:

{skill_menu}

User request: {task}

Select the skills needed. Explain each choice in one sentence."""


# ============================================================================
# SkillSelector
# ============================================================================


@dataclass
class SkillSelector:
    """LLM 驱动的 Skill 选择器。

    Parameters:
        llm: LangChain 模型实例。用于 Phase 2 structured output。
    """

    llm: BaseChatModel | None = None
    _cache: dict[str, SkillSelectionResult] = field(default_factory=dict)
    _cache_max_size: int = 128

    # ==================================================================
    # 公开 API
    # ==================================================================

    async def select(
        self,
        task: str,
        candidates: dict[str, BaseSkill],
        *,
        max_skills: int = 3,
    ) -> SkillSelectionResult:
        """选择适用于 *task* 的 skill 集合。

        Args:
            task: 用户输入文本。
            candidates: 全部可用 skill 字典 {name: BaseSkill}。
            max_skills: 最多选择的 skill 数量。

        Returns:
            SkillSelectionResult，包含选中的 skill 名和理由。
        """
        # Phase 0: 快速路径
        if self._is_trivial(task):
            return SkillSelectionResult(skills=[])

        # Phase 0.5: 缓存
        cache_key = self._cache_key(task)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Phase 1: 标签过滤
        filtered = self._filter_by_tags(task, candidates)

        if len(filtered) == 0:
            return SkillSelectionResult(skills=[])

        # Phase 2: LLM 选择
        result = await self._llm_select(task, filtered, max_skills)

        # Phase 3: 依赖解析（委托给 SkillRegistry）
        result = self._resolve_deps(result, candidates)

        self._set_cache(cache_key, result)
        return result

    @property
    def skill_names(self) -> list[str]:
        """便捷属性：从最近一次选择结果获取 skill 名列表。"""
        return []

    # ==================================================================
    # Phase 0: 快速路径
    # ==================================================================

    @staticmethod
    def _is_trivial(task: str) -> bool:
        cleaned = task.strip().lower().rstrip("?!。！？")
        return cleaned in _SIMPLE_PATTERNS or len(cleaned) <= 2

    # ==================================================================
    # Phase 0.5: 缓存
    # ==================================================================

    @staticmethod
    def _cache_key(task: str) -> str:
        return hashlib.md5(task.encode()).hexdigest()

    def _set_cache(self, key: str, result: SkillSelectionResult) -> None:
        if len(self._cache) >= self._cache_max_size:
            first = next(iter(self._cache))
            del self._cache[first]
        self._cache[key] = result

    # ==================================================================
    # Phase 1: 标签过滤
    # ==================================================================

    def _filter_by_tags(
        self,
        task: str,
        candidates: dict[str, BaseSkill],
    ) -> dict[str, BaseSkill]:
        """基于标签同义词集快速过滤候选 skill。"""
        task_lower = task.lower()

        matched_tags: set[str] = set()
        for tag, keywords in _TAG_SYNSET.items():
            if any(kw.lower() in task_lower for kw in keywords):
                matched_tags.add(tag)

        if not matched_tags:
            return {
                name: s
                for name, s in candidates.items()
                if not s.default
            }

        filtered: dict[str, BaseSkill] = {}
        for name, skill in candidates.items():
            if skill.default:
                continue
            if any(t in matched_tags for t in skill.tags):
                filtered[name] = skill

        return filtered or {
            name: s
            for name, s in candidates.items()
            if not s.default
        }

    # ==================================================================
    # Phase 2: LLM 选择
    # ==================================================================

    async def _llm_select(
        self,
        task: str,
        filtered: dict[str, BaseSkill],
        max_skills: int,
    ) -> SkillSelectionResult:
        if self.llm is None:
            raise RuntimeError("SkillSelector requires an LLM instance")

        menu_lines: list[str] = []
        for skill in filtered.values():
            tools_str = ", ".join(skill.tools) if skill.tools else "none"
            deps_str = ", ".join(skill.dependencies) if skill.dependencies else "none"
            menu_lines.append(
                f"- name: {skill.name}\n"
                f"  description: {skill.description or skill.name}\n"
                f"  tools: [{tools_str}]\n"
                f"  dependencies: [{deps_str}]"
            )

        system = _SELECTION_SYSTEM_PROMPT.format(
            max_skills=max_skills,
            skill_menu="\n".join(menu_lines),
            task=task,
        )

        structured_llm = self.llm.with_structured_output(SkillSelectionResult)

        try:
            result: SkillSelectionResult = await structured_llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=task),
            ])
        except Exception as exc:
            logger.warning("LLM skill selection failed: %s, returning empty", exc)
            return SkillSelectionResult(skills=[])

        valid_names = set(filtered.keys())
        result.skills = [
            s for s in result.skills if s.name in valid_names
        ]
        return result

    # ==================================================================
    # Phase 3: 依赖解析
    # ==================================================================

    @staticmethod
    def _resolve_deps(
        selection: SkillSelectionResult,
        all_skills: dict[str, BaseSkill],
    ) -> SkillSelectionResult:
        """解析依赖：选中的 skill 的依赖链全部加入。"""
        from haven.skills.registry import SkillRegistry

        selected_names = [s.name for s in selection.skills]
        resolved = SkillRegistry.resolve_dependencies(selected_names)

        # 追加依赖新增的 skill
        new_names = set(resolved) - set(selected_names)
        for name in new_names:
            if not any(s.name == name for s in selection.skills):
                selection.skills.append(
                    SelectedSkill(name=name, reason="依赖自动激活")
                )

        return selection
