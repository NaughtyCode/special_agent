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
    def list_agents(self) -> list[AgentMeta]:
        """
        返回所有注册 Agent 的元数据列表 (用于 Prompt 构建和 Crew 任务分解):
        [AgentMeta(name="CodeAgent", description="...", tags=[...], agent_cls=CodeAgent), ...]

        返回 AgentMeta 而非 dict 以保留 agent_cls 引用,
        使 plan_crew() 可直接使用此列表进行 Agent 匹配和后续实例化。
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
        self.tags = agent_meta.tags                # 继承 Agent 的标签
        self.requires_confirmation = False         # Agent 拉起默认无需确认 (由子 Agent 自行控制)

    def execute(self, **kwargs) -> ToolResult:
        """
        执行 = 拉起 Agent:
        1. 从 kwargs 提取 task 和 context
        2. 调用 agent_registry.launch(self._agent_name, task, context)
        3. 将 AgentResult 转换为 ToolResult:
           - success → output = agent_result.final_answer
           - failure → error = agent_result.error
        4. 异常时捕获并包装为失败 ToolResult, 避免中断 ReAct 循环
           (与 CrewTool.execute() 保持一致的错误处理策略)
        """
        try:
            task = kwargs["task"]
            context = kwargs.get("context")
            agent_result = self._registry.launch(self._agent_name, task, context)
            return ToolResult(
                success=agent_result.success,
                output=agent_result.final_answer,
                data=agent_result,
                tool_name=self.name,
                duration_ms=agent_result.total_duration_ms,
                error=str(agent_result.error) if agent_result.error else None
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output=f"Agent '{self._agent_name}' 执行失败: {e}",
                error=str(e),
                tool_name=self.name
            )
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

    设计要点:
    - task_id 使用 UUID 保证全局唯一, 用于依赖追踪和日志关联
    - required_tags 是 Agent 匹配的关键依据 — Agent 的 tags 与 required_tags
      的重叠度决定匹配得分
    - dependencies 仅在 DAG 策略下使用, 为空列表表示无依赖可立即执行
    - context 用于跨子任务传递数据, 前一子任务的 AgentResult 会注入为
      后续子任务的 context
    """
    task_id: str                        # 子任务唯一标识 (UUID v4)
    description: str                    # 子任务描述 (Agent 据此理解工作内容,
                                          # 应包含明确的输入/输出/验收标准)
    required_tags: list[str]            # 所需 Agent 能力标签 (用于匹配,
                                          # 如 ["code", "python", "refactor"])
    dependencies: list[str]             # 依赖的 task_id 列表 (DAG 模式使用,
                                          # 为空表示无依赖可立即执行)
    context: dict | None = None         # 传递的上下文数据 (来自前置任务结果)

@dataclass
class CrewMember:
    """
    Crew 成员 — 一个 Agent 绑定到一个子任务。

    由 CrewOrchestrator 在 plan_crew 阶段创建，
    在 execute_crew 阶段由 AgentPool 获取实例后填充 agent_instance。

    生命周期: PENDING → RUNNING → DONE / FAILED
    - PENDING: 已分配子任务, 等待执行
    - RUNNING: Agent 正在执行子任务 (已从 AgentPool 获取实例)
    - DONE:    Agent 成功完成子任务, result 包含 AgentResult
    - FAILED:  Agent 执行失败 (异常或超时), result 包含错误信息
    """
    agent_name: str                     # 匹配到的 Agent 名称 (如 "CodeAgent")
    agent_cls: type[BaseAgent] | None = None  # Agent 类引用 (用于延迟实例化,
                                                # 避免在 plan 阶段就创建重量实例)
    agent_instance: BaseAgent | None = None   # Agent 实例 (执行时由 AgentPool 填充)
    task: SubTask | None = None         # 分配的子任务 (含任务描述和依赖信息)
    status: str = "PENDING"             # PENDING → RUNNING → DONE / FAILED
    result: AgentResult | None = None   # 执行结果 (DONE/FAILED 时填充)
    started_at: float = 0.0             # 开始执行时间戳 (time.time(), RUNNING 时设置)
    completed_at: float = 0.0           # 完成时间戳 (time.time(), DONE/FAILED 时设置)
                                         # duration = completed_at - started_at, 用于性能诊断

