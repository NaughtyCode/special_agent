# 修改记录 — Issue #2 (Agent 框架计划审查修复)

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue2-agent |
| 修改日期 | 2026-04-30 |
| 修改类型 | 计划优化 — 审查修复与表达增强 |
| 关联文档 | `agent_doc/plan/` (全部 9 个文件) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 `agent_doc/plan/` 下的全部 9 个计划文档进行系统审查，修复发现的问题，并优化所有表述，使其具备更强、更普适、更灵活、更泛化的表达能力。

## 修改原则

1. **消除硬编码** — 将所有魔数替换为命名配置参数或可配置常量
2. **提升抽象层级** — 将具体实现细节（如 DeepSeekV4Client）替换为抽象概念（如 LLMProvider / LLMClient）
3. **增加扩展点** — 为关键组件添加策略模式/钩子/回调注入，支持自定义行为
4. **厂商无关化** — 将 DeepSeek 特定的类名/概念泛化为 provider-agnostic 设计
5. **完善错误处理** — 补全原有的错误处理缺口，增加错误传播路径和分类体系
6. **修复实际 Bug** — 修正类型名不一致、缺失状态转移、缺失配置项等问题

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/00_architecture_overview.md` | 全面重写 |
| 2 | `agent_doc/plan/01_base_agent.md` | 全面重写 |
| 3 | `agent_doc/plan/02_react_engine.md` | 全面重写 |
| 4 | `agent_doc/plan/03_tool_system.md` | 全面重写 |
| 5 | `agent_doc/plan/04_deepseek_client.md` | 全面重写 (重构为 LLM Client + Provider 模式) |
| 6 | `agent_doc/plan/05_root_agent.md` | 全面重写 |
| 7 | `agent_doc/plan/06_specialized_agents.md` | 全面重写 |
| 8 | `agent_doc/plan/07_context_and_infra.md` | 全面重写 |
| 9 | `agent_doc/plan/08_implementation_roadmap.md` | 全面重写 |

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 10 | `changelog/change_record_issue2_agent.md` | 本修改记录 |

## 详细变更内容

### 1. 00_architecture_overview.md — 架构总览

**修复的问题：**
- 架构图中 `DeepSeekV4Client` 硬绑定具体厂商 → 改为 `LLMClient` + `LLMProvider` Protocol 分层
- 数据流缺少错误处理路径 → ReAct 循环增加完整的错误分支（超时、限流、不可恢复错误）
- Agent 拉起流程缺少：Agent 实例复用、调用栈深度控制、结果校验 → 全部补全
- 模块依赖图中缺少策略注入和事件总线 → 新增 MatchStrategy、CompressStrategy、EventBus
- 文件结构中缺少 strategies/、events/、agent_pool、plugin_loader → 全部补充

**增强的表达能力：**
- 各层职责表新增"扩展点"列，标注每层可定制的策略注入点
- 架构分层图新增 LLMProvider 子层结构 (Interface → OpenAICompatProvider → CustomProvider)
- 新增 Agent 间通信 → 同步调用 + 返回值，符合父子任务语义
- 关键技术决策表从 6 项扩展到 10 项 (新增 LLM 后端抽象、Tool 匹配策略、上下文压缩、事件通知、Agent 实例化)
- 项目概述从"支持 DeepSeek V4 API"泛化为"通过 OpenAI-compatible API 调用大语言模型"

### 2. 01_base_agent.md — BaseAgent 设计

**修复的问题：**
- `max_iterations: int = 10` 硬编码 → 从 `AgentConfig` 读取
- `chat()` 返回类型 `LLMResponse` 与数据模型 `ChatResponse` 不一致 → 统一为 `ChatResponse`
- `llm_client: DeepSeekV4Client` 类型绑定 → 改为 `llm_client: LLMClient` (Facade)
- 状态机缺少 STOPPING/STOPPED 状态 → 新增停止流程
- `run()` 异常处理仅设置 ERROR 状态，未说明发布事件 → 补全 `AgentLifecycleEvent.ERROR`
- 缺少 Agent 级配置 → 新增 `AgentConfig` 数据类 (8 个可覆写字段)
- 缺少钩子方法 → 新增 `_on_before_react_loop` / `_on_after_react_loop`
- 缺少错误分类 → 新增 `AgentError` 体系 (5 个子类，含 recoverable 标记)

**增强的表达能力：**
- `BaseAgent` 从 10 属性/10 方法 → 扩展为 14 属性/18 方法
- 新增 `AgentConfig`: 每个 Agent 可独立调参 (max_iterations, temperature, model, call_depth 等)
- 新增错误分类：LLMCallError / ToolExecutionError / ToolNotFoundError / AgentDepthExceededError / AgentTimeoutError
- 新增 `reset()` 方法：重置 Agent 到初始状态而不重建实例
- 新增 `_validate_state_transition()`: 状态转移合法性校验
- 子类化指南补充钩子覆写示例 (加载领域知识、审计日志记录)

### 3. 02_react_engine.md — ReAct 引擎

**修复的问题：**
- `max_iterations: int = 10` 硬编码 → 从 Config/AgentConfig 合并读取
- 连续失败 `3 次` 硬编码 → `max_consecutive_failures` 可配置
- Tool 执行无超时控制 → 新增 `tool_execution_timeout` 参数
- 解析失败无恢复策略 → 新增 "将原始输出反馈 LLM 要求重新格式化"
- 引擎直接依赖 `DeepSeekV4Client` → 改为 `LLMClient`
- 缺少停止机制 → 新增 `request_stop()` 和 `_stop_requested` 标志

**增强的表达能力：**
- 新增 `MatchStrategy` 注入点: 精确 → 模糊 → 语义 → Agent 四级策略链
- 新增 `OutputParser` 注入点: CompositeParser(ReActParser + FunctionCallParser + FallbackParser)
- 新增 `CompressStrategy` 用于 Prompt 构建
- `ParsedReAct` 新增 `parse_method` 和 `raw_response` 字段 (调试与审计)
- `ReActStep` 新增 `action_result`, `llm_response`, `duration_ms`, `token_usage` 字段
- `ReActResult` 重构: 新增 `FinishReason` 枚举 (5 种终止原因)
- 终止条件从 4 种扩展到 5 种 (新增 LLM_UNRECOVERABLE)

### 4. 03_tool_system.md — Tool 系统

**修复的问题：**
- `top_k: int = 5` 硬编码 → 在 FuzzyMatchStrategy 内可配置
- `execute()` 无参数校验 → 新增 `validate_args()` 步骤
- 缺少 Tool 执行超时 → 新增 `execute_with_timeout()`
- 缺少安全机制 → 新增完整的 `ToolSecurityPolicy` + `sanitize_args` 方法
- AgentRegistry 无实例池管理 → 新增 `AgentPool` (复用/并发控制/空闲回收)

**增强的表达能力：**
- `BaseTool` 新增 `tags`, `requires_confirmation` 属性
- `ToolManager` 新增 `register_many` (批量原子注册), `list_tools_by_tag` (按标签筛选)
- 匹配策略从 4 级描述 → 独立策略类体系: `MatchStrategy` Protocol + `MatchStrategyChain` + 4 个实现类
- `AgentPool`: 解决 Agent 实例的惰性创建、复用和并发控制问题
- `ToolSecurityPolicy`: 9 个安全配置项 (目录白名单、命令白名单、文件大小限制、URL 协议限制、确认策略)
- 内置 Tool 表新增"风险等级"列
- 新增 `register_from_module`: 从模块路径批量注册 Agent (插件发现)
- `AgentResult → ToolResult` 转换逻辑：success → output，failure → error

### 5. 04_deepseek_client.md → LLM Client + Provider

**修复的问题：**
- **类名 `DeepSeekV4Client` 绑定厂商** → 重构为 `LLMProvider` (Protocol) + `OpenAICompatProvider` + `LLMClient` (Facade)
- **配置字段 `DEEPSEEK_*` 绑定厂商** → 全部改为 `LLM_*` provider-agnostic 命名
- 默认值硬编码 (`"https://api.deepseek.com"`, `"deepseek-chat"`, `4096`, `0.7`, `60`, `3`) → 保留默认值但全部可通过环境变量覆盖
- 缺少 Provider 健康检查 → 新增 `health_check()` 方法
- 缺少 Token 追踪 → 新增 `TokenTracker` 类
- `_should_retry` 无退避计算 → 新增 `_calculate_backoff` (指数退避 + 抖动)

**增强的表达能力：**
- **Provider 模式**: `LLMProvider` Protocol 定义抽象契约，`OpenAICompatProvider` 为默认实现，用户可实现自定义 Provider
- **LLMClient Facade**: 封装重试、日志、Token 统计，对上层透明
- 环境变量兼容: 新增 `DEEPSEEK_*` 回退支持 (平滑迁移)
- 新增 9 个环境变量: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_BASE_DELAY`, `LLM_MAX_DELAY`
- `TokenUsage` 支持 `__add__` 累加操作
- `ChatResponse` 新增 `request_id` 字段 (请求追踪)
- `Message` 新增 `tool_calls` 字段 (Assistant 消息携带 FC 请求)
- 错误体系从 5 类扩展为 6 类 (新增 `LLMContentFilterError`)
- `TokenTracker`: 支持按会话/按 Agent/按时间聚合统计

