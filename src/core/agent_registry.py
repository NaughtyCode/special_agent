"""
Agent 注册中心 — 管理特化 Agent 的注册、发现和实例化。

核心设计: Agent 本身作为一种特殊的 Tool 存在:
- Tool 名称 = Agent 名称
- Tool 描述 = Agent 的 description
- Tool "执行" = 从 AgentPool 获取实例并 run()

支持外部 Agent 插件动态加载 (通过 entry_points 或指定目录扫描)。
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class AgentNotFoundError(Exception):
    """Agent 未找到时抛出。"""
    pass


@dataclass
class AgentMeta:
    """Agent 元数据 — 由 AgentRegistry 缓存, 供 AgentTool 等消费。"""
    name: str  # Agent 名称
    description: str  # Agent 功能描述
    tags: list[str]  # 标签列表
    agent_cls: type  # Agent 类引用


@dataclass
class MatchResult:
    """Tool/Agent 匹配结果。"""
    tool_name: str | None = None  # 匹配到的 Tool 名称 (Tool 匹配时)
    agent_name: str | None = None  # 匹配到的 Agent 名称 (Agent 匹配时)
    score: float = 0.0  # 匹配得分 (0-1)
    strategy_used: str = ""  # 使用的匹配策略名称
    candidates: list[str] = None  # type: ignore  # 其他候选名称

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []


class AgentRegistry:
    """
    Agent 注册中心 — 管理特化 Agent 的注册、发现和实例化。

    核心设计: Agent 本身作为一种特殊的 Tool 存在:
    - Tool 名称 = Agent 名称
    - Tool 描述 = Agent 的 description
    - Tool "执行" = 从 AgentPool 获取实例并 run()

    支持外部 Agent 插件动态加载 (通过 entry_points 或指定目录扫描)。
    """

    def __init__(self, agent_pool: Any) -> None:
        """
        初始化 Agent 注册中心。

        Args:
            agent_pool: AgentPool 实例, 用于 Agent 实例管理
        """
        self._agent_classes: dict[str, type] = {}  # {name: AgentClass}
        self._agent_metas: dict[str, AgentMeta] = {}  # {name: AgentMeta}
        self._agent_pool = agent_pool

    # ── 注册 ─────────────────────────────────────────

    def register(self, agent_cls: type) -> None:
        """
        注册一个 Agent 类 (非实例)。

        注册时自动校验:
        - 必须继承自 BaseAgent
        - name 属性必须非空且不冲突
        - description 属性必须非空

        Args:
            agent_cls: Agent 类 (必须继承自 BaseAgent)
        """
        # 获取 Agent 元信息 (从类属性)
        name = getattr(agent_cls, "name", None) or agent_cls.__name__
        description = getattr(agent_cls, "description", "") or agent_cls.__doc__ or ""
        tags = list(getattr(agent_cls, "tags", []) or [])

        if not name:
            raise ValueError(f"Agent 类 '{agent_cls.__name__}' 必须定义 'name' 属性")

        if not description:
            raise ValueError(f"Agent 类 '{agent_cls.__name__}' 必须定义 'description' 属性")

        if name in self._agent_classes:
            logger.warning(f"Agent '{name}' 已注册, 将被覆盖")

        self._agent_classes[name] = agent_cls
        self._agent_metas[name] = AgentMeta(
            name=name,
            description=description,
            tags=tags,
            agent_cls=agent_cls,
        )
        logger.info(f"Registered agent: {name} (tags={tags})")

    def get_agent_meta(self, agent_name: str) -> AgentMeta:
        """
        获取 Agent 的元数据 (不创建实例)。

        Args:
            agent_name: Agent 名称

        Returns:
            AgentMeta 包含 name, description, tags, agent_cls

        Raises:
            AgentNotFoundError: 若 Agent 未注册
        """
        meta = self._agent_metas.get(agent_name)
        if meta is None:
            raise AgentNotFoundError(f"Agent '{agent_name}' 未注册")
        return meta

    def register_from_module(self, module_path: str) -> int:
        """
        从指定模块路径扫描并注册所有 BaseAgent 子类。

        动态导入模块, 查找所有 BaseAgent 的子类并注册。

        Args:
            module_path: 模块的导入路径 (如 "plugins.my_agent")

        Returns:
            注册的 Agent 数量
        """
        import importlib
        import inspect

        from src.core.base_agent import BaseAgent

        try:
            module = importlib.import_module(module_path)
        except ImportError as e:
            logger.error(f"无法导入模块 '{module_path}': {e}")
            return 0

        count = 0
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseAgent) and obj is not BaseAgent:
                try:
                    self.register(obj)
                    count += 1
                except Exception as e:
                    logger.warning(f"注册 Agent '{name}' 失败: {e}")

        logger.info(f"从模块 '{module_path}' 注册了 {count} 个 Agent")
        return count

    # ── 查找与匹配 ───────────────────────────────────

    def get_agent(self, agent_name: str) -> Any | None:
        """
        按名称获取 Agent 实例 (通过 AgentPool)。

        Args:
            agent_name: Agent 名称

        Returns:
            Agent 实例或 None
        """
        meta = self._agent_metas.get(agent_name)
        if meta is None:
            return None

        # 通过 AgentPool 获取实例
        def factory() -> Any:
            return meta.agent_cls()

        try:
            return self._agent_pool.acquire(agent_name, factory)
        except Exception as e:
            logger.error(f"获取 Agent '{agent_name}' 实例失败: {e}")
            return None

    def match_agent(self, task: str) -> MatchResult:
        """
        根据任务描述匹配最合适的特化 Agent。

        匹配策略 (可配置):
        1. 关键词匹配: 预定义的关键词 → Agent 映射表
        2. 描述相似度: TF-IDF / 嵌入相似度比对各 Agent 的 description

        Args:
            task: 任务描述文本

        Returns:
            MatchResult 包含匹配的 agent_name, score, strategy_used
        """
        import re

        task_lower = task.lower()

        # 策略 1: 关键词匹配 (快速路径)
        keyword_map: dict[str, list[str]] = {
            "CodeAgent": ["code", "代码", "写", "编程", "bug", "fix", "refactor", "test", "测试", "实现", "开发"],
            "DocAgent": ["doc", "文档", "readme", "说明", "api 文档", "注释", "manual", "手册"],
            "SearchAgent": ["搜索", "查找", "search", "find", "query", "查询", "研究", "research", "信息", "资料"],
            "ShellAgent": ["shell", "运行", "执行", "命令", "command", "run", "execute", "系统", "环境", "terminal"],
        }

        best_score = 0.0
        best_agent: str | None = None

        for agent_name, keywords in keyword_map.items():
            if agent_name not in self._agent_metas:
                continue
            score = sum(2.0 if kw in task_lower else 0 for kw in keywords)
            score = score / max(len(keywords), 1)
            if score > best_score:
                best_score = score
                best_agent = agent_name

        if best_score >= 0.1 and best_agent:
            return MatchResult(
                agent_name=best_agent,
                score=best_score,
                strategy_used="keyword",
            )

        # 策略 2: 描述相似度 (TF-IDF 风格)
        task_tokens = set(re.findall(r"[a-zA-Z0-9一-鿿]+", task_lower))
        for agent_name, meta in self._agent_metas.items():
            desc_tokens = set(re.findall(r"[a-zA-Z0-9一-鿿]+", meta.description.lower()))
            tag_tokens = set()
            for tag in meta.tags:
                tag_tokens.update(re.findall(r"[a-zA-Z0-9一-鿿]+", tag.lower()))

            all_agent_tokens = desc_tokens | tag_tokens
            if not all_agent_tokens:
                continue

            overlap = len(task_tokens & all_agent_tokens)
            score = overlap / len(task_tokens) if task_tokens else 0

            if score > best_score:
                best_score = score
                best_agent = agent_name

        if best_score >= 0.2 and best_agent:
            return MatchResult(
                agent_name=best_agent,
                score=best_score,
                strategy_used="description_similarity",
            )

        return MatchResult(strategy_used="none")

    # ── 拉起 Agent ───────────────────────────────────

    def launch(self, agent_name: str, task: str, context: dict | None = None) -> Any:
        """
        拉起指定 Agent 执行子任务:
        1. 从 AgentPool 获取或创建 Agent 实例
        2. 构建 AgentConfig (继承父 Agent 配置, call_depth + 1)
        3. 触发 AgentLifecycleEvent.SPAWNED
        4. 调用 agent.run(task, context)
        5. 触发 AgentLifecycleEvent.COMPLETED / FAILED
        6. 归还实例到 AgentPool

        Args:
            agent_name: Agent 名称
            task: 子任务描述
            context: 可选的上下文信息

        Returns:
            AgentResult 执行结果

        Raises:
            AgentNotFoundError: 若 Agent 未注册
        """
        meta = self._agent_metas.get(agent_name)
        if meta is None:
            raise AgentNotFoundError(f"Agent '{agent_name}' 未注册")

        # 构建工厂函数
        def factory() -> Any:
            return meta.agent_cls()

        # 从池中获取实例
        agent = self._agent_pool.acquire(agent_name, factory)

        try:
            # 执行子任务
            result = agent.run(task, context)
            return result
        finally:
            # 归还实例
            self._agent_pool.release(agent)

    # ── 导出 ─────────────────────────────────────────

    def list_agents(self) -> list[AgentMeta]:
        """
        返回所有注册 Agent 的元数据列表 (用于 Prompt 构建和 Crew 任务分解)。

        Returns:
            AgentMeta 列表
        """
        return list(self._agent_metas.values())

    def get_agent_tools_schema(self) -> list[dict]:
        """
        将所有注册 Agent 转换为 Function Calling Schema 格式。

        Returns:
            Tool Schema 列表
        """
        schemas: list[dict] = []
        for name, meta in self._agent_metas.items():
            schemas.append({
                "type": "function",
                "function": {
                    "name": f"launch_{name}",
                    "description": f"拉起 {name}: {meta.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": f"分配给 {name} 的子任务描述",
                            },
                            "context": {
                                "type": "object",
                                "description": "可选的上下文信息",
                            },
                        },
                        "required": ["task"],
                    },
                },
            })
        return schemas

    @property
    def agent_count(self) -> int:
        """获取已注册 Agent 数量。"""
        return len(self._agent_classes)
