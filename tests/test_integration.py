"""
集成测试 — 验证各组件协同工作。

测试覆盖:
- Config → LLMClient 集成
- BaseAgent 完整启动流程 (使用 Mock Provider)
- Tool 注册与执行端到端
- ReActEngine 完整循环 (使用 Mock LLM)
- CrewOrchestrator 任务分解 (使用 Mock LLM)
- SessionManager 多会话管理
- EventBus 端到端事件流
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock

from src.core.models import (
    AgentConfig,
    AgentResult,
    AgentState,
    ChatResponse,
    ExecutionStrategy,
    FinishReason,
    Message,
    ReActStep,
    TokenUsage,
    ToolCall,
)
from src.infra.config import Config
from src.events.event_bus import EventBus
from src.events.events import AgentLifecycleEvent, Event
from src.core.tool_manager import ToolManager
from src.tools.base_tool import BaseTool, ToolResult


# ── 测试用 Mock Tool ─────────────────────────────────


class _EchoTool(BaseTool):
    """简单的 Echo Tool — 返回入参。"""
    name: str = "echo"
    description: str = "Echo back the input message"
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Message to echo"},
        },
        "required": ["message"],
    }
    tags: list[str] = ["test"]

    def execute(self, **kwargs) -> ToolResult:
        msg = kwargs.get("message", "")
        return ToolResult(success=True, output=f"Echo: {msg}", data={"msg": msg})


# ── 测试用 Mock Agent ────────────────────────────────


class _MockLLMClient:
    """模拟 LLMClient — 返回预设的 ChatResponse。"""

    def __init__(self, responses: list[ChatResponse] | None = None) -> None:
        self.responses = responses or []
        self.call_count = 0
        self.last_messages: list[Message] = []
        self.token_tracker = MagicMock()

    def chat(self, messages, tools=None, tool_choice="auto", model=None, temperature=None) -> ChatResponse:
        self.call_count += 1
        self.last_messages = messages
        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]
        # 默认返回 Final Answer
        return ChatResponse(content="Final answer from mock")

    def get_token_usage(self):
        return TokenUsage()

    def reset_token_usage(self):
        pass


# ── 集成测试 ─────────────────────────────────────────


class TestConfigIntegration(unittest.TestCase):
    """Config 端到端测试。"""

    def test_from_env_full_flow(self) -> None:
        """测试: 完整的环境变量 → Config 流程。"""
        import os

        saved = {}
        for key in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
                     "AGENT_MAX_ITERATIONS", "API_TIMEOUT_MS"):
            saved[key] = os.environ.get(key)
            if key in os.environ:
                del os.environ[key]

        try:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = "sk-test"
            os.environ["ANTHROPIC_BASE_URL"] = "https://api.test.com"
            os.environ["ANTHROPIC_MODEL"] = "test-model"
            os.environ["AGENT_MAX_ITERATIONS"] = "5"

            config = Config.from_env()
            config.validate()

            self.assertEqual(config.llm_api_key, "sk-test")
            self.assertEqual(config.agent_max_iterations, 5)
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value
                elif key in os.environ:
                    del os.environ[key]


class TestToolManagerIntegration(unittest.TestCase):
    """Tool 管理端到端测试。"""

    def test_register_and_execute_echo(self) -> None:
        """测试: 注册 EchoTool 并执行。"""
        manager = ToolManager()
        tool = _EchoTool()
        manager.register(tool)

        result = manager.execute("echo", message="Hello World")
        self.assertTrue(result.success)
        self.assertIn("Hello World", result.output)
        self.assertGreater(result.duration_ms, 0)

    def test_register_and_list_tools(self) -> None:
        """测试: 注册多个 Tool 并获取 Schema 列表。"""
        manager = ToolManager()
        manager.register(_EchoTool())

        tools_list = manager.list_tools()
        self.assertEqual(len(tools_list), 1)
        self.assertEqual(tools_list[0]["type"], "function")

    def test_execute_unregistered_tool_raises(self) -> None:
        """测试: 执行未注册 Tool 抛出异常。"""
        manager = ToolManager()
        from src.core.models import ToolNotFoundError
        with self.assertRaises(ToolNotFoundError):
            manager.execute("not_registered")


class TestEventBusIntegration(unittest.TestCase):
    """EventBus 端到端测试。"""

    def test_agent_lifecycle_event_flow(self) -> None:
        """测试: Agent 生命周期事件流。"""
        bus = EventBus()
        events: list[str] = []

        def track(event: Event) -> None:
            events.append(event.event_type.value)

        bus.subscribe(AgentLifecycleEvent, track)

        bus.publish(Event(event_type=AgentLifecycleEvent.INITIALIZED))
        bus.publish(Event(event_type=AgentLifecycleEvent.STARTED))
        bus.publish(Event(event_type=AgentLifecycleEvent.COMPLETED))

        self.assertEqual(events, ["initialized", "started", "completed"])

    def test_multiple_event_types(self) -> None:
        """测试: 多个事件类型独立订阅。"""
        from src.events.events import ToolCallEvent

        bus = EventBus()
        agent_events: list[str] = []
        tool_events: list[str] = []

        bus.subscribe(AgentLifecycleEvent, lambda e: agent_events.append(e.event_type.value))
        bus.subscribe(ToolCallEvent, lambda e: tool_events.append(e.event_type.value))

        bus.publish(Event(event_type=AgentLifecycleEvent.STARTED))
        bus.publish(Event(event_type=ToolCallEvent.BEFORE_EXECUTE))

        self.assertEqual(len(agent_events), 1)
        self.assertEqual(len(tool_events), 1)


class TestReActEngineIntegration(unittest.TestCase):
    """ReActEngine 集成测试 — 使用 Mock LLM。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.config.agent_max_iterations = 3

        self.tool_manager = ToolManager()
        self.tool_manager.register(_EchoTool())

        from src.core.agent_registry import AgentRegistry
        from src.core.agent_pool import AgentPool
        from src.core.context_store import ContextStore

        self.agent_pool = AgentPool()
        self.agent_registry = AgentRegistry(self.agent_pool)
        self.context_store = ContextStore(self.config)
        self.event_bus = EventBus()

    def test_react_engine_final_answer_immediate(self) -> None:
        """测试: LLM 直接返回 Final Answer (单次迭代)。"""
        from src.core.react_engine import ReActEngine

        llm_client = _MockLLMClient(responses=[
            ChatResponse(content="The answer is 42", model="test"),
        ])

        engine = ReActEngine(
            llm_client=llm_client,
            tool_manager=self.tool_manager,
            agent_registry=self.agent_registry,
            context_store=self.context_store,
            event_bus=self.event_bus,
            config=self.config,
        )

        system_msg = Message(role="system", content="You are helpful.")
        result = engine.run(system_msg, "What is the answer?")

        self.assertEqual(result.finish_reason, FinishReason.DONE)
        self.assertIn("42", result.final_answer)
        self.assertEqual(llm_client.call_count, 1)

    def test_react_engine_with_tool_call(self) -> None:
        """测试: LLM 调用 Tool 后给出 Final Answer (二次迭代)。"""
        from src.core.react_engine import ReActEngine

        tc = ToolCall(id="c1", function_name="echo", function_args={"message": "hello"})
        llm_client = _MockLLMClient(responses=[
            ChatResponse(content="Let me echo", tool_calls=[tc], model="test"),
            ChatResponse(content="Echo completed successfully", model="test"),
        ])

        engine = ReActEngine(
            llm_client=llm_client,
            tool_manager=self.tool_manager,
            agent_registry=self.agent_registry,
            context_store=self.context_store,
            event_bus=self.event_bus,
            config=self.config,
        )

        system_msg = Message(role="system", content="You are helpful.")
        result = engine.run(system_msg, "Say hello")

        self.assertEqual(llm_client.call_count, 2)
        self.assertEqual(len(result.trajectory), 2)

    def test_react_engine_max_iterations(self) -> None:
        """测试: 达到最大迭代次数后强制终止。"""
        from src.core.react_engine import ReActEngine

        tc = ToolCall(id="c1", function_name="echo", function_args={"message": "test"})
        # 总是返回 action (永不返回 Final Answer)
        responses = [ChatResponse(content="Let me try", tool_calls=[tc], model="test")] * 5
        llm_client = _MockLLMClient(responses=responses)

        engine = ReActEngine(
            llm_client=llm_client,
            tool_manager=self.tool_manager,
            agent_registry=self.agent_registry,
            context_store=self.context_store,
            event_bus=self.event_bus,
            config=self.config,
        )

        system_msg = Message(role="system", content="You are helpful.")
        result = engine.run(system_msg, "Do something")

        self.assertEqual(result.finish_reason, FinishReason.MAX_ITERATIONS)
        self.assertEqual(len(result.trajectory), 3)  # max_iterations=3


