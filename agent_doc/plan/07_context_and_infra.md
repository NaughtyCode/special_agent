# 上下文存储与基础设施设计

## 1. ContextStore — 上下文存储

### 1.1 概述

`ContextStore` 管理 Agent 执行期间的对话历史、Tool 调用记录和上下文变量。
是 ReAct 循环的记忆载体，支持可注入的压缩策略。

### 1.2 类设计

```python
class ContextStore:
    """
    上下文存储 — 管理对话历史和 Agent 工作记忆。

    职责:
    - 存储完整的消息历史 (system / user / assistant / tool)
    - 存储每次 ReAct 迭代的轨迹
    - 管理上下文变量 (供 Tool 和 Agent 共享)
    - 支持上下文窗口管理 (可注入压缩策略, 防止超出 LLM Token 限制)
    """

    # ── 存储 ─────────────────────────────────────────
    _messages: list[Message]            # 完整消息历史
    _react_steps: list[ReActStep]       # ReAct 迭代轨迹
    _variables: dict[str, Any]          # 上下文变量 (键值对)
    _tool_results: dict[str, ToolResult]  # Tool 执行结果缓存 (key = tool_name+args_hash)
    _system_message: Message | None     # 保留的 System Message (压缩后不丢)

    # ── 配置 ─────────────────────────────────────────
    max_context_tokens: int             # 上下文窗口 Token 上限 (从 Config)
    compress_strategy: CompressStrategy # 压缩策略 (可注入)

    # ── 消息操作 ─────────────────────────────────────
    def add_message(self, role: str, content: str,
                    name: str | None = None,
                    tool_call_id: str | None = None,
                    tool_calls: list[ToolCall] | None = None) -> None:
        """添加一条消息到历史。"""

    def get_messages(self, last_n: int | None = None) -> list[Message]:
        """
        获取消息历史。
        若指定 last_n, 只返回最近 N 条。
        """

    def get_messages_for_llm(self) -> list[Message]:
        """
        获取适合发送给 LLM 的消息列表。
        自动调用 compress_strategy 确保 Token 不超限。
        """

    def estimate_tokens(self) -> int:
        """
        估算当前消息历史的 Token 数。
        使用 tiktoken (若可用) 或启发式算法 (字符数 / 4)。
        """

    def clear(self) -> None:
        """清除所有历史 (保留 system_message)。"""

    # ── ReAct 轨迹 ───────────────────────────────────
    def add_react_step(self, step: ReActStep) -> None:
        """记录一次 ReAct 迭代。"""

    def get_react_trajectory(self) -> list[ReActStep]:
        """获取完整的 ReAct 轨迹。"""

    def get_last_n_steps(self, n: int) -> list[ReActStep]:
        """获取最近 N 次迭代轨迹。"""

    # ── 变量操作 ─────────────────────────────────────
    def set_variable(self, key: str, value: Any) -> None:
        """设置上下文变量 (跨 Tool / Agent 共享)。"""

    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取上下文变量。"""

    def get_all_variables(self) -> dict[str, Any]:
        """获取所有上下文变量 (快照副本)。"""

    # ── Tool 结果缓存 ────────────────────────────────
    def cache_tool_result(self, tool_name: str, args: dict,
                          result: ToolResult) -> None:
        """缓存 Tool 执行结果 (相同 tool_name + 相同 args_hash 可直接复用)。"""

    def get_cached_result(self, tool_name: str,
                          **kwargs) -> ToolResult | None:
        """查找缓存的 Tool 结果 (用于幂等调用优化)。"""

    # ── 导出/导入 ─────────────────────────────────────
    def export_snapshot(self) -> dict:
        """
        导出上下文快照 (用于会话持久化或跨 Agent 传递)。
        返回可序列化的 dict。
        """

    def import_snapshot(self, snapshot: dict) -> None:
        """从快照恢复上下文。"""
```

### 1.3 上下文压缩策略

