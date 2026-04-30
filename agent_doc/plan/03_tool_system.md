# Tool 系统设计

## 1. 概述

Tool 系统是 Agent 与外部世界交互的接口。包含四个核心组件：
- **BaseTool**: Tool 的抽象基类（定义契约）
- **ToolManager**: 管理已注册 Tool 的查找/匹配/调用
- **AgentRegistry**: 管理特化 Agent 的注册/发现/实例化 (Agent 作为一种特殊的 Tool)
- **AgentPool**: Agent 实例池（惰性创建、实例复用、并发控制）

## 2. BaseTool 设计

```python
class BaseTool(ABC):
    """
    Tool 抽象基类。

    每个 Tool 需要定义名称、描述和参数 Schema,
    LLM 根据这些信息决定何时调用哪个 Tool。
    """

    # ── 元数据 ────────────────────────────────────────
    name: str                       # Tool 名称 (用于 Action 匹配, 全局唯一)
    description: str                # Tool 功能描述 (LLM 据此选择 Tool)
    parameters_schema: dict         # 参数 JSON Schema (LLM 据此生成参数)
    tags: list[str]                 # 标签 (辅助匹配, 如 ["file", "read"])
    requires_confirmation: bool     # 是否需要用户确认 (危险操作标记)

    # ── 抽象方法 ─────────────────────────────────────
    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """
        执行 Tool 逻辑。子类必须实现。
        抛出 ToolExecutionError 时, 错误信息将作为 Observation 反馈 LLM。
        """

    # ── 辅助方法 ─────────────────────────────────────
    def to_llm_description(self) -> dict:
        """
        转换为 LLM Function Calling 格式的描述:
        {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema
            }
        }
        """

    def validate_args(self, **kwargs) -> dict:
        """
        使用 JSON Schema 验证参数:
        1. 类型校验 (str/int/float/bool/array/object)
        2. 必填字段检查
        3. 枚举值范围检查
        4. 返回验证后的参数字典
        抛出 ToolArgValidationError 若验证失败。
        """

    def sanitize_args(self, **kwargs) -> dict:
        """
        参数安全化处理:
        - 文件路径: 限制在项目根目录内
        - Shell 命令: 转义危险字符
        子类可覆写以实现特定的安全策略。
        """

@dataclass
class ToolResult:
    """Tool 执行结果"""
    success: bool                       # 是否成功
    output: str                         # 输出文本 (给 LLM 的 Observation)
    data: Any = None                    # 结构化数据 (给调用方使用)
    error: str | None = None            # 错误信息 (如有)
    tool_name: str = ""                 # 执行的 Tool 名称
    duration_ms: float = 0.0            # 执行耗时 (毫秒)
```

## 3. ToolManager 设计

```python
class ToolManager:
    """
    Tool 管理器 — 负责 Tool 的注册、查找、匹配和调用。

    支持:
    - 名称注册与去重检查
    - 多级匹配策略 (精确/模糊/语义)
    - Tool 执行超时控制
    - 调用审计日志
    """

    def __init__(self, config: Config) -> None:
        """
        初始化。
        - 创建空的 Tool 注册表 (_tools: dict[str, BaseTool])
        - 记录 tool_execution_timeout 配置
        """

    # ── 注册 ─────────────────────────────────────────
    def register(self, tool: BaseTool) -> None:
        """
        注册一个 Tool。
        若名称冲突则抛出 ToolNameConflictError (含冲突 Tool 信息)。
        """

    def register_many(self, tools: list[BaseTool]) -> None:
        """批量注册 Tool, 原子操作 (任一失败则全部回滚)。"""

    def unregister(self, tool_name: str) -> None:
        """注销一个 Tool。若未注册则静默忽略。"""

    # ── 查找 ─────────────────────────────────────────
    def get_tool(self, tool_name: str) -> BaseTool | None:
        """按名称精确查找 Tool。O(1)。"""

    def list_tools_by_tag(self, tag: str) -> list[BaseTool]:
        """按标签筛选 Tool。"""

    # ── 调用 ─────────────────────────────────────────
    def execute(self, tool_name: str, **kwargs) -> ToolResult:
        """
        根据名称执行 Tool:
        1. 精确查找 Tool
        2. 调用 tool.validate_args(**kwargs)
        3. 调用 tool.sanitize_args(**kwargs)
        4. 若 requires_confirmation → 触发确认流程 (发布 ConfirmationRequestEvent)
        5. 执行 tool.execute(**sanitized_args), 带超时控制
        6. 记录调用日志
        返回 ToolResult 或抛出 ToolNotFoundError / ToolExecutionError
        """

    def execute_with_timeout(self, tool_name: str,
                             timeout: float | None = None,
                             **kwargs) -> ToolResult:
        """
        带超时的 Tool 执行。
        若 timeout 为 None, 使用 Config 中的默认值。
        使用 concurrent.futures.ThreadPoolExecutor 实现超时。
        """

    # ── 导出 ─────────────────────────────────────────
    def list_tools(self) -> list[dict]:
        """返回所有 Tool 的 LLM 描述列表 (用于 Prompt 构建)。"""

    def get_tools_schema(self) -> list[dict]:
        """
        返回 OpenAI Function Calling 格式的 Tool Schema 列表,
        用于 LLM 的原生 Function Calling。
        """
```

