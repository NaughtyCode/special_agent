"""
LLMClient 和 TokenTracker 单元测试。

测试覆盖:
- TokenTracker: record, get_total, get_by_session, reset
- TokenUsage: 加法操作, 默认值
"""

import unittest

from src.core.models import TokenUsage
from src.llm.llm_client import TokenTracker


class TestTokenUsage(unittest.TestCase):
    """TokenUsage 测试。"""

    def test_default_values(self) -> None:
        """测试: 默认值均为 0。"""
        usage = TokenUsage()
        self.assertEqual(usage.prompt_tokens, 0)
        self.assertEqual(usage.completion_tokens, 0)
        self.assertEqual(usage.total_tokens, 0)

    def test_add_two_instances(self) -> None:
        """测试: TokenUsage 加法运算。"""
        a = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        b = TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300)
        c = a + b
        self.assertEqual(c.prompt_tokens, 300)
        self.assertEqual(c.completion_tokens, 150)
        self.assertEqual(c.total_tokens, 450)

    def test_add_not_implemented(self) -> None:
        """测试: 非 TokenUsage 加法返回 NotImplemented。"""
        a = TokenUsage()
        result = a.__add__(42)  # type: ignore
        self.assertIs(result, NotImplemented)


class TestTokenTracker(unittest.TestCase):
    """TokenTracker 测试。"""

    def setUp(self) -> None:
        self.tracker = TokenTracker()

    def test_record_updates_total(self) -> None:
        """测试: record 更新总计。"""
        self.tracker.record(TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150))
        total = self.tracker.get_total()
        self.assertEqual(total.prompt_tokens, 100)
        self.assertEqual(total.completion_tokens, 50)
        self.assertEqual(total.total_tokens, 150)

    def test_record_increments_call_count(self) -> None:
        """测试: record 增加调用计数。"""
        self.tracker.record(TokenUsage())
        self.tracker.record(TokenUsage())
        self.assertEqual(self.tracker.call_count, 2)

    def test_multiple_records_accumulate(self) -> None:
        """测试: 多次 record 累加 Token。"""
        self.tracker.record(TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))
        self.tracker.record(TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30))
        total = self.tracker.get_total()
        self.assertEqual(total.prompt_tokens, 30)
        self.assertEqual(total.total_tokens, 45)

    def test_get_by_session(self) -> None:
        """测试: 按会话获取 Token 用量 (返回默认为空)。"""
        usage = self.tracker.get_by_session("session_1")
        self.assertEqual(usage.total_tokens, 0)

    def test_get_by_session_idempotent(self) -> None:
        """测试: 多次获取同一会话返回同一对象。"""
        u1 = self.tracker.get_by_session("s1")
        u2 = self.tracker.get_by_session("s1")
        self.assertIs(u1, u2)

    def test_reset(self) -> None:
        """测试: 重置 Token 计数。"""
        self.tracker.record(TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150))
        self.tracker.reset()
        total = self.tracker.get_total()
        self.assertEqual(total.total_tokens, 0)
        self.assertEqual(self.tracker.call_count, 0)

    def test_initial_call_count_zero(self) -> None:
        """测试: 初始调用计数为 0。"""
        self.assertEqual(self.tracker.call_count, 0)


if __name__ == "__main__":
    unittest.main()