```python
class CompressStrategy(Protocol):
    """
    上下文压缩策略接口 — 当 Token 数超限时触发。

    框架内置三种实现, 可通过 Config 选择或自定义。
    """
    def compress(self, messages: list[Message],
                 system_message: Message,
                 max_tokens: int) -> list[Message]: ...

class SlidingWindowStrategy:
    """
    滑动窗口策略。
    保留 System Message + 最近 N 条消息, 丢弃旧的。
    简单高效, 但可能丢失早期重要信息。
    """

class SummarizeStrategy:
    """
    摘要压缩策略。
    将中间轮次的消息压缩为一段摘要 (通过 LLM 生成摘要),
    保留 System Message + 早期上下文摘要 + 最近消息。
    保留更多语义信息, 但需要额外 LLM 调用。
    """

class HybridStrategy:
    """
    混合策略 (默认)。
    1. 优先丢弃旧的 Tool 结果 (大段输出文本)
    2. 若仍超限, 将中间轮次压缩为摘要
    3. 若仍超限, 应用滑动窗口
    4. 确保 system_message 始终保留
    """
```

## 2. EventBus — 事件总线

```python
class EventBus:
    """
    事件总线 — 发布-订阅模式, 解耦 Agent 生命周期通知。

    事件类型:
    - AgentLifecycleEvent: INITIALIZED / STARTED / COMPLETED / ERROR / SPAWNED / STOPPED
    - ToolCallEvent: BEFORE_EXECUTE / AFTER_EXECUTE
    - LLMCallEvent: BEFORE_CALL / AFTER_CALL
    - ReActIterationEvent: ITERATION_START / ITERATION_END
    - CrewLifecycleEvent: PLANNED / STARTED / MEMBER_STARTED / MEMBER_COMPLETED / MEMBER_FAILED / COMPLETED / FAILED
      (每个 Crew 事件携带 CrewEvent 负载数据, 含 crew_id, member_name, task_id 等上下文)
    """

    def subscribe(self, event_type: type, handler: Callable) -> None:
        """订阅事件。handler 接收事件对象作为参数。"""

    def unsubscribe(self, event_type: type, handler: Callable) -> None:
        """取消订阅。"""

    def publish(self, event: Event) -> None:
        """
        发布事件 (同步, 按订阅顺序依次调用 handler)。
        单个 handler 异常不影响其他 handler。
        """

    async def publish_async(self, event: Event) -> None:
        """发布事件 (异步, 并发调用所有 handler)。"""
```

## 3. Config — 配置管理 (Provider-Agnostic)

