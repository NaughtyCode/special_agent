# 实现路线图

## 1. 实现阶段

### Phase 1: 基础设施 (预估 2-3 天)

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 1.1 | 创建项目目录结构 | `agent/` 完整目录树 | 无 |
| 1.2 | 实现 Config 配置管理 (provider-agnostic) | `agent/infra/config.py` | 1.1 |
| 1.3 | 实现 Logger 日志模块 | `agent/infra/logger.py` | 1.1 |
| 1.4 | 实现 EventBus 事件总线 | `agent/events/` | 1.1 |
| 1.5 | 定义 LLMProvider 接口 | `agent/llm/llm_provider.py` | 1.2 |
| 1.6 | 实现 OpenAICompatProvider | `agent/llm/openai_compat.py` | 1.5 |
| 1.7 | 实现 LLMClient Facade | `agent/llm/llm_client.py` | 1.5, 1.6 |
| 1.8 | 编写 LLM 层单元测试 | `tests/test_llm_client.py` | 1.7 |

### Phase 2: Agent 基类与 ReAct (预估 4-5 天)

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 2.1 | 定义数据模型 (Message, ChatResponse, TokenUsage 等) | `agent/core/models.py` | 无 |
| 2.2 | 实现 ReActParser (文本/FC/回退三级解析) | `agent/core/react_parser.py` | 2.1 |
| 2.3 | 实现 Tool 基类 + ToolResult | `agent/tools/base_tool.py` | 2.1 |
| 2.4 | 实现 ToolManager (含安全策略) | `agent/core/tool_manager.py` | 2.3 |
| 2.5 | 实现 MatchStrategy 体系 (Exact/Fuzzy/Semantic/Agent) | `agent/strategies/match_strategy.py` | 2.4 |
| 2.6 | 实现 AgentRegistry + AgentPool | `agent/core/agent_registry.py`, `agent_pool.py` | 无 |
| 2.6a | 实现 CrewOrchestrator (Plan/Execute/Aggregate + 三种执行策略) | `agent/core/crew_orchestrator.py` | 1.4, 1.7, 2.1, 2.6 |
| 2.7 | 实现 CompressStrategy 体系 (Sliding/Summarize/Hybrid) | `agent/strategies/compress_strategy.py` | 2.1 |
| 2.8 | 实现 ContextStore (含压缩策略) | `agent/core/context_store.py` | 2.1, 2.7 |
| 2.9 | 实现 ReActEngine (注入策略 + 终止条件) | `agent/core/react_engine.py` | 1.7, 2.2, 2.4, 2.5, 2.6, 2.8 |
| 2.10 | 实现 BaseAgent (状态机 + 钩子 + Crew 编排 + 错误处理) | `agent/core/base_agent.py` | 2.4, 2.6, 2.6a, 2.8, 2.9 |
| 2.11 | 编写 BaseAgent 单元测试 | `tests/test_base_agent.py` | 2.10 |

### Phase 3: 内置 Tool (预估 1-2 天)

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 3.1 | 实现 FileTools (Read/Write/List) | `agent/tools/file_tools.py` | 2.3 |
| 3.2 | 实现 ShellTool (含安全确认) | `agent/tools/shell_tools.py` | 2.3 |
| 3.3 | 实现 SearchTool + WebTools | `agent/tools/search_tools.py`, `web_tools.py` | 2.3 |
| 3.4 | 实现 AgentTool 适配器 | `agent/tools/agent_tool.py` | 2.3, 2.6 |
| 3.4a | 实现 CrewTool 适配器 (launch_crew → Tool) | `agent/tools/crew_tool.py` | 2.3, 2.6a, 2.10 |
| 3.5 | 编写 Tool 层单元测试 (含 CrewTool) | `tests/test_tool_*.py` | 3.1-3.4a |

### Phase 4: 特化 Agent (预估 2-3 天)

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 4.1 | 实现 CodeAgent (含 CrewLeader 角色) | `agent/agents/code_agent.py` | 2.10, 3.1-3.3, 3.4a |
| 4.2 | 实现 DocAgent (含 CrewLeader 角色) | `agent/agents/doc_agent.py` | 2.10, 3.1, 3.3, 3.4a |
| 4.3 | 实现 SearchAgent (含 CrewLeader 角色) | `agent/agents/search_agent.py` | 2.10, 3.1, 3.3, 3.4a |
| 4.4 | 实现 ShellAgent (含 CrewLeader 角色) | `agent/agents/shell_agent.py` | 2.10, 3.2, 3.4a |
| 4.5 | 编写 Agent 级测试 (含 Crew 编排测试) | `tests/test_agents.py` | 4.1-4.4 |

### Phase 5: RootAgent 与入口 (预估 2-3 天)

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 5.1 | 实现 SessionManager | `agent/core/session_manager.py` | 2.8 |
| 5.2 | 实现 AgentPluginLoader | `agent/core/plugin_loader.py` | 2.10 |
| 5.3 | 实现 RootAgent (REPL + 三级路由 + 插件) | `agent/agents/root_agent.py` | 2.10, 2.6, 4.1-4.4, 5.1, 5.2 |
| 5.4 | 实现 main.py 入口 | `agent/main.py` | 5.3 |
| 5.5 | 编写集成测试 (含 Crew 编排端到端测试) | `tests/test_integration.py` | 5.4 |

### Phase 6: 文档与发布 (预估 1 天)

