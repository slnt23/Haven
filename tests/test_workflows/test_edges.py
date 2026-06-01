"""Edge / ConditionalEdge + Router 函数测试。"""
from __future__ import annotations

import pytest


class TestEdge:
    """Edge 无条件边测试。"""

    def test_edge_creation(self):
        from haven.workflows.edges import Edge
        e = Edge("source", "target")
        assert e.source == "source"
        assert e.target == "target"

    def test_edge_repr(self):
        from haven.workflows.edges import Edge
        e = Edge("A", "B")
        assert "A" in repr(e)
        assert "B" in repr(e)


class TestConditionalEdge:
    """ConditionalEdge 条件边测试。"""

    def test_edge_creation(self):
        from haven.workflows.edges import ConditionalEdge

        def dummy_router(state):
            return "next"

        e = ConditionalEdge("source", dummy_router)
        assert e.source == "source"
        assert e.router is dummy_router
        assert e.route_map == {}

    @pytest.mark.asyncio
    async def test_resolve_sync_router(self):
        from haven.workflows.edges import ConditionalEdge

        def router(state):
            return "target_b"

        e = ConditionalEdge("source", router, {"target_b": "B"})

        class FakeState:
            pass

        result = await e.resolve(FakeState())
        assert result == "B"

    @pytest.mark.asyncio
    async def test_resolve_async_router(self):
        from haven.workflows.edges import ConditionalEdge

        async def async_router(state):
            return "async_target"

        e = ConditionalEdge("source", async_router)
        result = await e.resolve({})
        assert result == "async_target"

    def test_retry_sentinel(self):
        from haven.workflows.edges import ConditionalEdge
        assert ConditionalEdge.RETRY == "__RETRY__"
        assert ConditionalEdge.END == "__END__"


class TestRouterFunctions:
    """内置 Router 函数测试。"""

    def test_test_router_pass(self):
        from haven.workflows.edges import test_router, ConditionalEdge
        from haven.workflows.state import DevWorkflowState

        state = DevWorkflowState(task="test")
        state.test_passed = True

        result = test_router(state)
        assert result == ConditionalEdge.END

    def test_test_router_fail_within_retry(self):
        from haven.workflows.edges import test_router, ConditionalEdge
        from haven.workflows.state import DevWorkflowState

        state = DevWorkflowState(task="test")
        state.test_passed = False
        state.node_retry_counts = {"coder": 1}
        state.max_retries_per_node = 3

        result = test_router(state)
        assert result == "coder"

    def test_test_router_fail_exceeded_retry(self):
        from haven.workflows.edges import test_router, ConditionalEdge
        from haven.workflows.state import DevWorkflowState

        state = DevWorkflowState(task="test")
        state.test_passed = False
        state.node_retry_counts = {"coder": 5}
        state.max_retries_per_node = 3

        result = test_router(state)
        assert result == ConditionalEdge.END

    def test_research_quality_router_with_gap(self):
        from haven.workflows.edges import research_quality_router
        from haven.workflows.state import ResearchWorkflowState

        state = ResearchWorkflowState(task="research")
        state.analyzed_insights = "发现了一些结果，但仍有知识缺口需要补充"
        state.node_retry_counts = {"searcher": 1}

        result = research_quality_router(state)
        assert result == "searcher"

    def test_research_quality_router_no_gap(self):
        from haven.workflows.edges import research_quality_router
        from haven.workflows.state import ResearchWorkflowState

        state = ResearchWorkflowState(task="research")
        state.analyzed_insights = "全面分析完成"
        state.node_retry_counts = {"searcher": 1}

        result = research_quality_router(state)
        assert result == "synthesizer"

    def test_research_quality_router_exceeded_retry(self):
        from haven.workflows.edges import research_quality_router
        from haven.workflows.state import ResearchWorkflowState

        state = ResearchWorkflowState(task="research")
        state.analyzed_insights = "知识缺口"
        state.node_retry_counts = {"searcher": 5}

        result = research_quality_router(state)
        assert result == "synthesizer"
