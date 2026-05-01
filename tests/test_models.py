"""
数据模型单元测试。

测试覆盖:
- Message, ChatResponse, TokenUsage
- AgentState, FinishReason, ExecutionStrategy
- AgentResult, ReActStep, ReActResult
- ParsedReAct, ParsedAction, ActionResult
- AgentConfig, AgentError 子类
"""

import unittest

from src.core.models import (
    AgentConfig,
    AgentDepthExceededError,
    AgentError,
    AgentResult,
    AgentState,
    AgentTimeoutError,
    ChatResponse,
    ExecutionStrategy,
    FinishReason,
    LLMCallError,
    Message,
    ParsedAction,
    ParsedReAct,
    ParseMethod,
    ReActStep,
    ActionResult,
    TokenUsage,
    ToolCall,
    ToolExecutionError,
    ToolNotFoundError,
)


class TestTokenUsage(unittest.TestCase):
    """TokenUsage 测试。"""

    def test_default_values(self) -> None:
        """测试: 默认值。"""
        usage = TokenUsage()
        self.assertEqual(usage.prompt_tokens, 0)
        self.assertEqual(usage.completion_tokens, 0)
        self.assertEqual(usage.total_tokens, 0)

    def test_add_operation(self) -> None:
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


class TestMessage(unittest.TestCase):
    """Message 测试。"""

    def test_basic_message(self) -> None:
        """测试: 基本消息创建。"""
        msg = Message(role="user", content="Hello")
        self.assertEqual(msg.role, "user")
        self.assertEqual(msg.content, "Hello")
        self.assertIsNone(msg.tool_calls)

    def test_message_with_tool_calls(self) -> None:
        """测试: 带 tool_calls 的消息。"""
        tc = ToolCall(id="call_1", function_name="read_file", function_args={"path": "test.py"})
        msg = Message(role="assistant", content="", tool_calls=[tc])
        self.assertEqual(len(msg.tool_calls), 1)
        self.assertEqual(msg.tool_calls[0].function_name, "read_file")


class TestChatResponse(unittest.TestCase):
    """ChatResponse 测试。"""

    def test_basic_response(self) -> None:
        """测试: 基本响应。"""
        resp = ChatResponse(content="Hello world")
        self.assertEqual(resp.content, "Hello world")
        self.assertEqual(resp.finish_reason, "stop")


class TestAgentState(unittest.TestCase):
    """AgentState 测试。"""

    def test_enum_values(self) -> None:
        """测试: 状态枚举值。"""
        self.assertEqual(AgentState.IDLE.value, "idle")
        self.assertEqual(AgentState.RUNNING.value, "running")
        self.assertEqual(AgentState.DONE.value, "done")
        self.assertEqual(AgentState.ERROR.value, "error")
        self.assertEqual(AgentState.STOPPING.value, "stopping")
        self.assertEqual(AgentState.STOPPED.value, "stopped")


class TestFinishReason(unittest.TestCase):
    """FinishReason 测试。"""

    def test_enum_values(self) -> None:
        """测试: 终止原因枚举值。"""
        self.assertEqual(FinishReason.DONE.value, "done")
        self.assertEqual(FinishReason.MAX_ITERATIONS.value, "max_iterations")
        self.assertEqual(FinishReason.STOPPED.value, "stopped")


class TestExecutionStrategy(unittest.TestCase):
    """ExecutionStrategy 测试。"""

    def test_enum_values(self) -> None:
        """测试: 执行策略枚举值。"""
        self.assertEqual(ExecutionStrategy.SEQUENTIAL.value, "sequential")
        self.assertEqual(ExecutionStrategy.PARALLEL.value, "parallel")
        self.assertEqual(ExecutionStrategy.DAG.value, "dag")


class TestAgentConfig(unittest.TestCase):
    """AgentConfig 测试。"""

    def test_default_values(self) -> None:
        """测试: 默认值均为 None。"""
        config = AgentConfig()
        self.assertIsNone(config.max_iterations)
        self.assertIsNone(config.llm_temperature_override)
        self.assertEqual(config.call_depth, 0)

    def test_custom_values(self) -> None:
        """测试: 自定义值。"""
        config = AgentConfig(
            max_iterations=20,
            llm_temperature_override=0.5,
            call_depth=2,
        )
        self.assertEqual(config.max_iterations, 20)
        self.assertEqual(config.llm_temperature_override, 0.5)
        self.assertEqual(config.call_depth, 2)


class TestAgentErrors(unittest.TestCase):
    """Agent 错误体系测试。"""

    def test_agent_error_base(self) -> None:
        """测试: 基类错误。"""
        err = AgentError("test error")
        self.assertEqual(str(err), "test error")
        self.assertFalse(err.recoverable)

    def test_llm_call_error_is_recoverable(self) -> None:
        """测试: LLMCallError 可恢复。"""
        err = LLMCallError("llm failed")
        self.assertTrue(err.recoverable)

    def test_tool_execution_error_is_recoverable(self) -> None:
        """测试: ToolExecutionError 可恢复。"""
        err = ToolExecutionError("tool failed")
        self.assertTrue(err.recoverable)

    def test_tool_not_found_error_is_recoverable(self) -> None:
        """测试: ToolNotFoundError 可恢复。"""
        err = ToolNotFoundError("tool not found")
        self.assertTrue(err.recoverable)

    def test_agent_depth_exceeded_error_not_recoverable(self) -> None:
        """测试: AgentDepthExceededError 不可恢复。"""
        err = AgentDepthExceededError("depth exceeded")
        self.assertFalse(err.recoverable)

    def test_agent_timeout_error_not_recoverable(self) -> None:
        """测试: AgentTimeoutError 不可恢复。"""
        err = AgentTimeoutError("timeout")
        self.assertFalse(err.recoverable)


class TestParsedReAct(unittest.TestCase):
    """ParsedReAct 测试。"""

    def test_final_answer_parsing(self) -> None:
        """测试: 包含 Final Answer 的解析结果。"""
        resp = ChatResponse(content="Final answer text")
        parsed = ParsedReAct(
            has_final_answer=True,
            thought="Some thought",
            action_name=None,
            action_input=None,
            final_answer="Final answer text",
            parse_method=ParseMethod.TEXT_REACT,
            raw_response=resp,
        )
        self.assertTrue(parsed.has_final_answer)
        self.assertEqual(parsed.final_answer, "Final answer text")
        self.assertIsNone(parsed.action_name)

    def test_action_parsing(self) -> None:
        """测试: 包含 Action 的解析结果。"""
        resp = ChatResponse(content="")
        parsed = ParsedReAct(
            has_final_answer=False,
            thought="I need to read a file",
            action_name="read_file",
            action_input={"path": "test.py"},
            final_answer=None,
            parse_method=ParseMethod.FUNCTION_CALL,
            raw_response=resp,
        )
        self.assertFalse(parsed.has_final_answer)
        self.assertEqual(parsed.action_name, "read_file")
        self.assertEqual(parsed.action_input, {"path": "test.py"})


if __name__ == "__main__":
    unittest.main()
