"""ContextManager — 统一上下文收集与组装测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestContextManagerBuild:
    """ContextManager.build() 测试。"""

    @pytest.fixture
    def cm(self, runtime_with_mock_llm):
        return runtime_with_mock_llm.context_manager

    def test_build_empty(self, cm):
        """无任何输入 → 空 system_prompt。"""
        bundle = cm.build(use_memory=False)
        assert bundle.system_prompt == ""
        assert bundle.token_usage == 0

    def test_build_with_personality_skill(self, cm, register_test_skills):
        """人格 skill 注入 system prompt。"""
        haven = register_test_skills["haven"]
        bundle = cm.build(personality_skills=[haven], use_memory=False)
        assert "有帮助的 AI 助手" in bundle.system_prompt

    def test_build_with_domain_skill(self, cm, register_test_skills):
        """领域 skill 注入 system prompt。"""
        coder = register_test_skills["coder"]
        bundle = cm.build(domain_skills=[coder], use_memory=False)
        assert "代码编写专家" in bundle.system_prompt

    def test_build_with_tool_results(self, cm):
        """工具结果注入。"""
        bundle = cm.build(
            tool_results={"web_search": "搜索结果: Python 3.14 发布"},
            use_memory=False,
        )
        assert "web_search" in bundle.system_prompt
        assert "搜索结果" in bundle.system_prompt

    def test_build_with_rag_context(self, cm):
        """RAG 上下文注入。"""
        bundle = cm.build(rag_context="Python 3.14 新特性", use_memory=False)
        assert "参考知识" in bundle.system_prompt
        assert "Python 3.14" in bundle.system_prompt

    def test_build_with_rag_already_tagged(self, cm):
        """RAG 内容已有标签时不重复添加前缀。"""
        bundle = cm.build(rag_context="[已有标签] 知识内容", use_memory=False)
        # 已有 [ 开头，不会再添加 "参考知识" 前缀
        assert "[已有标签] 知识内容" in bundle.system_prompt

    def test_build_all_sources_combined(self, cm, register_test_skills):
        """所有来源合并后的 system prompt。"""
        haven = register_test_skills["haven"]
        coder = register_test_skills["coder"]

        bundle = cm.build(
            personality_skills=[haven],
            domain_skills=[coder],
            tool_results={"echo": "ech oresult"},
            rag_context="参考内容",
            use_memory=False,
        )
        prompt = bundle.system_prompt
        assert "有帮助的 AI 助手" in prompt
        assert "代码编写专家" in prompt
        assert "echo" in prompt
        assert "参考内容" in prompt


class TestContextManagerCollect:
    """ContextManager.collect() 测试。"""

    @pytest.fixture
    def cm(self, runtime_with_mock_llm):
        return runtime_with_mock_llm.context_manager

    def test_collect_returns_items(self, cm, register_test_skills):
        """collect 返回 ContextItem 列表。"""
        items = cm.collect(
            personality_skills=[register_test_skills["haven"]],
            use_memory=False,
        )
        assert len(items) == 1
        from haven.core.context import ContextItem, ContextSource
        assert isinstance(items[0], ContextItem)
        assert items[0].source == ContextSource.PERSONALITY

    def test_collect_multiple_sources(self, cm, register_test_skills):
        """多来源收集。"""
        items = cm.collect(
            personality_skills=[register_test_skills["haven"]],
            domain_skills=[register_test_skills["coder"]],
            tool_results={"a": "b"},
            rag_context="rag data",
            use_memory=False,
        )
        assert len(items) >= 3

    def test_collect_skips_empty_content(self, cm):
        """空 prompt 的 skill 被跳过。"""
        from haven.skills.base_skill import BaseSkill
        empty = BaseSkill(name="empty", description="", prompt="", default=False)
        items = cm.collect(personality_skills=[empty], use_memory=False)
        assert len(items) == 0


class TestContextAssembler:
    """ContextAssembler 测试。"""

    def test_assemble_empty(self):
        from haven.core.context import ContextAssembler
        assembler = ContextAssembler(max_tokens=4000)
        result = assembler.assemble([])
        assert result == ""

    def test_assemble_sorts_by_priority(self):
        from haven.core.context import ContextAssembler, ContextItem, ContextSource
        assembler = ContextAssembler(max_tokens=4000)

        items = [
            ContextItem(content="low priority", source=ContextSource.RAG),
            ContextItem(content="high priority", source=ContextSource.PERSONALITY),
        ]
        result = assembler.assemble(items)
        # PERSONALITY (0) < RAG (5)，high priority 应在前
        assert result.index("high priority") < result.index("low priority")

    def test_assemble_truncates_on_budget(self):
        from haven.core.context import ContextAssembler, ContextItem, ContextSource
        assembler = ContextAssembler(max_tokens=5)  # 极小预算

        # 约 15 tokens 的文本
        long_text = "这是一段很长很长的中文文本内容用于测试截断逻辑"
        items = [ContextItem(content=long_text, source=ContextSource.PERSONALITY)]
        result = assembler.assemble(items)
        # 高优先级的内容被截断或跳过
        assert "已截断" in result or len(result) < len(long_text)

    def test_assemble_respects_priority_under_budget(self):
        from haven.core.context import ContextAssembler, ContextItem, ContextSource
        # 高优内容排入，低优超出时被截断
        assembler = ContextAssembler(max_tokens=200)

        # "高优内容" ≈ 6 tokens, 低优 ≈ 450 tokens → 超出预算
        long_low = "低优" + "长" * 300
        items = [
            ContextItem(content="高优内容", source=ContextSource.PERSONALITY),
            ContextItem(content=long_low, source=ContextSource.RAG),
        ]
        result = assembler.assemble(items)
        assert "高优内容" in result
        # 低优内容超出预算后被截断或丢弃（不包含完整"低优"开头的长文本）
        assert result == "高优内容" or "已截断" in result


class TestTokenBudget:
    """TokenBudget 测试。"""

    def test_estimate_chinese(self):
        from haven.core.context import TokenBudget
        budget = TokenBudget(max_tokens=4000)
        tokens = budget.estimate("你好世界")
        assert tokens > 0
        # 中文: 4 char × 1.5 = 6 tokens
        assert tokens == 6

    def test_estimate_english(self):
        from haven.core.context import TokenBudget
        budget = TokenBudget(max_tokens=4000)
        tokens = budget.estimate("hello")
        assert tokens > 0
        # ASCII: 5 chars / 3 ≈ 1.67 → 1
        assert tokens == 1

    def test_fits(self):
        from haven.core.context import TokenBudget
        budget = TokenBudget(max_tokens=10)
        assert budget.fits("hi") is True
        assert budget.fits("x" * 100) is False


class TestContextManagerWorkflow:
    """ContextManager workflow 状态收集测试。"""

    @pytest.fixture
    def cm(self, runtime_with_mock_llm):
        return runtime_with_mock_llm.context_manager

    def test_collect_workflow_state(self, cm):
        """WorkflowState 注入 current_node 和 node_outputs。"""
        from haven.workflows.state import WorkflowState
        state = WorkflowState(task="test")
        state.current_node = "coder"
        state.node_outputs = {"planner": "需求分析结果"}

        bundle = cm.build(workflow_state=state, use_memory=False)
        assert "coder" in bundle.system_prompt
        assert "planner" in bundle.system_prompt

    def test_collect_workflow_no_current_node(self, cm):
        """无 current_node 时不注入节点标签。"""
        from haven.workflows.state import WorkflowState
        state = WorkflowState(task="test")
        # current_node 为空
        bundle = cm.build(workflow_state=state, use_memory=False)
        assert bundle.system_prompt == ""


class TestContextManagerExtension:
    """注册扩展收集器测试。"""

    @pytest.fixture
    def cm(self, runtime_with_mock_llm):
        return runtime_with_mock_llm.context_manager

    def test_register_collector(self, cm):
        from haven.core.context import ContextSource, ContextItem

        def custom_collector():
            return ContextItem(content="自定义上下文", source=ContextSource.TOOL_RESULT)

        cm.register_collector(ContextSource.TOOL_RESULT, custom_collector)
        bundle = cm.build(use_memory=False)
        assert "自定义上下文" in bundle.system_prompt
