# LLM 客户端与 Provider 设计

## 1. 概述

LLM 调用层采用 Provider 模式实现后端可替换：
- **LLMProvider** (Protocol): 定义 LLM 调用的抽象接口
- **OpenAICompatProvider**: OpenAI-compatible API 的默认实现
- **LLMClient** (Facade): 封装重试、日志、Token 统计的 Facade

## 2. LLMProvider 接口

```python
class LLMProvider(Protocol):
    """
    LLM Provider 接口 — 定义 LLM 调用的抽象契约。

    实现此接口即可接入任意 LLM 后端 (OpenAI / DeepSeek / 本地模型 / 自定义代理)。
    """

    # ── 属性 ─────────────────────────────────────────
    provider_name: str              # Provider 标识名
    supported_models: list[str]     # 支持的模型列表
    default_model: str              # 默认模型

    # ── 核心接口 ─────────────────────────────────────
    def chat(self, messages: list[Message],
             model: str | None = None,
             tools: list[dict] | None = None,
             tool_choice: str = "auto",
             max_tokens: int = 4096,
             temperature: float = 0.7,
             timeout: float = 60.0) -> ChatResponse:
        """同步 Chat Completion。"""
        ...

    def chat_stream(self, messages: list[Message],
                    model: str | None = None,
                    tools: list[dict] | None = None,
                    max_tokens: int = 4096,
                    temperature: float = 0.7,
                    timeout: float = 60.0) -> Iterator[str]:
        """流式 Chat Completion (同步迭代器)。"""
        ...

    async def achat(self, messages: list[Message],
                    model: str | None = None,
                    tools: list[dict] | None = None,
                    tool_choice: str = "auto",
                    max_tokens: int = 4096,
                    temperature: float = 0.7,
                    timeout: float = 60.0) -> ChatResponse:
        """异步 Chat Completion。"""
        ...

    async def achat_stream(self, messages: list[Message],
                           model: str | None = None,
                           tools: list[dict] | None = None,
                           max_tokens: int = 4096,
                           temperature: float = 0.7,
                           timeout: float = 60.0) -> AsyncIterator[str]:
        """异步流式 Chat Completion。"""
        ...

    # ── 健康检查 ─────────────────────────────────────
    def health_check(self) -> bool:
        """检查 Provider 是否可用 (快速 ping)。"""
        ...
```

## 3. OpenAICompatProvider — 默认实现

```python
class OpenAICompatProvider:
    """
    OpenAI-compatible API Provider。

    适用于所有兼容 OpenAI Chat Completions API 的后端:
    - DeepSeek V4 (默认)
    - 任意 OpenAI-compatible 代理 (如 packyapi 等)
    - 本地模型 (如 Ollama, vLLM)

    配置通过环境变量注入 (provider-agnostic 命名):
    - LLM_API_KEY
    - LLM_BASE_URL
    - LLM_MODEL
    - LLM_MAX_TOKENS
    - LLM_TEMPERATURE
    - LLM_TIMEOUT
    - LLM_MAX_RETRIES
    """

    # ── 构造 ─────────────────────────────────────────
    def __init__(self,
                 api_key: str,
                 base_url: str,
                 model: str | None = None,
                 max_tokens: int = 4096,
                 temperature: float = 0.7,
                 timeout: float = 60.0,
                 max_retries: int = 3,
                 extra_headers: dict[str, str] | None = None) -> None:
        """
        初始化 Provider。

        参数:
            api_key: API 密钥
            base_url: API 基础地址 (如 "https://api.deepseek.com")
            model: 默认模型名称
            max_tokens: 最大生成 Token 数
            temperature: 采样温度 (0-2)
            timeout: 请求超时 (秒)
            max_retries: 可重试错误的最大重试次数
            extra_headers: 额外的 HTTP 头
        """

    # ── 重试与错误处理 ────────────────────────────────
    def _should_retry(self, error: Exception, attempt: int) -> bool:
        """
        判断是否应重试:
        - 网络超时 / 连接错误: 重试
        - HTTP 429 (限流): 重试, 等待 Retry-After 头或指数退避
        - HTTP 5xx: 重试
        - HTTP 4xx (除 429): 不重试
        - attempt >= max_retries: 不重试
        """

    def _calculate_backoff(self, attempt: int) -> float:
        """
        计算退避时间 (指数退避 + 抖动):
        min(base_delay * 2^attempt + random_jitter, max_delay)
        base_delay: 1.0s, max_delay: 60.0s
        """
```