## 4. AgentRegistry 设计 — Agent 作为 Tool

```python
class AgentRegistry:
    """
    Agent 注册中心 — 管理特化 Agent 的注册、发现和实例化。

    核心设计: Agent 本身作为一种特殊的 Tool 存在:
    - Tool 名称 = Agent 名称
    - Tool 描述 = Agent 的 description
    - Tool "执行" = 从 AgentPool 获取实例并 run()

    支持外部 Agent 插件动态加载 (通过 entry_points 或指定目录扫描)。
    """

    def __init__(self, agent_pool: AgentPool) -> None:
        """初始化。绑定 AgentPool 用于实例管理。"""

    # ── 注册 ─────────────────────────────────────────
    def register(self, agent_cls: type[BaseAgent]) -> None:
        """
        注册一个 Agent 类 (非实例)。
        注册时自动校验:
        - 必须继承自 BaseAgent
        - name 属性必须非空且不冲突
        - description 属性必须非空
        同时提取 Agent 元数据缓存以供导出和 AgentTool 构造。
        """

    def get_agent_meta(self, agent_name: str) -> AgentMeta:
        """
        获取 Agent 的元数据 (不创建实例)。

        返回 AgentMeta:
            - name: str — Agent 名称
            - description: str — Agent 功能描述
            - tags: list[str] — 标签列表
            - agent_cls: type[BaseAgent] — Agent 类引用
        若未注册则抛出 AgentNotFoundError。
        """

    def register_from_module(self, module_path: str) -> int:
        """
        从指定模块路径扫描并注册所有 BaseAgent 子类。
        返回注册数量。
        """

    # ── 查找与匹配 ───────────────────────────────────
    def get_agent(self, agent_name: str) -> BaseAgent | None:
        """按名称获取 Agent 实例 (通过 AgentPool)。"""

    def match_agent(self, task: str) -> MatchResult:
        """
        根据任务描述匹配最合适的特化 Agent。
        匹配策略 (可配置):
        1. 关键词匹配: 预定义的关键词 → Agent 映射表
        2. LLM 路由: 将 [Agent 列表 + task] 发 LLM, 由 LLM 选择
        3. 描述相似度: TF-IDF / 嵌入相似度比对各 Agent 的 description
        返回 MatchResult(agent_name, score, strategy_used)
        """

    # ── 拉起 Agent ───────────────────────────────────
    def launch(self, agent_name: str, task: str,
               context: dict | None = None) -> AgentResult:
        """
        拉起指定 Agent 执行子任务:
        1. 从 AgentPool 获取或创建 Agent 实例
        2. 构建 AgentConfig (继承父 Agent 配置, call_depth + 1)
        3. 触发 AgentLifecycleEvent.SPAWNED
        4. 调用 agent.run(task, context)
        5. 触发 AgentLifecycleEvent.COMPLETED / FAILED
        6. 归还实例到 AgentPool
        返回 AgentResult
        """

    # ── 导出 ─────────────────────────────────────────
    def list_agents(self) -> list[dict]:
        """
        返回所有注册 Agent 的描述列表 (用于 Prompt 构建):
        [{"name": "CodeAgent", "description": "...", "tags": [...]}, ...]
        """

    def get_agent_tools_schema(self) -> list[dict]:
        """将所有注册 Agent 转换为 Function Calling Schema 格式。"""

@dataclass
class AgentMeta:
    """Agent 元数据 — 由 AgentRegistry 缓存, 供 AgentTool 等消费"""
    name: str                           # Agent 名称
    description: str                    # Agent 功能描述
    tags: list[str]                     # 标签列表
    agent_cls: type[BaseAgent]          # Agent 类引用

@dataclass
class MatchResult:
    """Tool/Agent 匹配结果"""
    tool_name: str | None               # 匹配到的 Tool 名称 (Tool 匹配时)
    agent_name: str | None              # 匹配到的 Agent 名称 (Agent 匹配时)
    score: float                        # 匹配得分 (0-1)
    strategy_used: str                  # 使用的匹配策略名称
    candidates: list[str]               # 其他候选名称 (得分低于阈值的前 N 个)
```

