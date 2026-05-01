"""
ReAct 输出解析器单元测试。

测试覆盖:
- FunctionCallParser: tool_calls 解析, content-only 解析
- ReActParser: Thought/Action/Final Answer 标签解析
- FallbackParser: 启发式回退解析
- CompositeParser: 多级组合解析
"""

import unittest

from src.core.models import ChatResponse, ParseMethod, ToolCall
from src.core.react_parser import (
    CompositeParser,
    FallbackParser,
    FunctionCallParser,
    ReActParser,
)


class TestFunctionCallParser(unittest.TestCase):
    """FunctionCallParser 测试。"""

    def setUp(self) -> None:
        self.parser = FunctionCallParser()

    def test_parse_tool_calls(self) -> None:
        """测试: 解析 tool_calls 为 Action。"""
        tc = ToolCall(id="call_1", function_name="read_file", function_args={"path": "test.py"})
        resp = ChatResponse(content="Let me read the file", tool_calls=[tc])
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertFalse(parsed.has_final_answer)  # type: ignore[union-attr]
        self.assertEqual(parsed.action_name, "read_file")  # type: ignore[union-attr]
        self.assertEqual(parsed.action_input, {"path": "test.py"})  # type: ignore[union-attr]
        self.assertEqual(parsed.parse_method, ParseMethod.FUNCTION_CALL)  # type: ignore[union-attr]

    def test_parse_content_only(self) -> None:
        """测试: 无 tool_calls 但有 content → Final Answer。"""
        resp = ChatResponse(content="The answer is 42")
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.has_final_answer)  # type: ignore[union-attr]
        self.assertEqual(parsed.final_answer, "The answer is 42")  # type: ignore[union-attr]

    def test_parse_empty_response(self) -> None:
        """测试: 空响应返回 None。"""
        resp = ChatResponse(content="")
        parsed = self.parser.parse(resp)
        self.assertIsNone(parsed)


class TestReActParser(unittest.TestCase):
    """ReActParser 测试。"""

    def setUp(self) -> None:
        self.parser = ReActParser()

    def test_parse_final_answer(self) -> None:
        """测试: 解析 Final Answer 格式。"""
        content = "Thought: I need to check the file.\nFinal Answer: The file contains 42 lines."
        resp = ChatResponse(content=content)
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.has_final_answer)  # type: ignore[union-attr]
        self.assertIn("42 lines", parsed.final_answer)  # type: ignore[union-attr]
        self.assertEqual(parsed.parse_method, ParseMethod.TEXT_REACT)  # type: ignore[union-attr]

    def test_parse_action(self) -> None:
        """测试: 解析 Action 格式。"""
        content = 'Thought: I need to read the config.\nAction: read_file\nAction Input: {"path": "config.yaml"}'
        resp = ChatResponse(content=content)
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertFalse(parsed.has_final_answer)  # type: ignore[union-attr]
        self.assertEqual(parsed.action_name, "read_file")  # type: ignore[union-attr]
        self.assertEqual(parsed.action_input, {"path": "config.yaml"})  # type: ignore[union-attr]

    def test_parse_action_with_raw_input(self) -> None:
        """测试: Action Input 为非 JSON 时的回退。"""
        content = "Thought: I need to search.\nAction: search_code\nAction Input: some plain text query"
        resp = ChatResponse(content=content)
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.action_name, "search_code")  # type: ignore[union-attr]
        self.assertEqual(parsed.action_input, {"raw": "some plain text query"})  # type: ignore[union-attr]

    def test_parse_empty_content(self) -> None:
        """测试: 空 content 返回 None。"""
        resp = ChatResponse(content="")
        parsed = self.parser.parse(resp)
        self.assertIsNone(parsed)

    def test_parse_non_react_format(self) -> None:
        """测试: 既不是 Final Answer 也不是 Action 格式的内容返回 None。"""
        resp = ChatResponse(content="Just some random text without any react tags.")
        parsed = self.parser.parse(resp)
        self.assertIsNone(parsed)

    def test_parse_final_answer_case_insensitive(self) -> None:
        """测试: Final Answer 大小写不敏感。"""
        content = "Thought: some thinking\nfinal answer: The result is done."
        resp = ChatResponse(content=content)
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.has_final_answer)  # type: ignore[union-attr]


