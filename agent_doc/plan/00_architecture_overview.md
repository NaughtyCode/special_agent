# Agent 框架架构总览

## 1. 项目概述

基于 Python 3 开发可继承的 Agent 框架，通过 OpenAI-compatible API 调用大语言模型，实现完整的 ReAct 推理-行动循环结构。

## 2. 核心设计目标

- **可继承性**: 所有 Agent 继承自 BaseAgent，通过覆写方法实现特化行为
- **ReAct 结构**: 内建 Reasoning + Acting 循环，支持 Thought → Action → Observation 完整链路
- **Tool 系统**: 统一 Tool 注册/匹配/调用机制，支持多种匹配策略，特化 Agent 本身也可作为 Tool 被拉起
- **Crew 编排**: 核心机制 — 任何特化 Agent 均可成为 CrewLeader，动态组建并领导一组匹配的特化 Agent 协同完成复杂任务
- **LLM 后端可替换**: 通过 LLMProvider 接口抽象，默认适配 OpenAI-compatible API，环境变量配置端点
- **可扩展**: 关键节点提供策略注入点与事件回调，支持自定义行为而不修改框架代码

## 3. 架构分层

```
┌──────────────────────────────────────────────────────┐
│                    Application Layer                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ RootAgent│  │ CodeAgent│  │ DocAgent │  ...       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘            │
├───────┼──────────────┼──────────────┼─────────────────┤
│       │     Agent Framework Layer    │                 │
│  ┌────┴──────────────┴──────────────┴────┐            │
│  │              BaseAgent                 │            │
│  │  ┌──────────┐ ┌──────────┐ ┌───────┐ │            │
│  │  │ ReAct     │ │ Tool     │ │Context│ │            │
│  │  │ Engine    │ │ Manager  │ │Store  │ │            │
│  │  │ Crew      │ │ Agent    │ │ Agent  │ │            │
│  │  │Orchestrator│ │Registry  │ │ Pool   │ │            │
│  │  └──────────┘ └──────────┘ └───────┘ │            │
│  └────────────────────┬──────────────────┘            │
├───────────────────────┼───────────────────────────────┤
│                       │       LLM Gateway Layer        │
│  ┌────────────────────┴──────────────────┐            │
│  │           LLMClient                    │            │
│  │  ┌──────────────────────────┐         │  ← 扩展点  │
│  │  │ LLMProvider (Protocol)   │         │            │
│  │  │ ├─ OpenAICompatProvider  │         │            │
│  │  │ └─ (CustomProvider...)   │         │            │
│  │  └──────────────────────────┘         │            │
│  └────────────────────┬──────────────────┘            │
├───────────────────────┼───────────────────────────────┤
│                       │     Infrastructure Layer       │
│  ┌────────────────────┴──────────────────┐            │
│  │   Config / Logger / EventBus           │            │
│  └───────────────────────────────────────┘            │
└──────────────────────────────────────────────────────┘
```

### 3.1 各层职责

| 层次 | 职责 | 核心类 | 扩展点 |
|------|------|--------|--------|
| Application Layer | 具体 Agent 实现，处理特定领域任务 | RootAgent, 各特化 Agent | 自定义 Agent 子类 |
| Agent Framework Layer | Agent 基类、ReAct 引擎、Tool 管理、上下文存储、Crew 编排 | BaseAgent, ReActEngine, ToolManager, ContextStore, CrewOrchestrator | 策略注入 (匹配策略/压缩策略/解析策略/执行策略) |
| LLM Gateway Layer | LLM API 调用封装，支持流式/非流式/Function Calling | LLMClient, LLMProvider | 自定义 Provider 实现 |
| Infrastructure Layer | 配置管理、日志、事件总线 | Config, Logger, EventBus | 自定义事件处理器 |

## 4. 核心数据流

### 4.1 ReAct 循环流程 (含错误处理路径)