## 5. AgentPool — Agent 实例池

```python
class AgentPool:
    """
    Agent 实例池 — 管理 Agent 实例的惰性创建、复用和并发控制。

    解决的问题:
    - 避免每次子任务重复创建 Agent 实例 (复用 LLMClient 连接等重量资源)
    - 限制并发 Agent 数量, 防止资源耗尽
    - 支持实例生命周期管理 (空闲超时回收)
    """

    def __init__(self, max_instances: int | None = None,
                 idle_timeout: float | None = None) -> None:
        """
        初始化。
        - max_instances: 最大并发实例数 (None = 无限制, 从 Config 读取)
        - idle_timeout: 实例空闲超时, 超时后回收 (None = 使用 Config 默认值 300s)
        """

    def acquire(self, agent_name: str,
                agent_factory: Callable[[], BaseAgent]) -> BaseAgent:
        """
        获取 Agent 实例。
        1. 若池中有空闲实例 → 直接返回 (复用)
        2. 若未达上限 → 调用 agent_factory 创建新实例
        3. 若已达上限 → 等待 (阻塞) 或抛出 AgentPoolExhaustedError
        """

    def release(self, agent: BaseAgent) -> None:
        """
        归还 Agent 实例。
        自动调用 agent.reset() 清理状态。
        """
```

## 6. AgentTool — Agent 作为 Tool 的适配器

```python
class AgentTool(BaseTool):
    """
    将 Agent 包装为 Tool, 使得调用方可以像调用普通 Tool 一样拉起子 Agent。

    这个适配器解决了 "Agent 也是 Tool" 的统一抽象问题,
    意味着调用方无需区分当前执行的是 Tool 还是子 Agent。
    """

    def __init__(self, agent_registry: AgentRegistry, agent_name: str) -> None:
        """
        从 AgentRegistry 中读取 Agent 元信息构建 Tool 描述。
        Tool 的 name/description/parameters_schema 从 Agent 类定义自动推导。
        """
        agent_meta = agent_registry.get_agent_meta(agent_name)
        self.name = agent_meta.name
        self.description = agent_meta.description
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "分配给此 Agent 的子任务描述"},
                "context": {"type": "object", "description": "可选的上下文信息"}
            },
            "required": ["task"]
        }
        self._agent_name = agent_name
        self._registry = agent_registry

    def execute(self, **kwargs) -> ToolResult:
        """
        执行 = 拉起 Agent:
        1. 从 kwargs 提取 task 和 context
        2. 调用 agent_registry.launch(self._agent_name, task, context)
        3. 将 AgentResult 转换为 ToolResult:
           - success → output = agent_result.final_answer
           - failure → error = agent_result.error
        """
```

## 7. 内置 Tool 列表

| Tool 名称 | 功能 | 参数 | 风险等级 |
|-----------|------|------|----------|
| `read_file` | 读取文件内容 | `path: str, encoding: str = "utf-8", max_lines: int | None` | 低 |
| `write_file` | 写入文件 (限制在项目目录) | `path: str, content: str` | 中 (需确认) |
| `run_shell` | 执行 Shell 命令 | `command: str, timeout: float | None` | 高 (需确认) |
| `search_code` | 代码内容搜索 | `pattern: str, path: str = ".", glob: str | None` | 低 |
| `list_files` | 列出目录文件 | `directory: str = ".", pattern: str = "*", recursive: bool = False` | 低 |
| `web_fetch` | 获取网页内容 | `url: str, max_size: int | None` | 中 |
| `web_search` | 网页搜索 | `query: str, max_results: int = 5` | 中 |
| `launch_<agent>` | 拉起单个特化 Agent (由 AgentRegistry 动态生成) | `task: str, context: dict | None` | 取决于子 Agent |
| `launch_crew` | 组建并执行 Agent 团队完成复杂使命 | `mission: str, strategy: str = "sequential", max_parallel: int | None` | 取决于成员 Agent |