class TestFallbackParser(unittest.TestCase):
    """FallbackParser 测试。"""

    def setUp(self) -> None:
        self.parser = FallbackParser()

    def test_parse_final_indicator(self) -> None:
        """测试: 包含 Final 指示词时识别为 Final Answer。"""
        resp = ChatResponse(content="综上所述, 项目共有 10 个模块。")
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.has_final_answer)  # type: ignore[union-attr]
        self.assertEqual(parsed.parse_method, ParseMethod.FALLBACK)  # type: ignore[union-attr]

    def test_parse_short_content_as_thought(self) -> None:
        """测试: 短内容识别为 Thought。"""
        resp = ChatResponse(content="Let me think about this...")
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertFalse(parsed.has_final_answer)  # type: ignore[union-attr]
        self.assertEqual(parsed.thought, "Let me think about this...")  # type: ignore[union-attr]

    def test_parse_long_content_as_final(self) -> None:
        """测试: 长内容(>=500字符)识别为 Final Answer。"""
        long_text = "A" * 600
        resp = ChatResponse(content=long_text)
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.has_final_answer)  # type: ignore[union-attr]

    def test_parse_empty(self) -> None:
        """测试: 空内容返回 None。"""
        resp = ChatResponse(content="")
        parsed = self.parser.parse(resp)
        self.assertIsNone(parsed)


class TestCompositeParser(unittest.TestCase):
    """CompositeParser 测试。"""

    def setUp(self) -> None:
        self.parser = CompositeParser()

    def test_function_call_takes_priority(self) -> None:
        """测试: FunctionCallParser 优先级最高。"""
        tc = ToolCall(id="c1", function_name="search", function_args={"q": "test"})
        resp = ChatResponse(content="Thought: searching\nFinal Answer: done", tool_calls=[tc])
        parsed = self.parser.parse(resp)

        self.assertEqual(parsed.parse_method, ParseMethod.FUNCTION_CALL)
        self.assertFalse(parsed.has_final_answer)

    def test_function_call_priority_over_text(self) -> None:
        """测试: 无 tool_calls 但有 content 时, FunctionCallParser 先捕获为 Final Answer。"""
        content = 'Thought: something\nAction: do_thing\nAction Input: {"key": "val"}'
        resp = ChatResponse(content=content)
        parsed = self.parser.parse(resp)

        # FunctionCallParser 优先: 无 tool_calls + 有 content → Final Answer
        self.assertEqual(parsed.parse_method, ParseMethod.FUNCTION_CALL)
        self.assertTrue(parsed.has_final_answer)

    def test_plain_text_goes_to_function_call(self) -> None:
        """测试: 纯文本内容由 FunctionCallParser 作为 Final Answer 捕获。"""
        resp = ChatResponse(content="A plain text response")
        parsed = self.parser.parse(resp)

        # FunctionCallParser: 无 tool_calls + 有 content → Final Answer
        self.assertEqual(parsed.parse_method, ParseMethod.FUNCTION_CALL)

    def test_all_parsers_fail_returns_default(self) -> None:
        """测试: 所有解析器都返回 None 时的兜底。"""
        resp = ChatResponse(content="")
        parsed = self.parser.parse(resp)

        self.assertIsNotNone(parsed)
        self.assertTrue(parsed.has_final_answer)

    def test_custom_parser_list(self) -> None:
        """测试: 自定义解析器列表。"""
        custom = CompositeParser(parsers=[FunctionCallParser()])
        tc = ToolCall(id="c1", function_name="run", function_args={})
        resp = ChatResponse(content="", tool_calls=[tc])
        parsed = custom.parse(resp)

        self.assertEqual(parsed.parse_method, ParseMethod.FUNCTION_CALL)


if __name__ == "__main__":
    unittest.main()
