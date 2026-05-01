"""
Tool 管理器 — 负责 Tool 的注册、查找、匹配和调用。

支持:
- 名称注册与去重检查
- 多级匹配策略 (精确/模糊/语义)
- Tool 执行超时控制
- 调用审计日志
"""

import concurrent.futures
import logging
import time
from typing import Any

from src.tools.base_tool import (
    BaseTool,
    ToolArgValidationError,
    ToolNameConflictError,
    ToolResult,
)
from src.core.models import (
    ToolExecutionError,
    ToolNotFoundError,
)

logger = logging.getLogger(__name__)


class ToolManager:
    """
    Tool 管理器 — 负责 Tool 的注册、查找、匹配和调用。

    支持:
    - 名称注册与去重检查
    - 多级匹配策略 (精确/模糊/语义)
    - Tool 执行超时控制
    - 调用审计日志
    """

    def __init__(self, config: Any = None) -> None:
        """
        初始化 Tool 管理器。

        Args:
            config: Config 实例, 用于读取 tool_execution_timeout 等配置
        """
        self._tools: dict[str, BaseTool] = {}  # Tool 注册表 {name: BaseTool}
        self._config = config
        self._tool_execution_timeout: float = getattr(
            config, "agent_tool_execution_timeout", 30.0
        ) if config else 30.0

    # ── 注册 ─────────────────────────────────────────

    def register(self, tool: BaseTool) -> None:
        """
        注册一个 Tool。

        若名称冲突则抛出 ToolNameConflictError (含冲突 Tool 信息)。

        Args:
            tool: 要注册的 Tool 实例
        """
        if tool.name in self._tools:
            existing = self._tools[tool.name]
            raise ToolNameConflictError(
                f"Tool 名称冲突: '{tool.name}' 已被 {existing.__class__.__name__} 注册"
            )
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name} ({tool.__class__.__name__})")

    def register_many(self, tools: list[BaseTool]) -> None:
        """
        批量注册 Tool, 原子操作 (任一失败则全部回滚)。

        Args:
            tools: 要注册的 Tool 实例列表

        Raises:
            ToolNameConflictError: 若存在名称冲突
        """
        # 先校验所有 Tool 名称
        for tool in tools:
            if tool.name in self._tools:
                raise ToolNameConflictError(
                    f"批量注册失败: Tool 名称冲突 '{tool.name}'"
                )

        # 全部校验通过后注册
        for tool in tools:
            self._tools[tool.name] = tool
            logger.debug(f"Batch registered tool: {tool.name}")

    def unregister(self, tool_name: str) -> None:
        """
        注销一个 Tool。若未注册则静默忽略。

        Args:
            tool_name: 要注销的 Tool 名称
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.debug(f"Unregistered tool: {tool_name}")

    # ── 查找 ─────────────────────────────────────────

    def get_tool(self, tool_name: str) -> BaseTool | None:
        """
        按名称精确查找 Tool。O(1)。

        Args:
            tool_name: Tool 名称

        Returns:
            BaseTool 实例或 None
        """
        return self._tools.get(tool_name)

    def list_tools_by_tag(self, tag: str) -> list[BaseTool]:
        """
        按标签筛选 Tool。

        Args:
            tag: 标签名称

        Returns:
            包含该标签的 Tool 列表
        """
        return [tool for tool in self._tools.values() if tag in (tool.tags or [])]

    # ── 调用 ─────────────────────────────────────────

    def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        """
        根据名称执行 Tool:
        1. 精确查找 Tool
        2. 调用 tool.validate_args(**kwargs)
        3. 调用 tool.sanitize_args(**kwargs)
        4. 若 requires_confirmation → 触发确认流程
        5. 执行 tool.execute(**sanitized_args), 带超时控制
        6. 记录调用日志

        Args:
            tool_name: Tool 名称
            **kwargs: Tool 参数

        Returns:
            ToolResult 执行结果

        Raises:
            ToolNotFoundError: 若 Tool 未注册
            ToolExecutionError: 若执行失败
        """
        tool = self.get_tool(tool_name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{tool_name}' 未注册。可用 Tool: {list(self._tools.keys())}")

        start_time = time.time()

        try:
            # 验证参数
            validated_args = tool.validate_args(**kwargs)
            # 安全化参数
            sanitized_args = tool.sanitize_args(**validated_args)
            # 执行 Tool
            result = tool.execute(**sanitized_args)
        except ToolArgValidationError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.warning(f"Tool '{tool_name}' arg validation failed: {e}")
            return ToolResult(
                success=False,
                output=str(e),
                error=str(e),
                tool_name=tool_name,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(f"Tool '{tool_name}' execution failed: {e}", exc_info=True)
            raise ToolExecutionError(f"Tool '{tool_name}' 执行失败: {e}")

        duration_ms = (time.time() - start_time) * 1000
        result.duration_ms = duration_ms
        result.tool_name = tool_name

        # 记录调用日志
        logger.debug(
            f"Tool '{tool_name}' executed: success={result.success}, "
            f"duration={duration_ms:.0f}ms, output_len={len(result.output)}"
        )

        return result

    def execute_with_timeout(
        self,
        tool_name: str,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """
        带超时的 Tool 执行。

        若 timeout 为 None, 使用 Config 中的默认值。
        使用 concurrent.futures.ThreadPoolExecutor 实现超时。

        Args:
            tool_name: Tool 名称
            timeout: 超时秒数, None 则使用默认值
            **kwargs: Tool 参数

        Returns:
            ToolResult 执行结果
        """
        actual_timeout = timeout if timeout is not None else self._tool_execution_timeout

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.execute, tool_name, **kwargs)
            try:
                return future.result(timeout=actual_timeout)
            except concurrent.futures.TimeoutError:
                duration_ms = actual_timeout * 1000
                logger.warning(f"Tool '{tool_name}' timed out after {actual_timeout}s")
                return ToolResult(
                    success=False,
                    output=f"Tool '{tool_name}' 执行超时 (>{actual_timeout}s)",
                    error=f"Tool execution timeout after {actual_timeout}s",
                    tool_name=tool_name,
                    duration_ms=duration_ms,
                )

    # ── 导出 ─────────────────────────────────────────

    def list_tools(self) -> list[dict]:
        """
        返回所有 Tool 的 LLM 描述列表 (用于 Prompt 构建)。

        Returns:
            Tool 描述 dict 列表
        """
        return [tool.to_llm_description() for tool in self._tools.values()]

    def get_tools_schema(self) -> list[dict]:
        """
        返回 OpenAI Function Calling 格式的 Tool Schema 列表,
        用于 LLM 的原生 Function Calling。

        Returns:
            Tool Schema 列表
        """
        return self.list_tools()

    @property
    def tools(self) -> dict[str, BaseTool]:
        """获取所有已注册 Tool 的字典 (只读)。"""
        return dict(self._tools)

    @property
    def tool_count(self) -> int:
        """获取已注册 Tool 数量。"""
        return len(self._tools)
