"""
LLMProvider 接口定义 — 定义 LLM 调用的抽象契约。

实现此接口即可接入任意 LLM 后端 (OpenAI / DeepSeek / 本地模型 / 自定义代理)。
"""

from typing import Any, AsyncIterator, Iterator, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """
    LLM Provider 接口 — 定义 LLM 调用的抽象契约。

    实现此接口即可接入任意 LLM 后端 (OpenAI / DeepSeek / 本地模型 / 自定义代理)。
    """

    # ── 属性 ─────────────────────────────────────────
    provider_name: str  # Provider 标识名
    supported_models: list[str]  # 支持的模型列表
    default_model: str  # 默认模型

    # ── 核心接口 ─────────────────────────────────────
    def chat(
        self,
        messages: list[Any],
        model: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> Any:
        """
        同步 Chat Completion。

        Args:
            messages: 消息列表 (Message 对象列表)
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            tool_choice: Tool 选择策略 ("auto", "none", "required")
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数

        Returns:
            ChatResponse 对象
        """
        ...

    def chat_stream(
        self,
        messages: list[Any],
        model: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> Iterator[str]:
        """
        流式 Chat Completion (同步迭代器)。

        Args:
            messages: 消息列表
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数

        Yields:
            str: 增量文本内容
        """
        ...

    async def achat(
        self,
        messages: list[Any],
        model: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> Any:
        """
        异步 Chat Completion。

        Args:
            messages: 消息列表
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            tool_choice: Tool 选择策略
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数

        Returns:
            ChatResponse 对象
        """
        ...

    async def achat_stream(
        self,
        messages: list[Any],
        model: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ) -> AsyncIterator[str]:
        """
        异步流式 Chat Completion。

        Args:
            messages: 消息列表
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数

        Yields:
            str: 增量文本内容
        """
        ...

    # ── 健康检查 ─────────────────────────────────────
    def health_check(self) -> bool:
        """
        检查 Provider 是否可用 (快速 ping)。

        Returns:
            bool: True 表示可用
        """
        ...