```
用户输入
   │
   ▼
┌──────────────────────────────────────────────────────┐
│  Agent.run(user_input, context)                       │
│   │                                                    │
│   ├─ 1. 状态: IDLE → RUNNING                          │
│   │                                                    │
│   ├─ 2. THOUGHT: 构建 Prompt → 调用 LLM               │
│   │      │                                             │
│   │      ├─ 成功 → 解析 Thought + Action               │
│   │      ├─ 超时 → 重试 (指数退避, 最多 N 次)          │
│   │      ├─ 限流 → 等待后重试                           │
│   │      └─ 不可恢复错误 → 状态 → ERROR, 返回错误       │
│   │      │                                             │
│   ├─ 3. ACTION: 解析 Action → 匹配 Tool                │
│   │      │                                             │
│   │      ├─ 匹配策略 (可注入):                          │
│   │      │   ├─ Strategy.ExactMatch → 精确名称匹配      │
│   │      │   ├─ Strategy.FuzzyMatch → 模糊匹配          │
│   │      │   ├─ Strategy.SemanticMatch → 语义匹配       │
│   │      │   └─ Strategy.AgentMatch → Agent 匹配        │
│   │      │                                             │
│   │      ├─ 匹配到普通 Tool → 执行 Tool                 │
│   │      ├─ 匹配到特化 Agent → 拉起 Agent               │
│   │      └─ 无匹配 → 将错误信息作为 Observation 反馈    │
│   │      │                                             │
│   ├─ 4. OBSERVATION: 收集执行结果                      │
│   │      │                                             │
│   │      ├─ Tool 成功 → 格式化结果为 Observation        │
│   │      ├─ Tool 失败 → 错误信息作为 Observation        │
│   │      └─ Tool 超时 → 超时信息作为 Observation        │
│   │      │                                             │
│   │      ▼                                             │
│   │   将 Observation 反馈给 LLM                        │
│   │      │                                             │
│   ├─ 5. 循环判断:                                      │
│   │      ├─ 有 Final Answer → 状态 → DONE, 返回结果     │
│   │      ├─ 达到 max_iterations → 强制要求总结          │
│   │      ├─ 连续 Tool 失败超 threshold → 状态 → ERROR   │
│   │      ├─ 外部调用 stop() → 状态 → STOPPED            │
│   │      └─ 否则 → 回到步骤 2                           │
│   │                                                    │
│   ▼                                                    │
│  返回 AgentResult (含完整迭代轨迹与 Token 统计)         │
└──────────────────────────────────────────────────────┘
```

### 4.2 Agent 作为 Tool 的拉起流程

```
调用方 Agent 解析到需要特化 Agent
   │
   ├─ 在 AgentRegistry 中匹配目标 Agent 类型
   │   匹配策略: 名称精确匹配 → 描述关键词匹配 → LLM 路由决策
   │
   ├─ 从 AgentPool 获取或创建 Agent 实例 (支持实例复用)
   │
   ├─ 构建子任务上下文: 继承父 Agent 的 Config, 注入调用栈深度限制
   │
   ├─ 子 Agent 独立执行 ReAct 循环
   │   触发事件: AgentLifecycleEvent.SPAWNED
   │
   ├─ 子 Agent 返回 AgentResult
   │   触发事件: AgentLifecycleEvent.COMPLETED / FAILED
   │
   ├─ 校验子结果有效性 (非空, 非循环引用)
   │
   ▼
调用方 Agent 将子 Agent 结果包装为 Observation 继续推理
```

### 4.3 Crew 编排流程 (多 Agent 协同)

```
CrewLeader (任意特化 Agent)
   │
   ├─ 1. LLM 在 ReAct 循环中判断: 当前任务需多 Agent 协同
   │     (任务复杂度高 / 涉及多个领域 / 需要并行加速)
   │
   ├─ 2. PLAN: 调用 form_crew(mission)
   │     └─ CrewOrchestrator.plan_crew()
   │           ├─ LLM 分解 mission → [SubTask₁, SubTask₂, ..., SubTaskₙ]
   │           ├─ 每个 SubTask 通过 AgentRegistry.match_agent() 匹配对应 Agent
   │           └─ 组建 AgentCrew (含 N 个 CrewMember)
   │               发布 CrewLifecycleEvent.PLANNED
   │
   ├─ 3. EXECUTE: 调用 launch_crew(mission, strategy)
   │     └─ CrewOrchestrator.execute_crew(crew, strategy)
   │           ├─ SEQUENTIAL: [CodeAgent] → [DocAgent] → [ShellAgent]
   │           ├─ PARALLEL:   [CodeAgent | DocAgent | SearchAgent] (并发)
   │           └─ DAG:        [SearchAgent] ──→ [CodeAgent] ──→ [ShellAgent]
   │                                    └──→ [DocAgent]
   │           每个成员执行: AgentPool.acquire → agent.run(task) → AgentPool.release
   │           发布 CrewLifecycleEvent.MEMBER_STARTED / MEMBER_COMPLETED / MEMBER_FAILED
   │
   ├─ 4. AGGREGATE: 汇总所有成员结果
   │     └─ CrewOrchestrator._aggregate_results()
   │           ├─ 拼接所有 member.final_answer
   │           ├─ LLM 生成统一的 mission_summary
   │           └─ 计算 total token_usage 和 total_duration_ms
   │
   ▼
CrewLeader 将 CrewResult.mission_summary 作为 Observation 继续 ReAct 推理
```

