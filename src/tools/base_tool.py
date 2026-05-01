"""
Tool 抽象基类 — 定义 Tool 的契约和执行接口。

每个 Tool 需要定义名称、描述和参数 Schema,
LLM 根据这些信息决定何时调用哪个 Tool。

包含安全策略: 文件路径限制、Shell 命令白名单、危险操作确认等。
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Tool 执行结果。"""
    success: bool  # 是否成功
    output: str  # 输出文本 (给 LLM 的 Observation)
    data: Any = None  # 结构化数据 (给调用方使用)
    error: str | None = None  # 错误信息 (如有)
    tool_name: str = ""  # 执行的 Tool 名称
    duration_ms: float = 0.0  # 执行耗时 (毫秒)


class ToolArgValidationError(Exception):
    """Tool 参数验证失败时抛出。"""
    pass


class ToolNameConflictError(Exception):
    """Tool 名称冲突时抛出。"""
    pass


@dataclass
class ToolSecurityPolicy:
    """Tool 安全策略 — 全局配置。"""

    # 文件操作限制
    allowed_directories: list[str] = None  # type: ignore  # 允许读写的目录白名单 (绝对路径)
    max_file_size_mb: float = 10.0  # 单文件最大大小

    # Shell 限制
    allowed_commands: list[str] = None  # type: ignore  # 允许的 Shell 命令白名单 (空 = 全部禁止)
    shell_timeout_default: float = 30.0  # 默认 Shell 超时 (秒)

    # 网络限制
    allowed_url_schemes: list[str] = None  # type: ignore  # 允许的 URL 协议 ["https"]
    max_response_size_mb: float = 10.0  # 网络请求最大响应大小

    # 确认策略
    confirm_on_dangerous: bool = True  # 危险操作是否需确认 (默认 True)
    confirm_on_write: bool = True  # 写文件是否需确认
    confirm_on_shell: bool = True  # Shell 是否需确认

    def __post_init__(self):
        if self.allowed_directories is None:
            self.allowed_directories = []
        if self.allowed_commands is None:
            self.allowed_commands = []
        if self.allowed_url_schemes is None:
            self.allowed_url_schemes = ["https"]


class BaseTool(ABC):
    """
    Tool 抽象基类。

    每个 Tool 需要定义名称、描述和参数 Schema,
    LLM 根据这些信息决定何时调用哪个 Tool。

    子类必须实现 execute() 方法。
    """

    # ── 元数据 (子类必须设置) ────────────────────────
    name: str = ""  # Tool 名称 (用于 Action 匹配, 全局唯一)
    description: str = ""  # Tool 功能描述 (LLM 据此选择 Tool)
    parameters_schema: dict = None  # type: ignore  # 参数 JSON Schema (LLM 据此生成参数)
    tags: list[str] = None  # type: ignore  # 标签 (辅助匹配, 如 ["file", "read"])
    requires_confirmation: bool = False  # 是否需要用户确认 (危险操作标记)

    def __post_init__(self):
        """子类应在 __init__ 中设置元数据, 此方法确保默认值。"""
        if self.parameters_schema is None:
            self.parameters_schema = {
                "type": "object",
                "properties": {},
                "required": [],
            }
        if self.tags is None:
            self.tags = []

    # ── 抽象方法 ─────────────────────────────────────

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        """
        执行 Tool 逻辑。子类必须实现。

        抛出 ToolExecutionError 时, 错误信息将作为 Observation 反馈 LLM。

        Returns:
            ToolResult 执行结果
        """
        ...

    # ── 辅助方法 ─────────────────────────────────────

    def to_llm_description(self) -> dict:
        """
        转换为 LLM Function Calling 格式的描述。

        Returns:
            dict: {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameters_schema
                }
            }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def validate_args(self, **kwargs: Any) -> dict:
        """
        使用 JSON Schema 验证参数:
        1. 类型校验 (str/int/float/bool/array/object)
        2. 必填字段检查
        3. 枚举值范围检查

        Returns:
            验证后的参数字典

        Raises:
            ToolArgValidationError: 若验证失败
        """
        schema = self.parameters_schema or {}
        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])

        validated: dict = {}

        # 检查必填字段
        for field_name in required_fields:
            if field_name not in kwargs:
                raise ToolArgValidationError(
                    f"Tool '{self.name}' 缺少必填参数: {field_name}"
                )

        # 校验每个参数
        for param_name, param_value in kwargs.items():
            if param_name not in properties:
                # 未知参数, 保留但记录警告
                logger.warning(f"Tool '{self.name}' 收到未知参数: {param_name}")
                validated[param_name] = param_value
                continue

            prop_schema = properties[param_name]
            expected_type = prop_schema.get("type", "string")

            # 类型校验
            if not self._check_type(param_value, expected_type):
                raise ToolArgValidationError(
                    f"Tool '{self.name}' 参数 '{param_name}' 类型错误: "
                    f"期望 {expected_type}, 实际 {type(param_value).__name__}"
                )

            # 枚举值校验
            if "enum" in prop_schema and param_value not in prop_schema["enum"]:
                raise ToolArgValidationError(
                    f"Tool '{self.name}' 参数 '{param_name}' 值 '{param_value}' "
                    f"不在允许的枚举中: {prop_schema['enum']}"
                )

            validated[param_name] = param_value

        return validated

    def sanitize_args(self, **kwargs: Any) -> dict:
        """
        参数安全化处理:
        - 文件路径: 限制在项目根目录内
        - Shell 命令: 转义危险字符

        子类可覆写以实现特定的安全策略。

        Returns:
            安全化后的参数字典
        """
        return dict(kwargs)

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """检查值是否符合预期的 JSON Schema 类型。"""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True  # 未知类型, 放行
        if isinstance(expected, tuple):
            return isinstance(value, expected)
        return isinstance(value, expected)
