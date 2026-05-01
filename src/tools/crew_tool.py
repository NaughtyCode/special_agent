"""
CrewTool — 将 BaseAgent.launch_crew() 包装为 Tool。

与 AgentTool (单个 Agent 拉起) 互补:
- AgentTool: 拉起单个指定 Agent → Tool 名 = Agent 名
- CrewTool:  组建并执行 Agent 团队 → Tool 名固定为 "launch_crew"

LLM 选择指南:
- 使用 launch_<agent> (AgentTool): 任务明确属于单一领域
- 使用 launch_crew (CrewTool): 任务涉及多个领域或阶段
"""

import time
from typing import Any

from src.core.models import ExecutionStrategy
from src.tools.base_tool import BaseTool, ToolResult


class CrewTool(BaseTool):
    """
    将 BaseAgent.launch_crew() 包装为 Tool, 使得 LLM 可在 ReAct 循环中
    通过 Function Calling 发起 Crew 编排。

    与 AgentTool (单个 Agent 拉起) 互补:
    - AgentTool: 拉起单个指定 Agent → Tool 名 = Agent 名
    - CrewTool:  组建并执行 Agent 团队 → Tool 名固定为 "launch_crew"
    """

    name: str = "launch_crew"
    description: str = (
        "组建并执行一个 Agent 团队 (Crew) 完成复杂使命。"
        "自动分解任务 → 匹配最佳 Agent → 按策略执行 → 汇总结果。"
        "适用场景: 需要多个领域 Agent 协同的复杂任务。"
    )
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "mission": {
                "type": "string",
                "description": "团队使命描述, 说明需要完成什么以及期望的结果",
            },
            "strategy": {
                "type": "string",
                "enum": ["sequential", "parallel", "dag"],
                "description": "执行策略: sequential (串行), parallel (并行), dag (依赖拓扑)",
                "default": "sequential",
            },
            "max_parallel": {
                "type": "integer",
                "description": "并行模式下最大并发成员数",
                "default": 4,
            },
        },
        "required": ["mission"],
    }
    tags: list[str] = ["crew", "team", "orchestrate", "coordinate"]
    requires_confirmation: bool = False

    def __init__(self, agent: Any) -> None:
        """
        初始化 CrewTool。

        Args:
            agent: 发起 Crew 编排的 Agent 实例 (CrewLeader)。
                   Tool 执行时将调用 agent.launch_crew()。
        """
        self._agent = agent  # CrewLeader 实例

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        执行 = 发起 Crew 编排:
        1. 从 kwargs 提取 mission, strategy, max_parallel
        2. 调用 self._agent.launch_crew(mission, strategy, max_parallel)
        3. 将 CrewResult 转换为 ToolResult
        4. 异常时捕获并包装为失败 ToolResult, 避免中断 ReAct 循环

        Returns:
            ToolResult
        """
        start = time.time()
        try:
            mission = kwargs["mission"]  # 若缺失则抛出 KeyError, 由 except 捕获
            strategy_str = kwargs.get("strategy", "sequential")
            max_parallel = kwargs.get("max_parallel")

            # 解析策略枚举
            strategy = ExecutionStrategy(strategy_str)
            crew_result = self._agent.launch_crew(
                mission=mission,
                strategy=strategy,
                max_parallel=max_parallel,
            )

            duration = (time.time() - start) * 1000
            return ToolResult(
                success=crew_result.success,
                output=crew_result.mission_summary,
                data=crew_result,
                tool_name=self.name,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"Crew 编排失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )
