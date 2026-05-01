"""
RootAgent — 框架入口 Agent。

继承 BaseAgent 的全部 ReAct 能力, 额外增加:
- 控制台交互 (REPL)
- Agent 自动匹配与调度 (三级路由策略)
- 多会话管理 (SessionManager)
- 插件 Agent 动态加载
"""

import sys
from typing import Any

from src.agents.code_agent import CodeAgent
from src.agents.doc_agent import DocAgent
from src.agents.search_agent import SearchAgent
from src.agents.shell_agent import ShellAgent
from src.core.base_agent import BaseAgent
from src.core.models import AgentConfig, AgentResult
from src.core.plugin_loader import AgentPluginLoader
from src.core.session_manager import SessionManager
from src.infra.config import Config
from src.tools.agent_tool import AgentTool
from src.tools.crew_tool import CrewTool
from src.tools.file_tools import ListFilesTool, ReadFileTool
from src.tools.search_tools import SearchCodeTool


class RootAgent(BaseAgent):
    """
    根 Agent — 框架入口, 处理控制台输入并调度特化 Agent。

    继承 BaseAgent 的全部 ReAct 能力, 额外增加:
    - 控制台交互 (REPL), 支持彩色输出与自动补全
    - Agent 自动匹配与调度 (三级路由策略)
    - 多会话管理 (SessionManager)
    - 插件 Agent 动态加载
    """

    name: str = "RootAgent"
    description: str = (
        "根 Agent — 理解用户意图并分派任务给特化 Agent。"
        "可直接调用 Tool 完成简单操作, 或拉起特化 Agent 处理复杂专业任务。"
    )
    tags: list[str] = ["root", "orchestrator", "entry"]

    def __init__(self, config: Config | None = None) -> None:
        """
        初始化 RootAgent:
        1. 调用 BaseAgent.__init__ 完成基础设施初始化
        2. 注册所有内置的特化 Agent
        3. 将每个特化 Agent 包装为 AgentTool 并注册到 ToolManager
        4. 初始化 SessionManager
        5. 若配置了 plugin_directories, 扫描并加载外部 Agent 插件
        """
        if config is None:
            config = Config.from_env()

        agent_config = AgentConfig(
            llm_temperature_override=0.7,
            max_iterations=12,
        )

        super().__init__(config=config, agent_config=agent_config)

        # 创建 SessionManager
        self.session_manager = SessionManager()

        # 注册内置特化 Agent
        self._register_builtin_agents()

        # REPL 配置
        self.repl_prompt: str = ">> "
        self.repl_welcome_message: str = (
            f"Welcome to SpecialAgent v1.0\n"
            f"Type /help for available commands, /exit to quit.\n"
            f"Available agents: {len(self.agent_registry.list_agents())}\n"
            f"Available tools: {self.tool_manager.tool_count}"
        )
        self.enable_syntax_highlight: bool = True

    @property
    def system_prompt(self) -> str:
        """返回 RootAgent 的系统提示词。"""
        return """你是 RootAgent, 框架的总入口 Agent。你的职责:
1. 理解用户意图, 判断任务的复杂度和领域归属
2. 对于简单操作 (如读取文件、搜索代码), 直接调用 Tool 完成
3. 对于复杂专业任务 (如代码编写、文档生成), 拉起对应的特化 Agent
4. 当任务涉及多个领域时, 使用 launch_crew 组建 Agent 团队协同完成
5. 优先考虑拉起专业 Agent 而非自行处理, 确保任务由最合适的 Agent 执行

调度原则:
- 代码编写/审查/修复 → CodeAgent
- 文档编写/API 文档 → DocAgent
- 信息搜索/代码搜索 → SearchAgent
- Shell 命令/系统操作 → ShellAgent
- 多领域复杂任务 → launch_crew"""

    def register_tools(self) -> None:
        """
        注册 RootAgent 的 Tool:
        1. 基础 Tool (文件操作、搜索等)
        2. 将注册的特化 Agent 包装为 AgentTool 并注册 (在 _register_builtin_agents 之后)
        """
        # 基础 Tool
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(ListFilesTool())
        self.tool_manager.register(SearchCodeTool())
        # Crew 编排 Tool
        self.tool_manager.register(CrewTool(agent=self))

    # ── 内置 Agent 注册 ─────────────────────────────────

    def _register_builtin_agents(self) -> None:
        """
        注册框架内置的特化 Agent。

        新增 Agent 只需在此添加一行注册。
        支持从 Config.plugin_directories 加载外部 Agent。
        """
        self.agent_registry.register(CodeAgent)
        self.agent_registry.register(DocAgent)
        self.agent_registry.register(SearchAgent)
        self.agent_registry.register(ShellAgent)

        # 将每个特化 Agent 包装为 AgentTool 并注册
        for meta in self.agent_registry.list_agents():
            self.tool_manager.register(AgentTool(self.agent_registry, meta.name))

        # 加载插件 Agent
        self._load_plugin_agents()

    def _load_plugin_agents(self) -> None:
        """
        从配置的 plugin_directories 扫描并加载外部 Agent。

        使用 AgentPluginLoader 动态导入, 记录加载成功/失败的 Agent。
        """
        if not self.config.plugin_directories:
            return

        loader = AgentPluginLoader(self.config.plugin_directories)
        discovered = loader.discover()

        for agent_cls in discovered:
            try:
                self.agent_registry.register(agent_cls)
                self._logger.info(f"Loaded plugin agent: {agent_cls.name}")
            except Exception as e:
                self._logger.warning(f"Failed to register plugin agent '{agent_cls.__name__}': {e}")

    # ── Agent 调度 ───────────────────────────────────

    def dispatch_to_agent(self, task: str) -> AgentResult | None:
        """
        根据 task 描述匹配并拉起最合适的特化 Agent。

        1. 调用 agent_registry.match_agent(task)
        2. 若匹配得分超阈值 → 拉起执行, 记录到会话历史
        3. 若未匹配或得分不足 → 返回 None, 由 RootAgent 自行处理

        Args:
            task: 任务描述

        Returns:
            AgentResult 或 None
        """
        match = self.agent_registry.match_agent(task)
        if match.agent_name and match.score >= 0.2:
            self._logger.info(
                f"Dispatching to {match.agent_name} (score={match.score:.2f})"
            )
            return self.launch_agent(match.agent_name, task)
        return None

    def process_once(self, user_input: str) -> AgentResult:
        """
        单次处理用户输入 (非 REPL 模式也可调用):
        1. 当前会话写入 ContextStore
        2. 尝试 agent_registry.match_agent(user_input)
        3. 若匹配到 → 拉起 Agent 执行 → 记录 → 返回子 Agent 结果
        4. 若未匹配 → 启动自身 ReAct 循环 → 返回结果

        Args:
            user_input: 用户输入文本

        Returns:
            AgentResult
        """
        # 尝试调度到特化 Agent
        agent_result = self.dispatch_to_agent(user_input)
        if agent_result is not None:
            # 记录到会话历史
            session = self.session_manager.get_current_session()
            session.agent_results.append(agent_result)
            if agent_result.token_usage:
                session.token_usage += agent_result.token_usage
            return agent_result

        # 未匹配, 自行处理
        return self.run(user_input)

    # ── REPL 交互 ────────────────────────────────────

    def start_repl(self) -> None:
        """
        启动交互式 REPL 循环。

        1. 打印欢迎信息与可用命令列表
        2. 循环: 打印提示符 → 读取用户输入
        3. 空输入 → 跳过
        4. 以 '/' 开头 → 调用 handle_command(command)
        5. 其他 → 调用 process_once(user_input)
        6. 打印 Agent 回复
        7. Ctrl+C → 中断当前执行, 不退出 REPL
        8. Ctrl+D 或 /exit → 退出
        """
        print(self.repl_welcome_message)

        while True:
            try:
                user_input = input(self.repl_prompt).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not user_input:
                continue

            # 内置命令
            if user_input.startswith("/"):
                should_continue = self.handle_command(user_input)
                if not should_continue:
                    break
                continue

            # 处理用户输入
            try:
                result = self.process_once(user_input)
                print(f"\n{self._format_result_display(result)}\n")
            except KeyboardInterrupt:
                print("\n[Interrupted]")
                self.stop()
            except Exception as e:
                print(f"\n[Error] {e}\n")

        # 退出前保存会话
        self.session_manager.save_to_disk()

    def handle_command(self, command: str) -> bool:
        """
        处理内置命令, 返回 True 表示 REPL 应继续运行。

        支持的命令:
        - /exit, /quit: 退出程序
        - /help: 显示帮助信息
        - /agents: 列出所有可用 Agent
        - /tools: 列出所有可用 Tool
        - /history: 显示当前会话的 ReAct 迭代历史
        - /clear: 清除当前会话上下文
        - /session <id>: 切换或创建会话
        - /sessions: 列出所有会话
        - /stats: 显示 Token 用量统计
        - /debug: 切换调试模式
        """
        cmd_parts = command.split()
        cmd = cmd_parts[0].lower()

        if cmd in ("/exit", "/quit"):
            print("Goodbye!")
            return False

        elif cmd == "/help":
            print("""
Available commands:
  /exit, /quit    Exit the program
  /help           Show this help message
  /agents         List all available agents
  /tools          List all available tools
  /history        Show current session's ReAct history
  /clear          Clear current session context
  /session <id>   Switch or create a session
  /sessions       List all sessions
  /stats          Show token usage statistics
  /debug          Toggle debug mode
""")

        elif cmd == "/agents":
            agents = self.agent_registry.list_agents()
            if not agents:
                print("(No agents registered)")
            else:
                for meta in agents:
                    tags_str = ", ".join(meta.tags) if meta.tags else "none"
                    print(f"  {meta.name}: {meta.description}")
                    print(f"    Tags: {tags_str}")

        elif cmd == "/tools":
            tools = self.tool_manager.tools
            if not tools:
                print("(No tools registered)")
            else:
                for name, tool in tools.items():
                    print(f"  {name}: {tool.description}")

        elif cmd == "/history":
            steps = self.context_store.get_react_trajectory()
            if not steps:
                print("(No history)")
            else:
                for step in steps:
                    print(f"  #{step.iteration}: {step.action_name} "
                          f"({step.duration_ms:.0f}ms, "
                          f"tokens={step.token_usage.total_tokens if step.token_usage else 'N/A'})")

        elif cmd == "/clear":
            self.session_manager.clear_current_session()
            self.reset()
            print("Session context cleared.")

        elif cmd == "/session":
            if len(cmd_parts) > 1:
                sid = cmd_parts[1]
                try:
                    self.session_manager.switch_session(sid)
                    print(f"Switched to session: {sid}")
                except Exception as e:
                    print(f"Error: {e}")
            else:
                session = self.session_manager.get_current_session()
                print(f"Current session: {session.name} ({session.session_id})")

        elif cmd == "/sessions":
            sessions = self.session_manager.list_sessions()
            if not sessions:
                print("(No sessions)")
            else:
                for s in sessions:
                    current = " [CURRENT]" if s.session_id == self.session_manager._current_session_id else ""
                    print(f"  {s.name} ({s.session_id}){current}")

        elif cmd == "/stats":
            usage = self.llm_client.get_token_usage()
            print(f"  LLM calls: {self.llm_client.token_tracker.call_count}")
            print(f"  Prompt tokens: {usage.prompt_tokens}")
            print(f"  Completion tokens: {usage.completion_tokens}")
            print(f"  Total tokens: {usage.total_tokens}")

        elif cmd == "/debug":
            self.config.log_llm_calls = not self.config.log_llm_calls
            status = "ON" if self.config.log_llm_calls else "OFF"
            print(f"Debug mode: {status}")

        else:
            print(f"Unknown command: {cmd}. Type /help for available commands.")

        return True

    def _format_result_display(self, result: AgentResult) -> str:
        """
        格式化 AgentResult 为控制台显示文本。

        包含: 来源 Agent 名称, 最终回答, 迭代次数, Token 用量。

        Args:
            result: AgentResult 实例

        Returns:
            格式化后的显示文本
        """
        parts: list[str] = []

        # 如果有子 Agent 结果, 显示来源
        if result.sub_agent_results:
            for sub in result.sub_agent_results:
                parts.append(f"[{sub.final_answer[:200]}...]")

        parts.append(result.final_answer)

        # 统计信息
        stats = []
        if result.iterations:
            stats.append(f"Iterations: {len(result.iterations)}")
        if result.token_usage and result.token_usage.total_tokens > 0:
            stats.append(f"Tokens: {result.token_usage.total_tokens}")
        if result.total_duration_ms > 0:
            stats.append(f"Duration: {result.total_duration_ms:.0f}ms")

        if stats:
            parts.append(f"\n--- {' | '.join(stats)} ---")

        return "\n".join(parts)