@dataclass
class AgentCrew:
    """
    由 CrewLeader 组建的一支 Agent 团队。

    包含团队标识、任务描述 (mission)、成员列表与执行状态。
    由 plan_crew() 创建 (status=ASSEMBLED), 由 execute_crew() 执行。

    生命周期: ASSEMBLED → RUNNING → COMPLETED / FAILED
    - ASSEMBLED: 已规划完成, 成员已分配, 等待执行
    - RUNNING:   正在执行 (至少一个成员处于 RUNNING 状态)
    - COMPLETED: 全部成员执行成功
    - FAILED:    至少一个成员执行失败 (不可恢复)
    """
    crew_id: str                        # Crew 唯一标识 (UUID v4, plan_crew 创建 AgentCrew 时生成,
                                          # 用于日志/审计追踪)
    lead_agent_name: str                # CrewLeader (发起方 Agent) 名称,
                                          # 用于记录发起者便于审计
    mission: str                        # 团队使命 (原始任务描述, 作为 LLM 分解的输入)
    members: list[CrewMember]           # 团队成员列表 (plan_crew 阶段填充)
    status: str = "ASSEMBLED"           # ASSEMBLED → RUNNING → COMPLETED / FAILED
    created_at: float = 0.0             # 创建时间戳 (time.time(), plan_crew 设置)
    completed_at: float = 0.0           # 完成时间戳 (time.time(), execute_crew 设置,
                                          # 用于计算 wall-clock total_duration_ms)
    crew_leader_call_depth: int = 0     # CrewLeader 的 call_depth (plan_crew 从 BaseAgent.form_crew 获取,
                                          # 用于为 CrewMember 构建 AgentConfig 时设置 call_depth + 1,
                                          # 实现 Crew 嵌套递归深度限制的向下传播)

@dataclass
class CrewResult:
    """
    Crew 执行结果 — 汇总所有成员结果。

    除聚合结果外, 保留每个成员的完整 AgentResult 用于调试和审计。

    success 判定规则:
    - True:  全部成员执行成功 (无异常), mission_summary 为完整的汇总报告
    - False: 任一成员执行失败 (抛出未捕获异常或返回 error),
             此时 mission_summary 包含已完成部分的结果 + 失败说明,
             member_results 中可区分成功和失败的成员
    """
    success: bool                       # 整体是否成功 (全部子任务成功 = True)
    crew_id: str                        # 来源 Crew 的 ID
    mission_summary: str                # LLM 汇总的团队使命报告 (失败时含错误说明)
    member_results: list[tuple[str, str, AgentResult]]  # (agent_name, task_id, result) 列表
                                                        # task_id 确保同类型 Agent 结果可区分
    execution_order: list[str]          # 子任务执行顺序 (task_id 列表)
    total_duration_ms: float            # 总耗时 (毫秒)
    token_usage: TokenUsage             # 团队总 Token 用量
    failed_members: list[tuple[str, str]]  # 失败的成员 (agent_name, task_id) 列表 (全部成功时为空)
                                           # 使用 task_id 而非 agent_name 作为唯一标识

# ── 执行策略枚举 ──────────────────────────────────

class ExecutionStrategy(Enum):
    """
    Crew 执行策略 — 决定子任务以何种顺序执行。

    SEQUENTIAL: 按 plan 返回顺序依次执行, 前一个完成后才开始下一个
    PARALLEL:   并发执行所有子任务 (忽略 dependencies 字段, 最大并发数可配置)。
                注意: 若 SubTask 定义了 dependencies 但使用 PARALLEL 策略,
                依赖关系被忽略, 执行顺序不确定, 可能导致依赖任务因缺少上游结果而失败。
                使用 PARALLEL 前应确保所有 SubTask.dependencies 均为空列表。
    DAG:        按依赖关系拓扑排序后执行, 无依赖的可并行
    """
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DAG = "dag"

# ── Crew 错误类型 ──────────────────────────────────

class CrewInvalidStateError(Exception):
    """
    Crew 状态不合法错误 — 当 execute_crew() 被调用时 crew.status != "ASSEMBLED" 时抛出。

    典型场景:
    - 重复执行同一个 AgentCrew 实例 (Crew 是一次性的, 不可复用)
    - 尝试执行尚未完成规划的 Crew
    - 手动修改了 crew.status 为非预期值
    """
    pass

class CrewPlanError(Exception):
    """
    Crew 任务分解失败错误 — 当 plan_crew() 调用 LLM 分解 mission 失败时抛出。

    典型场景:
    - LLM 返回的 JSON 格式错误, 且已耗尽 crew_max_iterations 次重试
    - LLM 返回的 SubTask 列表为空 (mission 无法分解)
    - SubTask.dependencies 中存在循环依赖 (DAG 无法拓扑排序)
    - LLM 调用超时或返回不可恢复错误

    携带 raw_llm_output 属性供调试, 包含 LLM 最后一次原始输出。
    """
    def __init__(self, message: str, raw_llm_output: str | None = None):
        super().__init__(message)
        self.raw_llm_output = raw_llm_output

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

    设计原则:
    - 无状态: 所有状态存储在 AgentCrew 中, Orchestrator 本身不持有 Crew 状态
    - 策略可替换: ExecutionStrategy 由调用方传入, 可扩展自定义策略
    - LLM 驱动: 任务分解和结果聚合均使用 LLM, 依赖 LLM 的语义理解能力
    - 事件驱动: 通过 EventBus 发布 Crew 生命周期事件, 便于监控和日志
    """

    # ── 依赖 ─────────────────────────────────────────
    agent_registry: AgentRegistry       # Agent 注册中心 (用于匹配 Agent)
    agent_pool: AgentPool               # Agent 实例池 (用于获取实例)
    llm_client: LLMClient               # LLM 客户端 (用于任务分解和结果聚合)
    event_bus: EventBus                 # 事件总线 (发布 Crew 生命周期事件)

    # ── 配置 ─────────────────────────────────────────
    max_parallel: int                   # 最大并行成员数 (从 Config.crew_max_parallel, 默认 4)
    crew_max_iterations: int            # Crew 级任务分解最大迭代 (从 Config.crew_max_iterations, 默认 3)
    plan_temperature: float             # 任务分解时的 LLM 温度 (从 Config.crew_plan_temperature, 默认 0.4)
    config: Config                      # 全局 Config 引用 — 除 Crew 专用配置外,
                                          # 还用于 agent_factory 中为 CrewMember 构造 Agent 实例时传递
                                          # Config (LLM 端点/密钥等), 以及 _aggregate_results 中读取
                                          # llm_temperature 等非 Crew 专用配置

    # ── 构造 ─────────────────────────────────────────
    def __init__(self, agent_registry: AgentRegistry,
                 agent_pool: AgentPool,
                 llm_client: LLMClient,
                 event_bus: EventBus,
                 config: Config) -> None:
        """
        初始化 CrewOrchestrator。
        - 绑定 AgentRegistry / AgentPool / LLMClient / EventBus
        - 存储 Config 引用到 self.config
        - 从 Config 读取 crew_max_parallel / crew_max_iterations / crew_plan_temperature
        """

    # ── Plan: 任务分解与 Agent 匹配 ───────────────────
    def plan_crew(self, mission: str,
                  lead_agent_name: str,
                  available_agents: list[AgentMeta] | None = None,
                  crew_leader_call_depth: int = 0
                  ) -> AgentCrew:
        """
        将 mission 分解为 SubTask 列表, 并为每个子任务匹配最佳 Agent。

        前置条件: mission 必须为非空字符串, 否则抛出 ValueError
        (空 mission 无法被 LLM 合理分解, 会导致无意义的 LLM 调用)。

        内部流程:
        1. 构建分解 Prompt (含可用 Agent 列表与能力描述)
           Prompt 要求 LLM 为每个 SubTask 输出临时标识符 (如 "task_1", "task_2"),
           并在 dependencies 中使用这些临时标识符引用依赖关系。
           LLM 不应自行生成 UUID — 框架会在后续步骤中替换为真正的 UUID v4。
        2. LLM 分析 mission (使用 self.plan_temperature 温度),
           输出结构化子任务列表 (JSON)
           - 若 LLM 输出无法解析为有效 JSON, 进行最多 crew_max_iterations 次重试,
             每次重试将解析错误作为反馈发送给 LLM 要求修正格式
           - 若全部重试耗尽仍失败, 抛出 CrewPlanError (含原始 LLM 输出供调试)
        2a. 生成正式 task_id:
           - 为每个 SubTask 生成真正的 UUID v4 作为 task_id
           - 构建临时标识符 → 正式 UUID 的映射表
           - 遍历所有 SubTask.dependencies, 将临时标识符引用替换为正式 UUID
           - 此步骤确保 task_id 全局唯一且依赖引用可靠,
             LLM 无法可靠生成 UUID v4, 因此不能依赖 LLM 输出作为正式标识符
        3. 每个子任务通过 AgentRegistry.match_agent() 匹配最佳 Agent
           - 若某个 SubTask 匹配失败 (无 Agent 满足 required_tags 或匹配得分低于阈值),
             抛出 CrewPlanError(f"no agent matched for subtask '{task_id}'"),
             避免构建出 agent_cls=None 的无效 CrewMember
        4. 校验依赖完整性:
           - 收集所有 SubTask.task_id → 构建合法 task_id 集合
           - 遍历每个 SubTask.dependencies, 检查其中每个 task_id 是否存在于集合中
           - 若引用了不存在的 task_id, 抛出 CrewPlanError(f"dependency '{dep}' not found")
           - 若存在循环依赖 (DFS 检测), 抛出 CrewPlanError("circular dependency detected")
           (步骤 2a 已确保 dependencies 使用正式 UUID, 因此此处校验的是最终标识符)
        5. 构建 AgentCrew:
           - 生成 crew_id (UUID v4)
           - 填充 CrewMember 列表
           - 设置 created_at = time.time()
           - 设置 crew_leader_call_depth = 参数 crew_leader_call_depth
             (由 BaseAgent.form_crew 传入 self.config.call_depth,
              供 execute_crew 为成员构建 AgentConfig 时计算 call_depth + 1)
           - completed_at 保持默认值 0.0 (由 execute_crew 在执行完成时设置)
        6. 发布 CrewLifecycleEvent.PLANNED (携带 CrewEvent 负载)

        返回已组建但尚未执行的 AgentCrew (status=ASSEMBLED)。

        若 available_agents 为 None, 则默认从 self.agent_registry.list_agents()
        获取全部已注册 Agent 的元数据, 确保任务分解时 LLM 了解所有可用的 Agent 能力。
        """

    # ── Execute: Crew 执行 ────────────────────────────
    def execute_crew(self, crew: AgentCrew,
                     strategy: ExecutionStrategy = ExecutionStrategy.SEQUENTIAL,
                     max_parallel: int | None = None
                     ) -> CrewResult:
        """
        按指定策略执行 Crew。

        前置条件:
        - crew.status 必须为 ASSEMBLED, 否则抛出 CrewInvalidStateError
        - crew.members 必须非空, 否则抛出 ValueError("crew has no members to execute")
          (空列表表示 plan_crew 未正确分解 mission, 或 LLM 返回了空 SubTask 列表)

        内部流程:
        1. 校验 crew.status == "ASSEMBLED", 不满足则抛出 CrewInvalidStateError
        2. 校验 len(crew.members) > 0, 不满足则抛出 ValueError
        3. 设置 crew.status = "RUNNING"
        4. 发布 CrewLifecycleEvent.STARTED (携带 CrewEvent 负载, 含 crew_id 和 strategy)
        5. 根据 strategy 分发:
           - SEQUENTIAL → _execute_sequential(crew)
           - PARALLEL   → _execute_parallel(crew, max_parallel if max_parallel is not None else self.max_parallel)
             (max_parallel 为 None 时回退到 self.max_parallel, 即 Config.crew_max_parallel;
              使用 `is not None` 判断而非 `or`, 因为 0 是合法的并发限制值, 不应被回退覆盖)
           - DAG        → _execute_dag(crew, max_parallel if max_parallel is not None else self.max_parallel)
             (DAG 就绪队列并发执行也受 max_parallel 限制, 防止无限线程创建)
        6. 在各执行方法内部, 每个成员执行: AgentPool.acquire → agent.run(task) → AgentPool.release
           每个成员必须使用 try/finally 确保 AgentPool.release 在异常时也被调用,
           避免 AgentPool 实例泄漏:
           ```
           # AgentPool.acquire 第二参数为工厂函数 (零参数 callable), 用于按需创建新实例;
           # 工厂内部需传递 Agent 类所需的全部构造参数 (name/description/config/agent_config),
           # 这些参数可从 CrewLeader 继承 (如 config) 或从 CrewMember 元数据获取
           # 关键: agent_config 必须设置 call_depth = crew.crew_leader_call_depth + 1,
           #   使 Crew 嵌套递归深度限制正确向下传播 (与 launch_agent 保护机制一致)
           try:
               member.agent_instance = agent_pool.acquire(member.agent_name,
                   agent_factory=lambda: member.agent_cls(
                       name=member.agent_name,
                       description=agent_registry.get_agent_meta(member.agent_name).description,
                       config=self.config,  # 继承全局 Config (LLM 端点/密钥等)
                       agent_config=AgentConfig(
                           call_depth=crew.crew_leader_call_depth + 1)))
           except Exception as e:
               # acquire 失败 (如 AgentPool 耗尽或工厂函数异常) —
               # 标记为 FAILED 并跳过此成员, 不终止整个 Crew 执行
               member.status = "FAILED"
               member.result = AgentResult(
                   success=False, final_answer=str(e),
                   iterations=[], token_usage=TokenUsage(),
                   total_duration_ms=0, finish_reason=FinishReason.ERROR,
                   error=ToolExecutionError(str(e)))
               member.completed_at = time.time()
               continue  # 跳过此成员, 继续处理下一个 (SEQUENTIAL) 或释放槽位 (PARALLEL/DAG)
           try:
               member.status = "RUNNING"
               member.started_at = time.time()
               member.result = member.agent_instance.run(
                   member.task.description, member.task.context)
               member.status = "DONE"
           except Exception as e:
               member.status = "FAILED"
               member.result = AgentResult(
                   success=False, final_answer=str(e),
                   iterations=[], token_usage=TokenUsage(),
                   total_duration_ms=0, finish_reason=FinishReason.ERROR,
                   error=ToolExecutionError(str(e)))
           finally:
               member.completed_at = time.time()
               agent_pool.release(member.agent_instance)
           ```
           (每个成员执行时发布 MEMBER_STARTED / MEMBER_COMPLETED / MEMBER_FAILED,
            MEMBER_COMPLETED 携带 duration_ms=completed_at-started_at,
            MEMBER_FAILED 携带 error_message)
        7. 设置 crew.completed_at = time.time() (记录完成时间戳, 用于计算 wall-clock 总耗时)
        8. 汇总所有成员结果 → 调用 _aggregate_results(crew, results)
           (_aggregate_results 内部以 crew.completed_at - crew.created_at 计算 total_duration_ms)
        9. 根据聚合结果设置 crew.status = "COMPLETED" (全部成功) 或 "FAILED" (有失败成员)
        10. 发布 CrewLifecycleEvent.COMPLETED 或 FAILED (携带 CrewEvent 负载)
        11. 返回 CrewResult
        """

    def _execute_sequential(self, crew: AgentCrew) -> list[tuple[str, str, AgentResult]]:
        """
        串行执行 — 按 members 列表顺序依次执行每个成员。

        执行前校验: 每个 member.task 必须非 None, 否则抛出 ValueError
        (task 为 None 表示 plan_crew 阶段未正确分配子任务)。

        每个成员执行时, 将 SubTask 映射为 agent.run() 参数:
        - agent.run(user_input=task.description, context=task.context)

        首个成员使用 plan_crew 阶段分配的原始 task.context (无 previous_result),
        若 task.context 为 None 则直接传递 None 给 agent.run()
        (agent.run() 的 context 参数接受 dict | None, None 表示无可用的上下文数据),
        后续每个成员执行前, 将前一成员的结果合并入 context:
        - 若 task.context 为 None, 先初始化为空 dict {}
        - context["previous_result"] = 前一成员的 final_answer
        - context["previous_error"] = 前一成员的错误信息 (如有)

        前一成员的结果 (final_answer) 自动作为后一成员的 task.context 传入,
        确保信息在任务链中流动。context 合并策略: 保留原有 task.context 的键,
        新增 "previous_result" 键存储前一成员的 final_answer,
        若键冲突则以新增的 "previous_result" 为准。

        设计说明: 仅传递 final_answer 字符串而非完整 AgentResult 是有意简化 —
        final_answer 是 LLM 可直接理解的文本, 而 AgentResult 的结构化数据
        (iterations, token_usage 等) 对下游 LLM 的语义理解帮助有限且消耗 context token。
        若下游任务需要上游的完整结构化结果, 应使用 DAG 策略并在 task.context 中
        显式包含所需字段。

        适用于有强顺序依赖的任务链。

        若任一成员失败, 默认继续执行后续成员 (不立即终止),
        失败信息会通过 context["previous_error"] 传递给后续成员作为上下文参考。

        返回的 list[tuple[str, str, AgentResult]] 按执行顺序排列 (即 members 列表顺序),
        每个 tuple 为 (agent_name, task_id, AgentResult),
        此顺序即 execution_order (task_id 列表)。
        """

    def _execute_parallel(self, crew: AgentCrew,
                          max_parallel: int) -> list[tuple[str, str, AgentResult]]:
        """
        并行执行 — 并发执行所有成员 (受 max_parallel 限制)。

        执行前校验: 每个 member.task 必须非 None, 否则抛出 ValueError。

        每个成员执行时, 将 SubTask 映射为 agent.run() 参数:
        - agent.run(user_input=task.description, context=task.context)
        每个成员使用各自的 task.context (由 plan_crew 阶段设定),
        成员之间不共享运行时 context (因为任务间无依赖),
        但各自保留 plan 阶段分配的 task.context 数据。

        使用 concurrent.futures.ThreadPoolExecutor 实现并发控制。
        适用于成员间无依赖的独立子任务 (如同时搜索多个信息源)。

        若某成员失败, 不影响其他成员的执行 (任务间无依赖),
        失败信息记录在 member.result 中, 由 _aggregate_results 统一收集到 failed_members。

        返回结果按提交顺序排列 (通过遍历 futures 列表而非 as_completed 收集),
        与 members 列表顺序一致。返回的 list 顺序即 execution_order (task_id 列表)。
        """

    def _execute_dag(self, crew: AgentCrew, max_parallel: int) -> list[tuple[str, str, AgentResult]]:
        """
        DAG 执行 — 按依赖关系拓扑排序, 无依赖的成员可并行。

        执行前校验: 每个 member.task 必须非 None, 否则抛出 ValueError。

        每个成员执行时, 将 SubTask 映射为 agent.run() 参数:
        - agent.run(user_input=task.description, context=task.context)

        算法:
        1. 构建依赖图 (SubTask.dependencies → task_id → 被哪些 task 依赖)
        2. 检测循环依赖: 若依赖图中存在环 (拓扑排序无法找到入度为 0 的节点),
           抛出 CrewPlanError("circular dependency detected in DAG"),
           因为含环的 DAG 无法确定执行起点
        3. 找出所有入度为 0 的成员, 加入就绪队列
        4. 并发执行就绪队列中的所有成员 (受 max_parallel 限制,
           使用 ThreadPoolExecutor(max_workers=max_parallel))
        5. 每完成一个成员, 将其结果传递给所有依赖它的后续成员:
           context 合并策略 — 若 task.context 为 None, 先初始化为空 dict {};
           保留原有键, 新增 "dependency_results" 键 (dict[task_id, final_answer]),
           记录所有已完成的依赖任务结果, 供后续成员参考上游输出。
           若键冲突则以新增键为准, 确保上游结果不会被静默丢弃。
        6. 当某成员的所有依赖都已满足 (全部完成), 将其加入就绪队列
        7. 重复步骤 4-6 直到所有成员完成

        若某成员失败, 依赖它的后续成员仍会执行:
        失败信息通过 context["dependency_errors"] 传递 (dict[task_id, error_message]),
        不会因单点失败导致整个 DAG 阻塞。

        执行模型说明: 上述算法采用"波次" (wave) 模型 — 每轮找出所有就绪成员,
        并发执行, 全部完成后才检查新就绪成员并开始下一波。此模型实现简单,
        但在以下场景中并行槽位可能未充分利用: 某成员执行时间远短于同波其他成员时,
        它无法提前触发其下游成员进入就绪状态。未来版本可优化为连续流模型:
        使用有界信号量 (max_parallel) 控制并发, 任一成员完成时立即检查并
        提交新就绪成员到执行器, 使并行槽位始终保持饱和。

        线程安全: 并发执行时, 以下字段的读写必须通过 threading.Lock 保护:
        - crew.members[i].status — 防止两个线程同时判定依赖满足并重复执行
        - crew.members[i].result — 防止并发写入导致数据损坏
        - crew.members[i].task.context — 当多个上游成员同时完成时,
          它们会并发地向同一个下游成员的 context 中合并 dependency_results,
          若不加锁保护, context["dependency_results"] 字典可能被部分覆盖或损坏
        实现建议: 每个 CrewMember 使用独立 threading.Lock, 或对 context 合并操作
        使用 copy-on-write (先深拷贝原 context, 修改副本, 再原子赋值)。

        返回的 list[tuple[str, str, AgentResult]] 按完成顺序排列 (先完成的先出现),
        每个 tuple 为 (agent_name, task_id, AgentResult),
        此顺序即 execution_order (task_id 列表)。
        """

    # ── Aggregate: 结果聚合 ───────────────────────────
    def _aggregate_results(self, crew: AgentCrew,
                           results: list[tuple[str, str, AgentResult]]) -> CrewResult:
        """
        汇总所有成员结果:
        1. 遍历 results, 将每个 (agent_name, task_id, AgentResult) 拆分:
           - 若 AgentResult.success == True → 提取 final_answer
           - 若 AgentResult.success == False → 将 (agent_name, task_id) 记录到
             failed_members 列表, 提取 error 信息作为上下文
        2. 将所有 member final_answer 和失败信息拼接为上下文
        3. 调用 LLM 生成统一的 mission_summary:
           使用 Config.llm_temperature (默认 0.7) 而非 plan_temperature (默认 0.4),
           因为聚合任务是总结性工作, 需要一定的语言表达灵活性,
           而 plan_temperature 追求的是分解的结构稳定性。
           若 LLM 调用失败 (超时/限流/不可恢复错误), 降级为人工拼接:
           mission_summary = "\n\n".join([f"[{agent_name}] {result.final_answer}"
                                          for agent_name, task_id, result in results]),
           确保已完成的所有成员工作不会因聚合失败而丢失
        4. 计算 total_duration_ms 和 total_token_usage:
           - total_duration_ms = max(0, (crew.completed_at - crew.created_at)) * 1000
             (wall-clock 时间, 反映用户实际等待时长; 各成员的独立耗时可通过
             member_results 中每个 AgentResult.total_duration_ms 获取;
             使用 max(0, ...) 防止 completed_at 因异常路径未正确设置时产生负值,
             正常路径下 completed_at 由 execute_crew 步骤 7 保证设置)
           - total_token_usage = sum of all member token_usage
             (token 量可累加, 不受并发影响)
        5. 从 results 每个 tuple 中提取 task_id (第二个元素) 构建 execution_order,
           顺序与执行方法返回的 results 顺序一致
           (SEQUENTIAL: members 列表顺序; PARALLEL: 提交顺序;
            DAG: 拓扑完成顺序)
        6. 判定整体 success:
           - True: failed_members 为空 (全部成员 success=True 且无异常)
           - False: failed_members 非空, mission_summary 包含已完成部分 + 失败说明
        7. 构建并返回 CrewResult (含 failed_members 列表)
        """
```

### 9.3 Crew 事件类型

```python
class CrewLifecycleEvent(Enum):
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
    PLANNED = "planned"
    STARTED = "started"
    MEMBER_STARTED = "member_started"
    MEMBER_COMPLETED = "member_completed"
    MEMBER_FAILED = "member_failed"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class CrewEvent:
    """
    Crew 生命周期事件的负载数据 — 随 CrewLifecycleEvent 发布到 EventBus。

    不同事件类型携带不同的字段子集 (未携带的字段为 None):
    - PLANNED:          crew_id, lead_agent_name, member_count
    - STARTED:          crew_id, strategy
    - MEMBER_STARTED:   crew_id, member_name, task_id
    - MEMBER_COMPLETED: crew_id, member_name, task_id, duration_ms
    - MEMBER_FAILED:    crew_id, member_name, task_id, error_message
    - COMPLETED:        crew_id, total_duration_ms, token_usage
    - FAILED:           crew_id, error_message, partial_results
    """
    event_type: CrewLifecycleEvent           # 事件类型
    crew_id: str                             # Crew 唯一标识 (所有事件必带)
    lead_agent_name: str | None = None       # CrewLeader 名称 (PLANNED)
    member_name: str | None = None           # 成员 Agent 名称 (MEMBER_* 事件)
    task_id: str | None = None               # 子任务 ID (MEMBER_* 事件)
    member_count: int = 0                    # 成员总数 (PLANNED)
    strategy: str | None = None              # 执行策略 (STARTED)
    duration_ms: float = 0.0                 # 耗时 (MEMBER_COMPLETED, COMPLETED)
    token_usage: TokenUsage | None = None    # Token 用量 (COMPLETED)
    error_message: str | None = None         # 错误信息 (MEMBER_FAILED, FAILED)
    partial_results: list[tuple[str, str, AgentResult]] | None = None  # 部分成功结果 (FAILED 事件携带, 同 member_results 格式)
```

### 9.4 Crew 编排流程

```
CrewLeader (任意特化 Agent)
   │
   ├─ 1. 识别到任务需要多 Agent 协同
   │     (LLM 在 ReAct 循环中判断任务复杂度,
   │      通过已注册的 CrewTool 调用 launch_crew)
   │
   ├─ 2. 调用 self.launch_crew(mission, strategy)
   │     │
   │     ├─ 2a. form_crew(mission)
   │     │     └─ crew_orchestrator.plan_crew(mission, lead_agent_name, available_agents)
   │     │           ├─ LLM 分解 mission → SubTask[]
   │     │           ├─ AgentRegistry.match_agent() × N → CrewMember[]
   │     │           └─ 返回 AgentCrew (status=ASSEMBLED, created_at 已设置)
   │     │
   │     ├─ 2b. crew_orchestrator.execute_crew(crew, strategy)
   │     │     ├─ 校验 crew.status == ASSEMBLED → 设置 RUNNING
   │     │     ├─ SEQUENTIAL: [CodeAgent] → [DocAgent] → [ShellAgent]
   │     │     ├─ PARALLEL:   [CodeAgent | DocAgent | SearchAgent] (并发)
   │     │     └─ DAG:        [SearchAgent] → [CodeAgent] → [ShellAgent]
   │     │                            └──────────────→ [DocAgent]
   │     │     每个成员: acquire → run(task) → release (try/finally)
   │     │
   │     ├─ 2c. _aggregate_results()
   │     │     ├─ 拆分成功/失败成员 (提取 agent_name + task_id)
   │     │     ├─ LLM 生成 mission_summary
   │     │     └─ 构建 execution_order + 计算 token/duration
   │     │
   │     └─ 2d. 将 CrewResult.mission_summary 写入 ContextStore
   │
   ▼
返回 CrewResult, CrewLeader 将 mission_summary 作为 Observation 继续 ReAct 推理

注: 若需要手动审查/调整 Crew 成员, 可跳过 launch_crew(),
    直接调用 form_crew(mission) → 检查/修改 AgentCrew → execute_crew(crew, strategy)。
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

### 9.6 CrewTool — Crew 编排的 Tool 适配器

```python
class CrewTool(BaseTool):
    """
    将 BaseAgent.launch_crew() 包装为 Tool, 使得 LLM 可在 ReAct 循环中
    通过 Function Calling 发起 Crew 编排。

    与 AgentTool (单个 Agent 拉起) 互补:
    - AgentTool: 拉起单个指定 Agent → Tool 名 = Agent 名
    - CrewTool:  组建并执行 Agent 团队 → Tool 名固定为 "launch_crew"

    LLM 选择指南 (写入 system_prompt 的 Tool 使用说明):
    - 使用 launch_<agent> (AgentTool): 任务明确属于单一领域 (如"写一段代码"→CodeAgent,
      "查一下这个函数用法"→SearchAgent), 无需分解和协调
    - 使用 launch_crew (CrewTool): 任务涉及多个领域或阶段 (如"实现一个完整的 API 系统:
      需要代码+文档+测试"), 需要自动分解和协调多个 Agent
    """

    def __init__(self, agent: BaseAgent) -> None:
        """
        初始化 CrewTool。

        参数:
            agent: 发起 Crew 编排的 Agent 实例 (CrewLeader)。
                   Tool 执行时将调用 agent.launch_crew()。

        Tool 元数据:
            name: "launch_crew"
            description: "组建并执行一个 Agent 团队完成复杂使命。
                          自动将任务分解为子任务, 匹配最合适的 Agent,
                          按指定策略 (串行/并行/DAG) 执行, 并汇总结果。"
            parameters_schema: mission (required), strategy (optional), max_parallel (optional)
        """
        self.name = "launch_crew"
        self.description = (
            "组建并执行一个 Agent 团队 (Crew) 完成复杂使命。"
            "自动分解任务 → 匹配最佳 Agent → 按策略执行 → 汇总结果。"
            "适用场景: 需要多个领域 Agent 协同的复杂任务。"
        )
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "mission": {
                    "type": "string",
                    "description": "团队使命描述, 说明需要完成什么以及期望的结果"
                },
                "strategy": {
                    "type": "string",
                    "enum": ["sequential", "parallel", "dag"],
                    "description": "执行策略: sequential (串行), parallel (并行), dag (依赖拓扑)",
                    "default": "sequential"
                },
                "max_parallel": {
                    "type": "integer",
                    "description": "并行模式下最大并发成员数",
                    "default": 4
                }
            },
            "required": ["mission"]
        }
        self._agent = agent  # CrewLeader 实例
        self.tags = ["crew", "team", "orchestrate", "coordinate"]
        self.requires_confirmation = False

    def execute(self, **kwargs) -> ToolResult:
        """
        执行 = 发起 Crew 编排:
        1. 从 kwargs 提取 mission, strategy, max_parallel
        2. 调用 self._agent.launch_crew(mission, strategy, max_parallel)
        3. 将 CrewResult 转换为 ToolResult:
           - success → output = crew_result.mission_summary
           - failure → error = 失败描述
        4. 异常时捕获并包装为失败 ToolResult, 避免中断 ReAct 循环
        """
        try:
            # 所有参数提取和校验均放入 try 块, 确保任何异常 (含 KeyError/ValueError)
            # 都被捕获并转换为失败 ToolResult, 避免中断 ReAct 循环
            mission = kwargs["mission"]  # 若缺失则抛出 KeyError, 由 except 捕获
            strategy_str = kwargs.get("strategy", "sequential")
            max_parallel = kwargs.get("max_parallel")

            # 解析策略枚举 — 放入 try 块中以捕获非法 strategy 值 (如 LLM 幻觉产生的无效策略名),
            # 避免 ValueError 绕过异常处理直接中断 ReAct 循环
            strategy = ExecutionStrategy(strategy_str)
            crew_result = self._agent.launch_crew(
                mission=mission,
                strategy=strategy,
                max_parallel=max_parallel
            )

            return ToolResult(
                success=crew_result.success,
                output=crew_result.mission_summary,
                data=crew_result,          # 保留完整 CrewResult 供程序使用
                tool_name=self.name,
                duration_ms=crew_result.total_duration_ms
            )
        except Exception as e:
            # Crew 编排失败时, 将错误信息作为 Observation 反馈给 LLM,
            # 使 LLM 可以选择重试或采用替代方案
            return ToolResult(
                success=False,
                output=f"Crew 编排失败: {e}",
                error=str(e),
                tool_name=self.name
            )
```