| 序号 | 任务 | 产出 | 依赖 |
|------|------|------|------|
| 6.1 | 编写 README (含快速开始与配置说明) | `README.md` | 5.4 |
| 6.2 | 编写 requirements.txt | `requirements.txt` | 全 Phase |
| 6.3 | 编写示例插件 Agent | `plugins/example_agent.py` | 5.2 |
| 6.4 | 端到端验证与错误场景测试 (含 Crew 串行/并行/DAG) | 测试报告 | 5.5 |

## 2. 依赖关系图

```
Phase 1 (基础设施)
  ├─ 1.1 目录结构
  ├─ 1.2 Config ──────────────────────┐
  ├─ 1.3 Logger                        │
  ├─ 1.4 EventBus                      │
  ├─ 1.5 LLMProvider 接口              │
  ├─ 1.6 OpenAICompatProvider ← 1.5    │
  └─ 1.7 LLMClient ← 1.5,1.6 ─────────┤
                                       │
Phase 2 (Agent 基类与 ReAct)           │
  ├─ 2.1 数据模型                      │
  ├─ 2.2 ReActParser ← 2.1            │
  ├─ 2.3 BaseTool ← 2.1               │
  ├─ 2.4 ToolManager ← 2.3            │
  ├─ 2.5 MatchStrategy ← 2.4          │
  ├─ 2.6 AgentRegistry + AgentPool    │
  ├─ 2.6a CrewOrchestrator ← 1.4,1.7,2.1,2.6  │
  ├─ 2.7 CompressStrategy ← 2.1       │
  ├─ 2.8 ContextStore ← 2.1,2.7      │
  ├─ 2.9 ReActEngine ← 1.7,2.2,2.4,2.5,2.6,2.8
  └─ 2.10 BaseAgent ← 2.4,2.6,2.6a,2.8,2.9│
                                       │
Phase 3 (内置 Tool)                    │
  ├─ 3.1 FileTools ← 2.3              │
  ├─ 3.2 ShellTool ← 2.3              │
  ├─ 3.3 SearchTool + WebTools ← 2.3  │
  ├─ 3.4 AgentTool ← 2.3,2.6          │
  └─ 3.4a CrewTool ← 2.3,2.6a,2.10    │
                                       │
Phase 4 (特化 Agent)                   │
  ├─ 4.1 CodeAgent ← 2.10,3.1-3.3,3.4a│
  ├─ 4.2 DocAgent ← 2.10,3.1,3.3,3.4a │
  ├─ 4.3 SearchAgent ← 2.10,3.1,3.3,3.4a│
  └─ 4.4 ShellAgent ← 2.10,3.2,3.4a   │
                                       │
Phase 5 (RootAgent 与入口)             │
  ├─ 5.1 SessionManager ← 2.8         │
  ├─ 5.2 PluginLoader ← 2.10          │
  ├─ 5.3 RootAgent ← 2.10,2.6,4.*,5.1,5.2
  └─ 5.4 main.py ← 5.3                │
                                       │
Phase 6 (文档与发布) ← 全 Phase ───────┘
```

## 3. 关键技术要点

### 3.1 ReAct Prompt 工程
- 系统消息中明确 ReAct 输出格式
- 提供 few-shot 示例指导 LLM 输出格式
- 同时支持文本解析和 Function Calling 两条路径
- 解析失败时自动反馈 LLM 重新格式化

### 3.2 Tool 执行安全
- Shell 命令执行前白名单检查
- 文件操作限制在项目目录内 (sanitize_args)
- 危险操作 (写文件/Shell) 需确认 (requires_confirmation)
- 所有 Tool 调用记录完整审计日志
- 参数 JSON Schema 校验, 防止注入

### 3.3 错误处理与恢复 (三层递进)
- **可恢复**: Tool 执行失败 → 将错误作为 Observation 反馈 LLM
- **可重试**: LLM 调用失败 → 指数退避自动重试
- **不可恢复**: 认证失败/深度超限 → 立即终止并报告

### 3.4 Token 管理
- 实时估算 Token 用量 (tiktoken / 启发式)
- 接近限制时自动触发压缩策略 (可注入)
- 记录每次 LLM 调用的 Token 消耗 (TokenTracker)

### 3.5 LLM 后端可替换性
- LLMProvider 接口解耦具体实现
- 默认 OpenAICompatProvider 适配所有兼容服务
- 通过环境变量切换后端, 无需修改代码
- 通过 ANTHROPIC_* 环境变量配置 LLM 后端 (ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL 等)

### 3.6 可扩展性设计
- 策略模式: Tool 匹配策略、上下文压缩策略均可注入
- 钩子方法: _on_before_react_loop / _on_after_react_loop
- 插件系统: AgentPluginLoader 动态发现外部 Agent
- 事件总线: 发布-订阅模式, 便于监控/日志/审计集成

### 3.7 Crew 编排
- 核心机制 — 任何特化 Agent 均可通过 CrewOrchestrator 成为 CrewLeader
- 任务分解: LLM 将复杂使命分解为 SubTask 列表
- Agent 匹配: 每个 SubTask 自动匹配最合适的特化 Agent (通过 AgentRegistry)
- 三种执行策略: SEQUENTIAL (串行) / PARALLEL (并行) / DAG (依赖拓扑)
- CrewTool 适配器: 将 launch_crew 暴露为 LLM 可调用的 Tool
- 结果聚合: LLM 汇总所有成员结果, 生成统一的 mission_summary
