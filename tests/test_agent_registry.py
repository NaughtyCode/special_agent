"""
AgentRegistry 单元测试。

测试覆盖:
- Agent 类注册与校验
- 元数据获取
- 模块扫描注册
- Agent 匹配 (关键词 + 描述相似度)
- 已注册 Agent 列表导出
"""

import unittest
from unittest.mock import MagicMock, patch

from src.core.agent_registry import AgentRegistry, AgentNotFoundError, MatchResult
from src.core.models import AgentConfig


class _MockAgentCls:
    """模拟 Agent 类, 用于注册测试。"""
    name = "MockAgent"
    description = "A mock agent for testing purposes"
    tags = ["mock", "test"]

    def __init__(self) -> None:
        self.name = "MockAgent"


class _MockAgentPool:
    """模拟 AgentPool。"""

    def __init__(self) -> None:
        self.instances: list = []

    def acquire(self, agent_name: str, factory) -> object:
        instance = factory()
        self.instances.append(instance)
        return instance

    def release(self, agent) -> None:
        pass


class TestAgentRegistryRegistration(unittest.TestCase):
    """Agent 注册测试。"""

    def setUp(self) -> None:
        self.pool = _MockAgentPool()
        self.registry = AgentRegistry(self.pool)

    def test_register_valid_agent(self) -> None:
        """测试: 注册有效的 Agent 类。"""
        self.registry.register(_MockAgentCls)
        self.assertEqual(self.registry.agent_count, 1)

    def test_register_missing_name(self) -> None:
        """测试: 缺少 name 属性时使用类名。"""
        class NoNameAgent:
            description = "Has description"
            tags = []
        # 注册不应抛出异常 (使用类名作为 name)
        self.registry.register(NoNameAgent)
        self.assertEqual(self.registry.agent_count, 1)

    def test_register_missing_description(self) -> None:
        """测试: 缺少 description 时使用 docstring。"""
        class NoDescAgent:
            """Fallback description from docstring."""
            name = "NoDescAgent"
            tags = []
        self.registry.register(NoDescAgent)
        meta = self.registry.get_agent_meta("NoDescAgent")
        self.assertIn("Fallback", meta.description)

    def test_register_missing_both(self) -> None:
        """测试: name 和 description 都缺失时抛出。"""
        class EmptyAgent:
            __doc__ = ""
            tags = []
        with self.assertRaises(ValueError):
            self.registry.register(EmptyAgent)

    def test_register_overwrite(self) -> None:
        """测试: 重复注册覆盖前一个。"""
        self.registry.register(_MockAgentCls)

        class UpdatedAgent:
            name = "MockAgent"
            description = "Updated description"
            tags = ["updated"]

        self.registry.register(UpdatedAgent)
        meta = self.registry.get_agent_meta("MockAgent")
        self.assertEqual(meta.description, "Updated description")


class TestAgentRegistryLookup(unittest.TestCase):
    """Agent 查找测试。"""

    def setUp(self) -> None:
        self.pool = _MockAgentPool()
        self.registry = AgentRegistry(self.pool)
        self.registry.register(_MockAgentCls)

    def test_get_agent_meta(self) -> None:
        """测试: 获取 Agent 元数据。"""
        meta = self.registry.get_agent_meta("MockAgent")
        self.assertEqual(meta.name, "MockAgent")
        self.assertEqual(meta.description, "A mock agent for testing purposes")
        self.assertEqual(meta.tags, ["mock", "test"])

    def test_get_agent_meta_not_found(self) -> None:
        """测试: 获取不存在 Agent 的元数据时抛出。"""
        with self.assertRaises(AgentNotFoundError):
            self.registry.get_agent_meta("NonExistent")

    def test_get_agent(self) -> None:
        """测试: 通过 AgentPool 获取 Agent 实例。"""
        agent = self.registry.get_agent("MockAgent")
        self.assertIsNotNone(agent)
        self.assertEqual(agent.name, "MockAgent")  # type: ignore[union-attr]

    def test_get_agent_not_found(self) -> None:
        """测试: 获取不存在的 Agent 返回 None。"""
        agent = self.registry.get_agent("NonExistent")
        self.assertIsNone(agent)


