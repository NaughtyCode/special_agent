"""
ReAct 输出解析器 — 将 LLM 原始输出解析为结构化的 ParsedReAct。

支持三级解析:
1. FunctionCallParser: 解析 tool_calls (结构化, 无歧义)
2. ReActParser: 解析文本中的 Thought/Action/Final Answer 标签
3. FallbackParser: 将整个 content 视为 Thought, 尝试推断
"""

import json
import logging
import re
from typing import Protocol

from src.core.models import (
    ChatResponse,
    ParsedReAct,
    ParseMethod,
)

logger = logging.getLogger(__name__)


class OutputParser(Protocol):
    """输出解析器接口 — 可替换实现。"""

    def parse(self, response: ChatResponse) -> ParsedReAct | None:
        """
        解析 LLM 响应, 若无法解析则返回 None。

        Args:
            response: LLM 返回的 ChatResponse

        Returns:
            ParsedReAct 或 None (无法解析)
        """
        ...


class FunctionCallParser:
    """
    Function Calling 解析器 — 解析 response.tool_calls。

    当 LLM 返回 tool_calls 时, 直接转换为 Action 格式。
    无 tool_calls 但有 content 时, 视为 Final Answer。
    """

    def parse(self, response: ChatResponse) -> ParsedReAct | None:
        """
        解析 Function Calling 格式的响应。

        Args:
            response: LLM 返回的 ChatResponse

        Returns:
            ParsedReAct 或 None (无 tool_calls 但有 content 仍可解析为 Final Answer)
        """
        if response.tool_calls:
            # 有 tool_calls → 解析为 Action
            tc = response.tool_calls[0]
            return ParsedReAct(
                has_final_answer=False,
                thought=response.content or "",
                action_name=tc.function_name,
                action_input=tc.function_args,
                final_answer=None,
                parse_method=ParseMethod.FUNCTION_CALL,
                raw_response=response,
            )

        if response.content:
            # 无 tool_calls 但有 content → Final Answer
            return ParsedReAct(
                has_final_answer=True,
                thought=None,
                action_name=None,
                action_input=None,
                final_answer=response.content,
                parse_method=ParseMethod.FUNCTION_CALL,
                raw_response=response,
            )

        return None


class ReActParser:
    """
    文本解析器 — 解析 Thought/Action/Final Answer 标签格式。

    支持标准的 ReAct 文本格式:
    Thought: <推理>
    Action: <动作名>
    Action Input: <JSON 参数>
    ...
    Final Answer: <最终回答>
    """

    # 可配置的匹配模式 (允许子类覆写以适配不同 LLM 的格式偏好)
    THOUGHT_PATTERN: str = r"Thought:\s*(.+?)(?=\n(?:Action|Final|Observation)|\Z)"
    ACTION_PATTERN: str = r"Action:\s*(.+?)(?:\n|$)"
    ACTION_INPUT_PATTERN: str = r"Action Input:\s*(.+?)(?=\n(?:Thought|Action|Final|Observation)|\Z)"
    FINAL_ANSWER_PATTERN: str = r"Final Answer:\s*(.+?)(?=\n(?:Thought|Action)|\Z)"

    def parse(self, response: ChatResponse) -> ParsedReAct | None:
        """
        解析文本 ReAct 格式的响应。

        Args:
            response: LLM 返回的 ChatResponse

        Returns:
            ParsedReAct 或 None (无法解析)
        """
        if not response.content:
            return None

        content = response.content

        # 检测 Final Answer
        final_match = re.search(self.FINAL_ANSWER_PATTERN, content, re.DOTALL | re.IGNORECASE)
        if final_match:
            final_answer = final_match.group(1).strip()
            # 提取 Final Answer 前的 Thought
            thought_text = content[:final_match.start()].strip()
            thought_match = re.search(self.THOUGHT_PATTERN, thought_text, re.DOTALL | re.IGNORECASE)
            thought = thought_match.group(1).strip() if thought_match else None
            return ParsedReAct(
                has_final_answer=True,
                thought=thought,
                action_name=None,
                action_input=None,
                final_answer=final_answer,
                parse_method=ParseMethod.TEXT_REACT,
                raw_response=response,
            )

        # 检测 Action
        action_match = re.search(self.ACTION_PATTERN, content, re.IGNORECASE)
        if action_match:
            action_name = action_match.group(1).strip()

            # 提取 Thought
            thought_text = content[:action_match.start()].strip()
            thought_match = re.search(self.THOUGHT_PATTERN, thought_text, re.DOTALL | re.IGNORECASE)
            thought = thought_match.group(1).strip() if thought_match else thought_text

            # 提取 Action Input
            input_match = re.search(self.ACTION_INPUT_PATTERN, content, re.DOTALL | re.IGNORECASE)
            action_input: dict = {}
            if input_match:
                input_str = input_match.group(1).strip()
                # 尝试解析 JSON
                try:
                    # 提取 JSON 对象 (可能在文本中嵌有额外内容)
                    json_match = re.search(r'\{.*\}', input_str, re.DOTALL)
                    if json_match:
                        action_input = json.loads(json_match.group(0))
                    else:
                        action_input = {"raw": input_str}
                except json.JSONDecodeError:
                    action_input = {"raw": input_str}

            return ParsedReAct(
                has_final_answer=False,
                thought=thought,
                action_name=action_name,
                action_input=action_input,
                final_answer=None,
                parse_method=ParseMethod.TEXT_REACT,
                raw_response=response,
            )

        return None


