"""
DocAgent — 技术文档编写专家 Agent。

能力范围: 技术文档、API 文档、README 文件、设计文档、代码注释补全
"""

from src.core.base_agent import BaseAgent
from src.core.models import AgentConfig
from src.infra.config import Config
from src.tools.crew_tool import CrewTool
from src.tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from src.tools.search_tools import SearchCodeTool
from src.tools.web_tools import WebSearchTool


class DocAgent(BaseAgent):
    """
    专门处理文档编写任务的 Agent。

    能力范围: 技术文档、API 文档、README 文件、设计文档、代码注释补全
    """

    name: str = "DocAgent"
    description: str = (
        "技术文档编写专家。擅长生成 API 文档、架构设计文档、README 文件，"
        "能查阅源代码并撰写准确的技术说明，确保文档与实现一致。"
    )
    tags: list[str] = ["doc", "documentation", "readme", "api", "manual"]

    @property
    def system_prompt(self) -> str:
        """返回 DocAgent 的系统提示词。"""
        return """你是一个专业的技术文档编写 Agent。你的职责:
1. 根据代码和需求生成准确的技术文档
2. 使用清晰、简洁、结构化的语言
3. 文档采用 Markdown 格式, 遵循 GFM 规范
4. 包含代码示例和 API 参数说明 (参数名、类型、默认值、含义)
5. 先读取目标代码再写文档, 确保文档与实现一致
6. 对于大型项目, 先生成文档大纲请用户确认, 再逐步填充
7. 使用 Mermaid 语法绘制架构图/流程图 (如适用)"""

    def register_tools(self) -> None:
        """注册 DocAgent 的特有 Tool。"""
        # 基础 Tool
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())
        self.tool_manager.register(SearchCodeTool())
        self.tool_manager.register(ListFilesTool())
        self.tool_manager.register(WebSearchTool())  # 用于查找外部参考
        # Crew 编排 Tool
        self.tool_manager.register(CrewTool(agent=self))

    def __init__(
        self,
        config: Config | None = None,
        agent_config: AgentConfig | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """初始化 DocAgent, 使用中等温度以平衡准确性和表达力。"""
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.6,
                max_iterations=10,
            )
        super().__init__(name=name, description=description, config=config, agent_config=agent_config)
