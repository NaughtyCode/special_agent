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
        同时生成对应的 AgentTool 元数据以供导出。
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
                 idle_timeout: float = 300.0) -> None:
        """
        初始化。
        - max_instances: 最大并发实例数 (None = 无限制)
        - idle_timeout: 实例空闲超时 (秒), 超时后回收
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
| `launch_<agent>` | 拉起特化 Agent (由 AgentRegistry 动态生成) | `task: str, context: dict | None` | 取决于子 Agent |

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