class TestSessionManagerIntegration(unittest.TestCase):
    """SessionManager 集成测试。"""

    def setUp(self) -> None:
        import os
        self._saved_auth = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "test-key"

    def tearDown(self) -> None:
        import os
        if self._saved_auth is not None:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = self._saved_auth
        elif "ANTHROPIC_AUTH_TOKEN" in os.environ:
            del os.environ["ANTHROPIC_AUTH_TOKEN"]

    def test_create_and_switch_session(self) -> None:
        """测试: 创建会话并切换。"""
        from src.core.session_manager import SessionManager

        mgr = SessionManager()
        s1 = mgr.create_session(name="Session 1")
        s2 = mgr.create_session(name="Session 2")

        self.assertEqual(mgr.session_count, 2)

        current = mgr.get_current_session()
        self.assertEqual(current.session_id, s2.session_id)

        switched = mgr.switch_session(s1.session_id)
        self.assertEqual(switched.session_id, s1.session_id)

    def test_delete_session(self) -> None:
        """测试: 删除非当前会话。"""
        from src.core.session_manager import SessionManager

        mgr = SessionManager()
        s1 = mgr.create_session(name="S1")
        s2 = mgr.create_session(name="S2")

        mgr.switch_session(s1.session_id)
        mgr.delete_session(s2.session_id)
        self.assertEqual(mgr.session_count, 1)

    def test_delete_current_session_raises(self) -> None:
        """测试: 删除当前会话抛出异常。"""
        from src.core.session_manager import SessionManager

        mgr = SessionManager()
        s = mgr.create_session(name="Only")
        with self.assertRaises(ValueError):
            mgr.delete_session(s.session_id)

    def test_clear_current_session(self) -> None:
        """测试: 清除当前会话上下文。"""
        from src.core.session_manager import SessionManager

        mgr = SessionManager()
        session = mgr.create_session(name="Test")
        session.context_store.add_message(role="user", content="Hello")
        session.token_usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)

        mgr.clear_current_session()
        # 上下文被清除 (只有 system message 保留)
        msgs = session.context_store.get_messages()
        self.assertEqual(len(msgs), 0)  # 没有 system message

    def test_export_import_session(self) -> None:
        """测试: 导出导入会话。"""
        from src.core.session_manager import SessionManager

        mgr = SessionManager()
        session = mgr.create_session(name="ExportTest")
        session.context_store.add_message(role="user", content="Test content")
        session.token_usage = TokenUsage(prompt_tokens=50, completion_tokens=25, total_tokens=75)

        exported = mgr.export_session(session.session_id)
        imported = mgr.import_session(exported)

        self.assertEqual(imported.name, "ExportTest")
        msgs = imported.context_store.get_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "Test content")