class TestAgentRegistryMatch(unittest.TestCase):
    """Agent 匹配测试。"""

    def setUp(self) -> None:
        self.pool = _MockAgentPool()
        self.registry = AgentRegistry(self.pool)

        # 注册几种不同的 Agent
        class CodeAgentCls:
            name = "CodeAgent"
            description = "Handles code writing, debugging, refactoring and testing tasks"
            tags = ["code", "programming", "debug", "refactor", "test"]

        class DocAgentCls:
            name = "DocAgent"
            description = "Handles documentation, README, API docs and manual writing"
            tags = ["doc", "documentation", "readme", "api", "manual"]

        class SearchAgentCls:
            name = "SearchAgent"
            description = "Handles searching, finding files and researching information"
            tags = ["search", "查找", "研究", "research", "信息"]

        self.registry.register(CodeAgentCls)
        self.registry.register(DocAgentCls)
        self.registry.register(SearchAgentCls)

    def test_match_by_keyword_code(self) -> None:
        """测试: 关键词匹配到 CodeAgent。"""
        result = self.registry.match_agent("帮我写一段 Python 代码实现排序功能")
        self.assertEqual(result.agent_name, "CodeAgent")
        self.assertEqual(result.strategy_used, "keyword")

    def test_match_by_keyword_doc(self) -> None:
        """测试: 关键词匹配到 DocAgent。"""
        result = self.registry.match_agent("为这个项目写一个 README 文档")
        self.assertEqual(result.agent_name, "DocAgent")
        self.assertEqual(result.strategy_used, "keyword")

    def test_match_by_keyword_search(self) -> None:
        """测试: 关键词匹配到 SearchAgent。"""
        result = self.registry.match_agent("帮我搜索和查找项目中的文件信息")
        self.assertEqual(result.agent_name, "SearchAgent")
        self.assertEqual(result.strategy_used, "keyword")

    def test_match_by_description_similarity(self) -> None:
        """测试: 关键词未命中时通过描述相似度匹配。"""
        result = self.registry.match_agent("help me handle writing tasks")
        self.assertIsNotNone(result.agent_name)
        # "writing" 出现在 DocAgent 描述中, 通过描述相似度匹配
        self.assertEqual(result.strategy_used, "description_similarity")

    def test_match_no_agents_registered(self) -> None:
        """测试: 无 Agent 注册时返回空结果。"""
        empty_registry = AgentRegistry(_MockAgentPool())
        result = empty_registry.match_agent("any task")
        self.assertIsNone(result.agent_name)
        self.assertEqual(result.strategy_used, "none")

    def test_match_no_relevant_agent(self) -> None:
        """测试: 没有匹配的 Agent 时返回空结果。"""
        result = self.registry.match_agent("xyzzy")
        # 既不命中关键词也不命中描述相似度
        # 返回空 MatchResult
        self.assertEqual(result.strategy_used, "none")


class TestAgentRegistryExport(unittest.TestCase):
    """Agent 导出功能测试。"""

    def setUp(self) -> None:
        self.pool = _MockAgentPool()
        self.registry = AgentRegistry(self.pool)
        self.registry.register(_MockAgentCls)

    def test_list_agents(self) -> None:
        """测试: list_agents 返回元数据列表。"""
        agents = self.registry.list_agents()
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].name, "MockAgent")

    def test_get_agent_tools_schema(self) -> None:
        """测试: 将 Agent 转换为 Function Calling Schema。"""
        schemas = self.registry.get_agent_tools_schema()
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["type"], "function")
        self.assertIn("launch_MockAgent", schemas[0]["function"]["name"])

    def test_agent_count(self) -> None:
        """测试: agent_count 属性。"""
        self.assertEqual(self.registry.agent_count, 1)


if __name__ == "__main__":
    unittest.main()
