# RootAgent 设计

## 1. 概述

`RootAgent` 是框架的入口 Agent，继承自 `BaseAgent`，负责：
- 处理控制台输入 (REPL 交互模式)
- 根据用户意图自动匹配并拉起特化 Agent
- 管理所有子 Agent 的注册和生命周期
- 提供交互式命令行体验，支持多会话切换

## 2. 类设计

```python
class RootAgent(BaseAgent):
    """
    根 Agent — 框架入口, 处理控制台输入并调度特化 Agent。

    继承 BaseAgent 的全部 ReAct 能力, 额外增加:
    - 控制台交互 (REPL), 支持彩色输出与自动补全
    - Agent 自动匹配与调度 (三级路由策略)
    - 多会话管理 (SessionManager)
    - 插件 Agent 动态加载
    """

    # ── 标识 ──────────────────────────────────────────
    name: str = "RootAgent"
    description: str = (
        "根 Agent — 理解用户意图并分派任务给特化 Agent。"
        "可直接调用 Tool 完成简单操作, 或拉起特化 Agent 处理复杂专业任务。"
    )

    # ── 子 Agent 管理 ────────────────────────────────
    agent_registry: AgentRegistry       # 所有特化 Agent 的注册中心
    agent_pool: AgentPool               # Agent 实例池

    # ── 会话 ─────────────────────────────────────────
    session_manager: SessionManager     # 多会话管理器

    # ── REPL 配置 ───────────────────────────────────
    repl_prompt: str                    # REPL 提示符 (默认 ">> ")
    repl_welcome_message: str           # 欢迎信息
    enable_syntax_highlight: bool       # 是否启用语法高亮 (默认 True)

    # ── 构造 ─────────────────────────────────────────
    def __init__(self, config: Config | None = None) -> None:
        """
        初始化 RootAgent:
        1. 调用 BaseAgent.__init__ 完成基础设施初始化
        2. 创建 AgentPool 和 AgentRegistry
        3. 注册所有内置的特化 Agent
        4. 将每个特化 Agent 包装为 AgentTool 并注册到 ToolManager
        5. 初始化 SessionManager
        6. 若配置了 plugin_directories, 扫描并加载外部 Agent 插件
        """

    # ── System Prompt ────────────────────────────────
    @property
    def system_prompt(self) -> str:
        """
        返回 RootAgent 的系统提示词:
        "你是 RootAgent, 负责理解用户意图并将任务分派给合适的特化 Agent。
         你可以使用以下 Tool 和 Agent:
         - 直接调用 Tool 完成简单操作 (如读取文件、搜索代码)
         - 拉起特化 Agent 处理复杂专业任务 (如代码编写、文档生成)
         当任务超出你的能力范围时, 优先考虑拉起专业 Agent 而非自行处理。"
        """

    # ── Tool 注册 ─────────────────────────────────────
    def register_tools(self) -> None:
        """
        注册 RootAgent 的 Tool:
        1. 注册基础 Tool (文件操作、Shell、搜索等)
        2. 将每个注册的特化 Agent 包装为 AgentTool 并注册
        3. 注册会话管理相关 Tool (switch_session, list_sessions)
        """

    # ── 控制台交互 ───────────────────────────────────
    def start_repl(self) -> None:
        """
        启动交互式 REPL 循环。
        1. 打印欢迎信息与可用命令列表
        2. 循环: 打印提示符 → 读取用户输入 (支持 readline)
        3. 空输入 → 跳过
        4. 以 '/' 开头 → 调用 handle_command(command)
        5. 其他 → 调用 process_once(user_input)
        6. 打印 Agent 回复 (区分来自 RootAgent 还是子 Agent)
        7. Ctrl+C → 中断当前执行, 不退出 REPL
        8. Ctrl+D 或 /exit → 退出
        """

    def handle_command(self, command: str) -> bool:
        """
        处理内置命令, 返回 True 表示 REPL 应继续运行。

        支持的命令:
        - /exit, /quit: 退出程序
        - /help: 显示帮助信息 (含每个命令的简短说明)
        - /agents: 列出所有可用 Agent (名称 + 描述 + 状态)
        - /tools: 列出所有可用 Tool (名称 + 描述)
        - /history: 显示当前会话的 ReAct 迭代历史
        - /clear: 清除当前会话上下文
        - /session <id>: 切换或创建会话
        - /sessions: 列出所有会话
        - /stats: 显示 Token 用量统计
        - /debug: 切换调试模式 (显示 LLM 原始输出)
        """

    # ── Agent 调度 ───────────────────────────────────
    def dispatch_to_agent(self, task: str) -> AgentResult | None:
        """
        根据 task 描述匹配并拉起最合适的特化 Agent。
        1. 调用 agent_registry.match_agent(task)
        2. 若匹配得分超阈值 → 拉起执行, 记录到会话历史
        3. 若未匹配或得分不足 → 返回 None, 由 RootAgent 自行处理
        """

    # ── 单次处理 ────────────────────────────────────
    def process_once(self, user_input: str) -> AgentResult:
        """
        单次处理用户输入 (非 REPL 模式也可调用):
        1. 当前会话写入 ContextStore
        2. 尝试 agent_registry.match_agent(user_input)
        3. 若匹配到 → 拉起 Agent 执行 → 记录 → 返回子 Agent 结果
        4. 若未匹配 → 启动自身 ReAct 循环 → 返回结果
        """

    # ── 内部方法 ─────────────────────────────────────
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
        self._load_plugin_agents()

    def _load_plugin_agents(self) -> None:
        """
        从配置的 plugin_directories 扫描并加载外部 Agent。
        使用 importlib 动态导入, 记录加载成功/失败的 Agent。
        """

    def _format_result_display(self, result: AgentResult) -> str:
        """
        格式化 AgentResult 为控制台显示文本。
        包含: 来源 Agent 名称, 最终回答, 迭代次数, Token 用量。
        """
```

