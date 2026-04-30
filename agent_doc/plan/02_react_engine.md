# ReActEngine 设计

## 1. 概述

`ReActEngine` 是实现 Reasoning + Acting 循环的核心引擎。它负责：
- 构建符合 ReAct 范式的 Prompt（可注入 PromptBuilder 策略）
- 解析 LLM 输出中的 Thought / Action / Final Answer（可注入 OutputParser 策略）
- 驱动迭代循环直到获得最终结果或触发终止条件

## 2. ReAct 范式

采用标准的 ReAct 格式，并支持 Function Calling 作为结构化备选路径：

```
Thought: <推理过程, 分析当前状态和下一步>
Action: <要执行的动作名称>
Action Input: <动作的参数 (JSON)>
Observation: <动作执行结果>
... (重复 Thought → Action → Observation)
Thought: I now have enough information to answer.
Final Answer: <最终回答>
```

当使用 Function Calling 模式时，LLM 直接返回结构化的 `tool_calls`，引擎自动转换为对应的 Action/Observation 格式，保持迭代轨迹一致性。

## 3. 类设计

```python
class ReActEngine:
    """
    ReAct 推理-行动循环引擎。

    驱动 Agent 执行 Thought → Action → Observation 循环,
    直到 LLM 给出 Final Answer 或触发终止条件。

    关键扩展点:
    - match_strategy: Tool 匹配策略 (可注入)
    - output_parser: 输出解析策略 (可注入)
    - hooks: 迭代生命周期钩子
    """

    # ── 配置 (全部来自 Config) ───────────────────────
    max_iterations: int                 # 最大迭代次数
    max_consecutive_failures: int       # 连续 Tool 失败上限
    tool_execution_timeout: float       # 单次 Tool 执行超时 (秒)
    stop_on_error: bool                 # 不可恢复错误时是否终止

    # ── 策略注入 ─────────────────────────────────────
    match_strategy: MatchStrategy       # Tool 匹配策略链
    output_parser: OutputParser         # LLM 输出解析器

    # ── 依赖 ─────────────────────────────────────────
    llm_client: LLMClient               # LLM 客户端
    tool_manager: ToolManager           # Tool 管理器
    agent_registry: AgentRegistry       # Agent 注册中心
    context_store: ContextStore         # 上下文存储
    event_bus: EventBus                 # 事件总线

    # ── 运行时状态 ───────────────────────────────────
    _stop_requested: bool               # 是否请求停止
    _consecutive_failures: int          # 当前连续失败计数

    # ── 核心方法 ─────────────────────────────────────
    def __init__(self, llm_client: LLMClient,
                 tool_manager: ToolManager,
                 agent_registry: AgentRegistry,
                 context_store: ContextStore,
                 event_bus: EventBus,
                 config: Config,
                 agent_config: AgentConfig | None = None,
                 match_strategy: MatchStrategy | None = None,
                 output_parser: OutputParser | None = None) -> None:
        """
        初始化引擎。
        - 绑定 LLM 客户端、Tool 管理器、Agent 注册中心、上下文存储、事件总线
        - 合并 Config 和 AgentConfig 中的参数
        - 若未提供 match_strategy, 使用默认 MatchStrategyChain(Exact, Fuzzy, Semantic, Agent)
        - 若未提供 output_parser, 使用 CompositeParser(FunctionCallParser, ReActParser, FallbackParser)
        """

    def run(self, system_message: Message, user_input: str) -> ReActResult:
        """
        执行 ReAct 循环 (同步)。

        参数:
            system_message: 系统提示消息 (含 Tool 描述)
            user_input: 用户输入

        返回:
            ReActResult 包含 final_answer, trajectory, token_usage, finish_reason
        """

    def request_stop(self) -> None:
        """请求停止循环 (线程安全)。"""

    # ── 内部方法 ─────────────────────────────────────
    def _build_prompt(self, system_msg: Message,
                      user_input: str) -> list[Message]:
        """
        构建发送给 LLM 的完整消息列表。
        1. System Message (含 Tool Schema + Agent 列表)
        2. 从 ContextStore 获取历史消息 (自动压缩)
        3. 当前轮 User Message
        """

    def _parse_llm_output(self, response: ChatResponse) -> ParsedReAct:
        """
        解析 LLM 输出。
        1. 若 response.tool_calls 非空 → FunctionCallParser 解析
        2. 否则 → ReActParser 解析 response.content
        3. 容错: 若均失败 → 以原始内容构建 Thought="(解析失败)",
           将原始输出作为 Observation 反馈 LLM 要求重新格式化
        """

    def _execute_action(self, parsed: ParsedReAct) -> ActionResult:
        """
        执行 Action。
        1. 更新连续失败计数
        2. 调用 self.match_strategy.match(parsed.action_name, parsed.action_input)
        3. 匹配到 → 执行 (带超时控制) → 重置连续失败计数
        4. 未匹配 → 返回 ACTION_NOT_FOUND 错误
        """

    def _format_observation(self, result: ActionResult) -> str:
        """
        将执行结果格式化为 Observation 文本。
        成功: 截断过长结果, 添加 token 估算提示
        失败: 包含错误类型和建议 (如 "Tool X not found. Available: Y, Z")
        """

    def _check_termination(self, parsed: ParsedReAct,
                           iteration: int) -> TerminationDecision | None:
        """
        检查是否应终止循环。
        返回 TerminationDecision 或 None (继续循环)。
        """
```

