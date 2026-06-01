"""共享 fixtures — mock LLM、Runtime、ToolManager、Memory 等。"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models import BaseChatModel

# 确保 src/haven 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


# ============================================================================
# Mock LLM
# ============================================================================


class MockLLMResponse:
    """可配置的 mock LLM。"""

    def __init__(self, content: str = "mock response"):
        self.content = content

    async def ainvoke(self, messages, **kwargs):
        return AIMessage(content=self.content)


def make_mock_llm(content: str = "mock response") -> MagicMock:
    """创建 mock BaseChatModel，ainvoke 返回指定内容。"""
    llm = MagicMock(spec=BaseChatModel)
    llm.model_name = "mock-model"
    llm.ainvoke = AsyncMock(return_value=AIMessage(content=content))

    def _bind_tools(tools):
        return llm

    llm.bind_tools = MagicMock(side_effect=_bind_tools)
    return llm


def make_mock_structured_llm(plan_result) -> MagicMock:
    """创建 mock LLM，其 with_structured_output 返回 ainvoke 产生 plan_result。"""
    llm = MagicMock(spec=BaseChatModel)
    llm.model_name = "mock-model"

    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=plan_result)

    llm.with_structured_output = MagicMock(return_value=structured)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="mock response"))

    def _bind_tools(tools):
        return llm

    llm.bind_tools = MagicMock(side_effect=_bind_tools)
    return llm


# ============================================================================
# Runtime Fixtures
# ============================================================================


@pytest.fixture
def mock_llm():
    """基础 mock LLM — ainvoke 返回 'mock response'。"""
    return make_mock_llm()


@pytest.fixture
def runtime_with_mock_llm(mock_llm):
    """AgentRuntime 注入 mock LLM（不通过 create_agent，手动构建）。"""
    from haven.runtime.runtime import AgentRuntime
    from haven.core.context import ContextManager

    rt = AgentRuntime(name="test")
    rt.llm = mock_llm
    rt.context_manager = ContextManager(memory=rt.memory, max_system_tokens=4000)
    return rt


# ============================================================================
# DB Fixtures
# ============================================================================


@pytest.fixture
def temp_db():
    """临时 SQLite 数据库路径。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def memory_db_conn(temp_db):
    """SQLite 连接 (row_factory=Row)，语义/情景记忆使用。"""
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ============================================================================
# ToolManager / ToolResolver Fixtures
# ============================================================================


@pytest.fixture
def empty_tool_manager():
    """空的 ToolManager（未启动，无 provider）。"""
    from haven.tools.manager import ToolManager
    return ToolManager()


@pytest.fixture
async def populated_tool_manager():
    """已启动的 ToolManager（含 BuiltinProvider 工具）。"""
    from haven.tools.manager import ToolManager
    from haven.tools.providers.builtin import BuiltinProvider

    tm = ToolManager()
    tm.add_provider(BuiltinProvider())
    await tm.start_all()
    return tm


@pytest.fixture
def tool_resolver(populated_tool_manager):
    """ToolResolver 绑定已启动的 ToolManager。"""
    from haven.tools.resolver import ToolResolver
    return ToolResolver(populated_tool_manager)


# ============================================================================
# Skill Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clean_skill_registry():
    """每个测试前后清空 SkillRegistry。"""
    from haven.skills.registry import SkillRegistry
    SkillRegistry.clear()
    yield
    SkillRegistry.clear()


@pytest.fixture
def register_test_skills():
    """注册测试用 skill 到 SkillRegistry。"""
    from haven.skills.registry import SkillRegistry
    from haven.skills.base_skill import BaseSkill

    coder = BaseSkill(
        name="coder",
        description="代码编写与开发相关任务",
        prompt="你是代码编写专家，负责软件开发相关任务。",
        tags=["development", "coding"],
        tools=["code_exec", "file_ops", "web_search"],
        default=False,
    )
    medical = BaseSkill(
        name="medical",
        description="医学知识查询与健康建议",
        tags=["health", "knowledge"],
        tools=["medical_kb"],
        default=False,
    )
    code_review = BaseSkill(
        name="code_review",
        description="代码审查",
        tags=["development"],
        tools=["code_exec"],
        dependencies=["coder"],
        default=False,
    )
    haven_skill = BaseSkill(
        name="haven",
        description="Haven 系统人格",
        prompt="你是一个有帮助的 AI 助手。",
        tags=["system"],
        tools=[],
        default=True,
    )

    SkillRegistry.register_instance(haven_skill)
    SkillRegistry.register_instance(coder)
    SkillRegistry.register_instance(medical)
    SkillRegistry.register_instance(code_review)
    return {"coder": coder, "medical": medical, "code_review": code_review, "haven": haven_skill}


# ============================================================================
# Workflow Fixtures
# ============================================================================


@pytest.fixture
def workflow_state():
    """基础 WorkflowState。"""
    from haven.workflows.state import WorkflowState
    return WorkflowState(task="test task", session_id="test_session")


@pytest.fixture
def dev_workflow_state():
    """DevWorkflowState。"""
    from haven.workflows.state import DevWorkflowState
    return DevWorkflowState(task="写一个排序算法", session_id="test_session")


@pytest.fixture
def mock_node():
    """创建返回固定结果的 mock WorkflowNode。"""

    class _MockNode:
        def __init__(self, name="mock_node", output="mock output"):
            self.name = name
            self._output = output

        async def __call__(self, state):
            return {
                "current_node": self.name,
                "node_outputs": {**state.node_outputs, self.name: self._output},
            }

    return _MockNode


@pytest.fixture
def temp_db_path():
    """临时 checkpoint 数据库路径。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass
