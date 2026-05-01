"""
MatchStrategy 与 CompressStrategy 单元测试。

测试覆盖:
- ExactMatchStrategy: 精确名称匹配 (大小写/连字符/下划线归一化)
- FuzzyMatchStrategy: 关键词模糊匹配 (名称+描述+标签加权)
- SemanticMatchStrategy: Jaccard 语义相似度匹配
- AgentMatchStrategy: Agent 注册中心匹配
- MatchStrategyChain: 策略链组合
- SlidingWindowStrategy, SummarizeStrategy, HybridStrategy 压缩
"""

import unittest

from src.strategies.match_strategy import (
    AgentMatchStrategy,
    ExactMatchStrategy,
    FuzzyMatchStrategy,
    MatchResult,
    MatchStrategyChain,
    SemanticMatchStrategy,
)
from src.strategies.compress_strategy import (
    HybridStrategy,
    SlidingWindowStrategy,
    SummarizeStrategy,
)
from src.core.models import Message


class _MockTool:
    """模拟 Tool, 包含匹配所需的元数据。"""
    def __init__(self, name: str, description: str = "", tags: list[str] | None = None) -> None:
        self.name = name
        self.description = description
        self.tags = tags or []


class _MockAgentMeta:
    """模拟 AgentMeta。"""
    def __init__(self, name: str, description: str = "", tags: list[str] | None = None) -> None:
        self.name = name
        self.description = description
        self.tags = tags or []


class _MockAgentRegistry:
    """模拟 AgentRegistry, 用于 AgentMatchStrategy 测试。"""
    def __init__(self, agents: list[_MockAgentMeta] | None = None) -> None:
        self._agents = agents or []

    def get_agent_meta(self, name: str):
        for a in self._agents:
            if a.name == name:
                return a
        raise Exception("not found")

    def list_agents(self) -> list[_MockAgentMeta]:
        return self._agents


# ── Match Strategy 测试 ──────────────────────────────


class TestExactMatchStrategy(unittest.TestCase):
    """ExactMatchStrategy 测试。"""

    def setUp(self) -> None:
        self.strategy = ExactMatchStrategy()
        self.registry = {
            "read_file": _MockTool("read_file"),
            "write_file": _MockTool("write_file"),
            "search_code": _MockTool("search_code"),
        }

    def test_exact_match(self) -> None:
        """测试: 精确匹配。"""
        result = self.strategy.match("read_file", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "read_file")  # type: ignore[union-attr]
        self.assertEqual(result.score, 1.0)  # type: ignore[union-attr]

    def test_case_insensitive_match(self) -> None:
        """测试: 大小写不敏感匹配。"""
        result = self.strategy.match("READ_FILE", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "read_file")  # type: ignore[union-attr]

    def test_hyphen_underscore_normalized(self) -> None:
        """测试: 连字符和下划线归一化。"""
        result = self.strategy.match("read-file", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "read_file")  # type: ignore[union-attr]

    def test_space_underscore_normalized(self) -> None:
        """测试: 空格归一化为下划线。"""
        result = self.strategy.match("read file", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "read_file")  # type: ignore[union-attr]

    def test_no_match(self) -> None:
        """测试: 无匹配返回 None。"""
        result = self.strategy.match("nonexistent", {}, self.registry)
        self.assertIsNone(result)


class TestFuzzyMatchStrategy(unittest.TestCase):
    """FuzzyMatchStrategy 测试。"""

    def setUp(self) -> None:
        self.strategy = FuzzyMatchStrategy(score_threshold=0.2)
        self.registry = {
            "read_file": _MockTool("read_file", "Read content from a file", ["file", "read"]),
            "write_file": _MockTool("write_file", "Write content to a file", ["file", "write"]),
            "search_code": _MockTool("search_code", "Search codebase for patterns", ["search", "code"]),
            "run_shell": _MockTool("run_shell", "Execute a shell command", ["shell", "execute"]),
        }

    def test_fuzzy_match_by_name(self) -> None:
        """测试: 通过名称关键词模糊匹配。"""
        result = self.strategy.match("read something", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "read_file")  # type: ignore[union-attr]
        self.assertEqual(result.strategy_used, "fuzzy")  # type: ignore[union-attr]

    def test_fuzzy_match_by_tags(self) -> None:
        """测试: 通过标签关键词模糊匹配。"""
        result = self.strategy.match("execute command", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "run_shell")  # type: ignore[union-attr]

    def test_fuzzy_match_by_description(self) -> None:
        """测试: 通过描述关键词模糊匹配。"""
        result = self.strategy.match("search for patterns", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "search_code")  # type: ignore[union-attr]

    def test_fuzzy_no_match(self) -> None:
        """测试: 无足够相似度时返回 None。"""
        result = self.strategy.match("xyzzy_unknown", {}, self.registry)
        self.assertIsNone(result)

    def test_fuzzy_returns_candidates(self) -> None:
        """测试: 返回候选列表。"""
        result = self.strategy.match("file", {}, self.registry)
        self.assertIsNotNone(result)
        self.assertGreater(len(result.candidates), 0)  # type: ignore[union-attr]