```python
class Config:
    """
    全局配置管理 — 从环境变量读取所有配置。

    所有字段名去除厂商前缀, 使用 provider-agnostic 命名。
    兼容旧的 DEEPSEEK_* 环境变量 (LLM_* 未设置时回退)。
    """

    # ── LLM Provider ────────────────────────────────
    llm_api_key: str                        # API 密钥 (环境变量: LLM_API_KEY)
    llm_base_url: str = "https://api.deepseek.com/anthropic"  # API 地址 (LLM_BASE_URL)
    llm_model: str = "deepseek-v4-pro"        # 默认模型 (LLM_MODEL)
    llm_max_tokens: int = 4096              # 最大生成 Token (LLM_MAX_TOKENS)
    llm_temperature: float = 0.7            # 采样温度 (LLM_TEMPERATURE)
    llm_timeout: float = 60.0               # 请求超时秒 (LLM_TIMEOUT)
    llm_max_retries: int = 3                # 最大重试次数 (LLM_MAX_RETRIES)
    llm_retry_base_delay: float = 1.0       # 重试基础延迟秒 (LLM_BASE_DELAY)
    llm_retry_max_delay: float = 60.0       # 重试最大延迟秒 (LLM_MAX_DELAY)

    # ── Agent ───────────────────────────────────────
    agent_max_iterations: int = 10          # ReAct 最大迭代次数 (AGENT_MAX_ITERATIONS)
    agent_max_consecutive_failures: int = 3 # 连续 Tool 失败上限 (AGENT_MAX_CONSECUTIVE_FAILURES)
    agent_max_call_depth: int = 3           # Agent 嵌套调用最大深度 (AGENT_MAX_CALL_DEPTH)
    agent_tool_execution_timeout: float = 30.0  # Tool 执行超时秒 (AGENT_TOOL_TIMEOUT)
    agent_default_name: str = "RootAgent"   # 默认 Agent 名称

    # ── Crew ────────────────────────────────────────
    # Crew 团队编排相关配置 — CrewOrchestrator 在初始化时读取这些值
    crew_max_parallel: int = 4              # Crew 最大并行成员数 (CREW_MAX_PARALLEL)
                                              # 控制 PARALLEL 和 DAG 策略下的最大并发 Agent 数
    crew_max_iterations: int = 3            # Crew 任务分解最大 LLM 迭代 (CREW_MAX_ITERATIONS)
                                              # plan_crew() 调用 LLM 分解任务时的最大重试次数
    crew_plan_temperature: float = 0.4      # Crew 任务分解时的 LLM 温度 (CREW_PLAN_TEMPERATURE)
                                              # 较低的温度 (0.3-0.5) 可提高分解的稳定性和一致性

    # ── 上下文 ──────────────────────────────────────
    context_max_tokens: int = 64000         # 上下文窗口 Token 上限 (CONTEXT_MAX_TOKENS)
    context_compress_strategy: str = "hybrid"  # 压缩策略: sliding | summarize | hybrid

    # ── 插件 ────────────────────────────────────────
    plugin_directories: list[str] = []      # Agent 插件目录 (PLUGIN_DIRS, 逗号分隔)

    # ── 日志 ────────────────────────────────────────
    log_level: str = "INFO"                 # 日志级别 (LOG_LEVEL)
    log_file: str | None = None             # 日志文件路径 (LOG_FILE)
    log_format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_llm_calls: bool = False             # 是否记录 LLM 调用详情 (LOG_LLM_CALLS)

    # ── 安全 ────────────────────────────────────────
    security_allowed_directories: list[str]  # 允许的文件目录白名单
    security_allowed_commands: list[str]     # 允许的 Shell 命令白名单
    security_confirm_dangerous: bool = True  # 危险操作是否需确认
    security_max_file_size_mb: float = 10.0  # 单文件最大大小

    # ── 加载方法 ─────────────────────────────────────
    @classmethod
    def from_env(cls) -> Config:
        """
        从环境变量加载配置。
        优先级: LLM_* 环境变量 > DEEPSEEK_* 环境变量 (兼容) > 默认值
        """

    def validate(self) -> None:
        """
        校验必要配置项:
        - llm_api_key 不为空
        - llm_base_url 格式合法
        - 数值范围合理 (temperature 0-2, max_tokens > 0, timeout > 0)
        抛出 ConfigValidationError 若校验失败。
        """

    def to_provider_kwargs(self) -> dict:
        """导出为 LLMProvider 构造函数所需的参数字典。"""
```

## 4. Logger — 日志模块

```python
class AgentLogger:
    """
    Agent 专用日志器 — 封装标准 logging, 添加 Agent 上下文。

    支持日志级别分级:
    - DEBUG: LLM 原始响应、Tool 参数/结果详情
    - INFO: ReAct 迭代摘要、Agent 状态变化
    - WARNING: 重试、恢复、降级
    - ERROR: 不可恢复错误
    """

    def __init__(self, name: str, config: Config) -> None:
        """创建日志器。同时输出到控制台和文件 (若配置了)。"""

    def debug(self, msg: str, **kwargs) -> None: ...
    def info(self, msg: str, **kwargs) -> None: ...
    def warning(self, msg: str, **kwargs) -> None: ...
    def error(self, msg: str, **kwargs) -> None: ...

    def log_react_step(self, step: ReActStep) -> None:
        """记录 ReAct 迭代 (Info 级别): 迭代序号 + Action + 耗时 + Token。"""

    def log_tool_call(self, tool_name: str, args: dict,
                      result: ToolResult) -> None:
        """记录 Tool 调用 (Debug 级别): 含参数和结果摘要。"""

    def log_llm_call(self, messages: list[Message],
                     response: ChatResponse) -> None:
        """
        记录 LLM 调用 (Debug 级别, 需 config.log_llm_calls=True):
        含输入摘要、输出摘要、Token 用量。
        """
```

## 5. 目录结构完整视图

