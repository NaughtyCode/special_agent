"""
事件总线 — 发布-订阅模式, 解耦 Agent 生命周期通知。

事件类型:
- AgentLifecycleEvent: INITIALIZED / STARTED / COMPLETED / ERROR / SPAWNED / STOPPED
- ToolCallEvent: BEFORE_EXECUTE / AFTER_EXECUTE
- LLMCallEvent: BEFORE_CALL / AFTER_CALL
- ReActIterationEvent: ITERATION_START / ITERATION_END
- CrewLifecycleEvent: PLANNED / STARTED / MEMBER_STARTED / MEMBER_COMPLETED / MEMBER_FAILED / COMPLETED / FAILED
- ConfirmationRequestEvent: 危险操作确认请求
"""

import logging
from collections import defaultdict
from typing import Any, Callable

from src.events.events import Event

logger = logging.getLogger(__name__)


class EventBus:
    """
    事件总线 — 发布-订阅模式, 解耦 Agent 生命周期通知。

    支持订阅特定类型的事件, 发布时间步按订阅顺序依次调用 handler。
    单个 handler 异常不影响其他 handler。
    """

    def __init__(self) -> None:
        """初始化事件总线, 创建空的订阅者注册表。"""
        # 按事件类型组织订阅者: {event_type: [handler1, handler2, ...]}
        self._subscribers: dict[type, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable[[Event], None]) -> None:
        """
        订阅事件。

        Args:
            event_type: 要订阅的事件类型 (如 AgentLifecycleEvent, ToolCallEvent)
            handler: 事件处理函数, 接收 Event 对象作为参数
        """
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type, handler: Callable[[Event], None]) -> None:
        """
        取消订阅事件。

        Args:
            event_type: 事件类型
            handler: 要移除的处理函数
        """
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        """
        发布事件 (同步, 按订阅顺序依次调用 handler)。

        单个 handler 异常不影响其他 handler, 异常会被记录到日志。

        Args:
            event: 要发布的事件对象
        """
        event_type = type(event.event_type)
        handlers = self._subscribers.get(event_type, [])

        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    f"Event handler {handler.__name__} failed for event {event.event_type}"
                )

    async def publish_async(self, event: Event) -> None:
        """
        发布事件 (异步, 并发调用所有 handler)。

        注意: 当前实现仍是同步的 — handler 必须自身是 async 函数才能异步执行。
        若 handler 是同步函数, 行为与 publish() 相同。

        Args:
            event: 要发布的事件对象
        """
        import asyncio

        event_type = type(event.event_type)
        handlers = self._subscribers.get(event_type, [])

        # 并发执行所有异步 handler
        tasks = []
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    tasks.append(asyncio.create_task(handler(event)))
                else:
                    handler(event)
            except Exception:
                logger.exception(
                    f"Event handler {handler.__name__} failed for event {event.event_type}"
                )

        # 等待所有异步 handler 完成
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def clear(self) -> None:
        """清除所有订阅者。"""
        self._subscribers.clear()
