# Changelog — SpecialAgent Framework v1.0.0

## [v1.0.0] — 2026-05-01

### Infrastructure Layer (Phase 1)

**Global Configuration** (`src/infra/config.py`)
- 从环境变量加载全局配置, 使用 ANTHROPIC_* 命名体系
- 支持 LLM Provider 参数, Agent/Crew 参数, 上下文/日志/安全参数
- `from_env()` 类方法从环境变量构建配置
- `validate()` 方法校验必要配置项 (API Key, URL 格式, 参数范围)
- `to_provider_kwargs()` 导出为 LLMProvider 构造函数参数字典

**Logger** (`src/infra/logger.py`)
- AgentLogger 封装标准 logging, 支持 Agent 上下文
- 结构化日志: react_step / tool_call / llm_call

**Event System** (`src/events/`)
- AgentLifecycleEvent: INITIALIZED / STARTED / COMPLETED / ERROR / SPAWNED / STOPPED
- ToolCallEvent: BEFORE_EXECUTE / AFTER_EXECUTE
- LLMCallEvent: BEFORE_CALL / AFTER_CALL
- ReActIterationEvent: ITERATION_START / ITERATION_END
- CrewLifecycleEvent: PLANNED / STARTED / MEMBER_STARTED / MEMBER_COMPLETED / MEMBER_FAILED / COMPLETED / FAILED
- CrewEvent 数据负载类, ConfirmationRequestEvent 确认请求事件
- EventBus 发布-订阅模式, handler 异常隔离, 同步/异步发布

**LLM Integration** (`src/llm/`)
- LLMProvider Protocol: 定义 chat / chat_stream / achat / achat_stream / health_check
- OpenAICompatProvider: httpx 实现, 指数退避重试, LLM 错误分类 (Auth/RateLimit/Server/Timeout/ContentFilter)
- LLMClient Facade: 封装重试/日志/Token统计, 同步和异步接口
- TokenTracker: 累计 Token 用量统计, 按会话聚合

### Core Layer (Phase 2)

**Data Models** (`src/core/models.py`)
- Message: 对话消息 (system/user/assistant/tool), 支持 tool_calls
- ToolCall: Function Call 数据结构
- TokenUsage: Token 用量统计, 支持加法操作
- ChatResponse: LLM 响应封装
- AgentState: IDLE → RUNNING → DONE/ERROR 状态机
- FinishReason: DONE / MAX_ITERATIONS / CONSECUTIVE_FAILURES / STOPPED / LLM_UNRECOVERABLE / ERROR
- ExecutionStrategy: SEQUENTIAL / PARALLEL / DAG
- ParseMethod: TEXT_REACT / FUNCTION_CALL / FALLBACK
- AgentConfig: Agent 级配置, 可覆写全局参数
- AgentError 体系: LLMCallError / ToolExecutionError / ToolNotFoundError / AgentDepthExceededError / AgentTimeoutError
- ReAct 结果类型: ParsedAction / ParsedReAct / ActionResult / ReActStep / ReActResult / AgentResult

**ReAct Parser** (`src/core/react_parser.py`)
- FunctionCallParser: 解析 LLM 原生 tool_calls
- ReActParser: 解析 Thought/Action/Final Answer 文本标签
- FallbackParser: 启发式回退解析 (关键词+长度)
- CompositeParser: 三级组合解析器链

**Tool System** (`src/tools/`)
- BaseTool ABC: name / description / parameters_schema / tags / requires_confirmation
- ToolResult 数据类, ToolArgValidationError / ToolNameConflictError
- ToolSecurityPolicy: 文件目录白名单, Shell命令白名单, URL协议限制, 确认策略
- ToolManager: register / unregister / execute / execute_with_timeout
- JSON Schema 参数验证 (类型/必填/枚举)
- 批量注册原子操作 (全部校验通过后注册)
- Built-in Tools:
  - ReadFileTool / WriteFileTool / ListFilesTool: 文件操作, 路径安全控制
  - RunShellTool: 命令白名单/危险模式黑名单, 子进程超时控制
  - SearchCodeTool: regex 搜索, 文件类型过滤, 上下文行
  - WebFetchTool / WebSearchTool: URL 协议检查, HTML 剥离
  - AgentTool: 将 Agent 包装为 Tool, A→B 代理调用
  - CrewTool: 将 Crew 编排包装为 Tool

