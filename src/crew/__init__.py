"""Crew 团队编排系统 — 独立于 core 的 Crew 功能模块。

CrewOrchestrator 使任何特化 Agent 都能成为 CrewLeader,
动态组建并领导一组 Agent 协同完成复杂任务。

支持三种执行策略: SEQUENTIAL (串行) / PARALLEL (并行) / DAG (依赖拓扑)
"""
from src.crew.models import (
    SubTask,
    CrewMember,
    AgentCrew,
    CrewResult,
    CrewPlanError,
    CrewInvalidStateError,
)
from src.crew.orchestrator import CrewOrchestrator

__all__ = [
    "SubTask",
    "CrewMember",
    "AgentCrew",
    "CrewResult",
    "CrewPlanError",
    "CrewInvalidStateError",
    "CrewOrchestrator",
]
