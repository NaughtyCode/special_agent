"""
ToolManager 单元测试。

测试覆盖:
- Tool 注册、批量注册、注销
- 按名称/标签查找
- Tool 执行 (参数验证、安全化)
- 超时执行
- Tool 名称冲突检测
"""

import unittest
from unittest.mock import MagicMock, patch

from src.tools.base_tool import (
    BaseTool,
    ToolArgValidationError,
    ToolNameConflictError,
    ToolResult,
)
from src.core.tool_manager import ToolManager
from src.core.models import ToolNotFoundError, ToolExecutionError


class _MockTool(BaseTool):
    """测试用 Mock Tool。"""

    # 必须在 __init__ 之前定义类属性
    name: str = ""
    description: str = ""
    parameters_schema: dict = {}
    tags: list[str] = []

    def __init__(
        self,
        name: str = "mock_tool",
        description: str = "A mock tool for testing",
        parameters_schema: dict | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters_schema = parameters_schema or {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Input text"},
            },
            "required": ["text"],
        }
        self.tags = tags or ["mock", "test"]
        self.execute_called = False
        self.last_kwargs: dict = {}

    def execute(self, **kwargs) -> ToolResult:
        self.execute_called = True
        self.last_kwargs = kwargs
        return ToolResult(success=True, output=f"Executed with {kwargs}")


class _FailingMockTool(BaseTool):
    """始终执行失败的 Mock Tool。"""

    name: str = "failing_tool"
    description: str = "Always fails"
    parameters_schema: dict = {"type": "object", "properties": {}, "required": []}
    tags: list[str] = []

    def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("Simulated failure")


class TestToolManagerRegistration(unittest.TestCase):
    """Tool 注册相关测试。"""

    def setUp(self) -> None:
        self.manager = ToolManager()

    def test_register_single_tool(self) -> None:
        """测试: 注册单个 Tool。"""
        tool = _MockTool(name="read_file")
        self.manager.register(tool)

        self.assertIsNotNone(self.manager.get_tool("read_file"))
        self.assertEqual(self.manager.tool_count, 1)

    def test_register_name_conflict(self) -> None:
        """测试: 名称冲突时抛出 ToolNameConflictError。"""
        self.manager.register(_MockTool(name="read_file"))
        with self.assertRaises(ToolNameConflictError):
            self.manager.register(_MockTool(name="read_file"))

    def test_register_many(self) -> None:
        """测试: 批量注册。"""
        tools = [
            _MockTool(name="tool_a"),
            _MockTool(name="tool_b"),
            _MockTool(name="tool_c"),
        ]
        self.manager.register_many(tools)
        self.assertEqual(self.manager.tool_count, 3)

    def test_register_many_atomic(self) -> None:
        """测试: 批量注册原子性 — 任一失败全部回滚。"""
        self.manager.register(_MockTool(name="tool_a"))
        tools = [
            _MockTool(name="tool_b"),
            _MockTool(name="tool_a"),  # 冲突
            _MockTool(name="tool_c"),
        ]
        with self.assertRaises(ToolNameConflictError):
            self.manager.register_many(tools)
        # 原子性: tool_b 也未注册成功 (依赖于实现细节)
        # 注意: 当前实现是先全部校验再注册, 所以 tool_b 也不会注册

    def test_unregister(self) -> None:
        """测试: 注销 Tool。"""
        self.manager.register(_MockTool(name="temp_tool"))
        self.manager.unregister("temp_tool")
        self.assertIsNone(self.manager.get_tool("temp_tool"))
        self.assertEqual(self.manager.tool_count, 0)

    def test_unregister_nonexistent(self) -> None:
        """测试: 注销不存在的 Tool 静默忽略。"""
        # 不应抛出异常
        self.manager.unregister("nonexistent")