## 4. Prompt 构建策略

### 4.1 系统消息结构 (分层构建)

```
System Message 包含以下部分 (按优先级):

1. 角色定义: {system_prompt} (由子 Agent 提供)
2. 行为规范:
   - 必须遵循 ReAct 格式 (提供 few-shot 示例)
   - 每次输出 Thought + Action 或 Final Answer
   - 当 Function Calling 可用时, 优先使用结构化 tool_calls
3. Tool 列表: 所有可用 Tool 的名称、描述和 JSON Schema
4. 子 Agent 列表: 所有可拉起的 Agent 名称和描述
5. 约束条件:
   - 输出语言: 与用户输入保持一致
   - 如连续 3 次 Tool 调用失败, 请重新评估策略
   - 如多次尝试仍无法完成任务, 诚实告知用户并说明原因
```

### 4.2 用户消息构造

```
用户消息构造:
  第 1 轮: user_input (纯文本)
  第 N 轮 (N>1): 通过 ContextStore 中的 assistant/tool 消息自然拼接,
                 不重复插入原始 user_input。
```

## 5. 输出解析体系

```python
class OutputParser(Protocol):
    """输出解析器接口 — 可替换实现。"""
    def parse(self, response: ChatResponse) -> ParsedReAct: ...

class CompositeParser:
    """
    组合解析器 — 按优先级尝试多个解析器。
    1. FunctionCallParser: 解析 response.tool_calls (结构化, 无歧义)
    2. ReActParser: 解析 response.content 中的 Thought/Action/Final Answer 标签
    3. FallbackParser: 将整个 content 视为 Thought, 尝试推断是否包含最终回答
    """

class ReActParser:
    """文本解析器 — 支持可配置的正则模式与容错策略。"""

    # 可配置的匹配模式 (允许子类覆写以适配不同 LLM 的格式偏好)
    THOUGHT_PATTERN: str
    ACTION_PATTERN: str
    ACTION_INPUT_PATTERN: str
    FINAL_ANSWER_PATTERN: str
```

### 5.1 ParsedReAct 数据模型

