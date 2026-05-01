"""
OpenAI-compatible API Provider。

适用于所有兼容 OpenAI Chat Completions API 的后端:
- DeepSeek V4 (默认)
- 任意 OpenAI-compatible 代理
- 本地模型 (如 Ollama, vLLM)

配置通过环境变量注入 (ANTHROPIC_* 命名体系):
- ANTHROPIC_AUTH_TOKEN      — API 认证令牌 (必需)
- ANTHROPIC_BASE_URL         — API 基础地址
- ANTHROPIC_MODEL            — 默认模型名称
- ANTHROPIC_SMALL_FAST_MODEL — 小型快速模型 (用于简单任务, 可选)
- ANTHROPIC_CUSTOM_MODEL_OPTION — 自定义模型选项 (JSON 字符串, 可选)
- API_TIMEOUT_MS             — API 请求超时时间 (毫秒)
"""

import json
import logging
import random
import time
from typing import Any, AsyncIterator, Iterator

import httpx

from src.core.models import ChatResponse, Message, TokenUsage, ToolCall
from src.llm.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


# ── LLM 错误体系 ──────────────────────────────────────


class LLMError(Exception):
    """LLM 错误基类。"""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error


class LLMAuthError(LLMError):
    """认证错误 (HTTP 401) — API Key 无效或过期。"""
    pass


class LLMRateLimitError(LLMError):
    """限流错误 (HTTP 429) — 可重试, 自动等待 Retry-After。"""
    pass


class LLMServerError(LLMError):
    """服务端错误 (HTTP 5xx) — 可重试。"""
    pass


class LLMTimeoutError(LLMError):
    """请求超时 — 可重试。"""
    pass


class LLMConfigError(LLMError):
    """配置错误 — api_key 未设置等, 不可重试。"""
    pass


class LLMContentFilterError(LLMError):
    """内容过滤 (finish_reason="content_filter") — 不可重试。"""
    pass