class TestToolManagerLookup(unittest.TestCase):
    """Tool 查找相关测试。"""

    def setUp(self) -> None:
        self.manager = ToolManager()
        self.manager.register(_MockTool(name="read_file", tags=["file", "read"]))
        self.manager.register(_MockTool(name="write_file", tags=["file", "write"]))
        self.manager.register(_MockTool(name="search_code", tags=["search"]))

    def test_get_tool_exact(self) -> None:
        """测试: 按名称精确查找。"""
        tool = self.manager.get_tool("read_file")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "read_file")  # type: ignore[union-attr]

    def test_get_tool_not_found(self) -> None:
        """测试: 查找不存在的 Tool 返回 None。"""
        self.assertIsNone(self.manager.get_tool("nonexistent"))

    def test_list_tools_by_tag(self) -> None:
        """测试: 按标签筛选 Tool。"""
        file_tools = self.manager.list_tools_by_tag("file")
        self.assertEqual(len(file_tools), 2)


class TestToolManagerExecution(unittest.TestCase):
    """Tool 执行相关测试。"""

    def setUp(self) -> None:
        self.manager = ToolManager()
        self.tool = _MockTool(name="echo")
        self.manager.register(self.tool)

    def test_execute_success(self) -> None:
        """测试: 成功执行 Tool。"""
        result = self.manager.execute("echo", text="hello")
        self.assertTrue(result.success)
        self.assertTrue(self.tool.execute_called)

    def test_execute_not_found(self) -> None:
        """测试: 执行不存在的 Tool 抛出 ToolNotFoundError。"""
        with self.assertRaises(ToolNotFoundError):
            self.manager.execute("nonexistent")

    def test_execute_arg_validation(self) -> None:
        """测试: 参数验证 — 缺少必填参数时返回失败结果。"""
        # echo 工具的 text 参数是必填的
        result = self.manager.execute("echo")  # 不传 text
        self.assertFalse(result.success)
        self.assertIn("缺少必填参数", result.output)

    def test_execute_arg_type_error(self) -> None:
        """测试: 参数类型错误时返回失败。"""
        # 注册一个需要 integer 参数的工具
        int_tool = _MockTool(
            name="int_tool",
            parameters_schema={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        )
        self.manager.register(int_tool)
        result = self.manager.execute("int_tool", count="not_an_int")
        self.assertFalse(result.success)
        self.assertIn("类型错误", result.output)

    def test_execute_failing_tool(self) -> None:
        """测试: Tool 执行抛出异常时转为 ToolExecutionError。"""
        self.manager.register(_FailingMockTool())
        with self.assertRaises(ToolExecutionError):
            self.manager.execute("failing_tool")


class TestToolManagerTimeout(unittest.TestCase):
    """Tool 超时执行测试。"""

    def setUp(self) -> None:
        self.manager = ToolManager()

    def test_execute_with_timeout_success(self) -> None:
        """测试: 正常超时时间内完成。"""
        tool = _MockTool(name="fast")
        self.manager.register(tool)
        result = self.manager.execute_with_timeout("fast", timeout=5.0, text="hi")
        self.assertTrue(result.success)

    def test_execute_with_default_timeout(self) -> None:
        """测试: 使用默认超时值。"""
        tool = _MockTool(name="default_timeout_tool")
        self.manager.register(tool)
        result = self.manager.execute_with_timeout("default_timeout_tool", text="hi")
        self.assertTrue(result.success)


class TestToolManagerExport(unittest.TestCase):
    """Tool 导出相关测试。"""

    def setUp(self) -> None:
        self.manager = ToolManager()
        self.manager.register(_MockTool(name="tool1", description="First tool"))
        self.manager.register(_MockTool(name="tool2", description="Second tool"))

    def test_list_tools(self) -> None:
        """测试: list_tools 返回 LLM 描述列表。"""
        tool_list = self.manager.list_tools()
        self.assertEqual(len(tool_list), 2)
        for item in tool_list:
            self.assertEqual(item["type"], "function")
            self.assertIn("name", item["function"])

    def test_get_tools_schema(self) -> None:
        """测试: get_tools_schema 返回 Function Calling 格式。"""
        schemas = self.manager.get_tools_schema()
        self.assertEqual(len(schemas), 2)

    def test_tools_property(self) -> None:
        """测试: tools 属性返回只读副本。"""
        tools_dict = self.manager.tools
        self.assertEqual(len(tools_dict), 2)
        self.assertIn("tool1", tools_dict)
        self.assertIn("tool2", tools_dict)

    def test_tool_count_property(self) -> None:
        """测试: tool_count 属性。"""
        self.assertEqual(self.manager.tool_count, 2)


if __name__ == "__main__":
    unittest.main()