### 6. 05_root_agent.md — RootAgent

**修复的问题：**
- 提示符 `">> "` 硬编码 → `repl_prompt` 可配置
- `_register_builtin_agents()` 中硬编码 Agent 类 → 新增插件加载机制
- Agent 匹配仅有关键词 → 扩展为三级路由策略 (关键词 → LLM 路由 → 描述相似度)
- 缺少错误恢复 → REPL 中 Ctrl+C 中断当前执行而不退出
- 缺少 Agent 调用栈深度控制 → 通过 AgentConfig.call_depth 限制

**增强的表达能力：**
- 新增 `repl_welcome_message`, `enable_syntax_highlight` 配置
- 新增 `/stats`, `/debug`, `/sessions` 命令
- 三级路由策略: 关键词快速匹配 (≤1ms) → LLM 智能路由 (~API 响应时间) → 描述相似度兜底 (~10ms)
- `SessionManager` 新增: `delete_session`, `export_session`, `import_session` (支持持久化与分享)
- 新增 `AgentPluginLoader`: 目录扫描 + `entry_points` 发现 + 隔离加载 + 错误隔离
- REPL 流程图增强: 增加 `_format_result_display` 步骤 (区分来源 Agent)

### 7. 06_specialized_agents.md — 特化 Agent

**修复的问题：**
- `register_tools()` 中 Tool 类名直接硬编码 → 补全 import 路径说明
- 缺少 Agent 级配置 → 每个 Agent 增加 `AgentConfig` 初始化示例
- DocAgent 缺少 web_search Tool → 新增 (查找外部参考)
- Agent 缺少标签 → 新增 `tags` 属性 (辅助匹配)

