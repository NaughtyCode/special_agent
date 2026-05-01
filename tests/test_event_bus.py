"""
EventBus 单元测试。

测试覆盖:
- 订阅与取消订阅
- 同步发布
- handler 异常隔离
- 清除订阅者
"""

import unittest

from src.events.event_bus import EventBus
from src.events.events import (
    AgentLifecycleEvent,
    CrewEvent,
    CrewLifecycleEvent,
    Event,
)


class TestEventBus(unittest.TestCase):
    """EventBus 测试。"""

    def setUp(self) -> None:
        self.bus = EventBus()
        self.received: list[Event] = []

    def _handler(self, event: Event) -> None:
        self.received.append(event)

    def test_subscribe_and_publish(self) -> None:
        """测试: 订阅后能收到发布的事件。"""
        self.bus.subscribe(AgentLifecycleEvent, self._handler)
        evt = Event(event_type=AgentLifecycleEvent.INITIALIZED, payload={"agent": "test"})

        self.bus.publish(evt)
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0].event_type, AgentLifecycleEvent.INITIALIZED)

    def test_unsubscribe(self) -> None:
        """测试: 取消订阅后不再收到事件。"""
        self.bus.subscribe(AgentLifecycleEvent, self._handler)
        self.bus.unsubscribe(AgentLifecycleEvent, self._handler)
        self.bus.publish(Event(event_type=AgentLifecycleEvent.STARTED))

        self.assertEqual(len(self.received), 0)

    def test_only_matching_type_receives(self) -> None:
        """测试: 只收到订阅类型的事件。"""
        self.bus.subscribe(AgentLifecycleEvent, self._handler)
        self.bus.publish(Event(event_type=CrewLifecycleEvent.STARTED))

        self.assertEqual(len(self.received), 0)

    def test_multiple_subscribers(self) -> None:
        """测试: 多个订阅者都能收到事件。"""
        received2: list[Event] = []

        def handler2(event: Event) -> None:
            received2.append(event)

        self.bus.subscribe(AgentLifecycleEvent, self._handler)
        self.bus.subscribe(AgentLifecycleEvent, handler2)
        self.bus.publish(Event(event_type=AgentLifecycleEvent.COMPLETED))

        self.assertEqual(len(self.received), 1)
        self.assertEqual(len(received2), 1)

    def test_handler_exception_is_isolated(self) -> None:
        """测试: 单个 handler 异常不影响其他 handler。"""
        received2: list[Event] = []

        def bad_handler(event: Event) -> None:
            raise RuntimeError("handler failed")

        def good_handler(event: Event) -> None:
            received2.append(event)

        self.bus.subscribe(AgentLifecycleEvent, bad_handler)
        self.bus.subscribe(AgentLifecycleEvent, good_handler)
        self.bus.publish(Event(event_type=AgentLifecycleEvent.ERROR))

        self.assertEqual(len(received2), 1)

    def test_duplicate_subscribe_noop(self) -> None:
        """测试: 重复订阅同一 handler 不会重复添加。"""
        self.bus.subscribe(AgentLifecycleEvent, self._handler)
        self.bus.subscribe(AgentLifecycleEvent, self._handler)
        self.bus.publish(Event(event_type=AgentLifecycleEvent.INITIALIZED))

        self.assertEqual(len(self.received), 1)

    def test_clear(self) -> None:
        """测试: clear 后所有订阅者被移除。"""
        self.bus.subscribe(AgentLifecycleEvent, self._handler)
        self.bus.clear()
        self.bus.publish(Event(event_type=AgentLifecycleEvent.INITIALIZED))

        self.assertEqual(len(self.received), 0)

    def test_publish_custom_event_type(self) -> None:
        """测试: 发布自定义事件类型。"""
        self.bus.subscribe(CrewLifecycleEvent, self._handler)
        evt = Event(
            event_type=CrewLifecycleEvent.STARTED,
            payload=CrewEvent(
                event_type=CrewLifecycleEvent.STARTED,
                crew_id="crew_1",
                strategy="sequential",
            ),
        )
        self.bus.publish(evt)
        self.assertEqual(len(self.received), 1)


if __name__ == "__main__":
    unittest.main()