```
SpecialAgent/
├── agent_doc/
│   ├── issues/                        # 需求文档
│   ├── plan/                          # 计划文档
│   │   ├── 00_architecture_overview.md
│   │   ├── 01_base_agent.md
│   │   ├── 02_react_engine.md
│   │   ├── 03_tool_system.md
│   │   ├── 04_deepseek_client.md      # LLMClient + LLMProvider
│   │   ├── 05_root_agent.md
│   │   ├── 06_specialized_agents.md
│   │   ├── 07_context_and_infra.md
│   │   └── 08_implementation_roadmap.md
│   ├── changelog/                     # 修改记录文档
│   └── tasks.txt
├── agent/                             # Agent 框架源码 (待实现)
│   ├── __init__.py
│   ├── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py                  # 共享数据模型 (Message, ChatResponse, TokenUsage 等)
│   │   ├── base_agent.py              # BaseAgent 基类 + AgentConfig + 状态机
│   │   ├── react_engine.py            # ReAct 推理引擎 + 终止条件
│   │   ├── react_parser.py            # ReAct 输出解析器 (文本/FC/回退)
│   │   ├── tool_manager.py            # Tool 管理器
│   │   ├── context_store.py           # 上下文存储 + 压缩策略
│   │   ├── agent_registry.py          # Agent 注册中心 + AgentMeta + MatchResult
│   │   ├── agent_pool.py              # Agent 实例池
│   │   ├── crew_orchestrator.py       # Crew 团队编排引擎
│   │   ├── session_manager.py         # 会话管理器
│   │   └── plugin_loader.py           # Agent 插件加载器
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── llm_client.py              # LLMClient Facade
│   │   ├── llm_provider.py            # LLMProvider 接口定义
│   │   └── openai_compat.py           # OpenAICompatProvider 实现
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── root_agent.py              # RootAgent + REPL
│   │   ├── code_agent.py              # CodeAgent
│   │   ├── doc_agent.py               # DocAgent
│   │   ├── search_agent.py            # SearchAgent
│   │   └── shell_agent.py             # ShellAgent
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base_tool.py               # BaseTool + ToolResult + 安全策略
│   │   ├── file_tools.py              # ReadFileTool, WriteFileTool, ListFilesTool
│   │   ├── shell_tools.py             # RunShellTool
│   │   ├── search_tools.py            # SearchCodeTool
│   │   ├── web_tools.py               # WebFetchTool, WebSearchTool
│   │   ├── crew_tool.py               # CrewTool (Crew 编排 → Tool 适配器)
│   │   └── agent_tool.py              # AgentTool (Agent → Tool 适配器)
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── match_strategy.py          # MatchStrategy 接口 + Exact/Fuzzy/Semantic/Agent
│   │   └── compress_strategy.py       # CompressStrategy 接口 + Sliding/Summarize/Hybrid
│   ├── events/
│   │   ├── __init__.py
│   │   ├── events.py                  # 事件类定义 (AgentLifecycleEvent, ToolCallEvent, CrewLifecycleEvent 等)
│   │   └── event_bus.py               # EventBus
│   └── infra/
│       ├── __init__.py
│       ├── config.py                  # Config (provider-agnostic, 兼容 DEEPSEEK_*)
│       └── logger.py                  # AgentLogger
├── tests/
│   ├── test_base_agent.py
│   ├── test_react_engine.py
│   ├── test_tool_manager.py
│   ├── test_llm_client.py
│   ├── test_context_store.py
│   └── test_integration.py
├── plugins/                           # Agent 插件目录 (用户自定义 Agent)
│   └── example_agent.py
├── changelog/                         # 修改记录 (历史)
├── requirements.txt
└── README.md
```

## 6. 依赖项

```text
# requirements.txt
# 核心依赖
httpx>=0.27.0                # 异步 HTTP 客户端 (LLM API 调用)
pydantic>=2.0.0              # 数据模型与类型校验
pydantic-settings>=2.0.0     # 环境变量配置加载

# 可选依赖
tiktoken>=0.5.0              # Token 计数 (精确估算, 若不可用则回退启发式)
sentence-transformers>=2.0.0 # 语义匹配 (可选, 未安装时回退 TF-IDF)
rich>=13.0.0                 # 终端富文本输出 (REPL 彩色显示)
readchar>=4.0.0              # 跨平台单字符读取 (REPL 交互)
```
