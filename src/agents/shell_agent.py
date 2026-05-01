"""
ShellAgent — Shell 命令执行专家 Agent。

能力范围: Shell 命令执行、环境检查、文件操作、进程管理、系统诊断
"""

from src.core.base_agent import BaseAgent
from src.core.models import AgentConfig
from src.infra.config import Config
from src.tools.crew_tool import CrewTool
from src.tools.file_tools import ListFilesTool, ReadFileTool, WriteFileTool
from src.tools.shell_tools import RunShellTool


class ShellAgent(BaseAgent):
    """
    专门处理 Shell 命令执行任务的 Agent。

    能力范围: Shell 命令执行、环境检查、文件操作、进程管理、系统诊断
    """

    name: str = "ShellAgent"
    description: str = (
        "Shell 命令执行专家。擅长构建安全可靠的 Shell 命令，"
        "处理文件操作、环境配置和系统管理任务，执行前会解释影响。"
    )
    tags: list[str] = ["shell", "command", "run", "execute", "system"]

    @property
    def system_prompt(self) -> str:
        """返回 ShellAgent 的系统提示词。"""
        return """你是一个专业的 Shell 操作 Agent。你的职责:
1. 构建安全可靠的 Shell 命令
2. 避免危险的系统操作 (如 rm -rf /, dd, >/dev/sda 等)
3. 在执行前解释命令的作用和潜在影响
4. 使用绝对路径而非相对路径
5. 优先使用安全的方式完成任务 (如先备份再修改)
6. 对于破坏性操作, 必须先获得用户确认
7. 命令输出过长时, 使用截断并提示完整输出位置"""

    def register_tools(self) -> None:
        """注册 ShellAgent 的特有 Tool。"""
        # 基础 Tool
        self.tool_manager.register(RunShellTool(requires_confirmation=True))
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())
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
        """初始化 ShellAgent, 使用最低温度确保命令的确定性和安全性。"""
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.2,
                max_iterations=6,
            )
        super().__init__(name=name, description=description, config=config, agent_config=agent_config)