class FallbackParser:
    """
    回退解析器 — 当 FunctionCallParser 和 ReActParser 均无法解析时使用。

    将整个 response.content 视为 Final Answer 或 Thought,
    尝试推断是否包含最终回答。
    """

    # 关键词启发式: 若 content 中包含这些模式, 认为是 Final Answer
    FINAL_INDICATORS: list[str] = [
        "总结", "综上", "最终", "答案", "结果是", "结论",
        "in summary", "in conclusion", "to conclude", "the answer is",
        "therefore", "thus",
    ]

    def parse(self, response: ChatResponse) -> ParsedReAct | None:
        """
        回退解析 — 将 content 整体视为一个结果。

        Args:
            response: LLM 返回的 ChatResponse

        Returns:
            ParsedReAct 或 None (content 为空)
        """
        if not response.content:
            return None

        content = response.content.strip()

        # 启发式判断是否包含最终回答
        is_final = any(
            indicator in content.lower() for indicator in self.FINAL_INDICATORS
        )

        if is_final:
            return ParsedReAct(
                has_final_answer=True,
                thought=None,
                action_name=None,
                action_input=None,
                final_answer=content,
                parse_method=ParseMethod.FALLBACK,
                raw_response=response,
            )

        # 尝试从内容中提取 Thought
        # 如果内容较短, 可能是纯 Thought
        if len(content) < 500:
            return ParsedReAct(
                has_final_answer=False,
                thought=content,
                action_name=None,
                action_input=None,
                final_answer=None,
                parse_method=ParseMethod.FALLBACK,
                raw_response=response,
            )

        # 长内容 → 视为 Final Answer
        return ParsedReAct(
            has_final_answer=True,
            thought=None,
            action_name=None,
            action_input=None,
            final_answer=content,
            parse_method=ParseMethod.FALLBACK,
            raw_response=response,
        )


class CompositeParser:
    """
    组合解析器 — 按优先级依次尝试多个解析器。

    1. FunctionCallParser: 解析 response.tool_calls (结构化, 无歧义)
    2. ReActParser: 解析 response.content 中的 Thought/Action/Final Answer 标签
    3. FallbackParser: 将整个 content 视为 Thought, 尝试推断是否包含最终回答
    """

    def __init__(self, parsers: list[OutputParser] | None = None) -> None:
        """
        初始化组合解析器。

        Args:
            parsers: 解析器列表, 按优先级排序。默认使用 FunctionCallParser → ReActParser → FallbackParser
        """
        self._parsers = parsers or [
            FunctionCallParser(),
            ReActParser(),
            FallbackParser(),
        ]

    def parse(self, response: ChatResponse) -> ParsedReAct:
        """
        按优先级尝试解析, 返回第一个成功的结果。

        若所有解析器都失败, FallbackParser 应始终返回一个结果。

        Args:
            response: LLM 返回的 ChatResponse

        Returns:
            ParsedReAct 解析结果
        """
        for parser in self._parsers:
            try:
                result = parser.parse(response)
                if result is not None:
                    logger.debug(f"Parser {parser.__class__.__name__} succeeded: {result.parse_method.value}")
                    return result
            except Exception as e:
                logger.warning(f"Parser {parser.__class__.__name__} failed: {e}")
                continue

        # 最终兜底: 返回一个空的 ParsedReAct
        logger.warning("All parsers failed, returning fallback ParsedReAct")
        return ParsedReAct(
            has_final_answer=True,
            thought=None,
            action_name=None,
            action_input=None,
            final_answer=response.content or "",
            parse_method=ParseMethod.FALLBACK,
            raw_response=response,
        )