## 4. LLMClient — Facade

```python
class LLMClient:
    """
    LLM 客户端 Facade — 封装重试、日志、Token 统计。

    对上层 (ReActEngine / BaseAgent) 提供统一接口,
    隐藏具体 Provider 实现细节。
    """

    # ── 属性 ─────────────────────────────────────────
    provider: LLMProvider               # 当前 Provider 实例
    max_retries: int                    # 最大重试次数
    token_tracker: TokenTracker         # Token 用量追踪器

    # ── 构造 ─────────────────────────────────────────
    def __init__(self, provider: LLMProvider,
                 config: Config) -> None:
        """
        初始化客户端。
        - 绑定 Provider 实例
        - 从 Config 读取 max_retries 等参数
        - 初始化 TokenTracker
        """

    # ── 同步接口 ─────────────────────────────────────
    def chat(self, messages: list[Message],
             tools: list[dict] | None = None,
             tool_choice: str = "auto",
             model: str | None = None,
             temperature: float | None = None) -> ChatResponse:
        """
        发送 Chat Completion 请求 (同步, 带重试)。

        内部流程:
        1. 合并参数 (不传则使用 Provider 默认值)
        2. 调用 provider.chat(...)
        3. 成功 → 记录 TokenTracker, 返回 ChatResponse
        4. 可重试错误 → 等待退避后重试
        5. 不可重试错误 → 转为对应的 LLMError 子类抛出
        """

    def chat_stream(self, messages: list[Message],
                    tools: list[dict] | None = None,
                    model: str | None = None,
                    temperature: float | None = None) -> Iterator[str]:
        """流式 Chat Completion (同步迭代器, 带重试)。"""

    # ── 异步接口 ─────────────────────────────────────
    async def achat(self, messages: list[Message],
                    tools: list[dict] | None = None,
                    tool_choice: str = "auto",
                    model: str | None = None,
                    temperature: float | None = None) -> ChatResponse:
        """同 chat(), 异步版本。"""

    async def achat_stream(self, messages: list[Message],
                           tools: list[dict] | None = None,
                           model: str | None = None,
                           temperature: float | None = None) -> AsyncIterator[str]:
        """同 chat_stream(), 异步版本。"""

    # ── 统计 ─────────────────────────────────────────
    def get_token_usage(self) -> TokenUsage:
        """获取累计 Token 用量。"""

    def reset_token_usage(self) -> None:
        """重置 Token 用量计数。"""
```

## 5. 环境变量配置 (Provider-Agnostic)

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `LLM_API_KEY` | API 密钥 (必需) | 无, 必须设置 |
| `LLM_BASE_URL` | API 基础地址 | `https://api.deepseek.com` |
| `LLM_MODEL` | 默认模型名称 | `deepseek-v4-pro` |
| `LLM_MAX_TOKENS` | 最大生成 Token 数 | `4096` |
| `LLM_TEMPERATURE` | 采样温度 (0-2) | `0.7` |
| `LLM_TIMEOUT` | 请求超时 (秒) | `60` |
| `LLM_MAX_RETRIES` | 最大重试次数 | `3` |
| `LLM_BASE_DELAY` | 重试基础延迟 (秒) | `1.0` |
| `LLM_MAX_DELAY` | 重试最大延迟 (秒) | `60.0` |

命名从 `DEEPSEEK_*` 改为 `LLM_*`，去除对具体厂商的绑定，提高配置的普适性。

为兼容旧项目，框架同时支持检测 `DEEPSEEK_*` 前缀的环境变量（若 `LLM_*` 未设置则回退）。

