"""
Agent 插件加载器 — 从指定目录动态发现并加载 BaseAgent 子类。

支持:
- 目录扫描: 递归扫描指定目录下的 .py 文件
- 入口点: 通过 Python entry_points 发现插件
- 隔离加载: 每个插件在独立命名空间中加载
- 错误隔离: 单个插件加载失败不影响其他插件
"""

import importlib
import importlib.util
import inspect
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)


class AgentPluginLoader:
    """
    Agent 插件加载器 — 从指定目录动态发现并加载 BaseAgent 子类。

    支持:
    - 目录扫描: 递归扫描指定目录下的 .py 文件
    - 入口点: 通过 Python entry_points 发现插件
    - 隔离加载: 每个插件在独立命名空间中加载
    - 错误隔离: 单个插件加载失败不影响其他插件
    """

    def __init__(self, plugin_directories: list[str]) -> None:
        """
        初始化插件加载器。

        Args:
            plugin_directories: 插件目录列表 (绝对路径)
        """
        self._plugin_directories = plugin_directories
        self._loaded_modules: list[str] = []

    def discover(self) -> list[type]:
        """
        发现所有可用插件 Agent 类。

        1. 扫描每个 plugin_directory 下的 .py 文件
        2. 动态导入模块
        3. 查找 BaseAgent 子类
        4. 校验插件

        Returns:
            加载成功的 Agent 类列表
        """
        from src.core.base_agent import BaseAgent

        agent_classes: list[type] = []

        # 方法 1: 目录扫描
        for directory in self._plugin_directories:
            if not os.path.isdir(directory):
                logger.warning(f"插件目录不存在: {directory}")
                continue

            for root, _dirs, files in os.walk(directory):
                for filename in files:
                    if not filename.endswith(".py") or filename.startswith("_"):
                        continue

                    filepath = os.path.join(root, filename)
                    try:
                        discovered = self._load_from_file(filepath, BaseAgent)
                        agent_classes.extend(discovered)
                    except Exception as e:
                        logger.warning(f"加载插件失败 '{filepath}': {e}")

        # 方法 2: entry_points (可选)
        try:
            from importlib.metadata import entry_points

            eps = entry_points(group="specialagent.plugins")
            for ep in eps:
                try:
                    agent_cls = ep.load()
                    if self.validate_plugin(agent_cls):
                        agent_classes.append(agent_cls)
                        logger.info(f"Loaded plugin via entry_point: {ep.name}")
                except Exception as e:
                    logger.warning(f"加载 entry_point 插件 '{ep.name}' 失败: {e}")
        except Exception:
            pass  # entry_points 不可用

        logger.info(f"Discovered {len(agent_classes)} plugin Agent classes")
        return agent_classes

    def _load_from_file(self, filepath: str, base_cls: type) -> list[type]:
        """
        从单个 .py 文件加载 BaseAgent 子类。

        Args:
            filepath: .py 文件路径
            base_cls: BaseAgent 基类

        Returns:
            加载成功的 Agent 类列表
        """
        # 生成唯一模块名
        mod_name = f"_plugin_{os.path.basename(filepath).replace('.py', '')}_{hash(filepath) % 100000}"
        mod_name = mod_name.replace("-", "_").replace(" ", "_")

        # 动态加载模块
        spec = importlib.util.spec_from_file_location(mod_name, filepath)
        if spec is None or spec.loader is None:
            logger.warning(f"无法创建模块 spec: {filepath}")
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module

        try:
            spec.loader.exec_module(module)
            self._loaded_modules.append(mod_name)
        except Exception as e:
            logger.error(f"执行模块 '{mod_name}' 失败: {e}")
            del sys.modules[mod_name]
            return []

        # 查找 BaseAgent 子类
        agent_classes: list[type] = []
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, base_cls) and obj is not base_cls:
                if self.validate_plugin(obj):
                    agent_classes.append(obj)
                    logger.info(f"Discovered plugin Agent: {obj.__name__} from {filepath}")

        return agent_classes

    def validate_plugin(self, agent_cls: type) -> bool:
        """
        校验插件 Agent:
        - 必须继承自 BaseAgent
        - 必须有非空的 name 和 description
        - system_prompt 和 register_tools 必须已实现

        Args:
            agent_cls: 待校验的 Agent 类

        Returns:
            bool: 是否通过校验
        """
        from src.core.base_agent import BaseAgent

        if not issubclass(agent_cls, BaseAgent):
            logger.warning(f"'{agent_cls.__name__}' 不是 BaseAgent 子类")
            return False

        # 检查 name
        name = getattr(agent_cls, "name", None)
        if not name:
            logger.warning(f"'{agent_cls.__name__}' 缺少 'name' 属性")
            return False

        # 检查 description
        description = getattr(agent_cls, "description", None)
        if not description:
            logger.warning(f"'{agent_cls.__name__}' 缺少 'description' 属性")
            return False

        # 检查 system_prompt (不被基类的 @abstractmethod 覆盖即可)
        if "system_prompt" not in agent_cls.__dict__:
            logger.warning(f"'{agent_cls.__name__}' 未覆写 'system_prompt'")
            return False

        # 检查 register_tools (不被基类的 @abstractmethod 覆盖即可)
        if "register_tools" not in agent_cls.__dict__:
            logger.warning(f"'{agent_cls.__name__}' 未覆写 'register_tools'")
            return False

        return True