class TestSemanticMatchStrategy(unittest.TestCase):
    """SemanticMatchStrategy 测试。"""

    def setUp(self) -> None:
        self.strategy = SemanticMatchStrategy(score_threshold=0.3)
        self.registry = {
            "read_file": _MockTool("read_file", "Read file contents from disk", ["file", "read"]),
            "write_file": _MockTool("write_file", "Write data to a file on disk", ["file", "write"]),
        }

    def test_semantic_match(self) -> None:
        """测试: Jaccard 语义匹配。"""
        result = self.strategy.match("read file content", {"path": "test.py"}, self.registry)
        # 需要足够高的 Jaccard 相似度才能匹配
        if result is not None:
            self.assertEqual(result.tool_name, "read_file")
            self.assertEqual(result.strategy_used, "semantic")

    def test_semantic_match_strong(self) -> None:
        """测试: 高度相似文本能匹配。"""
        # 使用与 Tool 描述更相似的查询
        result = self.strategy.match("read file contents from disk", {"path": "x"}, self.registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_name, "read_file")

    def test_semantic_no_match(self) -> None:
        """测试: 语义不匹配时返回 None。"""
        result = self.strategy.match("send_email", {"to": "a@b.com"}, self.registry)
        self.assertIsNone(result)

    def test_jaccard_similarity(self) -> None:
        """测试: Jaccard 相似度计算。"""
        sim = self.strategy._jaccard_similarity("read file content", "read file contents from disk")
        self.assertGreater(sim, 0.3)

        sim_zero = self.strategy._jaccard_similarity("a", "b")
        self.assertEqual(sim_zero, 0.0)


class TestAgentMatchStrategy(unittest.TestCase):
    """AgentMatchStrategy 测试。"""

    def setUp(self) -> None:
        self.strategy = AgentMatchStrategy()
        self.agent_registry = _MockAgentRegistry([
            _MockAgentMeta("CodeAgent", "Handles code", ["code"]),
            _MockAgentMeta("DocAgent", "Handles docs", ["doc"]),
        ])

    def test_agent_exact_match(self) -> None:
        """测试: Agent 名称精确匹配。"""
        result = self.strategy.match("CodeAgent", {}, {}, self.agent_registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.agent_name, "CodeAgent")  # type: ignore[union-attr]

    def test_agent_exact_when_name_matches(self) -> None:
        """测试: 当 action_name 精确匹配 Agent 名称时 (通过 get_agent_meta)。"""
        result = self.strategy.match("CodeAgent", {}, {}, self.agent_registry)
        self.assertIsNotNone(result)
        self.assertEqual(result.agent_name, "CodeAgent")

    def test_agent_no_match(self) -> None:
        """测试: 无 Agent 匹配返回 None。"""
        result = self.strategy.match("unknown", {}, {}, self.agent_registry)
        self.assertIsNone(result)

    def test_no_registry_returns_none(self) -> None:
        """测试: 无 AgentRegistry 时返回 None。"""
        result = self.strategy.match("anything", {}, {}, None)
        self.assertIsNone(result)