## 6. 数据模型

```python
@dataclass
class Message:
    """对话消息 — 兼容 OpenAI 格式"""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None             # 可选发送者名称
    tool_call_id: str | None = None     # Tool 调用 ID (role="tool" 时)
    tool_calls: list[ToolCall] | None = None  # Assistant 的 tool_calls (role="assistant" 时)

@dataclass
class ChatResponse:
    """Chat Completion 响应"""
    content: str | None                 # 纯文本回复
    tool_calls: list[ToolCall] | None   # Function Call 请求
    usage: TokenUsage                   # Token 用量
    finish_reason: str                  # "stop" | "tool_calls" | "length" | "content_filter"
    model: str                          # 实际使用的模型名称
    request_id: str | None = None       # 请求追踪 ID (便于调试)

@dataclass
class ToolCall:
    """Function Call"""
    id: str                             # Tool Call ID (全局唯一)
    function_name: str                  # 函数名
    function_args: dict                 # 函数参数 (已解析为 dict)

@dataclass
class TokenUsage:
    """Token 用量统计"""
    prompt_tokens: int = 0              # 输入 Token
    completion_tokens: int = 0          # 输出 Token
    total_tokens: int = 0               # 总计

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """支持累加操作。"""

class TokenTracker:
    """
    Token 用量追踪器 — 记录每次 LLM 调用的 Token 消耗。
    支持按会话 / 按 Agent / 按时间段聚合统计。
    """
    def record(self, usage: TokenUsage) -> None: ...
    def get_total(self) -> TokenUsage: ...
    def get_by_session(self, session_id: str) -> TokenUsage: ...
```

## 7. API 请求格式 (OpenAI-compatible)

### 7.1 基本 Chat Completion

```json
POST {LLM_BASE_URL}/v1/chat/completions
Headers:
  Authorization: Bearer {LLM_API_KEY}
  Content-Type: application/json

Body:
{
  "model": "{LLM_MODEL}",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "max_tokens": 4096,
  "temperature": 0.7,
  "stream": false
}
```

### 7.2 带 Function Calling 的请求

```json
{
  "model": "{LLM_MODEL}",
  "messages": [...],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "读取指定路径的文件内容",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {"type": "string", "description": "文件路径 (绝对或相对)"}
          },
          "required": ["path"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

## 8. 错误体系

```python
class LLMError(Exception):
    """LLM 错误基类"""

class LLMAuthError(LLMError):
    """认证错误 (HTTP 401) — API Key 无效或过期"""

class LLMRateLimitError(LLMError):
    """限流错误 (HTTP 429) — 可重试, 自动等待 Retry-After"""

class LLMServerError(LLMError):
    """服务端错误 (HTTP 5xx) — 可重试"""

class LLMTimeoutError(LLMError):
    """请求超时 — 可重试"""

class LLMConfigError(LLMError):
    """配置错误 — api_key 未设置等, 不可重试"""

class LLMContentFilterError(LLMError):
    """内容过滤 (finish_reason="content_filter") — 不可重试"""
```

## 9. 使用示例

```python
# 初始化: 自动从环境变量读取配置
config = Config.from_env()
provider = OpenAICompatProvider(
    api_key=config.llm_api_key,
    base_url=config.llm_base_url,
    model=config.llm_model,
)
client = LLMClient(provider, config)

# 同步调用
response = client.chat([
    Message(role="system", content="You are a helpful assistant."),
    Message(role="user", content="What is Python?")
])
print(response.content)
print(f"Tokens: {response.usage.total_tokens}")

# 流式调用
for chunk in client.chat_stream([...]):
    print(chunk, end="", flush=True)

# 带 Function Calling
response = client.chat(
    messages=[...],
    tools=tool_manager.get_tools_schema(),
    tool_choice="auto"
)
if response.tool_calls:
    for tc in response.tool_calls:
        result = tool_manager.execute(tc.function_name, **tc.function_args)
```
