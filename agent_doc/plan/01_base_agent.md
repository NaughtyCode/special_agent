# BaseAgent 设计

## 1. 概述

`BaseAgent` 是所有 Agent 的抽象基类，提供：
- 完整的 LLM 访问能力（通过可替换的 LLMProvider 接口）
- 完整的 ReAct（Reasoning + Acting）循环引擎
- Tool 注册与管理
- 上下文存储与历史消息管理
- Agent 生命周期管理与事件通知

## 2. 类设计

### 2.1 核心属性

```python
class BaseAgent(ABC):
    """
    Agent 抽象基类 — 提供 LLM 访问 + ReAct 循环 + Tool 管理的完整能力。

    子类只需覆写 system_prompt 属性和 register_tools 方法即可实现特化。
    通过覆写 _build_system_message 可自定义 Prompt 构建逻辑。
    """

    # ── 标识 ──────────────────────────────────────────
    name: str                       # Agent 名称, 用于注册和日志
    description: str                # Agent 功能描述, 用于 Tool 匹配

    # ── LLM ──────────────────────────────────────────
    llm_client: LLMClient           # LLM 客户端 (门面, 内部持有 LLMProvider)

    # ── ReAct ────────────────────────────────────────
    react_engine: ReActEngine       # ReAct 推理引擎
    max_iterations: int             # 最大推理迭代次数 (从 Config 读取)

    # ── Tool ─────────────────────────────────────────
    tool_manager: ToolManager       # Tool 管理器
    agent_registry: AgentRegistry   # Agent 注册中心 (用于拉起子 Agent)

    # ── 上下文 ───────────────────────────────────────
    context_store: ContextStore     # 上下文存储 (消息历史)

    # ── 状态与事件 ───────────────────────────────────
    state: AgentState               # Agent 状态
    event_bus: EventBus             # 事件总线 (生命周期通知)

    # ── 配置 ─────────────────────────────────────────
    config: AgentConfig             # Agent 级配置 (可覆写全局配置)
```

### 2.2 AgentConfig — Agent 级配置

```python
@dataclass
class AgentConfig:
    """
    Agent 级配置 — 可覆写全局 Config 中的对应项, 实现每个 Agent 独立调参。

    未设置的项将回退到全局 Config。
    """
    max_iterations: int | None = None       # ReAct 最大迭代次数
    max_consecutive_failures: int | None = None  # 连续 Tool 失败上限
    tool_execution_timeout: float | None = None  # 单次 Tool 执行超时 (秒)
    llm_model_override: str | None = None   # 覆写 LLM 模型名称
    llm_temperature_override: float | None = None  # 覆写温度参数
    context_max_tokens: int | None = None   # 上下文窗口 Token 上限
    parent_agent: str | None = None         # 父 Agent 名称 (嵌套调用时设置)
    call_depth: int = 0                     # 调用栈深度 (防止无限递归)
```

### 2.3 核心方法

```python
class BaseAgent(ABC):
    # ── 构造与生命周期 ───────────────────────────────
    def __init__(self, name: str, description: str,
                 config: Config | None = None,
                 agent_config: AgentConfig | None = None) -> None:
        """
        初始化 Agent。
        - 从 Config 和 AgentConfig 合并配置参数
        - 创建 LLMClient (内部根据 Config 选择 Provider)
        - 创建 ReActEngine / ToolManager / ContextStore / EventBus
        - 调用 self.register_tools() 注册子类特有 Tool
        - 状态初始化为 IDLE, 发布 AgentLifecycleEvent.INITIALIZED
        """

    # ── 抽象方法 (子类覆写) ──────────────────────────
    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """返回此 Agent 的系统提示词, 定义其角色和行为规范。"""

    @abstractmethod
    def register_tools(self) -> None:
        """
        子类在此注册自身特有的 Tool。
        框架保证此方法在 __init__ 末尾自动调用。
        """

    # ── 可选覆写 ─────────────────────────────────────
    def _build_system_message(self) -> Message:
        """
        构建系统消息。默认包含 system_prompt + Tool 描述 + Agent 列表。
        子类可覆写以自定义 Prompt 结构。
        """

    def _on_before_react_loop(self) -> None:
        """ReAct 循环启动前的钩子。子类可覆写以注入预处理逻辑。"""

    def _on_after_react_loop(self, result: AgentResult) -> None:
        """ReAct 循环结束后的钩子。子类可覆写以注入后处理逻辑。"""

    # ── 公开接口 ─────────────────────────────────────
    def run(self, user_input: str, context: dict | None = None) -> AgentResult:
        """
        执行 Agent 主流程 (同步入口)。
        1. 校验状态 (必须在 IDLE 或 STOPPED)
        2. 设置状态为 RUNNING, 发布 AgentLifecycleEvent.STARTED
        3. 将 user_input 写入 ContextStore
        4. 调用 _on_before_react_loop() 钩子
        5. 启动 ReAct 循环
        6. 调用 _on_after_react_loop() 钩子
        7. 返回 AgentResult, 设置状态为 DONE
        8. 异常时设置状态为 ERROR, 发布 AgentLifecycleEvent.ERROR
        """

    async def arun(self, user_input: str,
                   context: dict | None = None) -> AgentResult:
        """同 run(), 异步版本, 支持并发调用。"""

    def stop(self) -> None:
        """
        请求停止 Agent 执行。
        设置停止标志, ReAct 循环在下次迭代检查点响应。
        状态转为 STOPPING → (循环响应后) → STOPPED。
        """

    def reset(self) -> None:
        """
        重置 Agent 到初始状态。
        清除 ContextStore, 重置状态为 IDLE。
        保留 Tool 注册和配置。
        """

    # ── Tool 操作 ─────────────────────────────────────
    def use_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """
        调用指定 Tool 并返回结果。
        自动记录到 ContextStore 和日志。
        """

    def launch_agent(self, agent_name: str, task: str,
                     context: dict | None = None) -> AgentResult:
        """
        拉起指定名称的特化 Agent 执行子任务。
        自动注入 AgentConfig(call_depth = self.config.call_depth + 1),
        若超出最大深度则抛出 AgentDepthExceededError。
        """

    # ── LLM 操作 ──────────────────────────────────────
    def chat(self, messages: list[Message],
             tools: list[dict] | None = None) -> ChatResponse:
        """
        发送消息到 LLM, 获取回复。
        自动添加调用日志和 Token 统计。
        """

    # ── 内部方法 ──────────────────────────────────────
    def _handle_react_iteration(self, thought: str,
                                action: ParsedAction) -> Observation:
        """处理单次 ReAct 迭代中的 Action 执行。"""

    def _validate_state_transition(self, target: AgentState) -> bool:
        """校验状态转移合法性。"""

    def _record_error(self, error: Exception, context: str) -> None:
        """记录错误并发布 ErrorEvent。"""
```