**Match Strategies** (`src/strategies/match_strategy.py`)
- MatchStrategy Protocol: 可替换匹配策略接口
- ExactMatchStrategy: 精确名称匹配 (大小写/连字符/下划线归一化)
- FuzzyMatchStrategy: 关键词加权匹配 (名称×2 / 描述×1 / 标签×1.5)
- SemanticMatchStrategy: Jaccard 语义相似度 (可升级为嵌入相似度)
- AgentMatchStrategy: Agent 注册中心匹配
- MatchStrategyChain: 策略链组合, 按优先级依次尝试

**Context Compression** (`src/strategies/compress_strategy.py`)
- CompressStrategy Protocol: 可替换压缩策略接口
- SlidingWindowStrategy: 滑动窗口 (保留最近 N 条 + system message)
- SummarizeStrategy: LLM 摘要压缩 (退化为滑动窗口)
- HybridStrategy: 截断旧 Tool 输出 → 摘要 → 滑动窗口, 逐步收紧

**Crew Independent Directory** (`src/crew/`)
- SubTask: 子任务模型, UUID 标识, 依赖关系, 上下文传递
- CrewMember: Agent → SubTask 绑定, PENDING → RUNNING → DONE/FAILED
- AgentCrew: 团队模型, ASSEMBLED → RUNNING → COMPLETED/FAILED
- CrewResult: 聚合结果, 成员结果列表, 执行顺序, Token 统计
- CrewPlanError / CrewInvalidStateError: Crew 专用错误类型
- CrewOrchestrator: plan_crew() LLM 任务分解, execute_crew() 多策略执行
  - _execute_sequential: 串行, 前序结果传递
  - _execute_parallel: ThreadPoolExecutor 并发
  - _execute_dag: 拓扑排序, 无依赖并行
  - _aggregate_results: LLM 生成 mission_summary

### Agent System (Phases 2-5)

**BaseAgent** (`src/core/base_agent.py`)
- ABC 基类, 完整 Agent 能力: LLM + ReAct + Tool + Crew
- system_prompt (abstract) + register_tools (abstract)
- run(): 状态校验 → 钩子 → ReAct 循环 → 结果返回
- _build_system_message(): 系统提示 + Tool 列表 + Agent 列表
- launch_agent(): 子 Agent 拉起, 深度检查
- form_crew() / launch_crew(): Crew 编排入口

**AgentRegistry** (`src/core/agent_registry.py`)
- register(): 校验 BaseAgent 子类, 缓存 AgentMeta
- register_from_module(): 动态导入模块扫描
- match_agent(): 关键词匹配 + 描述相似度匹配
- launch(): acquire → run → release
- get_agent_tools_schema(): Agent 转为 Function Calling Schema

**AgentPool** (`src/core/agent_pool.py`)
- acquire(): 复用空闲实例 / 创建新实例 (上限检查)
- release(): 重置状态 + 标记空闲
- 线程安全 (Condition), 空闲超时回收

**ContextStore** (`src/core/context_store.py`)
- 消息管理: add_message / get_messages_for_llm (自动压缩)
- ReAct 轨迹记录: add_react_step / get_react_trajectory
- 上下文变量: set_variable / get_variable
- Tool 结果缓存: MD5 hash key, 幂等调用优化
- 导出/导入快照: export_snapshot / import_snapshot

