"""
上下文压缩策略 — 当 Token 数超限时自动触发。

框架内置三种实现, 可通过 Config 选择或自定义:
- SlidingWindowStrategy: 滑动窗口 (保留最近 N 条)
- SummarizeStrategy: 摘要压缩 (LLM 生成摘要)
- HybridStrategy: 混合策略 (丢弃大段 → 摘要 → 滑动窗口, 逐步收紧)
"""

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class CompressStrategy(Protocol):
    """
    上下文压缩策略接口 — 当 Token 数超限时触发。

    框架内置三种实现, 可通过 Config 选择或自定义。
    """

    def compress(
        self,
        messages: list[Any],
        system_message: Any,
        max_tokens: int,
    ) -> list[Any]:
        """
        压缩消息列表, 确保 Token 数不超过限制。

        Args:
            messages: 完整消息列表
            system_message: 系统消息 (必须保留)
            max_tokens: Token 上限

        Returns:
            压缩后的消息列表
        """
        ...


class SlidingWindowStrategy:
    """
    滑动窗口策略。

    保留 System Message + 最近 N 条消息, 丢弃旧的。
    简单高效, 但可能丢失早期重要信息。
    """

    def __init__(self, window_size: int = 20) -> None:
        """
        初始化滑动窗口策略。

        Args:
            window_size: 保留的最近消息数量
        """
        self.window_size = window_size

    def compress(
        self,
        messages: list[Any],
        system_message: Any,
        max_tokens: int,
    ) -> list[Any]:
        """
        滑动窗口压缩: 保留 system_message + 最近 window_size 条消息。

        Args:
            messages: 完整消息列表
            system_message: 系统消息
            max_tokens: Token 上限 (用于动态调整窗口大小)

        Returns:
            压缩后的消息列表
        """
        if len(messages) <= self.window_size:
            return list(messages)

        # 动态调整窗口大小: 基于 max_tokens 粗略估算
        # 假设每条消息平均 500 tokens
        estimated_per_message = 500
        dynamic_window = max(4, max_tokens // estimated_per_message)
        actual_window = min(self.window_size, dynamic_window)

        # 保留系统消息 + 最近 N 条
        kept = messages[-actual_window:]

        # 确保第一条是 system 消息
        has_system = any(
            getattr(msg, "role", None) == "system" for msg in kept
        )
        if not has_system and system_message is not None:
            kept = [system_message] + kept

        logger.debug(
            f"SlidingWindow: compressed {len(messages)} → {len(kept)} messages "
            f"(window={actual_window})"
        )
        return kept


class SummarizeStrategy:
    """
    摘要压缩策略。

    将中间轮次的消息压缩为一段摘要 (通过 LLM 生成摘要),
    保留 System Message + 早期上下文摘要 + 最近消息。
    保留更多语义信息, 但需要额外 LLM 调用。
    """

    def __init__(self, keep_recent: int = 10) -> None:
        """
        初始化摘要压缩策略。

        Args:
            keep_recent: 保留的最近消息数量
        """
        self.keep_recent = keep_recent

    def compress(
        self,
        messages: list[Any],
        system_message: Any,
        max_tokens: int,
        llm_client: Any = None,
    ) -> list[Any]:
        """
        摘要压缩: 将中间消息总结为摘要。

        注意: 当前实现为占位版本, 实际摘要生成需要 LLM 调用。
        在没有 LLM 客户端的情况下, 退化为滑动窗口。

        Args:
            messages: 完整消息列表
            system_message: 系统消息
            max_tokens: Token 上限
            llm_client: LLM 客户端 (用于生成摘要, 可选)

        Returns:
            压缩后的消息列表
        """
        if len(messages) <= self.keep_recent + 5:
            return list(messages)

        # 若无 LLM 客户端, 退化为滑动窗口
        if llm_client is None:
            logger.debug("SummarizeStrategy: no LLM client, falling back to sliding window")
            sliding = SlidingWindowStrategy(window_size=self.keep_recent)
            return sliding.compress(messages, system_message, max_tokens)

        # 保留最近消息
        recent = messages[-self.keep_recent:]
        # 中间部分需要摘要 (简化实现: 直接取中间消息的文本拼接)
        middle = messages[1:-self.keep_recent] if len(messages) > self.keep_recent + 1 else []
        middle_text = "\n".join(
            f"[{getattr(m, 'role', 'unknown')}]: {getattr(m, 'content', '')[:200]}"
            for m in middle
        )

        # 构建摘要消息 (占位: 实际应由 LLM 生成)
        from src.core.models import Message

        summary_msg = Message(
            role="system",
            content=f"[上下文摘要] 之前的对话摘要:\n{middle_text[:1000]}...\n[摘要结束]",
        )

        result = [system_message, summary_msg] + recent if system_message else [summary_msg] + recent
        logger.debug(
            f"SummarizeStrategy: compressed {len(messages)} → {len(result)} messages"
        )
        return result


class HybridStrategy:
    """
    混合策略 (默认)。

    1. 优先丢弃旧的 Tool 结果 (大段输出文本)
    2. 若仍超限, 将中间轮次压缩为摘要
    3. 若仍超限, 应用滑动窗口
    4. 确保 system_message 始终保留
    """

    def __init__(
        self,
        keep_recent: int = 10,
        max_tool_result_chars: int = 2000,
    ) -> None:
        """
        初始化混合压缩策略。

        Args:
            keep_recent: 保留的最近消息数量
            max_tool_result_chars: Tool 结果文本最大保留字符数
        """
        self.keep_recent = keep_recent
        self.max_tool_result_chars = max_tool_result_chars

    def compress(
        self,
        messages: list[Any],
        system_message: Any,
        max_tokens: int,
    ) -> list[Any]:
        """
        混合压缩策略。

        分三步:
        1. 截断旧的 tool 角色消息中的大段输出
        2. 若仍超限, 对中间消息应用摘要压缩
        3. 若仍超限, 应用滑动窗口

        Args:
            messages: 完整消息列表
            system_message: 系统消息
            max_tokens: Token 上限

        Returns:
            压缩后的消息列表
        """
        if len(messages) <= self.keep_recent:
            return list(messages)

        # 估算 token 数: 粗略使用 字符数/4
        total_chars = sum(len(getattr(msg, "content", "")) for msg in messages)
        estimated_tokens = total_chars / 4

        if estimated_tokens <= max_tokens:
            return list(messages)

        # 步骤 1: 截断旧的 tool 角色消息中的大段输出
        compressed: list[Any] = []
        for msg in messages:
            role = getattr(msg, "role", "")
            content = getattr(msg, "content", "")

            if role == "tool" and len(content) > self.max_tool_result_chars:
                # 截断 tool 输出, 保留头部和尾部
                truncation_note = f"\n\n... [输出截断: 原始长度 {len(content)} 字符]"
                half_limit = (self.max_tool_result_chars - len(truncation_note)) // 2
                truncated_content = (
                    content[:half_limit] + truncation_note + content[-half_limit:]
                )
                # 创建新消息对象 (保留原始类型)
                msg_copy = type(msg)(
                    role=role,
                    content=truncated_content,
                    name=getattr(msg, "name", None),
                    tool_call_id=getattr(msg, "tool_call_id", None),
                    tool_calls=getattr(msg, "tool_calls", None),
                )
                compressed.append(msg_copy)
            else:
                compressed.append(msg)

        # 步骤 2: 检查是否仍超限
        total_chars = sum(len(getattr(msg, "content", "")) for msg in compressed)
        if total_chars / 4 <= max_tokens:
            logger.debug(
                f"HybridStrategy step1: compressed {len(messages)} → {len(compressed)} messages"
            )
            return compressed

        # 步骤 3: 应用滑动窗口
        sliding = SlidingWindowStrategy(window_size=self.keep_recent)
        result = sliding.compress(compressed, system_message, max_tokens)

        logger.debug(
            f"HybridStrategy step3: compressed {len(messages)} → {len(result)} messages"
        )
        return result