### 2.4 AgentState 状态机

```
                    ┌───────── stop() ─────────┐
                    │                          │
                    ▼                          │
IDLE ──→ RUNNING ──→ DONE          STOPPING ──→ STOPPED
  │        │          │                │
  │        │          │                │
  └────────┴──── ERROR ◄───────────────┘
           (任意状态发生不可恢复错误)
```

| 状态 | 含义 | 允许操作 | 下一状态 |
|------|------|----------|----------|
| `IDLE` | 初始/空闲 | run(), reset() | RUNNING |
| `RUNNING` | 正在执行 ReAct 循环 | stop() | STOPPING, DONE, ERROR |
| `DONE` | 正常完成 | 读取结果, reset() | IDLE |
| `ERROR` | 执行出错 | 读取错误, reset() | IDLE |
| `STOPPING` | 正在响应停止请求 | 等待循环退出 | STOPPED |
| `STOPPED` | 已被用户停止 | 读取部分结果, reset() | IDLE |

### 2.5 错误分类与处理

```python
class AgentError(Exception):
    """Agent 错误基类"""
    recoverable: bool = False       # 是否可恢复 (可恢复 = 反馈给 LLM 继续)

class LLMCallError(AgentError):
    """LLM 调用失败 — 可重试, 重试耗尽后不可恢复"""

class ToolExecutionError(AgentError):
    """Tool 执行失败 — 可恢复 (将错误反馈给 LLM)"""

class ToolNotFoundError(AgentError):
    """Tool 未找到 — 可恢复 (反馈给 LLM 要求使用其他 Tool)"""

class AgentDepthExceededError(AgentError):
    """Agent 嵌套调用深度超限 — 不可恢复"""

class AgentTimeoutError(AgentError):
    """Agent 执行超时 — 不可恢复"""
```

### 2.6 AgentResult 结构

```python
@dataclass
class AgentResult:
    """Agent 执行结果"""
    success: bool                       # 是否成功
    final_answer: str                   # 最终回答文本
    iterations: list[ReActStep]         # 每次 ReAct 迭代的详细记录
    token_usage: TokenUsage             # 总 token 用量
    sub_agent_results: list[AgentResult]  # 子 Agent 执行结果 (如有)
    total_duration_ms: float            # 总执行耗时 (毫秒)
    finish_reason: FinishReason         # DONE / MAX_ITERATIONS / STOPPED / ERROR
    error: AgentError | None = None     # 错误信息 (如有)
```

## 3. 子类化指南

子类需要覆写以下内容即可获得完整的 Agent 能力：

```python
class MySpecialAgent(BaseAgent):
    """示例: 特化 Agent — 仅需定义 system_prompt + register_tools"""

    @property
    def system_prompt(self) -> str:
        return "你是一个专门处理 X 任务的 Agent..."

    def register_tools(self) -> None:
        self.tool_manager.register(MyCustomTool())
        self.tool_manager.register(AnotherTool())

    # 可选: 覆写钩子以注入自定义行为
    def _on_before_react_loop(self) -> None:
        """加载领域知识到上下文。"""
        domain_knowledge = load_knowledge_base()
        self.context_store.add_message("system", domain_knowledge)

    def _on_after_react_loop(self, result: AgentResult) -> None:
        """后处理: 记录审计日志。"""
        audit_log.record(self.name, result)
```

不需要覆写 `run()` 方法 — ReAct 循环由基类统一处理。
