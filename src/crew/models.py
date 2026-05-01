"""
Crew 数据模型 — SubTask, CrewMember, AgentCrew, CrewResult 等。

Crew 编排的核心数据结构, 独立于其他模块。
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


# ── Crew 错误类型 ──────────────────────────────────


class CrewInvalidStateError(Exception):
    """
    Crew 状态不合法错误 — 当 execute_crew() 被调用时 crew.status != "ASSEMBLED" 时抛出。

    典型场景:
    - 重复执行同一个 AgentCrew 实例 (Crew 是一次性的, 不可复用)
    - 尝试执行尚未完成规划的 Crew
    - 手动修改了 crew.status 为非预期值
    """
    pass


class CrewPlanError(Exception):
    """
    Crew 任务分解失败错误 — 当 plan_crew() 调用 LLM 分解 mission 失败时抛出。

    典型场景:
    - LLM 返回的 JSON 格式错误, 且已耗尽 crew_max_iterations 次重试
    - LLM 返回的 SubTask 列表为空 (mission 无法分解)
    - SubTask.dependencies 中存在循环依赖 (DAG 无法拓扑排序)
    - LLM 调用超时或返回不可恢复错误

    携带 raw_llm_output 属性供调试, 包含 LLM 最后一次原始输出。
    """

    def __init__(self, message: str, raw_llm_output: str | None = None) -> None:
        super().__init__(message)
        self.raw_llm_output = raw_llm_output


# ── 数据模型 ──────────────────────────────────────


@dataclass
class SubTask:
    """
    由 CrewOrchestrator 分解出的子任务。

    每个子任务描述一个独立的、可分配给特定 Agent 的工作单元。

    设计要点:
    - task_id 使用 UUID 保证全局唯一, 用于依赖追踪和日志关联
    - required_tags 是 Agent 匹配的关键依据 — Agent 的 tags 与 required_tags
      的重叠度决定匹配得分
    - dependencies 仅在 DAG 策略下使用, 为空列表表示无依赖可立即执行
    - context 用于跨子任务传递数据, 前一子任务的 AgentResult 会注入为
      后续子任务的 context
    """
    task_id: str  # 子任务唯一标识 (UUID v4)
    description: str  # 子任务描述
    required_tags: list[str] = field(default_factory=list)  # 所需 Agent 能力标签
    dependencies: list[str] = field(default_factory=list)  # 依赖的 task_id 列表 (DAG 模式使用)
    context: dict | None = None  # 传递的上下文数据

    @classmethod
    def create(cls, description: str, required_tags: list[str] | None = None,
               dependencies: list[str] | None = None, context: dict | None = None) -> "SubTask":
        """创建 SubTask 并自动生成 UUID task_id。"""
        return cls(
            task_id=str(uuid.uuid4()),
            description=description,
            required_tags=required_tags or [],
            dependencies=dependencies or [],
            context=context,
        )


@dataclass
class CrewMember:
    """
    Crew 成员 — 一个 Agent 绑定到一个子任务。

    由 CrewOrchestrator 在 plan_crew 阶段创建，
    在 execute_crew 阶段由 AgentPool 获取实例后填充 agent_instance。

    生命周期: PENDING → RUNNING → DONE / FAILED
    """
    agent_name: str  # 匹配到的 Agent 名称
    agent_cls: type | None = None  # Agent 类引用 (用于延迟实例化)
    agent_instance: Any | None = None  # Agent 实例 (执行时由 AgentPool 填充)
    task: SubTask | None = None  # 分配的子任务
    status: str = "PENDING"  # PENDING → RUNNING → DONE / FAILED
    result: Any | None = None  # 执行结果 (DONE/FAILED 时填充)
    started_at: float = 0.0  # 开始执行时间戳
    completed_at: float = 0.0  # 完成时间戳


@dataclass
class AgentCrew:
    """
    由 CrewLeader 组建的一支 Agent 团队。

    包含团队标识、任务描述 (mission)、成员列表与执行状态。
    由 plan_crew() 创建 (status=ASSEMBLED), 由 execute_crew() 执行。

    生命周期: ASSEMBLED → RUNNING → COMPLETED / FAILED
    """
    crew_id: str  # Crew 唯一标识 (UUID v4)
    lead_agent_name: str  # CrewLeader (发起方 Agent) 名称
    mission: str  # 团队使命 (原始任务描述)
    members: list[CrewMember] = field(default_factory=list)  # 团队成员列表
    status: str = "ASSEMBLED"  # ASSEMBLED → RUNNING → COMPLETED / FAILED
    created_at: float = 0.0  # 创建时间戳
    completed_at: float = 0.0  # 完成时间戳
    crew_leader_call_depth: int = 0  # CrewLeader 的 call_depth

    @classmethod
    def create(cls, lead_agent_name: str, mission: str,
               crew_leader_call_depth: int = 0) -> "AgentCrew":
        """创建 AgentCrew 并自动生成 UUID。"""
        return cls(
            crew_id=str(uuid.uuid4()),
            lead_agent_name=lead_agent_name,
            mission=mission,
            created_at=time.time(),
            crew_leader_call_depth=crew_leader_call_depth,
        )


@dataclass
class CrewResult:
    """
    Crew 执行结果 — 汇总所有成员结果。

    除聚合结果外, 保留每个成员的完整 AgentResult 用于调试和审计。

    success 判定规则:
    - True: 全部成员执行成功
    - False: 任一成员执行失败
    """
    success: bool  # 整体是否成功
    crew_id: str  # 来源 Crew 的 ID
    mission_summary: str  # LLM 汇总的团队使命报告
    member_results: list[tuple[str, str, Any]] = field(default_factory=list)  # (agent_name, task_id, result)
    execution_order: list[str] = field(default_factory=list)  # 子任务执行顺序 (task_id 列表)
    total_duration_ms: float = 0.0  # 总耗时 (毫秒)
    token_usage: Any | None = None  # 团队总 Token 用量
    failed_members: list[tuple[str, str]] = field(default_factory=list)  # 失败的成员 (agent_name, task_id)
