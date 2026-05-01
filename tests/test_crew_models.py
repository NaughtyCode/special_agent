"""
Crew 模型单元测试。

测试覆盖:
- SubTask 创建与字段
- CrewMember 状态生命周期
- AgentCrew 创建与状态
- CrewResult 数据结构
- Crew 错误类型
"""

import unittest

from src.crew.models import (
    AgentCrew,
    CrewInvalidStateError,
    CrewMember,
    CrewPlanError,
    CrewResult,
    SubTask,
)
from src.core.models import AgentResult, TokenUsage, FinishReason


class TestSubTask(unittest.TestCase):
    """SubTask 测试。"""

    def test_create_with_uuid(self) -> None:
        """测试: create() 自动生成 UUID task_id。"""
        task = SubTask.create(description="Test task")
        self.assertIsNotNone(task.task_id)
        self.assertNotEqual(task.task_id, "")
        self.assertEqual(task.description, "Test task")

    def test_create_with_tags_and_deps(self) -> None:
        """测试: 带标签和依赖的创建。"""
        task = SubTask.create(
            description="Write code",
            required_tags=["code", "python"],
            dependencies=["task_1"],
            context={"key": "value"},
        )
        self.assertEqual(task.required_tags, ["code", "python"])
        self.assertEqual(task.dependencies, ["task_1"])
        self.assertEqual(task.context, {"key": "value"})

    def test_unique_ids(self) -> None:
        """测试: 每个 SubTask 有唯一 ID。"""
        t1 = SubTask.create(description="Task 1")
        t2 = SubTask.create(description="Task 2")
        self.assertNotEqual(t1.task_id, t2.task_id)

    def test_default_values(self) -> None:
        """测试: 直接构造的默认值。"""
        task = SubTask(task_id="id1", description="desc")
        self.assertEqual(task.required_tags, [])
        self.assertEqual(task.dependencies, [])
        self.assertIsNone(task.context)


class TestCrewMember(unittest.TestCase):
    """CrewMember 测试。"""

    def test_default_status(self) -> None:
        """测试: 默认状态为 PENDING。"""
        member = CrewMember(agent_name="TestAgent")
        self.assertEqual(member.status, "PENDING")

    def test_default_timestamps(self) -> None:
        """测试: 默认时间戳为 0。"""
        member = CrewMember(agent_name="TestAgent")
        self.assertEqual(member.started_at, 0.0)
        self.assertEqual(member.completed_at, 0.0)

    def test_full_initialization(self) -> None:
        """测试: 完整初始化。"""
        task = SubTask.create(description="Test")
        member = CrewMember(
            agent_name="TestAgent",
            task=task,
            status="RUNNING",
            started_at=100.0,
        )
        self.assertEqual(member.agent_name, "TestAgent")
        self.assertEqual(member.task, task)
        self.assertEqual(member.status, "RUNNING")


class TestAgentCrew(unittest.TestCase):
    """AgentCrew 测试。"""

    def test_create_auto_generates_uuid(self) -> None:
        """测试: create() 自动生成 UUID。"""
        crew = AgentCrew.create(lead_agent_name="RootAgent", mission="Test mission")
        self.assertIsNotNone(crew.crew_id)
        self.assertNotEqual(crew.crew_id, "")
        self.assertEqual(crew.lead_agent_name, "RootAgent")
        self.assertEqual(crew.mission, "Test mission")

    def test_default_status(self) -> None:
        """测试: 默认状态为 ASSEMBLED。"""
        crew = AgentCrew.create(lead_agent_name="Root", mission="Test")
        self.assertEqual(crew.status, "ASSEMBLED")

    def test_members_empty_initially(self) -> None:
        """测试: 初始成员列表为空。"""
        crew = AgentCrew.create(lead_agent_name="Root", mission="Test")
        self.assertEqual(len(crew.members), 0)

    def test_crew_leader_call_depth(self) -> None:
        """测试: crew_leader_call_depth 传递。"""
        crew = AgentCrew.create(
            lead_agent_name="Root",
            mission="Test",
            crew_leader_call_depth=2,
        )
        self.assertEqual(crew.crew_leader_call_depth, 2)


class TestCrewResult(unittest.TestCase):
    """CrewResult 测试。"""

    def test_success_result(self) -> None:
        """测试: 成功结果。"""
        result = CrewResult(
            success=True,
            crew_id="crew_1",
            mission_summary="All tasks completed",
            member_results=[("Agent1", "task_1", AgentResult(
                success=True,
                final_answer="Done",
                iterations=[],
                token_usage=TokenUsage(),
            ))],
            execution_order=["task_1"],
            total_duration_ms=1500.0,
        )
        self.assertTrue(result.success)
        self.assertEqual(len(result.failed_members), 0)

    def test_failed_result(self) -> None:
        """测试: 包含失败成员的结果。"""
        result = CrewResult(
            success=False,
            crew_id="crew_2",
            mission_summary="Partial failure",
            member_results=[
                ("Agent1", "task_1", AgentResult(
                    success=True,
                    final_answer="OK",
                    iterations=[],
                    token_usage=TokenUsage(),
                )),
                ("Agent2", "task_2", AgentResult(
                    success=False,
                    final_answer="Error",
                    iterations=[],
                    token_usage=TokenUsage(),
                    finish_reason=FinishReason.ERROR,
                )),
            ],
            failed_members=[("Agent2", "task_2")],
        )
        self.assertFalse(result.success)
        self.assertEqual(len(result.failed_members), 1)


class TestCrewErrors(unittest.TestCase):
    """Crew 错误类型测试。"""

    def test_crew_invalid_state_error(self) -> None:
        """测试: CrewInvalidStateError。"""
        err = CrewInvalidStateError("Invalid state transition")
        self.assertEqual(str(err), "Invalid state transition")

    def test_crew_plan_error_basic(self) -> None:
        """测试: CrewPlanError 基础消息。"""
        err = CrewPlanError("Plan failed")
        self.assertEqual(str(err), "Plan failed")
        self.assertIsNone(err.raw_llm_output)

    def test_crew_plan_error_with_raw_output(self) -> None:
        """测试: CrewPlanError 携带 LLM 原始输出。"""
        raw = "{invalid json}"
        err = CrewPlanError("Plan failed", raw_llm_output=raw)
        self.assertEqual(str(err), "Plan failed")
        self.assertEqual(err.raw_llm_output, raw)


if __name__ == "__main__":
    unittest.main()