## 8. Tool 安全机制

```python
@dataclass
class ToolSecurityPolicy:
    """Tool 安全策略 — 全局配置"""

    # 文件操作限制
    allowed_directories: list[str]      # 允许读写的目录白名单 (绝对路径)
    max_file_size_mb: float             # 单文件最大大小

    # Shell 限制
    allowed_commands: list[str]         # 允许的 Shell 命令白名单 (空 = 全部禁止)
    shell_timeout_default: float        # 默认 Shell 超时 (秒)

    # 网络限制
    allowed_url_schemes: list[str]      # 允许的 URL 协议 ["https"]
    max_response_size_mb: float         # 网络请求最大响应大小

    # 确认策略
    confirm_on_dangerous: bool          # 危险操作是否需确认 (默认 True)
    confirm_on_write: bool              # 写文件是否需确认
    confirm_on_shell: bool              # Shell 是否需确认
```

## 9. CrewOrchestrator — 团队编排机制

### 9.1 概述

`CrewOrchestrator` 是 Agent 框架的核心机制之一，使任何特化 Agent 都能成为 **CrewLeader** (团队领导)，根据复杂任务动态组建并领导一组特化 Agent (称为 **Crew**) 协同完成任务。

与 `AgentTool` (单 Agent 拉起) 的关键区别：

| 维度 | AgentTool (§6) | CrewOrchestrator (§9) |
|------|---------------|----------------------|
| 拉起数量 | 单个 Agent | 一组 Agent (Crew) |
| 任务粒度 | 一个完整任务 | 自动分解为多个子任务 |
| Agent 匹配 | 调用方指定名称 | 自动按子任务匹配最佳 Agent |
| 执行策略 | 单一: 同步调用 | 多种: 串行 / 并行 / DAG |
| 结果处理 | 返回原始结果 | 自动汇总聚合 |
| 适用场景 | 简单委托 | 复杂多面任务 |

### 9.2 核心类设计

