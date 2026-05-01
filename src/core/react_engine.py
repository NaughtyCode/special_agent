"""
ReAct 推理-行动循环引擎。

驱动 Agent 执行 Thought → Action → Observation 循环,
直到 LLM 给出 Final Answer 或触发终止条件。

关键扩展点:
- match_strategy: Tool 匹配策略 (可注入)
- output_parser: 输出解析策略 (可注入)
- hooks: 迭代生命周期钩子
"""

import logging
import time
from typing import Any

from src.core.models import (
    ActionResult,
    ChatResponse,
    FinishReason,
    Message,
    ParsedReAct,
    ReActResult,
    ReActStep,
    TokenUsage,
)
from src.core.react_parser import CompositeParser, OutputParser
from src.core.tool_manager import ToolManager
from src.infra.config import Config
from src.strategies.match_strategy import MatchResult, MatchStrategy, MatchStrategyChain
from src.strategies.match_strategy import (
    ExactMatchStrategy,
    FuzzyMatchStrategy,
    SemanticMatchStrategy,
    AgentMatchStrategy,
)

logger = logging.getLogger(__name__)


class ReActEngine:
    """
    ReAct 推理-行动循环引擎。

    驱动 Agent 执行 Thought → Action → Observation 循环,
    直到 LLM 给出 Final Answer 或触发终止条件。

    关键扩展点:
    - match_strategy: Tool 匹配策略 (可注入)
    - output_parser: 输出解析策略 (可注入)
    """

    def __init__(
        self,
        llm_client: Any,
        tool_manager: ToolManager,
        agent_registry: Any,
        context_store: Any,
        event_bus: Any,
        config: Config,
        agent_config: Any = None,
        match_strategy: MatchStrategy | None = None,
        output_parser: OutputParser | None = None,
    ) -> None:
        """
        初始化 ReAct 引擎。

        Args:
            llm_client: LLMClient 实例
            tool_manager: ToolManager 实例
            agent_registry: AgentRegistry 实例
            context_store: ContextStore 实例
            event_bus: EventBus 实例
            config: Config 实例
            agent_config: AgentConfig 实例 (可选)
            match_strategy: 匹配策略 (可选, 默认使用策略链)
            output_parser: 输出解析器 (可选, 默认使用 CompositeParser)
        """
        self.llm_client = llm_client
        self.tool_manager = tool_manager
        self.agent_registry = agent_registry
        self.context_store = context_store
        self.event_bus = event_bus

        # 合并 Config 和 AgentConfig 参数
        self.max_iterations = (
            agent_config.max_iterations if agent_config and agent_config.max_iterations is not None
            else config.agent_max_iterations
        )
        self.max_consecutive_failures = (
            agent_config.max_consecutive_failures if agent_config and agent_config.max_consecutive_failures is not None
            else config.agent_max_consecutive_failures
        )
        self.tool_execution_timeout = (
            agent_config.tool_execution_timeout if agent_config and agent_config.tool_execution_timeout is not None
            else config.agent_tool_execution_timeout
        )
        self.stop_on_error = True

        # 策略注入
        self.match_strategy = match_strategy or MatchStrategyChain([
            ExactMatchStrategy(),
            FuzzyMatchStrategy(),
            SemanticMatchStrategy(),
            AgentMatchStrategy(),
        ])
        self.output_parser = output_parser or CompositeParser()

        # 运行时状态
        self._stop_requested = False
        self._consecutive_failures = 0

    def run(self, system_message: Message, user_input: str) -> ReActResult:
        """
        执行 ReAct 循环 (同步)。

        Args:
            system_message: 系统提示消息 (含 Tool 描述)
            user_input: 用户输入

        Returns:
            ReActResult 包含 final_answer, trajectory, token_usage, finish_reason
        """
        start_time = time.time()
        trajectory: list[ReActStep] = []
        total_tokens = TokenUsage()
        final_answer = ""
        finish_reason = FinishReason.DONE

        self._stop_requested = False
        self._consecutive_failures = 0

        # 初始化上下文: 写入 system message 和 user input
        self.context_store.add_message(
            role=system_message.role,
            content=system_message.content,
        )

        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            iter_start = time.time()

            # 检查停止请求
            if self._stop_requested:
                final_answer = self._force_summarize()
                finish_reason = FinishReason.STOPPED
                break

            # 检查连续失败
            if self._consecutive_failures >= self.max_consecutive_failures:
                logger.warning(
                    f"连续 Tool 失败 {self._consecutive_failures} 次, 达到上限"
                )
                final_answer = self._force_summarize()
                finish_reason = FinishReason.CONSECUTIVE_FAILURES
                break

            try:
                # 构建发送给 LLM 的消息列表
                messages = self._build_prompt(system_message, user_input if iteration == 1 else None)

                # 调用 LLM
                tools_schema = self.tool_manager.get_tools_schema()
                agent_tools_schema = self.agent_registry.get_agent_tools_schema()
                all_tools = tools_schema + agent_tools_schema if agent_tools_schema else tools_schema

                response = self.llm_client.chat(
                    messages=messages,
                    tools=all_tools if all_tools else None,
                )

                # 记录 LLM 调用
                if response.usage:
                    total_tokens += response.usage

            except Exception as e:
                logger.error(f"LLM 调用失败 (iteration {iteration}): {e}")
                # 不可恢复的 LLM 错误
                if iteration == 1:
                    # 第一次就失败, 无法继续
                    final_answer = f"LLM 调用失败: {e}"
                    finish_reason = FinishReason.LLM_UNRECOVERABLE
                    break
                # 否则使用已有轨迹强制总结
                final_answer = self._force_summarize()
                finish_reason = FinishReason.LLM_UNRECOVERABLE
                break

            # 解析 LLM 输出
            parsed = self._parse_llm_output(response)

            # 检查是否包含 Final Answer
            if parsed.has_final_answer:
                final_answer = parsed.final_answer or ""
                finish_reason = FinishReason.DONE
                # 记录最后一步轨迹
                step = ReActStep(
                    iteration=iteration,
                    thought=parsed.thought or "",
                    action_name="final_answer",
                    action_input={},
                    observation="",
                    action_result=ActionResult(success=True, observation=final_answer),
                    llm_response=response,
                    duration_ms=(time.time() - iter_start) * 1000,
                    timestamp=time.time(),
                    token_usage=response.usage,
                )
                trajectory.append(step)
                break

            # 执行 Action
            if parsed.action_name:
                action_result = self._execute_action(parsed)
            else:
                # 无 Action 也无 Final Answer → 将内容视为 Thought, 提示 LLM 继续
                action_result = ActionResult(
                    success=False,
                    observation="请继续推理: 给出下一个 Action 或提供 Final Answer。",
                    error="Missing action",
                )

            # 格式化为 Observation
            observation = self._format_observation(action_result)

            # 记录 ReAct 步骤
            step = ReActStep(
                iteration=iteration,
                thought=parsed.thought or response.content or "",
                action_name=parsed.action_name or "none",
                action_input=parsed.action_input or {},
                observation=observation,
                action_result=action_result,
                llm_response=response,
                duration_ms=(time.time() - iter_start) * 1000,
                timestamp=time.time(),
                token_usage=response.usage,
            )
            trajectory.append(step)
            self.context_store.add_react_step(step)

            # 将 Observation 反馈给 LLM (写入 ContextStore)
            self.context_store.add_message(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            )

            if action_result.success:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1

        # 循环结束但未给出 Final Answer → 强制总结
        if iteration >= self.max_iterations and not final_answer:
            final_answer = self._force_summarize()
            finish_reason = FinishReason.MAX_ITERATIONS

        total_duration = (time.time() - start_time) * 1000

        return ReActResult(
            final_answer=final_answer,
            trajectory=trajectory,
            token_usage=total_tokens,
            finish_reason=finish_reason,
            total_duration_ms=total_duration,
        )

    def request_stop(self) -> None:
        """请求停止循环 (线程安全)。"""
        self._stop_requested = True
        logger.info("ReAct engine stop requested")

    # ── 内部方法 ─────────────────────────────────────

    def _build_prompt(self, system_msg: Message, user_input: str | None) -> list[Message]:
        """
        构建发送给 LLM 的完整消息列表。

        Args:
            system_msg: 系统消息
            user_input: 用户输入 (仅第一次迭代)

        Returns:
            消息列表
        """
        messages: list[Message] = []

        # 1. System Message (含 Tool Schema + Agent 列表)
        messages.append(system_msg)

        # 2. 从 ContextStore 获取历史消息 (自动压缩)
        context_messages = self.context_store.get_messages_for_llm()
        # 跳过 context 中的 system message (已添加)
        for msg in context_messages:
            if msg.role != "system":
                messages.append(msg)

        # 3. 当前轮 User Message (仅在首次迭代)
        if user_input:
            messages.append(Message(role="user", content=user_input))

        return messages

    def _parse_llm_output(self, response: ChatResponse) -> ParsedReAct:
        """
        解析 LLM 输出。

        容错: 若解析失败 → 以原始内容构建 Thought="(解析失败)",
        将原始输出作为 Observation 反馈 LLM 要求重新格式化。

        Args:
            response: LLM 返回的 ChatResponse

        Returns:
            ParsedReAct 解析结果
        """
        return self.output_parser.parse(response)

    def _execute_action(self, parsed: ParsedReAct) -> ActionResult:
        """
        执行 Action。

        1. 调用 match_strategy.match() 匹配 Tool 或 Agent
        2. 匹配到 → 执行 (带超时控制)
        3. 未匹配 → 返回 ACTION_NOT_FOUND 错误

        Args:
            parsed: 解析后的 ReAct 结果

        Returns:
            ActionResult 执行结果
        """
        action_name = parsed.action_name or ""
        action_input = parsed.action_input or {}

        # 使用匹配策略查找
        match_result: MatchResult = self.match_strategy.match(
            action_name,
            action_input,
            self.tool_manager.tools,
            self.agent_registry,
        )

        if match_result.tool_name:
            # 匹配到普通 Tool
            try:
                tool_result = self.tool_manager.execute_with_timeout(
                    match_result.tool_name,
                    timeout=self.tool_execution_timeout,
                    **action_input,
                )
                return ActionResult(
                    success=tool_result.success,
                    observation=tool_result.output,
                    tool_result=tool_result,
                    error=tool_result.error,
                )
            except Exception as e:
                return ActionResult(
                    success=False,
                    observation=f"Tool '{match_result.tool_name}' 执行失败: {e}",
                    error=str(e),
                )

        elif match_result.agent_name:
            # 匹配到特化 Agent → 拉起执行
            try:
                agent_result = self.agent_registry.launch(
                    match_result.agent_name,
                    action_input.get("task", parsed.thought or ""),
                    action_input.get("context"),
                )
                return ActionResult(
                    success=agent_result.success,
                    observation=agent_result.final_answer,
                    agent_result=agent_result,
                    error=str(agent_result.error) if agent_result.error else None,
                )
            except Exception as e:
                return ActionResult(
                    success=False,
                    observation=f"Agent '{match_result.agent_name}' 拉起失败: {e}",
                    error=str(e),
                )

        # 未匹配到任何 Tool/Agent
        available = list(self.tool_manager.tools.keys())
        return ActionResult(
            success=False,
            observation=(
                f"未找到 Tool 或 Agent: '{action_name}'。"
                f"可用 Tool: {available}。"
                f"可用 Agent: {[a.name for a in self.agent_registry.list_agents()]}。"
                f"请使用可用 Tool 或 Final Answer 回复。"
            ),
            error=f"Tool/Agent not found: {action_name}",
        )

    def _format_observation(self, result: ActionResult) -> str:
        """
        将执行结果格式化为 Observation 文本。

        成功: 截断过长结果, 添加 token 估算提示
        失败: 包含错误类型和建议。

        Args:
            result: ActionResult 实例

        Returns:
            格式化后的 Observation 文本
        """
        if result.success:
            output = result.observation
            # 截断过长输出
            if len(output) > 4000:
                output = output[:4000] + f"\n\n... [输出截断, 原始长度: {len(result.observation)} 字符]"
            return output
        else:
            return f"错误: {result.error or result.observation}"

    def _force_summarize(self) -> str:
        """
        强制总结 — 向 LLM 发送最后一个请求, 要求基于已有信息给出回答。

        Returns:
            LLM 的最终回答文本
        """
        try:
            messages = self.context_store.get_messages_for_llm()
            messages.append(Message(
                role="user",
                content="基于以上信息, 请给出你的最终回答 (Final Answer), 即使信息不完整。",
            ))

            response = self.llm_client.chat(messages=messages)
            return response.content or "无法生成总结"
        except Exception as e:
            logger.error(f"强制总结失败: {e}")
            return f"Agent 执行终止: {e}"

    def _check_termination(self, parsed: ParsedReAct, iteration: int) -> FinishReason | None:
        """
        检查是否应终止循环。

        Args:
            parsed: 解析后的 ReAct 结果
            iteration: 当前迭代次数

        Returns:
            FinishReason 或 None (继续循环)
        """
        if parsed.has_final_answer:
            return FinishReason.DONE
        if iteration >= self.max_iterations:
            return FinishReason.MAX_ITERATIONS
        if self._stop_requested:
            return FinishReason.STOPPED
        if self._consecutive_failures >= self.max_consecutive_failures:
            return FinishReason.CONSECUTIVE_FAILURES
        return None
