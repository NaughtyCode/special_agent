"""
ContextStore 单元测试。

测试覆盖:
- 消息添加与获取
- LLM 消息获取 (含压缩)
- Token 估算
- ReAct 轨迹记录
- 上下文变量操作
- Tool 结果缓存
- 导出/导入快照
"""

import unittest
from unittest.mock import MagicMock

from src.core.context_store import ContextStore
from src.core.models import Message, ReActStep, ActionResult, ChatResponse, TokenUsage
from src.infra.config import Config


class TestContextStoreBase(unittest.TestCase):
    """ContextStore 基础测试。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.store = ContextStore(self.config)

    def test_add_message(self) -> None:
        """测试: 添加消息。"""
        self.store.add_message(role="user", content="Hello")
        msgs = self.store.get_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "user")
        self.assertEqual(msgs[0].content, "Hello")

    def test_add_message_with_tool_calls(self) -> None:
        """测试: 添加带 tool_calls 的消息。"""
        from src.core.models import ToolCall as TC
        tc = TC(id="c1", function_name="search", function_args={"q": "test"})
        self.store.add_message(role="assistant", content="Searching...", tool_calls=[tc])
        msgs = self.store.get_messages()
        self.assertEqual(len(msgs[0].tool_calls), 1)  # type: ignore[union-attr]

    def test_system_message_preserved(self) -> None:
        """测试: system message 被引用保存。"""
        self.store.add_message(role="system", content="You are helpful.")
        msgs = self.store.get_messages_for_llm()
        self.assertEqual(len(msgs), 1)

    def test_get_last_n_messages(self) -> None:
        """测试: 获取最近 N 条消息。"""
        for i in range(5):
            self.store.add_message(role="user", content=f"msg {i}")
        recent = self.store.get_messages(last_n=3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1].content, "msg 4")

    def test_estimate_tokens_heuristic(self) -> None:
        """测试: 启发式 Token 估算 (字符数/4)。"""
        self.store.add_message(role="user", content="A" * 400)  # ~100 tokens
        estimated = self.store.estimate_tokens()
        self.assertGreater(estimated, 0)
        self.assertLessEqual(estimated, 200)  # 保守上限

    def test_clear_preserves_system_message(self) -> None:
        """测试: clear() 保留 system message。"""
        self.store.add_message(role="system", content="preserved")
        self.store.add_message(role="user", content="removed")
        self.store.clear()
        msgs = self.store.get_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "preserved")


class TestReActTrajectory(unittest.TestCase):
    """ReAct 轨迹记录测试。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.store = ContextStore(self.config)

    def test_add_react_step(self) -> None:
        """测试: 记录 ReAct 步。"""
        step = ReActStep(
            iteration=1,
            thought="Need to read a file",
            action_name="read_file",
            action_input={"path": "test.py"},
            observation="File contents...",
            action_result=ActionResult(success=True, observation="File contents..."),
            llm_response=ChatResponse(content=""),
            duration_ms=100.0,
            timestamp=1234567890.0,
        )
        self.store.add_react_step(step)
        trajectory = self.store.get_react_trajectory()
        self.assertEqual(len(trajectory), 1)
        self.assertEqual(trajectory[0].action_name, "read_file")

    def test_get_last_n_steps(self) -> None:
        """测试: 获取最近 N 步。"""
        for i in range(5):
            step = ReActStep(
                iteration=i + 1,
                thought=f"Step {i + 1}",
                action_name="test",
                action_input={},
                observation="ok",
                action_result=ActionResult(success=True, observation="ok"),
                llm_response=ChatResponse(content=""),
                duration_ms=10.0,
                timestamp=float(i),
            )
            self.store.add_react_step(step)

        last_2 = self.store.get_last_n_steps(2)
        self.assertEqual(len(last_2), 2)
        self.assertEqual(last_2[0].iteration, 4)
        self.assertEqual(last_2[1].iteration, 5)


class TestVariables(unittest.TestCase):
    """上下文变量操作测试。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.store = ContextStore(self.config)

    def test_set_and_get_variable(self) -> None:
        """测试: 设置和获取变量。"""
        self.store.set_variable("project_root", "/home/user/project")
        self.assertEqual(self.store.get_variable("project_root"), "/home/user/project")

    def test_get_variable_default(self) -> None:
        """测试: 不存在的变量返回默认值。"""
        self.assertIsNone(self.store.get_variable("not_exist"))
        self.assertEqual(self.store.get_variable("not_exist", "default"), "default")

    def test_get_all_variables(self) -> None:
        """测试: 获取所有变量副本。"""
        self.store.set_variable("a", 1)
        self.store.set_variable("b", 2)
        all_vars = self.store.get_all_variables()
        self.assertEqual(all_vars, {"a": 1, "b": 2})
        # 确保返回的是副本
        all_vars["c"] = 3
        self.assertIsNone(self.store.get_variable("c"))


class TestToolResultCache(unittest.TestCase):
    """Tool 结果缓存测试。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.store = ContextStore(self.config)

    def test_cache_and_retrieve(self) -> None:
        """测试: 缓存和检索 Tool 结果。"""
        self.store.cache_tool_result("read_file", {"path": "a.txt"}, "content")
        cached = self.store.get_cached_result("read_file", path="a.txt")
        self.assertEqual(cached, "content")

    def test_cache_miss(self) -> None:
        """测试: 缓存未命中。"""
        result = self.store.get_cached_result("read_file", path="missing.txt")
        self.assertIsNone(result)

    def test_cache_different_args(self) -> None:
        """测试: 不同参数产生不同缓存 key。"""
        self.store.cache_tool_result("read_file", {"path": "a.txt"}, "content_a")
        self.store.cache_tool_result("read_file", {"path": "b.txt"}, "content_b")
        self.assertEqual(
            self.store.get_cached_result("read_file", path="a.txt"), "content_a"
        )
        self.assertEqual(
            self.store.get_cached_result("read_file", path="b.txt"), "content_b"
        )


class TestExportImport(unittest.TestCase):
    """导出/导入快照测试。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.store = ContextStore(self.config)

    def test_export_snapshot(self) -> None:
        """测试: 导出快照。"""
        self.store.add_message(role="user", content="Hello")
        self.store.set_variable("key", "value")
        snapshot = self.store.export_snapshot()

        self.assertIn("messages", snapshot)
        self.assertIn("variables", snapshot)
        self.assertEqual(len(snapshot["messages"]), 1)
        self.assertEqual(snapshot["variables"]["key"], "value")

    def test_import_snapshot(self) -> None:
        """测试: 从快照恢复上下文。"""
        self.store.add_message(role="user", content="Original")
        snapshot = self.store.export_snapshot()

        new_store = ContextStore(self.config)
        new_store.import_snapshot(snapshot)

        msgs = new_store.get_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "Original")


class TestCompression(unittest.TestCase):
    """上下文压缩测试。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.config.context_max_tokens = 100  # 很低的限制触发压缩
        self.store = ContextStore(self.config)

    def test_compression_triggered(self) -> None:
        """测试: 超限时触发压缩。"""
        # 添加大量消息使 token 数超限
        for i in range(50):
            self.store.add_message(role="user", content=f"Message number {i} with lots of padding " + "x" * 100)
        messages = self.store.get_messages_for_llm()
        # 压缩后消息数应显著减少
        self.assertLess(len(messages), 50)


if __name__ == "__main__":
    unittest.main()