## 3. REPL 交互流程

```
┌──────────────────────────────────────────────────────┐
│              RootAgent REPL 主循环                      │
│                                                        │
│  ┌──────────────────────────────────────────────┐     │
│  │ 1. 打印提示符 ">> "                            │     │
│  │ 2. 读取用户输入 (带 readline 支持)              │     │
│  └─────────────────┬────────────────────────────┘     │
│                    │                                   │
│             ┌──────┴──────┐                           │
│             │ 是否以 '/' 开头?│                         │
│             └──────┬──────┘                           │
│              Yes   │   No                              │
│               │    │    │                              │
│               ▼    │    ▼                              │
│      handle_command │ process_once                     │
│               │    │    │                              │
│               │    │    ├─ match_agent (三级路由)       │
│               │    │    │   ├─ 关键词匹配 (快速路径)     │
│               │    │    │   ├─ LLM 路由 (准确路径)      │
│               │    │    │   └─ 描述相似度 (兜底)        │
│               │    │    │                              │
│               │    │    ├─ 命中 → dispatch_to_agent    │
│               │    │    │   └─ 子 Agent 独立 ReAct     │
│               │    │    │                              │
│               │    │    └─ 未命中 → RootAgent ReAct    │
│               │    │                                   │
│               ▼    ▼                                   │
│          _format_result_display 并打印                  │
│          记录到 Session 历史                            │
│          循环继续                                       │
└──────────────────────────────────────────────────────┘
```

## 4. Agent 匹配路由 (三级策略)

```
用户输入
   │
   ├─ 第 1 级: 关键词快速匹配 (延迟 <1ms)
   │   预定义映射表 (可配置):
   │     "代码"/"写"/"编程"/"bug"/"fix" → CodeAgent
   │     "文档"/"doc"/"readme"/"说明" → DocAgent
   │     "搜索"/"查找"/"搜索"/"find" → SearchAgent
   │     "运行"/"执行"/"shell"/"命令" → ShellAgent
   │   命中且置信度高 → 直接路由 (跳过 LLM 调用, 节省 Token)
   │
   ├─ 第 2 级: LLM 智能路由 (延迟 ~LLM 响应时间)
   │   构建: "[Agent 列表 JSON] + [用户输入]"
   │   发送给 LLM (使用轻量 prompt, 仅要求返回 Agent 名称)
   │   适用: 关键词未命中或置信度低时
   │
   └─ 第 3 级: 描述相似度兜底 (延迟 ~10ms)
       使用 TF-IDF / 嵌入相似度比对 Agent 描述
       适用: LLM 路由失败或超时时的降级方案
       返回最佳匹配或 None
```

## 5. 会话管理

```python
@dataclass
class Session:
    """会话数据"""
    session_id: str                     # 会话唯一标识 (UUID)
    name: str                           # 用户可读名称
    created_at: float                   # 创建时间戳
    last_active_at: float               # 最后活跃时间戳
    context_store: ContextStore         # 对话上下文
    agent_results: list[AgentResult]    # Agent 执行记录
    token_usage: TokenUsage             # 会话 Token 累计
    metadata: dict[str, Any]            # 扩展元数据

class SessionManager:
    """
    会话管理器 — 支持多会话切换与持久化。

    所有会话保持在内存中, 可选持久化到磁盘 (JSON 文件)。
    """

    def __init__(self, storage_path: str | None = None) -> None:
        """
        初始化。
        - storage_path: 会话持久化路径 (None = 仅内存)
        """

    def create_session(self, name: str | None = None,
                       session_id: str | None = None) -> Session:
        """创建新会话, 自动生成 UUID。"""

    def switch_session(self, session_id: str) -> Session:
        """切换到指定会话。若不存在抛出 SessionNotFoundError。"""

    def get_current_session(self) -> Session:
        """获取当前会话。若不存在则自动创建。"""

    def list_sessions(self) -> list[Session]:
        """列出所有会话 (按最后活跃时间倒序)。"""

    def delete_session(self, session_id: str) -> None:
        """删除指定会话 (不能删除当前会话)。"""

    def clear_current_session(self) -> None:
        """清除当前会话的上下文, 保留会话元数据。"""

    def export_session(self, session_id: str) -> dict:
        """导出会话为可序列化字典 (用于持久化或分享)。"""

    def import_session(self, data: dict) -> Session:
        """从字典导入会话。"""
```

## 6. 插件系统

```python
class AgentPluginLoader:
    """
    Agent 插件加载器 — 从指定目录动态发现并加载 BaseAgent 子类。

    支持:
    - 目录扫描: 递归扫描指定目录下的 .py 文件
    - 入口点: 通过 Python entry_points 发现插件
    - 隔离加载: 每个插件在独立命名空间中加载
    - 错误隔离: 单个插件加载失败不影响其他插件
    """

    def __init__(self, plugin_directories: list[str]) -> None: ...

    def discover(self) -> list[type[BaseAgent]]:
        """
        发现所有可用插件 Agent 类。
        返回加载成功的 Agent 类列表。
        """

    def validate_plugin(self, agent_cls: type) -> bool:
        """
        校验插件 Agent:
        - 必须继承自 BaseAgent
        - 必须有非空的 name 和 description
        - system_prompt 和 register_tools 必须已实现
        """
```
