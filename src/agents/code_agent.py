"""
CodeAgent — 代码编写专家 Agent。

能力范围: 代码生成、代码审查、Bug 修复、重构建议、测试生成
支持语言: Python / JavaScript / TypeScript / Go / Rust / Java 等 (由 LLM 决定)
"""

from src.core.base_agent import BaseAgent
from src.core.models import AgentConfig
from src.infra.config import Config
from src.tools.crew_tool import CrewTool
from src.tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from src.tools.search_tools import SearchCodeTool
from src.tools.shell_tools import RunShellTool


class CodeAgent(BaseAgent):
    """
    专门处理代码编写任务的 Agent。

    能力范围: 代码生成、代码审查、Bug 修复、重构建议、测试生成
    支持语言: Python / JavaScript / TypeScript / Go / Rust / Java 等 (由 LLM 决定)
    """

    name: str = "CodeAgent"
    description: str = (
        "代码编写与审查专家。擅长代码生成、代码审查、Bug 修复、重构建议和测试生成。"
        "支持多种编程语言，遵循最佳实践和设计模式。"
    )
    tags: list[str] = ["code", "programming", "debug", "refactor", "test"]

    @property
    def system_prompt(self) -> str:
        """返回 CodeAgent 的系统提示词。"""
        return """你是一个专业的代码编写 Agent。你的职责:
1. 根据用户需求编写高质量、可运行的代码
2. 遵循最佳实践和设计模式 (SOLID, DRY, KISS)
3. 代码必须包含详细注释 (注释说明 WHY 而非 WHAT)
4. 考虑错误处理和边界情况
5. 优先使用标准库和成熟的开源库
6. 在编写代码前, 先用 read_file 了解项目上下文
7. 代码生成后, 用 write_file 写入文件
8. 对于需要测试的代码, 主动生成对应的测试用例
9. 若不确定需求, 主动向用户确认而非猜测"""

    def register_tools(self) -> None:
        """注册 CodeAgent 的特有 Tool。"""
        # 基础 Tool
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())
        self.tool_manager.register(SearchCodeTool())
        self.tool_manager.register(RunShellTool(requires_confirmation=True))
        self.tool_manager.register(ListFilesTool())
        # Crew 编排 Tool — 使此 Agent 可作为 CrewLeader 发起团队协作
        self.tool_manager.register(CrewTool(agent=self))

    def __init__(
        self,
        config: Config | None = None,
        agent_config: AgentConfig | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """初始化 CodeAgent, 使用较低温度以提高代码质量。"""
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.3,
                max_iterations=15,
            )
        super().__init__(name=name, description=description, config=config, agent_config=agent_config)
