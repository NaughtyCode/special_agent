"""
示例插件 Agent — 展示如何创建自定义 Agent 并注册到框架。

将此文件放入 plugins/ 目录 (或 Config.plugin_directories 指定的目录),
RootAgent 将自动发现并加载此 Agent。

使用方式:
1. 继承 BaseAgent
2. 设置 name, description, tags 类属性
3. 实现 system_prompt 属性 (定义 Agent 的行为规范)
4. 实现 register_tools() 方法 (注册 Agent 需要的 Tool)
5. 将 .py 文件放入 plugins/ 目录

框架会在启动时自动发现并注册此 Agent。
"""

from src.core.base_agent import BaseAgent
from src.core.models import AgentConfig
from src.infra.config import Config
from src.tools.crew_tool import CrewTool
from src.tools.file_tools import ReadFileTool, WriteFileTool, ListFilesTool
from src.tools.search_tools import SearchCodeTool


class ExamplePluginAgent(BaseAgent):
    """
    示例插件 Agent — 展示如何扩展框架。

    此 Agent 作为模板, 展示自定义 Agent 的最小实现。
    复制此文件并根据你的领域需求修改。
    """

    # ── 标识 (必须设置) ──
    name: str = "ExamplePluginAgent"
    description: str = (
        "示例插件 Agent — 展示如何创建自定义 Agent。"
        "可根据具体领域替换为实际功能描述。"
    )
    tags: list[str] = ["example", "plugin", "template"]

    @property
    def system_prompt(self) -> str:
        """定义 Agent 的行为规范 — 这是 Agent 的核心。"""
        return """你是一个示例插件 Agent。你的职责:
1. 处理你所在领域的专业任务
2. 使用注册的 Tool 完成工作
3. 遵循 ReAct 推理格式: Thought → Action → Observation
4. 当有足够信息时给出 Final Answer
5. 若不理解任务, 诚实告知并请求澄清"""

    def register_tools(self) -> None:
        """注册此 Agent 需要的 Tool。"""
        # 注册基础 Tool — 根据需要选择
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())
        self.tool_manager.register(ListFilesTool())
        self.tool_manager.register(SearchCodeTool())

        # 注册 CrewTool — 使此 Agent 可作为 CrewLeader 发起团队协作
        # 若此 Agent 不需要领导团队, 可移除此行
        self.tool_manager.register(CrewTool(agent=self))

    def __init__(
        self,
        config: Config | None = None,
        agent_config: AgentConfig | None = None,
    ) -> None:
        """初始化插件 Agent, 可自定义默认配置。"""
        if agent_config is None:
            agent_config = AgentConfig(
                max_iterations=10,
                llm_temperature_override=0.5,
            )
        super().__init__(config=config, agent_config=agent_config)