```python
# ── 数据模型 ──────────────────────────────────────

@dataclass
class SubTask:
    """
    由 CrewOrchestrator 分解出的子任务。

    每个子任务描述一个独立的、可分配给特定 Agent 的工作单元。
    """
    task_id: str                        # 子任务唯一标识 (UUID)
    description: str                    # 子任务描述 (Agent 据此理解工作内容)
    required_tags: list[str]            # 所需 Agent 能力标签 (用于匹配)
    dependencies: list[str]             # 依赖的 task_id 列表 (DAG 模式)
    context: dict | None = None         # 传递的上下文数据

@dataclass
class CrewMember:
    """
    Crew 成员 — 一个 Agent 绑定到一个子任务。

    由 CrewOrchestrator 在 plan_crew 阶段创建，
    在 execute_crew 阶段由 AgentPool 获取实例后填充 agent_instance。
    """
    agent_name: str                     # 匹配到的 Agent 名称
    agent_cls: type[BaseAgent] | None = None  # Agent 类引用 (用于延迟实例化)
    agent_instance: BaseAgent | None = None   # Agent 实例 (执行时填充)
    task: SubTask | None = None         # 分配的子任务
    status: str = "PENDING"             # PENDING → RUNNING → DONE / FAILED
    result: AgentResult | None = None   # 执行结果

@dataclass
class AgentCrew:
    """
    由 CrewLeader 组件的一支 Agent 团队。

    包含团队标识、任务描述 (mission)、成员列表与执行状态。
    """
    crew_id: str                        # Crew 唯一标识 (UUID)
    lead_agent_name: str                # CrewLeader (发起方 Agent) 名称
    mission: str                        # 团队使命 (原始任务描述)
    members: list[CrewMember]           # 团队成员列表
    status: str = "ASSEMBLED"           # ASSEMBLED → RUNNING → COMPLETED / FAILED
    created_at: float = 0.0             # 创建时间戳

@dataclass
class CrewResult:
    """
    Crew 执行结果 — 汇总所有成员结果。

    除聚合结果外, 保留每个成员的完整 AgentResult 用于调试和审计。
    """
    success: bool                       # 整体是否成功 (全部子任务成功 = True)
    crew_id: str                        # 来源 Crew 的 ID
    mission_summary: str                # LLM 汇总的团队使命报告
    member_results: list[tuple[str, AgentResult]]  # (agent_name, result) 列表
    execution_order: list[str]          # 子任务执行顺序 (task_id 列表)
    total_duration_ms: float            # 总耗时 (毫秒)
    token_usage: TokenUsage             # 团队总 Token 用量

# ── 执行策略枚举 ──────────────────────────────────

class ExecutionStrategy(Enum):
    """
    Crew 执行策略 — 决定子任务以何种顺序执行。

    SEQUENTIAL: 按 plan 返回顺序依次执行, 前一个完成后才开始下一个
    PARALLEL:   并发执行所有无依赖关系的子任务 (最大并发数可配置)
    DAG:        按依赖关系拓扑排序后执行, 无依赖的可并行
    """
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DAG = "dag"

# ── CrewOrchestrator ──────────────────────────────

class CrewOrchestrator:
    """
    Crew Orchestrator — 团队编排引擎。

    核心职责:
    1. 任务分解 (Plan):  将复杂使命分解为 SubTask 列表 (使用 LLM)
    2. Agent 匹配 (Match): 为每个 SubTask 匹配最合适的特化 Agent (通过 AgentRegistry)
    3. Crew 组建 (Assemble): 构建 AgentCrew 结构
    4. Crew 执行 (Execute): 按指定策略驱动各成员执行子任务
    5. 结果聚合 (Aggregate): 汇总所有成员结果, 生成统一的 CrewResult

    这是框架的核心扩展机制 — 任何特化 Agent 均可通过 CrewOrchestrator
    将复杂任务拆解并分派给一组更专业的 Agent 协同完成。
    """

    # ── 依赖 ─────────────────────────────────────────
    agent_registry: AgentRegistry       # Agent 注册中心 (用于匹配 Agent)
    agent_pool: AgentPool               # Agent 实例池 (用于获取实例)
    llm_client: LLMClient               # LLM 客户端 (用于任务分解和结果聚合)
    event_bus: EventBus                 # 事件总线 (发布 Crew 生命周期事件)

    # ── 配置 ─────────────────────────────────────────
    max_parallel: int                   # 最大并行成员数 (默认 4)
    crew_max_iterations: int            # Crew 级任务分解最大迭代 (默认 3)
    plan_temperature: float             # 任务分解时的 LLM 温度 (默认 0.4)

    # ── 构造 ─────────────────────────────────────────
    def __init__(self, agent_registry: AgentRegistry,
                 agent_pool: AgentPool,
                 llm_client: LLMClient,
                 event_bus: EventBus,
                 config: Config) -> None:
        """
        初始化 CrewOrchestrator。
        - 绑定 AgentRegistry / AgentPool / LLMClient / EventBus
        - 从 Config 读取 max_parallel / crew_max_iterations / plan_temperature
        """

    # ── Plan: 任务分解与 Agent 匹配 ───────────────────
    def plan_crew(self, mission: str,
                  lead_agent_name: str,
                  available_agents: list[AgentMeta] | None = None
                  ) -> AgentCrew:
        """
        将 mission 分解为 SubTask 列表, 并为每个子任务匹配最佳 Agent。

        内部流程:
        1. 构建分解 Prompt (含可用 Agent 列表与能力描述)
        2. LLM 分析 mission, 输出结构化子任务列表 (JSON)
        3. 每个子任务通过 AgentRegistry.match_agent() 匹配最佳 Agent
        4. 构建 AgentCrew (含 CrewMember 列表)
        5. 发布 CrewLifecycleEvent.PLANNED

        返回已组建但尚未执行的 AgentCrew (status=ASSEMBLED)。
        """

    # ── Execute: Crew 执行 ────────────────────────────
    def execute_crew(self, crew: AgentCrew,
                     strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL,
                     max_parallel: int | None = None
                     ) -> CrewResult:
        """
        按指定策略执行 Crew。

        内部流程:
        1. 发布 CrewLifecycleEvent.STARTED
        2. 根据 strategy 分发到 _execute_sequential / _execute_parallel / _execute_dag
        3. 每个成员执行: AgentPool.acquire → agent.run(task) → AgentPool.release
        4. 汇总所有成员结果 → 调用 _aggregate_results
        5. 发布 CrewLifecycleEvent.COMPLETED (或 FAILED)
        6. 返回 CrewResult
        """

    def _execute_sequential(self, crew: AgentCrew) -> list[tuple[str, AgentResult]]:
        """
        串行执行 — 按 members 列表顺序依次执行每个成员。
        前一成员的结果 (final_answer) 作为后一成员的 context 传入。
        适用于有强顺序依赖的任务链。
        """

    def _execute_parallel(self, crew: AgentCrew,
                          max_parallel: int) -> list[tuple[str, AgentResult]]:
        """
        并行执行 — 并发执行所有成员 (受 max_parallel 限制)。
        使用 concurrent.futures.ThreadPoolExecutor 实现。
        适用于成员间无依赖的独立子任务。
        """

    def _execute_dag(self, crew: AgentCrew) -> list[tuple[str, AgentResult]]:
        """
        DAG 执行 — 按依赖关系拓扑排序, 无依赖的成员可并行。
        每完成一个成员, 检查并释放依赖它的后续成员。
        """

    # ── Aggregate: 结果聚合 ───────────────────────────
    def _aggregate_results(self, crew: AgentCrew,
                           results: list[tuple[str, AgentResult]]) -> CrewResult:
        """
        汇总所有成员结果:
        1. 将所有 member final_answer 拼接为上下文
        2. 调用 LLM 生成统一的 mission_summary
        3. 计算 total_duration_ms 和 total token_usage
        4. 判定整体 success (全部成员 success=True)
        """
```

