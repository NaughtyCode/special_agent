"""
Agent 实例池 — 管理 Agent 实例的惰性创建、复用和并发控制。

解决的问题:
- 避免每次子任务重复创建 Agent 实例 (复用 LLMClient 连接等重量资源)
- 限制并发 Agent 数量, 防止资源耗尽
- 支持实例生命周期管理 (空闲超时回收)
"""

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AgentPoolExhaustedError(Exception):
    """Agent 池已耗尽时抛出。"""
    pass


class AgentPool:
    """
    Agent 实例池 — 管理 Agent 实例的惰性创建、复用和并发控制。

    解决的问题:
    - 避免每次子任务重复创建 Agent 实例 (复用 LLMClient 连接等重量资源)
    - 限制并发 Agent 数量, 防止资源耗尽
    - 支持实例生命周期管理 (空闲超时回收)
    """

    def __init__(
        self,
        max_instances: int | None = None,
        idle_timeout: float | None = None,
    ) -> None:
        """
        初始化 Agent 实例池。

        Args:
            max_instances: 最大并发实例数 (None = 无限制, 从 Config 读取)
            idle_timeout: 实例空闲超时, 超时后回收 (None = 使用默认值 300s)
        """
        self._max_instances = max_instances  # None = 无限制
        self._idle_timeout = idle_timeout or 300.0  # 默认 5 分钟

        # 池状态: {agent_name: [(instance, last_used_timestamp, in_use)]}
        self._pool: dict[str, list[tuple[Any, float, bool]]] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def acquire(
        self,
        agent_name: str,
        agent_factory: Callable[[], Any],
    ) -> Any:
        """
        获取 Agent 实例。

        1. 若池中有空闲实例 → 直接返回 (复用)
        2. 若未达上限 → 调用 agent_factory 创建新实例
        3. 若已达上限 → 等待 (阻塞) 或抛出 AgentPoolExhaustedError

        Args:
            agent_name: Agent 名称
            agent_factory: 创建 Agent 实例的工厂函数 (零参数 callable)

        Returns:
            Agent 实例

        Raises:
            AgentPoolExhaustedError: 若池已满且无法等待
        """
        with self._condition:
            # 尝试复用空闲实例
            idle_instance = self._find_idle(agent_name)
            if idle_instance is not None:
                instance, _, _ = idle_instance
                self._mark_in_use(agent_name, instance)
                logger.debug(f"AgentPool: reused '{agent_name}' instance")
                return instance

            # 检查是否达上限
            if self._max_instances is not None:
                current_count = self._count_instances(agent_name)
                if current_count >= self._max_instances:
                    logger.warning(
                        f"AgentPool: exhausted for '{agent_name}' "
                        f"(max={self._max_instances})"
                    )
                    raise AgentPoolExhaustedError(
                        f"Agent '{agent_name}' 实例池已满 (最大 {self._max_instances})"
                    )

            # 创建新实例
            instance = agent_factory()
            self._add_instance(agent_name, instance)
            logger.debug(f"AgentPool: created new '{agent_name}' instance")
            return instance

    def release(self, agent: Any) -> None:
        """
        归还 Agent 实例。

        自动调用 agent.reset() 清理状态。

        Args:
            agent: 要归还的 Agent 实例
        """
        agent_name = getattr(agent, "name", "unknown")

        with self._condition:
            # 调用 reset() 清理状态
            try:
                agent.reset()
            except Exception as e:
                logger.warning(f"AgentPool: error resetting '{agent_name}': {e}")

            # 标记为空闲
            self._mark_idle(agent_name, agent)
            self._condition.notify_all()
            logger.debug(f"AgentPool: released '{agent_name}' instance")

    def _find_idle(self, agent_name: str) -> tuple[Any, float, bool] | None:
        """查找空闲实例 (内部方法, 需持有锁)。"""
        instances = self._pool.get(agent_name, [])
        for i, (instance, last_used, in_use) in enumerate(instances):
            if not in_use:
                # 检查是否超时 (超时则回收)
                if time.time() - last_used > self._idle_timeout:
                    instances.pop(i)
                    logger.debug(f"AgentPool: removed idle '{agent_name}' instance (timeout)")
                    continue
                return (instance, last_used, in_use)
        return None

    def _mark_in_use(self, agent_name: str, instance: Any) -> None:
        """标记实例为使用中 (内部方法, 需持有锁)。"""
        instances = self._pool.get(agent_name, [])
        for i, (inst, _, _) in enumerate(instances):
            if inst is instance:
                instances[i] = (inst, time.time(), True)
                return

    def _mark_idle(self, agent_name: str, instance: Any) -> None:
        """标记实例为空闲 (内部方法, 需持有锁)。"""
        instances = self._pool.get(agent_name, [])
        for i, (inst, _, _) in enumerate(instances):
            if inst is instance:
                instances[i] = (inst, time.time(), False)
                return

    def _add_instance(self, agent_name: str, instance: Any) -> None:
        """添加新实例到池 (内部方法, 需持有锁)。"""
        if agent_name not in self._pool:
            self._pool[agent_name] = []
        self._pool[agent_name].append((instance, time.time(), True))

    def _count_instances(self, agent_name: str) -> int:
        """统计指定 Agent 的实例数 (内部方法, 需持有锁)。"""
        return len(self._pool.get(agent_name, []))

    def get_stats(self) -> dict[str, dict]:
        """
        获取池统计信息。

        Returns:
            {agent_name: {"total": int, "in_use": int, "idle": int}}
        """
        with self._lock:
            stats: dict[str, dict] = {}
            for name, instances in self._pool.items():
                total = len(instances)
                in_use = sum(1 for _, _, used in instances if used)
                stats[name] = {"total": total, "in_use": in_use, "idle": total - in_use}
            return stats

    def cleanup(self) -> int:
        """
        清理超时闲置实例。

        Returns:
            清理的实例数量
        """
        removed = 0
        now = time.time()
        with self._lock:
            for name in list(self._pool.keys()):
                self._pool[name] = [
                    (inst, ts, used)
                    for inst, ts, used in self._pool[name]
                    if used or (now - ts) <= self._idle_timeout
                ]
                removed += len(self._pool[name]) - len([
                    (inst, ts, used)
                    for inst, ts, used in self._pool[name]
                ])
        return removed