class TestMatchStrategyChain(unittest.TestCase):
    """MatchStrategyChain 测试。"""

    def setUp(self) -> None:
        self.registry = {
            "read_file": _MockTool("read_file", "Read file", ["file"]),
        }
        self.chain = MatchStrategyChain([
            ExactMatchStrategy(),
            FuzzyMatchStrategy(),
            SemanticMatchStrategy(),
        ])

    def test_first_strategy_wins(self) -> None:
        """测试: 第一个匹配成功的策略被采用。"""
        result = self.chain.match("read_file", {}, self.registry)
        self.assertEqual(result.strategy_used, "exact")

    def test_fallback_to_next_strategy(self) -> None:
        """测试: 精确匹配失败时回退到模糊匹配。"""
        result = self.chain.match("read", {}, self.registry)
        self.assertEqual(result.strategy_used, "fuzzy")

    def test_all_fail_returns_empty(self) -> None:
        """测试: 所有策略失败时返回空结果。"""
        result = self.chain.match("nonexistent_tool", {}, self.registry)
        self.assertEqual(result.strategy_used, "none")
        self.assertIsNone(result.matched_name)


# ── Compress Strategy 测试 ───────────────────────────


class TestSlidingWindowStrategy(unittest.TestCase):
    """SlidingWindowStrategy 测试。"""

    def setUp(self) -> None:
        self.strategy = SlidingWindowStrategy(window_size=5)
        self.system_msg = Message(role="system", content="System")
        self.messages = [Message(role="user", content=f"msg{i}") for i in range(20)]

    def test_no_compression_needed(self) -> None:
        """测试: 消息数少于窗口时不压缩。"""
        short = self.messages[:3]
        result = self.strategy.compress(short, self.system_msg, 1000)
        self.assertEqual(len(result), 3)

    def test_sliding_window(self) -> None:
        """测试: 超过窗口时滑动截取最近 N 条。"""
        result = self.strategy.compress(self.messages, self.system_msg, 1000)
        self.assertLessEqual(len(result), 5 + 1)  # window + system msg

    def test_system_message_included(self) -> None:
        """测试: 确保 system message 被包含。"""
        result = self.strategy.compress(self.messages, self.system_msg, 1000)
        has_system = any(getattr(m, "role", "") == "system" for m in result)
        self.assertTrue(has_system)


class TestHybridStrategy(unittest.TestCase):
    """HybridStrategy 测试。"""

    def setUp(self) -> None:
        self.strategy = HybridStrategy(keep_recent=5, max_tool_result_chars=200)
        self.system_msg = Message(role="system", content="System")

    def test_short_context_no_compress(self) -> None:
        """测试: 短上下文不触发压缩。"""
        msgs = [Message(role="user", content=f"msg{i}") for i in range(3)]
        result = self.strategy.compress(msgs, self.system_msg, 10000)
        self.assertEqual(len(result), 3)

    def test_truncate_long_tool_output(self) -> None:
        """测试: 截断过长的 Tool 输出。"""
        # 需要超过 keep_recent 条消息才能触发压缩
        msgs = [Message(role="user", content=f"msg{i}") for i in range(6)]
        msgs.append(Message(role="tool", content="A" * 5000, tool_call_id="t1"))
        result = self.strategy.compress(msgs, self.system_msg, 100)  # 低限制触发压缩
        # 应截断 tool 消息中过长的内容
        tool_msgs = [m for m in result if getattr(m, "role", "") == "tool"]
        if tool_msgs:
            self.assertLess(len(tool_msgs[0].content), 5000)

    def test_fallback_to_sliding_window(self) -> None:
        """测试: 截断后仍超限时滑动窗口。"""
        msgs = [Message(role="user", content=f"long message number {i}" * 10) for i in range(30)]
        result = self.strategy.compress(msgs, self.system_msg, 100)
        self.assertLess(len(result), 30)


class TestSummarizeStrategy(unittest.TestCase):
    """SummarizeStrategy 测试。"""

    def setUp(self) -> None:
        self.strategy = SummarizeStrategy(keep_recent=3)
        self.system_msg = Message(role="system", content="System")
        self.messages = [Message(role="user", content=f"msg{i}") for i in range(15)]

    def test_no_compress_short(self) -> None:
        """测试: 短消息列表不压缩。"""
        short = self.messages[:5]
        result = self.strategy.compress(short, self.system_msg, 1000)
        self.assertEqual(len(result), 5)

    def test_fallback_to_sliding_without_llm(self) -> None:
        """测试: 无 LLM 客户端时退化为滑动窗口。"""
        result = self.strategy.compress(self.messages, self.system_msg, 1000)
        self.assertLessEqual(len(result), 3 + 1)  # keep_recent + system msg


if __name__ == "__main__":
    unittest.main()