class OpenAICompatProvider:
    """
    OpenAI-compatible API Provider。

    适用于所有兼容 OpenAI Chat Completions API 的后端:
    - DeepSeek V4 (默认)
    - 任意 OpenAI-compatible 代理 (如 packyapi 等)
    - 本地模型 (如 Ollama, vLLM)
    """

    provider_name: str = "openai_compat"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str | None = None,
        small_fast_model: str | None = None,
        custom_model_option: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
        max_retries: int = 3,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """
        初始化 OpenAI-compatible Provider。

        Args:
            api_key: API 认证令牌 (来自 ANTHROPIC_AUTH_TOKEN 环境变量)
            base_url: API 基础地址 (来自 ANTHROPIC_BASE_URL 环境变量)
            model: 默认模型名称 (来自 ANTHROPIC_MODEL 环境变量)
            small_fast_model: 小型快速模型名称 (来自 ANTHROPIC_SMALL_FAST_MODEL 环境变量, 可选)
            custom_model_option: 自定义模型选项 (来自 ANTHROPIC_CUSTOM_MODEL_OPTION 环境变量, JSON 格式, 可选)
            max_tokens: 最大生成 Token 数 (默认 4096)
            temperature: 采样温度 0-2 (默认 0.7)
            timeout: 请求超时秒数 (由 API_TIMEOUT_MS 环境变量转换而来, 默认 60.0)
            max_retries: 可重试错误的最大重试次数 (默认 3)
            extra_headers: 额外的 HTTP 请求头 (用于自定义认证或追踪, 可选)
        """
        self._api_key = api_key
        # 确保 base_url 不以斜杠结尾
        self._base_url = base_url.rstrip("/")
        self.default_model = model or "deepseek-v4-pro"
        self._small_fast_model = small_fast_model
        self._custom_model_option = custom_model_option
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._timeout = timeout
        self._max_retries = max_retries
        self._extra_headers = extra_headers or {}

        self.supported_models = [self.default_model]
        if small_fast_model:
            self.supported_models.append(small_fast_model)

        # 解析自定义模型选项
        self._custom_options: dict = {}
        if custom_model_option:
            try:
                self._custom_options = json.loads(custom_model_option)
            except json.JSONDecodeError:
                logger.warning(f"无法解析 ANTHROPIC_CUSTOM_MODEL_OPTION: {custom_model_option}")

    def _build_headers(self) -> dict[str, str]:
        """构建 HTTP 请求头。"""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self._extra_headers)
        return headers

    def _build_request_body(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """构建 API 请求体。"""
        body: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._serialize_messages(messages),
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
            "temperature": temperature if temperature is not None else self._temperature,
            "stream": stream,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice

        # 合并自定义模型选项
        body.update(self._custom_options)

        return body

    def _serialize_messages(self, messages: list[Message]) -> list[dict]:
        """将 Message 对象列表序列化为 API 所需的 dict 列表。"""
        result: list[dict] = []
        for msg in messages:
            item: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                item["name"] = msg.name
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function_name,
                            "arguments": json.dumps(tc.function_args, ensure_ascii=False),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            result.append(item)
        return result

    def _parse_response(self, response_data: dict) -> ChatResponse:
        """解析 API 响应为 ChatResponse 对象。"""
        choice = response_data["choices"][0]
        message = choice.get("message", {})

        # 解析 tool_calls
        tool_calls: list[ToolCall] | None = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.get("id", ""),
                        function_name=tc["function"]["name"],
                        function_args=args,
                    )
                )

        # 解析 token 用量
        usage_data = response_data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.get("finish_reason", "stop"),
            model=response_data.get("model", ""),
            request_id=response_data.get("id"),
        )

    def _should_retry(self, error: Exception, attempt: int) -> bool:
        """
        判断是否应重试:
        - 网络超时 / 连接错误: 重试
        - HTTP 429 (限流): 重试, 等待 Retry-After 头或指数退避
        - HTTP 5xx: 重试
        - HTTP 4xx (除 429): 不重试
        - attempt >= max_retries: 不重试
        """
        if attempt >= self._max_retries:
            return False

        if isinstance(error, httpx.TimeoutException):
            return True
        if isinstance(error, httpx.NetworkError):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status == 429:
                return True
            if 500 <= status < 600:
                return True
            return False
        return True

    def _calculate_backoff(self, attempt: int) -> float:
        """
        计算退避时间 (指数退避 + 抖动):
        min(base_delay * 2^attempt + random_jitter, max_delay)
        base_delay: 1.0s, max_delay: 60.0s
        """
        import random as rand

        base_delay = 1.0
        max_delay = 60.0
        delay = min(base_delay * (2 ** attempt) + rand.uniform(0, 1), max_delay)
        return delay

    def _classify_error(self, error: Exception) -> LLMError:
        """将 HTTP/网络异常分类为对应的 LLMError 子类。"""
        if isinstance(error, httpx.TimeoutException):
            return LLMTimeoutError(str(error), error)
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status == 401:
                return LLMAuthError(f"认证失败 (HTTP 401): {error}", error)
            if status == 429:
                return LLMRateLimitError(f"请求限流 (HTTP 429): {error}", error)
            if 500 <= status < 600:
                return LLMServerError(f"服务端错误 (HTTP {status}): {error}", error)
            if status == 400:
                # 尝试检查是否是内容过滤
                try:
                    body = error.response.json()
                    if "content_filter" in str(body):
                        return LLMContentFilterError(f"内容过滤: {error}", error)
                except Exception:
                    pass
        return LLMError(str(error), error)

    # ── 同步 chat ───────────────────────────────────

    def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> ChatResponse:
        """
        同步 Chat Completion, 带自动重试和错误分类。

        Args:
            messages: 消息列表
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            tool_choice: Tool 选择策略
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数, None 则使用默认值

        Returns:
            ChatResponse 对象

        Raises:
            LLMAuthError: 认证失败
            LLMRateLimitError: 限流 (已耗尽重试)
            LLMServerError: 服务端错误 (已耗尽重试)
            LLMTimeoutError: 超时 (已耗尽重试)
            LLMContentFilterError: 内容过滤
        """
        actual_timeout = timeout if timeout is not None else self._timeout

        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=actual_timeout) as client:
                    response = client.post(
                        f"{self._base_url}/v1/chat/completions",
                        headers=self._build_headers(),
                        json=self._build_request_body(
                            messages=messages,
                            model=model,
                            tools=tools,
                            tool_choice=tool_choice,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            stream=False,
                        ),
                    )
                    response.raise_for_status()
                    return self._parse_response(response.json())

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            time.sleep(float(retry_after))
                        except ValueError:
                            time.sleep(self._calculate_backoff(attempt))
                    else:
                        time.sleep(self._calculate_backoff(attempt))
                    if attempt >= self._max_retries:
                        raise LLMRateLimitError(
                            f"请求限流 (HTTP 429), 已重试 {self._max_retries} 次", e
                        )
                    continue
                raise self._classify_error(e)

            except httpx.TimeoutException as e:
                if self._should_retry(e, attempt):
                    time.sleep(self._calculate_backoff(attempt))
                    continue
                raise LLMTimeoutError(f"请求超时, 已重试 {self._max_retries} 次", e)

            except httpx.NetworkError as e:
                if self._should_retry(e, attempt):
                    time.sleep(self._calculate_backoff(attempt))
                    continue
                raise self._classify_error(e)

        # 不应到达此处, 但作为安全保障
        raise LLMError("chat() 异常退出: 超过最大重试次数")

    # ── 流式 chat ───────────────────────────────────

    def chat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> Iterator[str]:
        """
        流式 Chat Completion (同步迭代器)。

        Args:
            messages: 消息列表
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数, None 则使用默认值

        Yields:
            str: 增量文本内容
        """
        actual_timeout = timeout if timeout is not None else self._timeout

        for attempt in range(self._max_retries + 1):
            try:
                with httpx.Client(timeout=actual_timeout) as client:
                    with client.stream(
                        "POST",
                        f"{self._base_url}/v1/chat/completions",
                        headers=self._build_headers(),
                        json=self._build_request_body(
                            messages=messages,
                            model=model,
                            tools=tools,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            stream=True,
                        ),
                    ) as response:
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    return
                                try:
                                    data = json.loads(data_str)
                                    choices = data.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            yield content
                                except json.JSONDecodeError:
                                    continue
                    return  # 正常完成

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    time.sleep(self._calculate_backoff(attempt))
                    if attempt >= self._max_retries:
                        raise LLMRateLimitError(
                            f"请求限流 (HTTP 429), 已重试 {self._max_retries} 次", e
                        )
                    continue
                raise self._classify_error(e)

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if self._should_retry(e, attempt):
                    time.sleep(self._calculate_backoff(attempt))
                    continue
                raise self._classify_error(e)

    # ── 异步 chat ───────────────────────────────────

    async def achat(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> ChatResponse:
        """
        异步 Chat Completion, 带自动重试和错误分类。

        Args:
            messages: 消息列表
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            tool_choice: Tool 选择策略
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数, None 则使用默认值

        Returns:
            ChatResponse 对象

        Raises:
            LLMAuthError: 认证失败
            LLMRateLimitError: 限流 (已耗尽重试)
            LLMServerError: 服务端错误 (已耗尽重试)
            LLMTimeoutError: 超时 (已耗尽重试)
            LLMContentFilterError: 内容过滤
        """
        actual_timeout = timeout if timeout is not None else self._timeout

        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=actual_timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/v1/chat/completions",
                        headers=self._build_headers(),
                        json=self._build_request_body(
                            messages=messages,
                            model=model,
                            tools=tools,
                            tool_choice=tool_choice,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            stream=False,
                        ),
                    )
                    response.raise_for_status()
                    return self._parse_response(response.json())

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    await self._async_sleep(self._calculate_backoff(attempt))
                    if attempt >= self._max_retries:
                        raise LLMRateLimitError(
                            f"请求限流 (HTTP 429), 已重试 {self._max_retries} 次", e
                        )
                    continue
                raise self._classify_error(e)

            except httpx.TimeoutException as e:
                if self._should_retry(e, attempt):
                    await self._async_sleep(self._calculate_backoff(attempt))
                    continue
                raise LLMTimeoutError(f"请求超时, 已重试 {self._max_retries} 次", e)

            except httpx.NetworkError as e:
                if self._should_retry(e, attempt):
                    await self._async_sleep(self._calculate_backoff(attempt))
                    continue
                raise self._classify_error(e)

        raise LLMError("achat() 异常退出: 超过最大重试次数")

    # ── 异步流式 chat ───────────────────────────────

    async def achat_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """
        异步流式 Chat Completion。

        Args:
            messages: 消息列表
            model: 模型名称, None 则使用默认模型
            tools: Function Calling Tool Schema 列表
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 0-2
            timeout: 请求超时秒数, None 则使用默认值

        Yields:
            str: 增量文本内容
        """
        actual_timeout = timeout if timeout is not None else self._timeout

        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=actual_timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{self._base_url}/v1/chat/completions",
                        headers=self._build_headers(),
                        json=self._build_request_body(
                            messages=messages,
                            model=model,
                            tools=tools,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            stream=True,
                        ),
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    return
                                try:
                                    data = json.loads(data_str)
                                    choices = data.get("choices", [])
                                    if choices:
                                        delta = choices[0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            yield content
                                except json.JSONDecodeError:
                                    continue
                    return

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    await self._async_sleep(self._calculate_backoff(attempt))
                    if attempt >= self._max_retries:
                        raise LLMRateLimitError(
                            f"请求限流 (HTTP 429), 已重试 {self._max_retries} 次", e
                        )
                    continue
                raise self._classify_error(e)

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if self._should_retry(e, attempt):
                    await self._async_sleep(self._calculate_backoff(attempt))
                    continue
                raise self._classify_error(e)

    # ── 健康检查 ─────────────────────────────────────

    def health_check(self) -> bool:
        """
        检查 Provider 是否可用 (快速 ping)。

        Returns:
            bool: True 表示可用
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(
                    f"{self._base_url}/v1/models",
                    headers=self._build_headers(),
                )
                return response.status_code == 200
        except Exception:
            return False

    # ── 辅助方法 ─────────────────────────────────────

    async def _async_sleep(self, seconds: float) -> None:
        """异步 sleep。"""
        import asyncio

        await asyncio.sleep(seconds)