```python
@dataclass
class ParsedReAct:
    """LLM 输出解析结果"""
    has_final_answer: bool
    thought: str | None
    action_name: str | None
    action_input: dict | None
    final_answer: str | None
    parse_method: ParseMethod          # TEXT_REACT | FUNCTION_CALL | FALLBACK
    raw_response: ChatResponse         # 原始响应 (调试与审计)

@dataclass
class ActionResult:
    """Action 执行结果"""
    success: bool
    observation: str                    # 给 LLM 的文本描述
    tool_result: ToolResult | None      # 原始 ToolResult
    agent_result: AgentResult | None    # 子 Agent 的 AgentResult (若拉起 Agent)
    error: str | None                   # 错误描述 (如有)
```

## 6. 匹配策略体系

```python
class MatchStrategy(Protocol):
    """Tool 匹配策略接口 — 可替换实现。"""
    def match(self, action_name: str, action_input: dict,
              tool_manager: ToolManager,
              agent_registry: AgentRegistry) -> MatchResult: ...

class MatchStrategyChain:
    """
    策略链 — 按优先级依次尝试多个策略。
    第一个成功的策略结果被采用。
    """
    def __init__(self, strategies: list[MatchStrategy]) -> None: ...

class ExactMatchStrategy:
    """精确名称匹配 — 在 ToolManager 中按名称精确查找。"""

class FuzzyMatchStrategy:
    """
    模糊匹配 — 对 Tool 名称/描述做关键词匹配。
    配置: score_threshold (最低匹配得分), max_candidates (返回候选数)
    """

class SemanticMatchStrategy:
    """
    语义匹配 — 对 Tool 描述和 action 意图做语义相似度比对。
    可选依赖: sentence-transformers (轻量嵌入模型)
    回退方案: 基于 TF-IDF 的关键词重叠度
    """

class AgentMatchStrategy:
    """Agent 匹配 — 在 AgentRegistry 中匹配特化 Agent。"""
```

## 7. 迭代轨迹

```python
@dataclass
class ReActStep:
    """单次 ReAct 迭代的完整记录"""
    iteration: int                      # 迭代序号 (从 1 开始)
    thought: str                        # 推理过程
    action_name: str                    # 执行的动作名
    action_input: dict                  # 动作参数
    observation: str                    # 执行结果
    action_result: ActionResult         # 结构化执行结果
    llm_response: ChatResponse          # LLM 原始响应
    duration_ms: float                  # 本迭代耗时 (毫秒)
    timestamp: float                    # Unix 时间戳
    token_usage: TokenUsage             # 本次 LLM 调用的 Token 用量

@dataclass
class ReActResult:
    """ReAct 循环结果"""
    final_answer: str                   # 最终回答
    trajectory: list[ReActStep]         # 完整迭代轨迹
    token_usage: TokenUsage             # 总 Token 用量
    finish_reason: FinishReason         # 终止原因
    total_duration_ms: float            # 总耗时

class FinishReason(Enum):
    DONE = "done"                       # LLM 给出 Final Answer
    MAX_ITERATIONS = "max_iterations"   # 达到最大迭代次数, 强制总结
    CONSECUTIVE_FAILURES = "consecutive_failures"  # 连续 Tool 失败超限
    STOPPED = "stopped"                 # 外部调用 stop()
    LLM_UNRECOVERABLE = "llm_unrecoverable"  # LLM 调用不可恢复错误
```

## 8. 终止条件

| 条件 | FinishReason | 行为 |
|------|-------------|------|
| LLM 输出包含 `Final Answer:` 或 FC 返回无 tool_calls | DONE | 正常返回 |
| 达到 `max_iterations` | MAX_ITERATIONS | 注入 "请基于已有信息给出最终回答" 的强制提示再调用一次 |
| 连续 Tool 失败 ≥ `max_consecutive_failures` | CONSECUTIVE_FAILURES | 终止并返回错误摘要 |
| `stop()` 被调用 | STOPPED | 在下次迭代检查点退出, 返回已有轨迹 |
| LLM 返回不可恢复错误 (认证失败等) | LLM_UNRECOVERABLE | 立即终止, 不重试 |
