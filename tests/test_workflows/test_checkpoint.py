"""SQLiteCheckpointer — 工作流状态持久化测试。"""
from __future__ import annotations

import pytest


class TestSQLiteCheckpointer:
    """SQLiteCheckpointer save/load 测试。"""

    @pytest.fixture
    def checkpointer(self, temp_db_path):
        from haven.workflows.checkpoint import SQLiteCheckpointer
        return SQLiteCheckpointer(db_path=temp_db_path)

    @pytest.mark.asyncio
    async def test_save_and_load(self, checkpointer, workflow_state):
        """保存后加载，恢复 node_name 和状态。"""
        workflow_state.current_node = "coder"
        workflow_state.node_outputs = {"planner": "需求分析完成"}
        workflow_state.status = "running"
        workflow_state.execution.start()
        workflow_state.execution.current_step = "coder"

        await checkpointer.save("session_1", "coder", workflow_state)

        saved = await checkpointer.load("session_1")
        assert saved is not None
        assert saved["node_name"] == "coder"
        assert saved["state"]["current_node"] == "coder"
        assert saved["execution"] is not None
        assert saved["execution"].status == "running"
        assert saved["execution"].current_step == "coder"

    @pytest.mark.asyncio
    async def test_load_nonexistent_session(self, checkpointer):
        """不存在的 session 返回 None。"""
        result = await checkpointer.load("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, checkpointer, workflow_state):
        """同 session+node 保存时更新已有记录（UPSERT）。"""
        import asyncio

        workflow_state.current_node = "step1"
        workflow_state.node_outputs = {"step1": "v1"}
        await checkpointer.save("session_2", "step1", workflow_state)
        await asyncio.sleep(0.01)

        # 更新同一 session+node 的记录
        workflow_state.node_outputs = {"step1": "v2"}
        await checkpointer.save("session_2", "step1", workflow_state)

        saved = await checkpointer.load("session_2")
        assert saved["node_name"] == "step1"
        # UPSERT 更新后 state_json 反映最新内容
        assert "v2" in saved["state"]["node_outputs"]["step1"]

    @pytest.mark.asyncio
    async def test_list_sessions(self, checkpointer, workflow_state):
        """list_sessions 返回活跃 session 列表。"""
        workflow_state.current_node = "node1"
        await checkpointer.save("session_a", "node1", workflow_state)
        await checkpointer.save("session_b", "node2", workflow_state)

        sessions = await checkpointer.list_sessions()
        # 至少包含刚保存的 session
        session_ids = [s["session_id"] for s in sessions]
        assert "session_a" in session_ids or "session_b" in session_ids

    @pytest.mark.asyncio
    async def test_execution_json_persisted(self, checkpointer, workflow_state):
        """ExecutionState 快照单独持久化到 execution_json 列。"""
        workflow_state.execution.start()
        workflow_state.execution.complete_step("step_a", "output_a")
        workflow_state.current_node = "step_b"

        await checkpointer.save("session_3", "step_b", workflow_state)

        saved = await checkpointer.load("session_3")
        assert saved["execution"] is not None
        es = saved["execution"]
        assert es.status == "running"
        assert "step_a" in es.completed_steps
        assert es.step_outputs.get("step_a") == "output_a"

    @pytest.mark.asyncio
    async def test_serialize_excludes_private_fields(self, checkpointer, workflow_state):
        """序列化时排除 _ 前缀字段。"""
        workflow_state._runtime = object()
        workflow_state.current_node = "test_node"

        await checkpointer.save("session_4", "test_node", workflow_state)

        saved = await checkpointer.load("session_4")
        state_dict = saved["state"]
        # _runtime 不应在序列化数据中
        for key in state_dict:
            if key.startswith("_"):
                assert state_dict[key] is None

    @pytest.mark.asyncio
    async def test_end_node_not_in_sessions(self, checkpointer, workflow_state):
        """__END__ 节点不计入活跃 session 列表。"""
        await checkpointer.save("session_5", "__END__", workflow_state)

        sessions = await checkpointer.list_sessions()
        session_ids = [s["session_id"] for s in sessions]
        # __END__ 被过滤掉
        assert "session_5" not in session_ids


class TestExecutionStateSnapshot:
    """ExecutionState snapshot/from_snapshot 测试。"""

    def test_full_roundtrip(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="abc123", goal="测试任务")
        es.start()
        es.current_step = "step2"
        es.completed_steps = ["step1"]
        es.step_outputs = {"step1": "结果1"}
        es.node_retry_counts = {"step1": 1}
        es.retry_count = 1
        es.max_retries = 5

        data = es.snapshot()
        restored = ExecutionState.from_snapshot(data)

        assert restored.task_id == "abc123"
        assert restored.goal == "测试任务"
        assert restored.current_step == "step2"
        assert restored.completed_steps == ["step1"]
        assert restored.step_outputs == {"step1": "结果1"}
        assert restored.node_retry_counts == {"step1": 1}
        assert restored.retry_count == 1
        assert restored.max_retries == 5
        assert restored.status == "running"

    def test_from_snapshot_defaults(self):
        """from_snapshot 对缺失字段使用默认值。"""
        from haven.runtime.execution import ExecutionState

        es = ExecutionState.from_snapshot({})
        assert es.task_id == ""
        assert es.goal == ""
        assert es.status == "pending"
        assert es.completed_steps == []
        assert es.max_retries == 3


class TestWorkflowStateExecutionSync:
    """WorkflowState 与 ExecutionState 同步测试。"""

    def test_post_init_syncs_goal(self, workflow_state):
        """__post_init__ 将 task 同步到 execution.goal。"""
        assert workflow_state.execution.goal == workflow_state.task

    def test_dev_state_inheritance(self, dev_workflow_state):
        """DevWorkflowState 继承完整。"""
        assert dev_workflow_state.execution is not None
        assert dev_workflow_state.architecture_doc == ""
        assert dev_workflow_state.source_code == ""
        assert dev_workflow_state.review_score == 0.0
        assert dev_workflow_state.test_passed is False


class TestWorkflowStateDomainFields:
    """领域 State 测试。"""

    def test_research_state(self):
        from haven.workflows.state import ResearchWorkflowState
        state = ResearchWorkflowState(task="调研 AI 趋势")
        assert state.research_topic == ""
        assert state.raw_findings == []
        assert state.final_report == ""
        assert state.execution.goal == "调研 AI 趋势"

    def test_diagnosis_state(self):
        from haven.workflows.state import DiagnosisWorkflowState
        state = DiagnosisWorkflowState(task="头疼三天")
        assert state.symptoms == ""
        assert state.diagnosis == ""
        assert state.recommendations == ""