**ReActEngine** (`src/core/react_engine.py`)
- run(): Thought → Action → Observation 循环
- 终止条件: Final Answer / MAX_ITERATIONS / CONSECUTIVE_FAILURES / STOPPED / LLM_UNRECOVERABLE
- _force_summarize(): 强制总结兜底
- 可注入策略: match_strategy / output_parser

**SessionManager** (`src/core/session_manager.py`)
- 多会话管理: create / switch / delete / clear
- 导出/导入: JSON 序列化, 上下文快照
- 可选持久化: save_to_disk / _load_from_disk

**PluginLoader** (`src/core/plugin_loader.py`)
- discover(): 目录扫描 + entry_points
- validate_plugin(): BaseAgent 子类校验 (name/description/system_prompt/register_tools)
- 隔离加载: 独立命名空间, 错误隔离

### Specialized Agents (`src/agents/`)

- **CodeAgent**: tags=[code/programming/debug/refactor/test], temperature=0.3, max_iterations=15
- **DocAgent**: tags=[doc/documentation/readme/api/manual], temperature=0.6, max_iterations=10
- **SearchAgent**: tags=[search/find/query/research], temperature=0.4, max_iterations=8
- **ShellAgent**: tags=[shell/command/execute/terminal], temperature=0.2, max_iterations=6

### Entry Point (`src/main.py`)

- 单次查询模式: 命令行参数, 执行后退出
- REPL 模式: 交互式循环, 支持 /exit /help /agents /tools /history /clear /session /sessions /stats /debug
- 自动特化 Agent 调度

### Tests (`tests/`)

- test_config.py: 13 tests — 默认值, 环境变量加载, 校验 (API Key/URL/Temperature/Timeout), 导出
- test_models.py: 18 tests — TokenUsage, Message, ChatResponse, AgentState, FinishReason, ExecutionStrategy, AgentConfig, AgentError 子类, ParsedReAct
- test_react_parser.py: 16 tests — FunctionCallParser, ReActParser, FallbackParser, CompositeParser
- test_event_bus.py: 8 tests — 订阅/发布, 取消订阅, 异常隔离, 类型过滤, 清除
- test_tool_manager.py: 18 tests — 注册/注销, 批量操作, 名称冲突, 执行, 参数验证, 超时, 导出
- test_context_store.py: 16 tests — 消息操作, ReAct 轨迹, 变量操作, 缓存, 导出/导入, 压缩
- test_agent_registry.py: 18 tests — 注册, 元数据, 查找, 匹配(关键词/描述相似度), 导出
- test_strategies.py: 27 tests — ExactMatch, FuzzyMatch, SemanticMatch, AgentMatch, StrategyChain, SlidingWindow, Summarize, Hybrid
- test_crew_models.py: 10 tests — SubTask, CrewMember, AgentCrew, CrewResult, Crew 错误类型
- test_llm_client.py: 9 tests — TokenUsage 加法, TokenTracker record/get/reset
- test_integration.py: 15 tests — Config 端到端, ToolManager 端到端, EventBus 端到端, ReActEngine 端到端, SessionManager 端到端, CrewOrchestrator 端到端

**Total: 181 tests, all passing**

### Plugin System (`plugins/`)

- example_agent.py: 示例插件 Agent 模板, 展示完整实现模式

---

## Architecture Decisions

1. **Crew 独立目录**: Crew 相关功能 (`src/crew/`) 完全独立于 Core Agent 逻辑, 通过 CrewOrchestrator 驱动
2. **公共代码共享**: infra (Config, Logger) + core (Models, Engine) + tools (BaseTool) 作为共享层
3. **Agent 作为 Tool**: AgentRegistry + AgentTool 实现 Agent 之间的代理调用, 语义集成
4. **策略可注入**: MatchStrategy / CompressStrategy / OutputParser 均为 Protocol, 支持依赖注入
5. **事件驱动**: EventBus 发布-订阅解耦, handler 异常不影响主流程
6. **LLM 后端无关**: LLMProvider Protocol + OpenAICompatProvider, 可扩展支持其他后端
