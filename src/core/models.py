"""
共享数据模型定义 — Agent 框架中所有组件使用的核心数据结构。

包含: Message, ChatResponse, TokenUsage, TokenTracker,
      AgentResult, ReActStep, ReActResult, ParsedReAct, ParsedAction, ActionResult,
      AgentState, AgentConfig, FinishReason, ParseMethod
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


# ── LLM 相关数据模型 ──────────────────────────────────


@dataclass
class ToolCall:
    """Function Call — LLM 返回的工具调用请求。"""
    id: str  # Tool Call ID (全局唯一)
    function_name: str  # 函数名
    function_args: dict  # 函数参数 (已解析为 dict)


@dataclass
class Message:
    """对话消息 — 兼容 OpenAI 格式。"""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None  # 可选发送者名称
    tool_call_id: str | None = None  # Tool 调用 ID (role="tool" 时)
    tool_calls: list[ToolCall] | None = None  # Assistant 的 tool_calls (role="assistant" 时)


@dataclass
class TokenUsage:
    """Token 用量统计。"""
    prompt_tokens: int = 0  # 输入 Token
    completion_tokens: int = 0  # 输出 Token
    total_tokens: int = 0  # 总计

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """支持累加操作。"""
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class ChatResponse:
    """Chat Completion 响应。"""
    content: str | None  # 纯文本回复
    tool_calls: list[ToolCall] | None = None  # Function Call 请求
    usage: TokenUsage | None = None  # Token 用量
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "length" | "content_filter"
    model: str = ""  # 实际使用的模型名称
    request_id: str | None = None  # 请求追踪 ID (便于调试)


# ── Agent 状态与配置 ──────────────────────────────────


class AgentState(Enum):
    """Agent 生命周期状态。

    状态转移:
    IDLE → RUNNING → DONE / ERROR
    RUNNING → STOPPING → STOPPED
    任意状态可 reset() 回到 IDLE
    """
    IDLE = "idle"  # 初始/空闲
    RUNNING = "running"  # 正在执行 ReAct 循环
    DONE = "done"  # 正常完成
    ERROR = "error"  # 执行出错
    STOPPING = "stopping"  # 正在响应停止请求
    STOPPED = "stopped"  # 已被用户停止


class FinishReason(Enum):
    """ReAct 循环终止原因。"""
    DONE = "done"  # LLM 给出 Final Answer
    MAX_ITERATIONS = "max_iterations"  # 达到最大迭代次数, 强制总结
    CONSECUTIVE_FAILURES = "consecutive_failures"  # 连续 Tool 失败超限
    STOPPED = "stopped"  # 外部调用 stop()
    LLM_UNRECOVERABLE = "llm_unrecoverable"  # LLM 调用不可恢复错误
    ERROR = "error"  # 其他未分类错误


class ExecutionStrategy(Enum):
    """
    Crew 执行策略 — 决定子任务以何种顺序执行。

    SEQUENTIAL: 按 plan 返回顺序依次执行, 前一个完成后才开始下一个
    PARALLEL:   并发执行所有子任务 (忽略 dependencies 字段, 最大并发数可配置)
    DAG:        按依赖关系拓扑排序后执行, 无依赖的可并行
    """
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DAG = "dag"


class ParseMethod(Enum):
    """LLM 输出解析方式。"""
    TEXT_REACT = "text_react"  # 文本 ReAct 格式解析
    FUNCTION_CALL = "function_call"  # Function Calling 结构化解析
    FALLBACK = "fallback"  # 回退解析 (容错)


@dataclass
class AgentConfig:
    """
    Agent 级配置 — 可覆写全局 Config 中的对应项, 实现每个 Agent 独立调参。

    未设置的项将回退到全局 Config。
    """
    max_iterations: int | None = None  # ReAct 最大迭代次数
    max_consecutive_failures: int | None = None  # 连续 Tool 失败上限
    tool_execution_timeout: float | None = None  # 单次 Tool 执行超时 (秒)
    llm_model_override: str | None = None  # 覆写 LLM 模型名称
    llm_temperature_override: float | None = None  # 覆写温度参数
    context_max_tokens: int | None = None  # 上下文窗口 Token 上限
    parent_agent: str | None = None  # 父 Agent 名称 (嵌套调用时设置)
    call_depth: int = 0  # 调用栈深度 (防止无限递归)

    # ── Crew 覆写 (可选, None = 使用全局 Config) ─────
    crew_max_parallel_override: int | None = None  # 覆写 Crew 最大并行数
    crew_strategy_override: str | None = None  # 覆写默认执行策略


# ── Agent 错误体系 ────────────────────────────────────


class AgentError(Exception):
    """Agent 错误基类。"""
    def __init__(self, message: str, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable  # 是否可恢复 (可恢复 = 反馈给 LLM 继续)


class LLMCallError(AgentError):
    """LLM 调用失败 — 可重试, 重试耗尽后不可恢复。"""
    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=True)


class ToolExecutionError(AgentError):
    """Tool 执行失败 — 可恢复 (将错误反馈给 LLM)。"""
    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=True)


class ToolNotFoundError(AgentError):
    """Tool 未找到 — 可恢复 (反馈给 LLM 要求使用其他 Tool)。"""
    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=True)


class AgentDepthExceededError(AgentError):
    """Agent 嵌套调用深度超限 — 不可恢复。"""
    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=False)


class AgentTimeoutError(AgentError):
    """Agent 执行超时 — 不可恢复。"""
    def __init__(self, message: str) -> None:
        super().__init__(message, recoverable=False)


# ── ReAct 执行结果 ────────────────────────────────────


@dataclass
class ParsedAction:
    """解析后的 Action — 由 ReActEngine 解析 LLM 输出后传递给 BaseAgent。"""
    name: str  # Action 名称 (Tool 名或 Agent 名)
    input: dict  # Action 参数


@dataclass
class ParsedReAct:
    """LLM 输出解析结果。"""
    has_final_answer: bool
    thought: str | None  # 推理过程
    action_name: str | None  # 执行的动作名 (无 final_answer 时)
    action_input: dict | None  # 动作参数
    final_answer: str | None  # 最终回答 (有 final_answer 时)
    parse_method: ParseMethod  # TEXT_REACT | FUNCTION_CALL | FALLBACK
    raw_response: ChatResponse  # 原始响应 (调试与审计)


@dataclass
class ActionResult:
    """Action 执行结果。"""
    success: bool
    observation: str  # 给 LLM 的文本描述
    tool_result: Any | None = None  # 原始 ToolResult
    agent_result: Any | None = None  # 子 Agent 的 AgentResult (若拉起 Agent)
    error: str | None = None  # 错误描述 (如有)


@dataclass
class ReActStep:
    """单次 ReAct 迭代的完整记录。"""
    iteration: int  # 迭代序号 (从 1 开始)
    thought: str  # 推理过程
    action_name: str  # 执行的动作名
    action_input: dict  # 动作参数 (dict 或空 dict)
    observation: str  # 执行结果
    action_result: ActionResult  # 结构化执行结果
    llm_response: ChatResponse  # LLM 原始响应
    duration_ms: float  # 本迭代耗时 (毫秒)
    timestamp: float  # Unix 时间戳
    token_usage: TokenUsage | None = None  # 本次 LLM 调用的 Token 用量


@dataclass
class ReActResult:
    """ReAct 循环结果。"""
    final_answer: str  # 最终回答
    trajectory: list[ReActStep]  # 完整迭代轨迹
    token_usage: TokenUsage  # 总 Token 用量
    finish_reason: FinishReason  # 终止原因
    total_duration_ms: float  # 总耗时


@dataclass
class AgentResult:
    """Agent 执行结果。"""
    success: bool  # 是否成功
    final_answer: str  # 最终回答文本
    iterations: list[ReActStep]  # 每次 ReAct 迭代的详细记录
    token_usage: TokenUsage  # 总 token 用量
    sub_agent_results: list["AgentResult"] = field(default_factory=list)  # 子 Agent 执行结果 (如有)
    total_duration_ms: float = 0.0  # 总执行耗时 (毫秒)
    finish_reason: FinishReason = FinishReason.DONE  # 终止原因
    error: AgentError | None = None  # 错误信息 (如有)