### 9.3 Crew 事件类型

```python
class CrewLifecycleEvent:
    """
    Crew 生命周期事件 — 发布到 EventBus, 供监控/日志/审计订阅。

    枚举值:
    - PLANNED:   plan_crew() 完成, crew 已组建
    - STARTED:   execute_crew() 开始
    - MEMBER_STARTED:  单个 CrewMember 开始执行
    - MEMBER_COMPLETED: 单个 CrewMember 执行完成
    - MEMBER_FAILED:    单个 CrewMember 执行失败
    - COMPLETED: 全部成员执行完毕且成功
    - FAILED:    存在成员失败且不可恢复
    """
```

### 9.4 Crew 编排流程

```
CrewLeader (任意特化 Agent)
   │
   ├─ 1. 识别到任务需要多 Agent 协同
   │     (LLM 在 ReAct 循环中判断任务复杂度)
   │
   ├─ 2. 调用 self.form_crew(mission)
   │     └─ crew_orchestrator.plan_crew(mission, lead_agent_name, available_agents)
   │           ├─ LLM 分解 mission → SubTask[]
   │           ├─ AgentRegistry.match_agent() × N → CrewMember[]
   │           └─ 返回 AgentCrew (status=ASSEMBLED)
   │
   ├─ 3. 调用 self.launch_crew(mission, strategy)
   │     └─ crew_orchestrator.execute_crew(crew, strategy)
   │           ├─ SEQUENTIAL: [CodeAgent] → [DocAgent] → [ShellAgent]
   │           ├─ PARALLEL:   [CodeAgent | DocAgent | SearchAgent] (并发)
   │           └─ DAG:        [SearchAgent] → [CodeAgent] → [ShellAgent]
   │                                  └──────────────→ [DocAgent]
   │
   ├─ 4. 聚合结果
   │     └─ LLM 汇总所有 member.final_answer → mission_summary
   │
   ▼
CrewLeader 将 CrewResult.mission_summary 作为 Observation 继续 ReAct 推理
```

### 9.5 与现有机制的关系

```
BaseAgent (CrewLeader 角色)
   ├─ react_engine: ReActEngine       # 自身 ReAct 推理
   ├─ tool_manager: ToolManager       # 调用 Tool (含 AgentTool 单 Agent 拉起)
   ├─ crew_orchestrator: CrewOrchestrator  # 组建并执行 Agent 团队 (NEW)
   │     ├─ plan_crew()               # 分解 + 匹配
   │     └─ execute_crew()            # 执行 + 聚合
   ├─ agent_registry: AgentRegistry   # 被 CrewOrchestrator 用于匹配 Agent
   └─ agent_pool: AgentPool           # 被 CrewOrchestrator 用于获取实例
```
