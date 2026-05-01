"""
Crew Orchestrator — 团队编排引擎。

核心职责:
1. 任务分解 (Plan):  将复杂使命分解为 SubTask 列表 (使用 LLM)
2. Agent 匹配 (Match): 为每个 SubTask 匹配最合适的特化 Agent (通过 AgentRegistry)
3. Crew 组建 (Assemble): 构建 AgentCrew 结构
4. Crew 执行 (Execute): 按指定策略驱动各成员执行子任务
5. 结果聚合 (Aggregate): 汇总所有成员结果, 生成统一的 CrewResult
"""

import concurrent.futures
import json
import logging
import threading
import time
from typing import Any

from src.crew.models import (
    AgentCrew,
    CrewInvalidStateError,
    CrewMember,
    CrewPlanError,
    CrewResult,
    SubTask,
)
from src.core.models import (
    AgentConfig,
    AgentResult,
    ExecutionStrategy,
    FinishReason,
    Message,
    TokenUsage,
    ToolExecutionError,
)
from src.events.events import CrewEvent, CrewLifecycleEvent, Event

logger = logging.getLogger(__name__)


class CrewOrchestrator:
    """
    Crew Orchestrator — 团队编排引擎。

    核心职责:
    1. 任务分解 (Plan):  将复杂使命分解为 SubTask 列表 (使用 LLM)
    2. Agent 匹配 (Match): 为每个 SubTask 匹配最合适的特化 Agent (通过 AgentRegistry)
    3. Crew 组建 (Assemble): 构建 AgentCrew 结构
    4. Crew 执行 (Execute): 按指定策略驱动各成员执行子任务
    5. 结果聚合 (Aggregate): 汇总所有成员结果, 生成统一的 CrewResult

    这是框架的核心扩展机制 — 任何特化 Agent 均可通过 CrewOrchestrator
    将复杂任务拆解并分派给一组更专业的 Agent 协同完成。

    设计原则:
    - 无状态: 所有状态存储在 AgentCrew 中, Orchestrator 本身不持有 Crew 状态
    - 策略可替换: ExecutionStrategy 由调用方传入, 可扩展自定义策略
    - LLM 驱动: 任务分解和结果聚合均使用 LLM, 依赖 LLM 的语义理解能力
    - 事件驱动: 通过 EventBus 发布 Crew 生命周期事件, 便于监控和日志
    """

    def __init__(
        self,
        agent_registry: Any,
        agent_pool: Any,
        llm_client: Any,
        event_bus: Any,
        config: Any,
    ) -> None:
        """
        初始化 CrewOrchestrator。

        Args:
            agent_registry: AgentRegistry 实例
            agent_pool: AgentPool 实例
            llm_client: LLMClient 实例
            event_bus: EventBus 实例
            config: Config 实例
        """
        self.agent_registry = agent_registry
        self.agent_pool = agent_pool
        self.llm_client = llm_client
        self.event_bus = event_bus
        self.config = config

        # 从 Config 读取 Crew 专用配置
        self.max_parallel = getattr(config, "crew_max_parallel", 4)
        self.crew_max_iterations = getattr(config, "crew_max_iterations", 3)
        self.plan_temperature = getattr(config, "crew_plan_temperature", 0.4)

    # ── Plan: 任务分解与 Agent 匹配 ───────────────────

    def plan_crew(
        self,
        mission: str,
        lead_agent_name: str,
        available_agents: list[Any] | None = None,
        crew_leader_call_depth: int = 0,
    ) -> AgentCrew:
        """
        将 mission 分解为 SubTask 列表, 并为每个子任务匹配最佳 Agent。

        前置条件: mission 必须为非空字符串, 否则抛出 ValueError。

        Args:
            mission: 团队使命描述
            lead_agent_name: CrewLeader 的名称
            available_agents: 可用 Agent 元数据列表, None 则从 agent_registry 获取
            crew_leader_call_depth: CrewLeader 的 call_depth

        Returns:
            已组建但尚未执行的 AgentCrew (status=ASSEMBLED)

        Raises:
            ValueError: 若 mission 为空
            CrewPlanError: 若分解或匹配失败
        """
        if not mission or not mission.strip():
            raise ValueError("mission 不能为空")

        # 获取可用 Agent 列表
        if available_agents is None:
            available_agents = self.agent_registry.list_agents()

        # 创建 AgentCrew
        crew = AgentCrew.create(
            lead_agent_name=lead_agent_name,
            mission=mission,
            crew_leader_call_depth=crew_leader_call_depth,
        )

        # 使用 LLM 分解 mission → SubTask 列表
        subtasks = self._decompose_mission(mission, available_agents)

        # 为每个 SubTask 匹配 Agent
        for subtask in subtasks:
            matched = self.agent_registry.match_agent(subtask.description)
            if matched.agent_name:
                meta = self.agent_registry.get_agent_meta(matched.agent_name)
                member = CrewMember(
                    agent_name=matched.agent_name,
                    agent_cls=meta.agent_cls,
                    task=subtask,
                )
                crew.members.append(member)
            else:
                raise CrewPlanError(
                    f"无法为子任务 '{subtask.task_id}' 匹配 Agent: {subtask.description}"
                )

        # 发布 PLANNED 事件 (带 CrewEvent 负载)
        self.event_bus.publish(Event(
            event_type=CrewLifecycleEvent.PLANNED,
            payload=CrewEvent(
                event_type=CrewLifecycleEvent.PLANNED,
                crew_id=crew.crew_id,
                lead_agent_name=lead_agent_name,
                member_count=len(crew.members),
            ),
        ))

        logger.info(
            f"Crew planned: {crew.crew_id}, mission='{mission[:50]}...', "
            f"members={len(crew.members)}"
        )
        return crew

    def _decompose_mission(self, mission: str, available_agents: list[Any]) -> list[SubTask]:
        """
        使用 LLM 将 mission 分解为 SubTask 列表。

        Args:
            mission: 团队使命
            available_agents: 可用 Agent 列表

        Returns:
            SubTask 列表

        Raises:
            CrewPlanError: 若 LLM 分解失败
        """
        # 构建分解 Prompt
        agents_desc = "\n".join(
            f"- {a.name} (tags: {', '.join(a.tags)}): {a.description}"
            for a in available_agents
        )

        system_prompt = f"""你是一个任务分解专家。请将以下使命分解为独立的子任务列表。

可用 Agent 及其能力:
{agents_desc}

请输出 JSON 格式的子任务列表:
[
  {{
    "description": "子任务描述",
    "required_tags": ["tag1", "tag2"],
    "dependencies": ["task_1"]  // 依赖的其他子任务临时 ID, 无依赖则为空数组
  }}
]

规则:
1. 每个子任务应独立且可分配给单个 Agent
2. 使用临时 ID (如 task_1, task_2) 表示依赖关系
3. required_tags 必须从上述 Agent 的 tags 中选择
4. 输出必须是合法的 JSON 数组
5. 子任务数量应合理 (通常 2-5 个)"""

        user_prompt = f"使命: {mission}"

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        # 调用 LLM, 最多重试 crew_max_iterations 次
        last_output: str | None = None
        for attempt in range(self.crew_max_iterations):
            try:
                response = self.llm_client.chat(
                    messages=messages,
                    temperature=self.plan_temperature,
                )

                content = response.content or ""
                last_output = content

                # 提取 JSON 数组
                subtasks_data = self._extract_json_array(content)
                if not subtasks_data:
                    raise ValueError("无法从 LLM 输出中提取 JSON 数组")

                # 构建 SubTask 列表
                subtasks: list[SubTask] = []
                temp_id_map: dict[str, str] = {}  # 临时 ID → 正式 UUID

                for item in subtasks_data:
                    desc = item.get("description", "")
                    tags = item.get("required_tags", [])
                    deps = item.get("dependencies", [])
                    context = item.get("context")

                    # 生成正式 UUID
                    subtask = SubTask.create(
                        description=desc,
                        required_tags=tags,
                        dependencies=[],  # 先空, 后续替换
                        context=context,
                    )
                    # 记录临时 ID 映射 (若 item 有 id 字段)
                    temp_id = item.get("id", f"task_{len(subtasks) + 1}")
                    temp_id_map[temp_id] = subtask.task_id
                    subtasks.append(subtask)

                # 替换依赖引用: 临时 ID → 正式 UUID
                for i, item in enumerate(subtasks_data):
                    deps = item.get("dependencies", [])
                    resolved_deps = [
                        temp_id_map.get(d, d) for d in deps
                    ]
                    subtasks[i].dependencies = resolved_deps

                # 校验依赖完整性
                all_task_ids = {s.task_id for s in subtasks}
                for subtask in subtasks:
                    for dep in subtask.dependencies:
                        if dep not in all_task_ids:
                            raise CrewPlanError(f"依赖 '{dep}' 不存在于子任务列表中")

                # 检测循环依赖 (DFS)
                self._check_circular_dependencies(subtasks, all_task_ids)

                return subtasks

            except Exception as e:
                logger.warning(
                    f"Crew plan attempt {attempt + 1}/{self.crew_max_iterations} failed: {e}"
                )
                if attempt < self.crew_max_iterations - 1:
                    # 反馈错误给 LLM
                    messages.append(Message(
                        role="user",
                        content=f"输出格式错误: {e}。请修正为合法的 JSON 数组格式。",
                    ))
                else:
                    raise CrewPlanError(
                        f"任务分解失败, 已重试 {self.crew_max_iterations} 次: {e}",
                        raw_llm_output=last_output,
                    )

        # 不应到达此处
        raise CrewPlanError("任务分解失败: 超过最大重试次数")

    def _extract_json_array(self, text: str) -> list[dict] | None:
        """从文本中提取 JSON 数组。"""
        import re

        # 尝试直接解析
        text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 数组 (在 ```json ... ``` 代码块中)
        code_block = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if code_block:
            try:
                data = json.loads(code_block.group(1).strip())
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # 尝试提取方括号包围的 JSON
        bracket_match = re.search(r'\[.*\]', text, re.DOTALL)
        if bracket_match:
            try:
                data = json.loads(bracket_match.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def _check_circular_dependencies(self, subtasks: list[SubTask], task_ids: set[str]) -> None:
        """使用 DFS 检测循环依赖。"""
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(task_id: str) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)

            for subtask in subtasks:
                if subtask.task_id == task_id:
                    for dep in subtask.dependencies:
                        if dep not in visited:
                            if dfs(dep):
                                return True
                        elif dep in rec_stack:
                            return True  # 发现环
                    break

            rec_stack.discard(task_id)
            return False

        for task_id in task_ids:
            if task_id not in visited:
                if dfs(task_id):
                    raise CrewPlanError("检测到循环依赖")

    # ── Execute: Crew 执行 ────────────────────────────

    def execute_crew(
        self,
        crew: AgentCrew,
        strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL,
        max_parallel: int | None = None,
    ) -> CrewResult:
        """
        按指定策略执行 Crew。

        前置条件:
        - crew.status 必须为 ASSEMBLED
        - crew.members 必须非空

        Args:
            crew: 要执行的 AgentCrew
            strategy: 执行策略
            max_parallel: 最大并行数, None 使用默认值

        Returns:
            CrewResult 汇总结果

        Raises:
            CrewInvalidStateError: 若 crew.status != "ASSEMBLED"
            ValueError: 若 crew.members 为空
        """
        if crew.status != "ASSEMBLED":
            raise CrewInvalidStateError(
                f"Crew 状态不合法: 期望 'ASSEMBLED', 实际 '{crew.status}'"
            )

        if not crew.members:
            raise ValueError("crew 没有可执行的成员")

        crew.status = "RUNNING"

        # 发布 STARTED 事件
        self.event_bus.publish(Event(
            event_type=CrewLifecycleEvent.STARTED,
            payload=CrewEvent(
                event_type=CrewLifecycleEvent.STARTED,
                crew_id=crew.crew_id,
                strategy=strategy.value,
            ),
        ))

        logger.info(
            f"Crew executing: {crew.crew_id}, strategy={strategy.value}, "
            f"members={len(crew.members)}"
        )

        # 根据策略分发执行
        actual_parallel = max_parallel if max_parallel is not None else self.max_parallel

        if strategy == ExecutionStrategy.SEQUENTIAL:
            results = self._execute_sequential(crew)
        elif strategy == ExecutionStrategy.PARALLEL:
            results = self._execute_parallel(crew, actual_parallel)
        elif strategy == ExecutionStrategy.DAG:
            results = self._execute_dag(crew, actual_parallel)
        else:
            raise ValueError(f"未知的执行策略: {strategy}")

        # 记录完成时间
        crew.completed_at = time.time()

        # 聚合结果
        crew_result = self._aggregate_results(crew, results)

        # 设置最终状态并发布事件
        if crew_result.success:
            crew.status = "COMPLETED"
            self.event_bus.publish(Event(
                event_type=CrewLifecycleEvent.COMPLETED,
                payload=CrewEvent(
                    event_type=CrewLifecycleEvent.COMPLETED,
                    crew_id=crew.crew_id,
                    total_duration_ms=crew_result.total_duration_ms,
                    token_usage=crew_result.token_usage,
                ),
            ))
        else:
            crew.status = "FAILED"
            self.event_bus.publish(Event(
                event_type=CrewLifecycleEvent.FAILED,
                payload=CrewEvent(
                    event_type=CrewLifecycleEvent.FAILED,
                    crew_id=crew.crew_id,
                    error_message=f"存在 {len(crew_result.failed_members)} 个失败成员",
                ),
            ))

        logger.info(
            f"Crew completed: {crew.crew_id}, success={crew_result.success}, "
            f"duration={crew_result.total_duration_ms:.0f}ms"
        )
        return crew_result

    def _agent_factory(self, member: CrewMember, crew: AgentCrew) -> Any:
        """为 CrewMember 创建 Agent 实例的工厂函数。"""
        meta = self.agent_registry.get_agent_meta(member.agent_name)
        return member.agent_cls(
            name=member.agent_name,
            description=meta.description,
            config=self.config,
            agent_config=AgentConfig(
                call_depth=crew.crew_leader_call_depth + 1,
            ),
        )

    def _run_member(self, member: CrewMember, crew: AgentCrew, extra_context: dict | None = None) -> tuple[str, str, Any]:
        """
        执行单个 CrewMember 的子任务。

        Args:
            member: CrewMember 实例
            crew: 所属 AgentCrew
            extra_context: 额外的上下文 (如前置任务结果)

        Returns:
            (agent_name, task_id, AgentResult)
        """
        if member.task is None:
            raise ValueError(f"成员 '{member.agent_name}' 没有分配子任务")

        task = member.task
        task_id = task.task_id

        # 合并 context
        context = dict(task.context) if task.context else {}
        if extra_context:
            context.update(extra_context)

        # 发布 MEMBER_STARTED
        self.event_bus.publish(Event(
            event_type=CrewLifecycleEvent.MEMBER_STARTED,
            payload=CrewEvent(
                event_type=CrewLifecycleEvent.MEMBER_STARTED,
                crew_id=crew.crew_id,
                member_name=member.agent_name,
                task_id=task_id,
            ),
        ))

        try:
            member.agent_instance = self.agent_pool.acquire(
                member.agent_name,
                lambda: self._agent_factory(member, crew),
            )
        except Exception as e:
            member.status = "FAILED"
            member.completed_at = time.time()
            fail_result = AgentResult(
                success=False,
                final_answer=str(e),
                iterations=[],
                token_usage=TokenUsage(),
                total_duration_ms=0,
                finish_reason=FinishReason.ERROR,
                error=ToolExecutionError(str(e)),
            )
            member.result = fail_result
            return (member.agent_name, task_id, fail_result)

        try:
            member.status = "RUNNING"
            member.started_at = time.time()
            member.result = member.agent_instance.run(
                task.description,
                context if context else None,
            )
            member.status = "DONE"

            # 发布 MEMBER_COMPLETED
            duration = (member.completed_at - member.started_at) * 1000 if member.started_at else 0
            self.event_bus.publish(Event(
                event_type=CrewLifecycleEvent.MEMBER_COMPLETED,
                payload=CrewEvent(
                    event_type=CrewLifecycleEvent.MEMBER_COMPLETED,
                    crew_id=crew.crew_id,
                    member_name=member.agent_name,
                    task_id=task_id,
                    duration_ms=duration,
                ),
            ))
        except Exception as e:
            member.status = "FAILED"
            member.result = AgentResult(
                success=False,
                final_answer=str(e),
                iterations=[],
                token_usage=TokenUsage(),
                total_duration_ms=0,
                finish_reason=FinishReason.ERROR,
                error=ToolExecutionError(str(e)),
            )
            # 发布 MEMBER_FAILED
            self.event_bus.publish(Event(
                event_type=CrewLifecycleEvent.MEMBER_FAILED,
                payload=CrewEvent(
                    event_type=CrewLifecycleEvent.MEMBER_FAILED,
                    crew_id=crew.crew_id,
                    member_name=member.agent_name,
                    task_id=task_id,
                    error_message=str(e),
                ),
            ))
        finally:
            member.completed_at = time.time()
            try:
                self.agent_pool.release(member.agent_instance)
            except Exception:
                pass

        return (member.agent_name, task_id, member.result)

    def _execute_sequential(self, crew: AgentCrew) -> list[tuple[str, str, Any]]:
        """
        串行执行 — 按 members 列表顺序依次执行每个成员。

        前一成员的结果 (final_answer) 自动作为后一成员的 task.context 传入。

        Args:
            crew: AgentCrew 实例

        Returns:
            (agent_name, task_id, AgentResult) 列表
        """
        results: list[tuple[str, str, Any]] = []
        previous_result: str | None = None
        previous_error: str | None = None

        for member in crew.members:
            if member.task is None:
                raise ValueError(f"成员 '{member.agent_name}' 没有分配子任务")

            # 构建传递上下文
            extra_context: dict = {}
            if previous_result is not None:
                extra_context["previous_result"] = previous_result
            if previous_error is not None:
                extra_context["previous_error"] = previous_error

            result_tuple = self._run_member(member, crew, extra_context if extra_context else None)
            results.append(result_tuple)

            # 更新上下文给下一个成员
            _, _, agent_result = result_tuple
            previous_result = agent_result.final_answer
            previous_error = str(agent_result.error) if agent_result.error else None

        return results

    def _execute_parallel(self, crew: AgentCrew, max_parallel: int) -> list[tuple[str, str, Any]]:
        """
        并行执行 — 并发执行所有成员 (受 max_parallel 限制)。

        Args:
            crew: AgentCrew 实例
            max_parallel: 最大并行数

        Returns:
            (agent_name, task_id, AgentResult) 列表
        """
        results: list[tuple[str, str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures = {
                executor.submit(self._run_member, member, crew, member.task.context if member.task else None): member
                for member in crew.members
                if member.task is not None
            }

            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    member = futures[future]
                    results.append((
                        member.agent_name,
                        member.task.task_id if member.task else "unknown",
                        AgentResult(
                            success=False,
                            final_answer=str(e),
                            iterations=[],
                            token_usage=TokenUsage(),
                            finish_reason=FinishReason.ERROR,
                            error=ToolExecutionError(str(e)),
                        ),
                    ))

        return results

    def _execute_dag(self, crew: AgentCrew, max_parallel: int) -> list[tuple[str, str, Any]]:
        """
        DAG 执行 — 按依赖关系拓扑排序, 无依赖的成员可并行。

        算法:
        1. 构建依赖图
        2. 检测循环依赖
        3. 找出所有入度为 0 的成员, 加入就绪队列
        4. 并发执行就绪队列中的所有成员
        5. 每完成一个成员, 将其结果传递给依赖它的后续成员
        6. 当某成员的所有依赖都已满足, 将其加入就绪队列

        Args:
            crew: AgentCrew 实例
            max_parallel: 最大并行数

        Returns:
            (agent_name, task_id, AgentResult) 列表
        """
        # 构建依赖图
        member_map: dict[str, CrewMember] = {}
        dep_graph: dict[str, set[str]] = {}  # task_id → {依赖它的 task_id 集合}
        in_degree: dict[str, int] = {}  # task_id → 入度

        for member in crew.members:
            if member.task is None:
                continue
            tid = member.task.task_id
            member_map[tid] = member
            dep_graph[tid] = set()
            in_degree[tid] = 0

        for member in crew.members:
            if member.task is None:
                continue
            tid = member.task.task_id
            for dep in member.task.dependencies:
                if dep in dep_graph:
                    dep_graph[dep].add(tid)
                    in_degree[tid] = in_degree.get(tid, 0) + 1

        # 找出入度为 0 的成员
        ready: list[str] = [tid for tid, deg in in_degree.items() if deg == 0]

        if not ready:
            raise CrewPlanError("DAG 无法确定执行起点")

        results: list[tuple[str, str, Any]] = []
        completed: dict[str, Any] = {}  # task_id → AgentResult
        lock = threading.Lock()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
            pending_futures: dict[concurrent.futures.Future, str] = {}

            # 提交初始就绪任务
            for tid in ready:
                member = member_map[tid]
                # 构建依赖结果的上下文
                dep_context: dict = dict(member.task.context) if member.task and member.task.context else {}
                dep_results = {}
                dep_errors = {}
                if member.task:
                    for dep_tid in member.task.dependencies:
                        if dep_tid in completed:
                            dep_results[dep_tid] = completed[dep_tid].final_answer
                        if dep_tid in completed and completed[dep_tid].error:
                            dep_errors[dep_tid] = str(completed[dep_tid].error)
                if dep_results:
                    dep_context["dependency_results"] = dep_results
                if dep_errors:
                    dep_context["dependency_errors"] = dep_errors

                future = executor.submit(
                    self._run_member, member, crew,
                    dep_context if dep_context else None,
                )
                pending_futures[future] = tid

            # 处理完成的任务, 触发依赖
            while pending_futures:
                done_futures = concurrent.futures.as_completed(pending_futures)
                for future in done_futures:
                    tid = pending_futures.pop(future)
                    try:
                        result = future.result()
                    except Exception as e:
                        member = member_map[tid]
                        result = (member.agent_name, tid, AgentResult(
                            success=False, final_answer=str(e),
                            iterations=[], token_usage=TokenUsage(),
                            finish_reason=FinishReason.ERROR,
                        ))

                    with lock:
                        results.append(result)
                        _, _, agent_result = result
                        completed[tid] = agent_result

                        # 检查依赖此任务的后续任务
                        for dependent_tid in dep_graph.get(tid, set()):
                            in_degree[dependent_tid] -= 1
                            if in_degree[dependent_tid] == 0:
                                # 所有依赖已满足, 加入就绪队列
                                member = member_map[dependent_tid]
                                dep_context = dict(member.task.context) if member.task and member.task.context else {}
                                dep_results = {}
                                dep_errors = {}
                                if member.task:
                                    for dep_tid in member.task.dependencies:
                                        if dep_tid in completed:
                                            dep_results[dep_tid] = completed[dep_tid].final_answer
                                        if dep_tid in completed and completed[dep_tid].error:
                                            dep_errors[dep_tid] = str(completed[dep_tid].error)
                                if dep_results:
                                    dep_context["dependency_results"] = dep_results
                                if dep_errors:
                                    dep_context["dependency_errors"] = dep_errors

                                future = executor.submit(
                                    self._run_member, member, crew,
                                    dep_context if dep_context else None,
                                )
                                pending_futures[future] = dependent_tid

                    # 每个完成就检查是否有新任务 → 跳出内层循环继续
                    break

        return results

    # ── Aggregate: 结果聚合 ───────────────────────────

    def _aggregate_results(
        self,
        crew: AgentCrew,
        results: list[tuple[str, str, Any]],
    ) -> CrewResult:
        """
        汇总所有成员结果:
        1. 遍历 results, 拆分成功/失败成员
        2. 将所有 member final_answer 和失败信息拼接为上下文
        3. 调用 LLM 生成统一的 mission_summary
        4. 计算 total_duration_ms 和 total_token_usage
        5. 构建 execution_order
        6. 判定整体 success

        Args:
            crew: AgentCrew 实例
            results: (agent_name, task_id, AgentResult) 列表

        Returns:
            CrewResult
        """
        failed_members: list[tuple[str, str]] = []
        total_tokens = TokenUsage()

        for agent_name, task_id, agent_result in results:
            if not agent_result.success:
                failed_members.append((agent_name, task_id))
            if agent_result.token_usage:
                total_tokens += agent_result.token_usage

        # 构建执行顺序
        execution_order = [task_id for _, task_id, _ in results]

        # 计算总耗时 (wall-clock)
        total_duration = max(0.0, (crew.completed_at - crew.created_at)) * 1000

        # 生成 mission_summary (尝试 LLM, 失败则人工拼接)
        try:
            mission_summary = self._generate_summary(crew.mission, results, failed_members)
        except Exception as e:
            logger.warning(f"LLM summary generation failed: {e}, falling back to manual")
            mission_summary = "\n\n".join(
                f"[{agent_name}] (task: {task_id})\n{result.final_answer}"
                for agent_name, task_id, result in results
            )
            if failed_members:
                mission_summary += f"\n\n注意: 以下成员执行失败: {failed_members}"

        return CrewResult(
            success=len(failed_members) == 0,
            crew_id=crew.crew_id,
            mission_summary=mission_summary,
            member_results=results,
            execution_order=execution_order,
            total_duration_ms=total_duration,
            token_usage=total_tokens,
            failed_members=failed_members,
        )

    def _generate_summary(
        self,
        mission: str,
        results: list[tuple[str, str, Any]],
        failed_members: list[tuple[str, str]],
    ) -> str:
        """
        使用 LLM 生成统一的 mission_summary。

        Args:
            mission: 原始使命
            results: 成员结果列表
            failed_members: 失败成员列表

        Returns:
            mission_summary 文本
        """
        # 构建摘要 prompt
        results_text = "\n\n".join(
            f"### {agent_name} (task: {task_id})\n{result.final_answer}"
            for agent_name, task_id, result in results
        )

        failure_note = ""
        if failed_members:
            failure_note = f"\n\n警告: 以下成员执行失败: {failed_members}"

        prompt = f"""请基于以下团队执行结果, 生成一个统一的使命摘要报告。

原始使命: {mission}

成员执行结果:
{results_text}
{failure_note}

请用中文生成一个结构化的摘要报告, 包含:
1. 总体完成情况
2. 各成员的关键成果
3. 存在的问题 (如有)
4. 下一步建议 (如有)"""

        messages = [
            Message(role="user", content=prompt),
        ]

        response = self.llm_client.chat(messages=messages)
        return response.content or "无法生成摘要"
