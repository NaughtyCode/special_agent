"""
Agent 抽象基类 — 提供 LLM 访问 + ReAct 循环 + Tool 管理的完整能力。

子类只需覆写 system_prompt 属性和 register_tools 方法即可实现特化。
通过覆写 _build_system_message 可自定义 Prompt 构建逻辑。
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from src.core.agent_pool import AgentPool
from src.core.agent_registry import AgentRegistry
from src.core.context_store import ContextStore
from src.core.models import (
    AgentConfig,
    AgentDepthExceededError,
    AgentError,
    AgentResult,
    AgentState,
    ExecutionStrategy,
    FinishReason,
    Message,
    ParsedAction,
    ReActStep,
    TokenUsage,
    ToolCall,
)
from src.core.react_engine import ReActEngine
from src.core.tool_manager import ToolManager
from src.crew.models import AgentCrew, CrewResult
from src.crew.orchestrator import CrewOrchestrator
from src.events.event_bus import EventBus
from src.events.events import AgentLifecycleEvent, Event
from src.infra.config import Config
from src.infra.logger import AgentLogger
from src.llm.llm_client import LLMClient
from src.llm.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Agent 抽象基类 — 提供 LLM 访问 + ReAct 循环 + Tool 管理的完整能力。

    子类只需覆写 system_prompt 属性和 register_tools 方法即可实现特化。
    通过覆写 _build_system_message 可自定义 Prompt 构建逻辑。
    """

    # ── 标识 (子类覆写) ──────────────────────────────
    name: str = ""  # Agent 名称, 用于注册和日志
    description: str = ""  # Agent 功能描述, 用于 Tool 匹配
    tags: list[str] = []  # 标签列表 (辅助匹配)

    def __init__(
        self,
        name: str | None = None,
        description: str | None = None,
        config: Config | None = None,
        agent_config: AgentConfig | None = None,
    ) -> None:
        """
        初始化 Agent。

        - 从 Config 和 AgentConfig 合并配置参数
        - 创建 LLMClient (内部根据 Config 选择 Provider)
        - 创建 ReActEngine / ToolManager / ContextStore / EventBus
        - 创建 AgentPool / AgentRegistry / CrewOrchestrator
        - 调用 self.register_tools() 注册子类特有 Tool
        - 状态初始化为 IDLE

        Args:
            name: Agent 名称 (可选, 默认使用类属性)
            description: Agent 描述 (可选, 默认使用类属性)
            config: 全局 Config 实例
            agent_config: Agent 级配置
        """
        if name:
            self.name = name
        if description:
            self.description = description

        self.config = config or Config.from_env()
        self.agent_config = agent_config or AgentConfig()

        # 创建日志器
        self._logger = AgentLogger(self.name, self.config)

        # 创建 LLM Provider 和 Client
        provider_kwargs = self.config.to_provider_kwargs()
        self._provider = OpenAICompatProvider(**provider_kwargs)
        self.llm_client = LLMClient(self._provider, self.config)

        # 创建事件总线
        self.event_bus = EventBus()

        # 创建 Tool 管理器
        self.tool_manager = ToolManager(self.config)

        # 创建 AgentPool 和 AgentRegistry
        self.agent_pool = AgentPool()
        self.agent_registry = AgentRegistry(self.agent_pool)

        # 创建 Crew 编排器
        self.crew_orchestrator = CrewOrchestrator(
            agent_registry=self.agent_registry,
            agent_pool=self.agent_pool,
            llm_client=self.llm_client,
            event_bus=self.event_bus,
            config=self.config,
        )

        # 创建上下文存储
        self.context_store = ContextStore(self.config)

        # 创建 ReAct 引擎
        self.react_engine = ReActEngine(
            llm_client=self.llm_client,
            tool_manager=self.tool_manager,
            agent_registry=self.agent_registry,
            context_store=self.context_store,
            event_bus=self.event_bus,
            config=self.config,
            agent_config=self.agent_config,
        )

        # 状态初始化
        self.state = AgentState.IDLE

        # 注册子类特有 Tool
        self.register_tools()

        # 发布初始化事件
        self.event_bus.publish(Event(
            event_type=AgentLifecycleEvent.INITIALIZED,
            payload={"agent_name": self.name},
        ))

        self._logger.info(f"Agent '{self.name}' initialized")

    # ── 抽象方法 (子类覆写) ──────────────────────────

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """返回此 Agent 的系统提示词, 定义其角色和行为规范。"""
        ...

    @abstractmethod
    def register_tools(self) -> None:
        """
        子类在此注册自身特有的 Tool。

        框架保证此方法在 __init__ 末尾自动调用。
        """
        ...

    # ── 可选覆写 ─────────────────────────────────────

    def _build_system_message(self) -> Message:
        """
        构建系统消息。默认包含 system_prompt + Tool 描述 + Agent 列表。

        子类可覆写以自定义 Prompt 结构。

        Returns:
            Message 对象
        """
        # 构建完整的系统提示
        parts: list[str] = []

        # 1. 角色定义
        parts.append(self.system_prompt)

        # 2. ReAct 行为规范
        parts.append("""
## 行为规范

你必须遵循 ReAct (Reasoning + Acting) 格式进行推理和行动:

1. **Thought**: 分析当前状态, 决定下一步行动
2. **Action**: 执行一个具体的行动 (调用 Tool 或拉起 Agent)
3. **Observation**: 观察行动结果
4. 重复以上步骤直到能够给出最终回答
5. **Final Answer**: 给出最终回答

格式示例:
```
Thought: 我需要读取配置文件来了解项目结构。
Action: read_file
Action Input: {"path": "config.yaml"}
Observation: [文件内容...]
Thought: 根据配置, 我需要...
Final Answer: [最终回答]
```

## 约束条件
- 输出语言与用户输入保持一致
- 如连续 3 次 Tool 调用失败, 请重新评估策略
- 如多次尝试仍无法完成任务, 诚实告知用户并说明原因
- 优先使用 Function Calling 格式调用 Tool (如支持)
""")

        # 3. Tool 列表
        if self.tool_manager.tool_count > 0:
            tools_desc = "\n".join(
                f"- **{tool.name}**: {tool.description}"
                for tool in self.tool_manager.tools.values()
            )
            parts.append(f"\n## 可用 Tool\n{tools_desc}")

        # 4. 子 Agent 列表
        agents = self.agent_registry.list_agents()
        if agents:
            agents_desc = "\n".join(
                f"- **{a.name}**: {a.description}"
                for a in agents
            )
            parts.append(f"\n## 可拉起的子 Agent\n{agents_desc}")

        return Message(role="system", content="\n\n".join(parts))

    def _on_before_react_loop(self) -> None:
        """ReAct 循环启动前的钩子。子类可覆写以注入预处理逻辑。"""
        pass

    def _on_after_react_loop(self, result: AgentResult) -> None:
        """ReAct 循环结束后的钩子。子类可覆写以注入后处理逻辑。"""
        pass

    # ── 公开接口 ─────────────────────────────────────

    def run(self, user_input: str, context: dict | None = None) -> AgentResult:
        """
        执行 Agent 主流程 (同步入口)。

        1. 校验状态 (必须在 IDLE 或 STOPPED)
        2. 设置状态为 RUNNING, 发布 STARTED 事件
        3. 将 user_input 写入 ContextStore
        4. 调用 _on_before_react_loop() 钩子
        5. 启动 ReAct 循环
        6. 调用 _on_after_react_loop() 钩子
        7. 返回 AgentResult

        Args:
            user_input: 用户输入文本
            context: 可选的上下文信息

        Returns:
            AgentResult 执行结果
        """
        # 状态校验
        if self.state not in (AgentState.IDLE, AgentState.STOPPED):
            raise AgentError(
                f"Agent '{self.name}' 无法执行: 当前状态 {self.state.value}, "
                f"需要 IDLE 或 STOPPED"
            )

        self.state = AgentState.RUNNING
        self.event_bus.publish(Event(
            event_type=AgentLifecycleEvent.STARTED,
            payload={"agent_name": self.name, "input": user_input[:100]},
        ))

        start_time = time.time()
        self._logger.info(f"Agent '{self.name}' started: input='{user_input[:50]}...'")

        try:
            # 写入上下文 (可选的额外上下文)
            if context:
                for key, value in context.items():
                    self.context_store.set_variable(key, value)

            # 前置钩子
            self._on_before_react_loop()

            # 构建系统消息
            system_message = self._build_system_message()

            # 启动 ReAct 循环
            react_result = self.react_engine.run(system_message, user_input)

            # 构建 AgentResult
            result = AgentResult(
                success=react_result.finish_reason == FinishReason.DONE,
                final_answer=react_result.final_answer,
                iterations=react_result.trajectory,
                token_usage=react_result.token_usage,
                total_duration_ms=(time.time() - start_time) * 1000,
                finish_reason=react_result.finish_reason,
            )

            # 后置钩子
            self._on_after_react_loop(result)

            self.state = AgentState.DONE
            self.event_bus.publish(Event(
                event_type=AgentLifecycleEvent.COMPLETED,
                payload={"agent_name": self.name},
            ))

            self._logger.info(
                f"Agent '{self.name}' completed: success={result.success}, "
                f"iterations={len(result.iterations)}, "
                f"duration={result.total_duration_ms:.0f}ms"
            )

            return result

        except Exception as e:
            self.state = AgentState.ERROR
            self.event_bus.publish(Event(
                event_type=AgentLifecycleEvent.ERROR,
                payload={"agent_name": self.name, "error": str(e)},
            ))

            self._logger.error(f"Agent '{self.name}' error: {e}")

            return AgentResult(
                success=False,
                final_answer=f"执行出错: {e}",
                iterations=[],
                token_usage=TokenUsage(),
                total_duration_ms=(time.time() - start_time) * 1000,
                finish_reason=FinishReason.ERROR,
                error=AgentError(str(e)),
            )

    async def arun(self, user_input: str, context: dict | None = None) -> AgentResult:
        """
        同 run(), 异步版本, 支持并发调用。

        Args:
            user_input: 用户输入文本
            context: 可选的上下文信息

        Returns:
            AgentResult 执行结果
        """
        # 异步版本: 在当前实现在线程池中运行同步 run()
        import asyncio
        import concurrent.futures

        loop = asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, self.run, user_input, context)

    def stop(self) -> None:
        """
        请求停止 Agent 执行。

        设置停止标志, ReAct 循环在下次迭代检查点响应。
        状态转为 STOPPING → (循环响应后) → STOPPED。
        """
        self.state = AgentState.STOPPING
        self.react_engine.request_stop()
        self._logger.info(f"Agent '{self.name}' stop requested")

    def reset(self) -> None:
        """
        重置 Agent 到初始状态。

        清除 ContextStore, 重置状态为 IDLE。
        保留 Tool 注册和配置。
        """
        self.context_store.clear()
        self.state = AgentState.IDLE
        self.react_engine._stop_requested = False
        self.react_engine._consecutive_failures = 0
        self._logger.debug(f"Agent '{self.name}' reset")

    # ── Tool 操作 ─────────────────────────────────────

    def use_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """
        调用指定 Tool 并返回结果。

        自动记录到 ContextStore 和日志。

        Args:
            tool_name: Tool 名称
            **kwargs: Tool 参数

        Returns:
            ToolResult 实例
        """
        result = self.tool_manager.execute(tool_name, **kwargs)
        self._logger.log_tool_call(tool_name, kwargs, result)
        return result

    def launch_agent(
        self,
        agent_name: str,
        task: str,
        context: dict | None = None,
    ) -> AgentResult:
        """
        拉起指定名称的特化 Agent 执行子任务。

        自动注入 AgentConfig(call_depth = self.agent_config.call_depth + 1),
        若超出最大深度则抛出 AgentDepthExceededError。

        Args:
            agent_name: Agent 名称
            task: 子任务描述
            context: 可选的上下文信息

        Returns:
            AgentResult 执行结果

        Raises:
            AgentDepthExceededError: 若调用深度超限
        """
        new_depth = self.agent_config.call_depth + 1
        if new_depth > self.config.agent_max_call_depth:
            raise AgentDepthExceededError(
                f"Agent 嵌套调用深度超限: {new_depth} > {self.config.agent_max_call_depth}"
            )

        # 触发 SPAWNED 事件
        self.event_bus.publish(Event(
            event_type=AgentLifecycleEvent.SPAWNED,
            payload={"parent": self.name, "child": agent_name, "task": task[:100]},
        ))

        result = self.agent_registry.launch(agent_name, task, context)
        return result

    # ── Crew 编排 ─────────────────────────────────────

    def form_crew(self, mission: str) -> AgentCrew:
        """
        将复杂使命分解为子任务并组建 Agent 团队。

        调用 crew_orchestrator.plan_crew():
        1. LLM 分析 mission, 分解为 SubTask 列表
        2. 每个 SubTask 通过 AgentRegistry 匹配最佳特化 Agent
        3. 构建并返回 AgentCrew (status=ASSEMBLED)

        Args:
            mission: 团队使命描述

        Returns:
            AgentCrew (status=ASSEMBLED)
        """
        return self.crew_orchestrator.plan_crew(
            mission=mission,
            lead_agent_name=self.name,
            available_agents=self.agent_registry.list_agents(),
            crew_leader_call_depth=self.agent_config.call_depth,
        )

    def launch_crew(
        self,
        mission: str,
        strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL,
        max_parallel: int | None = None,
    ) -> CrewResult:
        """
        组建并执行一个 Agent 团队完成复杂使命 (form_crew + execute_crew)。

        参数解析顺序 (优先级从高到低):
        - strategy: self.agent_config.crew_strategy_override → 参数 strategy → SEQUENTIAL
        - max_parallel: self.agent_config.crew_max_parallel_override → 参数 max_parallel → Config.crew_max_parallel

        流程:
        1. 调用 self.form_crew(mission) 组建团队
        2. 调用 crew_orchestrator.execute_crew(crew, strategy, max_parallel)
        3. 将 CrewResult.mission_summary 写入 ContextStore
        4. 返回聚合后的 CrewResult

        递归风险防护:
        - 入口处检查 call_depth 超限 → AgentDepthExceededError

        Args:
            mission: 团队使命描述
            strategy: 执行策略
            max_parallel: 最大并行数, None 使用配置默认值

        Returns:
            CrewResult

        Raises:
            AgentDepthExceededError: 若调用深度超限
        """
        # 检查深度限制
        if self.agent_config.call_depth >= self.config.agent_max_call_depth:
            raise AgentDepthExceededError(
                f"Crew 编排深度超限: {self.agent_config.call_depth} >= {self.config.agent_max_call_depth}"
            )

        # 解析 strategy 优先级
        actual_strategy = strategy
        if self.agent_config.crew_strategy_override:
            try:
                actual_strategy = ExecutionStrategy(self.agent_config.crew_strategy_override)
            except ValueError:
                pass

        # 解析 max_parallel 优先级
        actual_max_parallel = max_parallel
        if self.agent_config.crew_max_parallel_override is not None:
            actual_max_parallel = self.agent_config.crew_max_parallel_override

        # 组建团队
        crew = self.form_crew(mission)

        # 执行团队
        crew_result = self.crew_orchestrator.execute_crew(
            crew, actual_strategy, actual_max_parallel
        )

        # 将结果写入 ContextStore
        self.context_store.add_message(
            role="tool",
            content=f"[Crew Result] {crew_result.mission_summary}",
        )

        return crew_result

    # ── LLM 操作 ──────────────────────────────────────

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
    ) -> Any:
        """
        发送消息到 LLM, 获取回复。

        自动添加调用日志和 Token 统计。

        Args:
            messages: 消息列表
            tools: Function Calling Tool Schema 列表

        Returns:
            ChatResponse 对象
        """
        response = self.llm_client.chat(messages=messages, tools=tools)
        self._logger.log_llm_call(messages, response)
        return response
