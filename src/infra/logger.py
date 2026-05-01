"""
Agent 专用日志器 — 封装标准 logging, 添加 Agent 上下文。

支持日志级别分级:
- DEBUG: LLM 原始响应、Tool 参数/结果详情
- INFO: ReAct 迭代摘要、Agent 状态变化
- WARNING: 重试、恢复、降级
- ERROR: 不可恢复错误
"""

import logging
import sys
from typing import Any

from src.infra.config import Config


class AgentLogger:
    """
    Agent 专用日志器 — 封装标准 logging, 添加 Agent 上下文。

    同时输出到控制台和文件 (若配置了 log_file)。
    """

    def __init__(self, name: str, config: Config) -> None:
        """创建日志器。同时输出到控制台和文件 (若配置了)。"""
        self._name = name
        self._config = config
        self._logger = logging.getLogger(name)
        self._logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))

        # 避免重复添加 handler
        if not self._logger.handlers:
            # 控制台 handler
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setFormatter(logging.Formatter(config.log_format))
            self._logger.addHandler(console_handler)

            # 文件 handler (若配置了 log_file)
            if config.log_file:
                file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
                file_handler.setFormatter(logging.Formatter(config.log_format))
                self._logger.addHandler(file_handler)

    def debug(self, msg: str, **kwargs: Any) -> None:
        """记录 DEBUG 级别日志。"""
        self._logger.debug(self._format_msg(msg, **kwargs))

    def info(self, msg: str, **kwargs: Any) -> None:
        """记录 INFO 级别日志。"""
        self._logger.info(self._format_msg(msg, **kwargs))

    def warning(self, msg: str, **kwargs: Any) -> None:
        """记录 WARNING 级别日志。"""
        self._logger.warning(self._format_msg(msg, **kwargs))

    def error(self, msg: str, **kwargs: Any) -> None:
        """记录 ERROR 级别日志。"""
        self._logger.error(self._format_msg(msg, **kwargs))

    def log_react_step(self, step: Any) -> None:
        """
        记录 ReAct 迭代 (INFO 级别): 迭代序号 + Action + 耗时 + Token。

        Args:
            step: ReActStep 实例 (从 src.core.models 导入的类型在运行时传入)
        """
        self.info(
            f"ReAct Step #{step.iteration}: "
            f"action={step.action_name}, "
            f"duration={step.duration_ms:.0f}ms, "
            f"tokens={step.token_usage.total_tokens if step.token_usage else 0}"
        )

    def log_tool_call(self, tool_name: str, args: dict, result: Any) -> None:
        """
        记录 Tool 调用 (DEBUG 级别): 含参数和结果摘要。

        Args:
            tool_name: Tool 名称
            args: 调用参数
            result: ToolResult 实例
        """
        # 截断过长参数
        args_str = str(args)
        if len(args_str) > 200:
            args_str = args_str[:200] + "..."
        result_summary = f"success={result.success}, output_len={len(result.output)}" if hasattr(result, "output") else str(result)
        self.debug(f"Tool Call: {tool_name}({args_str}) → {result_summary}")

    def log_llm_call(self, messages: list[Any], response: Any) -> None:
        """
        记录 LLM 调用 (DEBUG 级别, 需 config.log_llm_calls=True):
        含输入摘要、输出摘要、Token 用量。
        """
        if not self._config.log_llm_calls:
            return
        msg_summary = f"messages_count={len(messages)}"
        resp_summary = f"content_len={len(response.content) if response.content else 0}, tokens={response.usage.total_tokens if response.usage else 'N/A'}"
        self.debug(f"LLM Call: {msg_summary} → {resp_summary}")

    def _format_msg(self, msg: str, **kwargs: Any) -> str:
        """格式化日志消息, 附加 Agent 上下文信息。"""
        if kwargs:
            extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"[{self._name}] {msg} | {extra}"
        return f"[{self._name}] {msg}"