**增强的表达能力：**
- 每个 Agent 增加 `tags` 属性 (用于关键词匹配和分类)
- 每个 Agent 增加 AgentConfig 覆写示例 (温度、迭代次数)
- CodeAgent system_prompt 补充: "注释说明 WHY 而非 WHAT"、"主动生成测试"、"不确定时确认"
- DocAgent system_prompt 补充: "使用 Mermaid 语法绘制架构图"、"大型项目先给大纲"
- ShellAgent system_prompt 补充: "破坏性操作需确认"、"超长输出截断提示"
- 协作模式从 3 种扩展为 4 种: 新增 Router 协作模式
- 新增"Agent 配置最佳实践"表 (5 个 Agent 的推荐 temperature 和 max_iterations)

### 8. 07_context_and_infra.md — 上下文与基础设施

**修复的问题：**
- `max_tokens: int = 8000` 硬编码 → 从 `Config.context_max_tokens` 读取 (默认 64000)
- 上下文压缩仅文字描述 → 新增 `CompressStrategy` Protocol + 3 种实现
- 缺少事件系统 → 新增 `EventBus` 发布-订阅模式
- Config 字段全部 `deepseek_*` 前缀 → 全部改为 `llm_*` provider-agnostic
- 缺少安全配置 → 新增 5 个安全配置项

**增强的表达能力：**
- 目录结构从 26 文件扩展到 42 文件 (新增 strategies/, events/, agent_pool, plugin_loader, search_tools, web_tools)
- `ContextStore` 新增: `estimate_tokens`, `get_last_n_steps`, `get_all_variables`, `export_snapshot`, `import_snapshot`
- 三种压缩策略: SlidingWindowStrategy (简单高效), SummarizeStrategy (语义保留), HybridStrategy (默认, 兼顾)
- `EventBus`: 4 类事件 (AgentLifecycle / ToolCall / LLMCall / ReActIteration) + sync/async publish
- Config 兼容策略: `LLM_*` 优先 → `DEEPSEEK_*` 回退 → 默认值
- 依赖项: 核心 (httpx/pydantic/pydantic-settings) + 可选 (tiktoken/sentence-transformers/rich/readchar)
- Config 新增 `validate()` 方法: API Key 非空、URL 格式、数值范围

