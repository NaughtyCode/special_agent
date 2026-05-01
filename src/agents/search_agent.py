"""
SearchAgent — 信息搜索专家 Agent。

能力范围: 代码搜索、网页搜索、信息检索、知识查询、资料收集
"""

from src.core.base_agent import BaseAgent
from src.core.models import AgentConfig
from src.infra.config import Config
from src.tools.crew_tool import CrewTool
from src.tools.file_tools import ListFilesTool, ReadFileTool
from src.tools.search_tools import SearchCodeTool
from src.tools.web_tools import WebFetchTool, WebSearchTool


class SearchAgent(BaseAgent):
    """
    专门处理信息搜索任务的 Agent。

    能力范围: 代码搜索、网页搜索、信息检索、知识查询、资料收集
    """

    name: str = "SearchAgent"
    description: str = (
        "信息搜索专家。擅长代码库搜索、网页信息检索、知识查询，"
        "能快速定位关键信息和代码位置，并将结果整理为结构化报告。"
    )
    tags: list[str] = ["search", "find", "query", "lookup", "research"]

    @property
    def system_prompt(self) -> str:
        """返回 SearchAgent 的系统提示词。"""
        return """你是一个专业的信息搜索 Agent。你的职责:
1. 快速准确地定位用户需要的信息
2. 在代码库中搜索特定模式或符号 (使用 search_code)
3. 必要时搜索互联网获取最新信息 (使用 web_search + web_fetch)
4. 将搜索结果整理为清晰的结构化报告 (分类/去重/按相关性排序)
5. 对于模糊的搜索需求, 先确认搜索范围再执行"""

    def register_tools(self) -> None:
        """注册 SearchAgent 的特有 Tool。"""
        # 基础 Tool
        self.tool_manager.register(SearchCodeTool())
        self.tool_manager.register(WebSearchTool())
        self.tool_manager.register(WebFetchTool())
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(ListFilesTool())
        # Crew 编排 Tool
        self.tool_manager.register(CrewTool(agent=self))

    def __init__(
        self,
        config: Config | None = None,
        agent_config: AgentConfig | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """初始化 SearchAgent, 使用较低温度提高搜索精确度。"""
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.4,
                max_iterations=8,
            )
        super().__init__(name=name, description=description, config=config, agent_config=agent_config)
