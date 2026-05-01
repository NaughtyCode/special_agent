"""
LLM 客户端 Facade — 封装重试、日志、Token 统计。

对上层 (ReActEngine / BaseAgent) 提供统一接口,
隐藏具体 Provider 实现细节。
"""

import logging
from typing import Any, AsyncIterator, Iterator

from src.core.models import ChatResponse, Message, TokenUsage
from src.infra.config import Config
from src.llm.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


class TokenTracker:
    """
    Token 用量追踪器 — 记录每次 LLM 调用的 Token 消耗。

    支持按会话 / 按 Agent / 按时间段聚合统计。
    """

    def __init__(self) -> None:
        """初始化 TokenTracker。"""
        self._total = TokenUsage()
        self._session_records: dict[str, TokenUsage] = {}
        self._call_count: int = 0

    def record(self, usage: TokenUsage) -> None:
        """
        记录一次 LLM 调用的 Token 用量。

        Args:
            usage: Token 用量统计
        """
        self._total += usage
        self._call_count += 1

    def get_total(self) -> TokenUsage:
        """
        获取累计 Token 用量。

        Returns:
            TokenUsage: 累计 Token 用量
        """
        return self._total

    def get_by_session(self, session_id: str) -> TokenUsage:
        """
        按会话获取 Token 用量。

        Args:
            session_id: 会话 ID

        Returns:
            TokenUsage: 该会话的 Token 用量
        """
        if session_id not in self._session_records:
            self._session_records[session_id] = TokenUsage()
        return self._session_records[session_id]

    @property
    def call_count(self) -> int:
        """获取 LLM 调用次数。"""
        return self._call_count

    def reset(self) -> None:
        """重置 Token 用量计数。"""
        self._total = TokenUsage()
        self._call_count = 0


class LLMClient:
    """
    LLM 客户端 Facade — 封装重试、日志、Token 统计。

    对上层 (ReActEngine / BaseAgent) 提供统一接口,
    隐藏具体 Provider 实现细节。
    """

    def __init__(self, provider: LLMProvider, config: Config) -> None:
        """
        初始化客户端。

        Args:
            provider: LLMProvider 实例
            config: 全局 Config 实例
        """
        self.provider = provider
        self._config = config
        self.max_retries = config.llm_max_retries
        self.token_tracker = TokenTracker()

    # ── 同步接口 ─────────────────────────────────────

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatResponse:
        """
        发送 Chat Completion 请求 (同步, 带重试)。

        内部流程:
        1. 合并参数 (不传则使用 Provider 默认值)
        2. 调用 provider.chat(...)
        3. 成功 → 记录 TokenTracker, 返回 ChatResponse
        4. 可重试错误 → 等待退避后重试
        5. 不可重试错误 → 转为对应的 LLMError 子类抛出

        Args:
            messages: 消息列表
            tools: Function Calling Tool Schema 列表
            tool_choice: Tool 选择策略
            model: 模型名称, None 则使用默认模型
            temperature: 采样温度, None 则使用默认值

        Returns:
            ChatResponse 对象
        """
        response = self.provider.chat(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature if temperature is not None else self._config.llm_temperature,
            max_tokens=self._config.llm_max_tokens,
        )

        # 记录 Token 用量
        if response.usage:
            self.token_tracker.record(response.usage)

        # 记录 LLM 调用日志
        if self._config.log_llm_calls:
            logger.debug(
                f"LLM call: model={response.model}, "
                f"tokens={response.usage.total_tokens if response.usage else 'N/A'}, "
                f"finish_reason={response.finish_reason}"
            )

        return response

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Iterator[str]:
        """
        流式 Chat Completion (同步迭代器, 带重试)。

        Args:
            messages: 消息列表
            tools: Function Calling Tool Schema 列表
            model: 模型名称, None 则使用默认模型
            temperature: 采样温度, None 则使用默认值

        Yields:
            str: 增量文本内容
        """
        for chunk in self.provider.chat_stream(
            messages=messages,
            model=model,
            tools=tools,
            temperature=temperature if temperature is not None else self._config.llm_temperature,
            max_tokens=self._config.llm_max_tokens,
        ):
            yield chunk

    # ── 异步接口 ─────────────────────────────────────

    async def achat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatResponse:
        """
        异步 Chat Completion。

        Args:
            messages: 消息列表
            tools: Function Calling Tool Schema 列表
            tool_choice: Tool 选择策略
            model: 模型名称, None 则使用默认模型
            temperature: 采样温度, None 则使用默认值

        Returns:
            ChatResponse 对象
        """
        response = await self.provider.achat(
            messages=messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature if temperature is not None else self._config.llm_temperature,
            max_tokens=self._config.llm_max_tokens,
        )

        if response.usage:
            self.token_tracker.record(response.usage)

        return response

    async def achat_stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """
        异步流式 Chat Completion。

        Args:
            messages: 消息列表
            tools: Function Calling Tool Schema 列表
            model: 模型名称, None 则使用默认模型
            temperature: 采样温度, None 则使用默认值

        Yields:
            str: 增量文本内容
        """
        async for chunk in self.provider.achat_stream(
            messages=messages,
            model=model,
            tools=tools,
            temperature=temperature if temperature is not None else self._config.llm_temperature,
            max_tokens=self._config.llm_max_tokens,
        ):
            yield chunk

    # ── 统计 ─────────────────────────────────────────

    def get_token_usage(self) -> TokenUsage:
        """
        获取累计 Token 用量。

        Returns:
            TokenUsage: 累计 Token 用量
        """
        return self.token_tracker.get_total()

    def reset_token_usage(self) -> None:
        """重置 Token 用量计数。"""
        self.token_tracker.reset()