### 9. 08_implementation_roadmap.md — 实现路线图

**修复的问题：**
- Phase 1 缺少 EventBus 和 LLMProvider 接口定义任务 → 新增 1.4/1.5
- Phase 2 缺少策略体系实现任务 → 新增 2.5 (MatchStrategy) / 2.7 (CompressStrategy)
- Phase 2 缺少 AgentPool → 并入 2.6
- 缺少安全测试阶段 → 纳入 Phase 6 端到端验证
- 依赖关系图缺少新增模块 → 完全重绘

**增强的表达能力：**
- 任务数从 18 扩展到 28 (+56%)
- Phase 1: 4→8 任务 (新增 EventBus, Provider, Facade)
- Phase 2: 8→11 任务 (新增 MatchStrategy, CompressStrategy)
- Phase 3: 4→5 任务 (新增 SearchTool)
- Phase 4: 4→5 任务 (新增 Agent 级测试)
- Phase 5: 4→5 任务 (新增 PluginLoader)
- Phase 6: 3→4 任务 (新增示例插件 Agent)
- 关键技术要点从 4 项扩展到 6 项 (新增 LLM 后端可替换性、可扩展性设计)

## 问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 硬编码值消除 | 30+ | 所有魔数替换为可配置参数 (max_iterations, top_k, max_tokens, timeout, retries 等) |
| Bug 修复 | 8 | 类型不一致 (LLMResponse→ChatResponse)、缺失状态转移 (STOPPING/STOPPED)、缺失 Tool 超时、字段缺失 (call_depth, tags) |
| 缺失类型/接口补充 | 12 | LLMProvider, MatchStrategy, CompressStrategy, AgentPool, EventBus, TokenTracker, AgentConfig, AgentError 体系, FinishReason, AgentPluginLoader, ToolSecurityPolicy, SessionManager 新增方法 |
| 缺失配置项补充 | 20+ | AgentConfig (8 字段), ToolSecurityPolicy (9 字段), Config 新增字段 (5 安全 + 2 重试 + 2 Agent + 2 插件) |
| 命名泛化 (去厂商绑定) | 15+ | DeepSeekV4Client→LLMClient/LLMProvider, deepseek_*→llm_*, DeepSeek*Error→LLM*Error |
| 抽象层级提升 | 8 | LLMProvider Protocol, MatchStrategy Protocol, CompressStrategy Protocol, OutputParser Protocol, EventBus, AgentPool, AgentConfig, AgentPluginLoader |
| 错误处理完善 | 6 | 错误分类体系 (6 类 LLMError + 5 类 AgentError)、恢复策略 (可恢复/可重试/不可恢复)、LLM 调用退避计算、Tool 超时控制、解析回退策略、Agent 调用栈深度限制 |
| 扩展点新增 | 10 | 策略注入点 (Match/Compress/Parse)、钩子方法 (on_before/after_react_loop)、EventBus 订阅、插件目录、AgentConfig 覆写、Provider 实现替换、sanitize_args 覆写、_build_system_message 覆写 |

## 影响分析

- **兼容性**: 配置字段从 `DEEPSEEK_*` 改为 `LLM_*`，但保留 `DEEPSEEK_*` 回退支持，平滑迁移
- **架构收益**: Provider 模式解耦使得框架不再绑定任何特定 LLM 厂商，可接入任意 OpenAI-compatible 后端
- **可扩展性**: 策略模式 + 钩子 + 插件 + 事件总线四层扩展机制，覆盖匹配/压缩/解析/通知全链路
- **可运维性**: TokenTracker、事件总线、分级日志、会话导出/导入，便于监控和故障诊断
- **安全性**: ToolSecurityPolicy 为文件/Shell/网络操作提供统一的安全管控层
- **后续步骤**: 按更新后的 `08_implementation_roadmap.md` 执行实现 (总任务数 28，预估 11-16 天)