## 5. 模块依赖关系

```
RootAgent ──→ BaseAgent ──→ ReActEngine ──→ LLMClient ──→ LLMProvider (接口)
                │                │                │
                ├─→ ToolManager  │                └─→ Config (llm_* 配置)
                ├─→ ContextStore │
                ├─→ AgentRegistry│
                ├─→ AgentPool    │
                ├─→ CrewOrchestrator ──→ AgentRegistry + AgentPool + LLMClient
                └─→ EventBus     │
                                 │
                  匹配策略注入 ──┘
```

## 6. 文件结构设计

```
SpecialAgent/
├── agent_doc/
│   ├── issues/                    # 需求文档
│   ├── plan/                      # 计划文档
│   ├── changelog/                 # 修改记录文档
│   └── tasks.txt                  # 任务入口
├── agent/                         # Agent 框架源码
│   ├── __init__.py
│   ├── main.py                    # 程序入口
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py              # 共享数据模型定义
│   │   ├── base_agent.py          # BaseAgent 基类
│   │   ├── react_engine.py        # ReAct 推理引擎
│   │   ├── react_parser.py        # ReAct 输出解析器
│   │   ├── tool_manager.py        # Tool 管理器
│   │   ├── context_store.py       # 上下文存储
│   │   ├── agent_registry.py      # Agent 注册中心
│   │   ├── agent_pool.py          # Agent 实例池 (复用)
│   │   ├── crew_orchestrator.py   # Crew 团队编排引擎
│   │   ├── session_manager.py     # 会话管理器
│   │   └── plugin_loader.py       # 插件加载器
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── llm_client.py          # LLM 客户端 (Facade)
│   │   ├── llm_provider.py        # LLMProvider 接口定义
│   │   └── openai_compat.py       # OpenAI-compatible Provider
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── root_agent.py          # RootAgent
│   │   ├── code_agent.py          # CodeAgent
│   │   ├── doc_agent.py           # DocAgent
│   │   ├── search_agent.py        # SearchAgent
│   │   └── shell_agent.py         # ShellAgent
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base_tool.py           # Tool 基类
│   │   ├── file_tools.py          # 文件操作 Tool
│   │   ├── shell_tools.py         # Shell 执行 Tool
│   │   ├── search_tools.py        # 代码搜索 Tool
│   │   ├── web_tools.py           # 网络搜索 Tool
│   │   ├── crew_tool.py           # Crew 编排 → Tool 适配器
│   │   └── agent_tool.py          # Agent → Tool 适配器
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── match_strategy.py      # Tool 匹配策略接口与实现
│   │   └── compress_strategy.py   # 上下文压缩策略接口与实现
│   ├── events/
│   │   ├── __init__.py
│   │   ├── events.py              # 事件类定义 (AgentLifecycleEvent, ToolCallEvent, CrewLifecycleEvent 等)
│   │   └── event_bus.py           # 事件总线
│   └── infra/
│       ├── __init__.py
│       ├── config.py              # 配置管理 (provider-agnostic)
│       └── logger.py              # 日志模块
├── tests/                         # 测试目录
├── plugins/                       # Agent 插件目录
├── changelog/                     # 修改记录 (历史)
├── requirements.txt
└── README.md
```

## 7. 关键技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 编程语言 | Python 3.10+ | 要求 Python3，生态丰富，支持 `str | None` 联合类型语法 |
| HTTP 客户端 | `httpx` (异步) | 支持 async/await，连接复用，HTTP/2 |
| LLM API 格式 | OpenAI-compatible Chat Completions | 业界标准，主流 LLM 服务均兼容 |
| LLM 后端抽象 | LLMProvider Protocol | 运行时可替换后端，不绑定特定厂商 |
| Agent 间通信 | 同步调用 + 返回值 | 简单可靠，符合父子任务语义 |
| Tool 匹配 | 策略模式 (可注入) | 支持精确/模糊/语义/FC 多种匹配策略按优先级链式执行 |
| 配置方式 | 环境变量 + pydantic-settings | 安全灵活，符合 12-Factor |
| 上下文压缩 | 策略模式 (可注入) | 支持滑动窗口/摘要压缩/混合策略 |
| 事件通知 | EventBus (发布-订阅) | 解耦 Agent 生命周期通知，便于监控与日志 |
| Agent 实例化 | AgentPool (惰性+复用) | 避免重复创建 Agent 实例，支持并发控制 |
| Crew 编排 | CrewOrchestrator + AgentCrew | 核心机制 — 任何特化 Agent 均可动态组建 Agent 团队，支持串行/并行/DAG 三种执行策略 |
