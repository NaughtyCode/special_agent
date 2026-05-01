"""
AgentTool — 将 Agent 包装为 Tool, 使得调用方可以像调用普通 Tool 一样拉起子 Agent。

这个适配器解决了 "Agent 也是 Tool" 的统一抽象问题,
意味着调用方无需区分当前执行的是 Tool 还是子 Agent。
"""

import time
from typing import Any

from src.tools.base_tool import BaseTool, ToolResult


class AgentTool(BaseTool):
    """
    将 Agent 包装为 Tool, 使得调用方可以像调用普通 Tool 一样拉起子 Agent。

    这个适配器解决了 "Agent 也是 Tool" 的统一抽象问题,
    意味着调用方无需区分当前执行的是 Tool 还是子 Agent。
    """

    def __init__(self, agent_registry: Any, agent_name: str) -> None:
        """
        从 AgentRegistry 中读取 Agent 元信息构建 Tool 描述。

        Tool 的 name/description/parameters_schema 从 Agent 类定义自动推导。

        Args:
            agent_registry: AgentRegistry 实例
            agent_name: Agent 名称
        """
        agent_meta = agent_registry.get_agent_meta(agent_name)
        self.name = f"launch_{agent_meta.name}"
        self.description = f"拉起 {agent_meta.name}: {agent_meta.description}"
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": f"分配给 {agent_meta.name} 的子任务描述",
                },
                "context": {
                    "type": "object",
                    "description": "可选的上下文信息",
                },
            },
            "required": ["task"],
        }
        self._agent_name = agent_name
        self._registry = agent_registry
        self.tags = list(agent_meta.tags)  # 继承 Agent 的标签
        self.requires_confirmation = False  # Agent 拉起默认无需确认

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        执行 = 拉起 Agent:
        1. 从 kwargs 提取 task 和 context
        2. 调用 agent_registry.launch(self._agent_name, task, context)
        3. 将 AgentResult 转换为 ToolResult
        4. 异常时捕获并包装为失败 ToolResult, 避免中断 ReAct 循环

        Returns:
            ToolResult
        """
        start = time.time()
        try:
            task = kwargs["task"]
            context = kwargs.get("context")
            agent_result = self._registry.launch(self._agent_name, task, context)
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=agent_result.success,
                output=agent_result.final_answer,
                data=agent_result,
                tool_name=self.name,
                duration_ms=duration,
                error=str(agent_result.error) if agent_result.error else None,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"Agent '{self._agent_name}' 执行失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )
