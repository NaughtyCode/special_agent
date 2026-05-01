"""
事件类定义 — Agent 生命周期事件, Tool 调用事件, LLM 调用事件等。

所有事件通过 EventBus 发布, 供监控/日志/审计订阅。
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentLifecycleEvent(Enum):
    """Agent 生命周期事件类型。"""
    INITIALIZED = "initialized"  # Agent 初始化完成
    STARTED = "started"  # Agent 开始执行
    COMPLETED = "completed"  # Agent 正常完成
    ERROR = "error"  # Agent 执行出错
    SPAWNED = "spawned"  # 子 Agent 被拉起
    STOPPED = "stopped"  # Agent 被停止


class ToolCallEvent(Enum):
    """Tool 调用事件类型。"""
    BEFORE_EXECUTE = "before_execute"  # Tool 执行前
    AFTER_EXECUTE = "after_execute"  # Tool 执行后


class LLMCallEvent(Enum):
    """LLM 调用事件类型。"""
    BEFORE_CALL = "before_call"  # LLM 调用前
    AFTER_CALL = "after_call"  # LLM 调用后


class ReActIterationEvent(Enum):
    """ReAct 迭代事件类型。"""
    ITERATION_START = "iteration_start"  # 迭代开始
    ITERATION_END = "iteration_end"  # 迭代结束


class CrewLifecycleEvent(Enum):
    """
    Crew 生命周期事件 — 发布到 EventBus, 供监控/日志/审计订阅。

    枚举值:
    - PLANNED:   plan_crew() 完成, crew 已组建
    - STARTED:   execute_crew() 开始
    - MEMBER_STARTED:   单个 CrewMember 开始执行
    - MEMBER_COMPLETED: 单个 CrewMember 执行完成
    - MEMBER_FAILED:    单个 CrewMember 执行失败
    - COMPLETED: 全部成员执行完毕且成功
    - FAILED:    存在成员失败且不可恢复
    """
    PLANNED = "planned"
    STARTED = "started"
    MEMBER_STARTED = "member_started"
    MEMBER_COMPLETED = "member_completed"
    MEMBER_FAILED = "member_failed"
    COMPLETED = "completed"
    FAILED = "failed"


class ConfirmationRequestEvent:
    """危险操作确认请求事件 — 当 Tool 设置了 requires_confirmation 时发布。"""

    def __init__(self, tool_name: str, action_description: str, args: dict) -> None:
        self.tool_name = tool_name
        self.action_description = action_description
        self.args = args
        self.timestamp = time.time()


@dataclass
class CrewEvent:
    """
    Crew 生命周期事件的负载数据 — 随 CrewLifecycleEvent 发布到 EventBus。

    不同事件类型携带不同的字段子集 (未携带的字段为 None):
    - PLANNED:          crew_id, lead_agent_name, member_count
    - STARTED:          crew_id, strategy
    - MEMBER_STARTED:   crew_id, member_name, task_id
    - MEMBER_COMPLETED: crew_id, member_name, task_id, duration_ms
    - MEMBER_FAILED:    crew_id, member_name, task_id, error_message
    - COMPLETED:        crew_id, total_duration_ms, token_usage
    - FAILED:           crew_id, error_message, partial_results
    """
    event_type: CrewLifecycleEvent  # 事件类型
    crew_id: str  # Crew 唯一标识 (所有事件必带)
    lead_agent_name: str | None = None  # CrewLeader 名称 (PLANNED)
    member_name: str | None = None  # 成员 Agent 名称 (MEMBER_* 事件)
    task_id: str | None = None  # 子任务 ID (MEMBER_* 事件)
    member_count: int = 0  # 成员总数 (PLANNED)
    strategy: str | None = None  # 执行策略 (STARTED)
    duration_ms: float = 0.0  # 耗时 (MEMBER_COMPLETED, COMPLETED)
    token_usage: Any | None = None  # Token 用量 (COMPLETED)
    error_message: str | None = None  # 错误信息 (MEMBER_FAILED, FAILED)
    partial_results: list[tuple[str, str, Any]] | None = None  # 部分成功结果 (FAILED 事件携带)


class Event:
    """
    通用事件基类 — 所有发布到 EventBus 的事件由此封装。

    包含事件类型枚举值和可选的 payload 数据。
    """

    def __init__(self, event_type: Any, payload: Any = None) -> None:
        self.event_type = event_type
        self.payload = payload
        self.timestamp = time.time()