class TestCrewOrchestratorIntegration(unittest.TestCase):
    """CrewOrchestrator 集成测试 — 使用 Mock LLM。"""

    def setUp(self) -> None:
        self.config = Config()
        self.config.llm_api_key = "test-key"
        self.config.crew_max_parallel = 2

        from src.core.agent_pool import AgentPool
        from src.core.agent_registry import AgentRegistry

        self.agent_pool = AgentPool()
        self.agent_registry = AgentRegistry(self.agent_pool)
        self.event_bus = EventBus()

    def test_execute_sequential_with_mock(self) -> None:
        """测试: 任务分解并匹配 Agent (使用 Mock, 验证 plan_crew 基本流程)。"""
        from src.crew.orchestrator import CrewOrchestrator
        from src.crew.models import AgentCrew, CrewMember, SubTask

        # 注册一个 Agent
        class MockAgentCls:
            name = "MockAgent"
            description = "A mock agent for testing purposes"
            tags = ["test", "mock"]

        self.agent_registry.register(MockAgentCls)

        # 构建模拟响应 — required_tags 使用已注册 Agent 的 tags
        llm_client = _MockLLMClient(responses=[
            ChatResponse(
                content='[{"description": "Do test task", "required_tags": ["test"], "dependencies": []}]',
                model="test",
            ),
        ])

        orchestrator = CrewOrchestrator(
            agent_registry=self.agent_registry,
            agent_pool=self.agent_pool,
            llm_client=llm_client,
            event_bus=self.event_bus,
            config=self.config,
        )

        crew = orchestrator.plan_crew(
            mission="Test mission",
            lead_agent_name="TestLeader",
        )

        self.assertEqual(crew.status, "ASSEMBLED")
        self.assertEqual(len(crew.members), 1)


if __name__ == "__main__":
    unittest.main()
