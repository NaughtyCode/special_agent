# 修改记录 — Issue #1 (Agent 框架设计)

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue1-agent |
| 修改日期 | 2026-04-30 |
| 修改类型 | 设计计划 — Agent 框架架构设计 |
| 关联文档 | `agent_doc/issues/issue1.txt` |
| 修改人 | SpecialArchAgent |

## 修改概述

基于 `agent_doc/issues/issue1.txt` 的需求，设计可继承的 Python3 Agent 框架完整方案。

框架核心特征：
- 基于 Python 3 开发，仅支持 DeepSeek V4 API
- BaseAgent 基类提供完整 LLM 访问 + ReAct 推理-行动循环
- RootAgent 继承 BaseAgent，处理控制台输入并调度特化 Agent
- 特化 Agent 均继承 BaseAgent，支持 Tool 匹配/拉起/运行
- API 地址通过环境变量配置

## 文件变更清单

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/00_architecture_overview.md` | 架构总览: 四层架构、核心数据流、模块依赖、文件结构、技术决策 |
| 2 | `agent_doc/plan/01_base_agent.md` | BaseAgent 设计: 核心属性/方法、状态机、AgentResult 结构、子类化指南 |
| 3 | `agent_doc/plan/02_react_engine.md` | ReActEngine 设计: ReAct 范式、Prompt 构建、输出解析、迭代轨迹、终止条件 |
| 4 | `agent_doc/plan/03_tool_system.md` | Tool 系统: BaseTool/ToolManager/AgentRegistry/AgentTool 适配器、4 级匹配策略 |
| 5 | `agent_doc/plan/04_deepseek_client.md` | DeepSeekV4Client 设计: 环境变量配置、类设计、数据模型、API 格式、错误处理 |
| 6 | `agent_doc/plan/05_root_agent.md` | RootAgent 设计: REPL 交互、Agent 调度、会话管理、3 层匹配策略 |
| 7 | `agent_doc/plan/06_specialized_agents.md` | 特化 Agent: CodeAgent/DocAgent/SearchAgent/ShellAgent、扩展指南、协作模式 |
| 8 | `agent_doc/plan/07_context_and_infra.md` | 上下文与基础设施: ContextStore、Config、Logger、完整目录结构、依赖项 |
| 9 | `agent_doc/plan/08_implementation_roadmap.md` | 实现路线图: 6 个 Phase、依赖关系图、关键技术要点 |
| 10 | `changelog/change_record_issue1_agent.md` | 本修改记录文件 |

### 修改文件

无 (仅新增文件, 未修改已有代码)

## 详细变更内容

### 1. 架构总览 (00_architecture_overview.md)

- 四层架构: Application Layer / Agent Framework Layer / LLM Gateway Layer / Infrastructure Layer
- 2 个核心数据流: ReAct 循环流程 (Thought→Action→Observation→循环判断)、Agent 作为 Tool 的拉起流程
- 模块依赖关系: RootAgent → BaseAgent → ReActEngine → DeepSeekV4Client (含 ToolManager/ContextStore/AgentRegistry)
- 完整文件结构设计 (agent/ 源码目录, 含 core/llm/agents/tools/infra 子包)
- 7 项关键技术决策表

### 2. BaseAgent (01_base_agent.md)

覆盖 5 个方面:
- **核心属性** (10 项): name, description, llm_client, react_engine, tool_manager, agent_registry, context_store, state, max_iterations
- **核心方法** (10 个): __init__, system_prompt (abstract), register_tools (abstract), run, arun, stop, use_tool, launch_agent, chat, 内部方法
- **AgentState 状态机**: IDLE → RUNNING → DONE/ERROR
- **AgentResult 结构**: success, final_answer, iterations, token_usage, sub_agent_results, error
- **子类化指南**: 只需覆写 system_prompt + register_tools, 无需修改 ReAct 逻辑

### 3. ReActEngine (02_react_engine.md)

覆盖 5 个方面:
- **ReAct 范式**: Thought → Action → Action Input → Observation 完整格式定义
- **类设计**: 配置项 (max_iterations, stop_on_error) + 核心方法 (run, _build_prompt, _parse_llm_output, _execute_action, _format_observation)
- **Prompt 构建策略**: 系统消息结构 (角色+规范+Tool列表+Agent列表+输出格式约束) + 用户消息结构
- **输出解析器 ParsedReAct**: 4 个正则匹配模式 + 容错推断逻辑
- **终止条件** (4 种): Final Answer / max_iterations / 连续 Tool 失败 3 次 / stop()

### 4. Tool 系统 (03_tool_system.md)

覆盖 7 个方面:
- **BaseTool**: name/description/parameters_schema 属性 + execute/to_llm_description/validate_args 方法 + ToolResult 数据类
- **ToolManager**: register/unregister/get_tool/match_tools/find_tool_by_capability/execute/list_tools/get_tools_schema
- **AgentRegistry**: register/get_agent/match_agent/launch/list_agents — Agent 作为特殊 Tool
- **AgentTool 适配器**: 将 Agent 包装为 Tool, 实现统一抽象
- **4 级匹配策略**: 精确匹配 → 模糊匹配 → Agent 匹配 → Function Calling 模式
- **8 个内置 Tool**: read_file/write_file/run_shell/search_code/list_files/web_fetch/web_search/launch_<agent>
- **Agent 匹配**: 关键词匹配 + LLM 意图识别 + 默认处理

### 5. DeepSeekV4Client (04_deepseek_client.md)

覆盖 7 个方面:
- **6 个环境变量**: DEEPSEEK_API_KEY (必需), DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, DEEPSEEK_MAX_TOKENS, DEEPSEEK_TEMPERATURE, DEEPSEEK_TIMEOUT
- **类设计**: 配置属性 + httpx.AsyncClient + chat/chat_stream/achat/achat_stream 4 个接口 + 内部方法
- **5 个数据模型**: Message, ChatResponse, ToolCall, TokenUsage, 枚举类型
- **API 请求格式** (2 种): 基本 Chat Completion + 带 Function Calling 的请求 (完整 JSON 示例)
- **5 类错误处理**: DeepSeekAuthError / RateLimitError / ServerError / TimeoutError / ConfigError
- **使用示例**: 同步/流式/Function Calling

### 6. RootAgent (05_root_agent.md)

覆盖 6 个方面:
- **类设计**: 继承 BaseAgent + agent_registry + session_id/history + System Prompt
- **REPL 主循环**: 完整流程图 — 读取输入 → 判断命令类型 → handle_command 或 process_once → 循环
- **内置命令** (7 个): /exit, /help, /agents, /tools, /history, /clear, /session
- **Agent 调度**: process_once → 匹配特化 Agent → 拉起执行 或 自行 ReAct
- **会话管理**: Session 数据类 + SessionManager (创建/切换/列出/清除)
- **3 层匹配策略**: 关键词 → LLM 意图识别 → 默认处理

### 7. 特化 Agent (06_specialized_agents.md)

覆盖 5 个方面:
- **4 个内置 Agent 的完整定义**:
  - CodeAgent: 代码编写/审查/修复/重构, 注册 5 个 Tool
  - DocAgent: 技术文档/API文档/README, 注册 4 个 Tool
  - SearchAgent: 代码搜索/网页搜索/信息检索, 注册 5 个 Tool
  - ShellAgent: Shell 命令执行/环境检查/文件操作, 注册 4 个 Tool
- **扩展指南**: 2 步创建自定义 Agent (定义类 + 注册到 RootAgent)
- **3 种协作模式**: 串行协作、嵌套协作、并行协作 (未来)

### 8. 上下文与基础设施 (07_context_and_infra.md)

覆盖 5 个方面:
- **ContextStore**: 消息管理 + ReAct 轨迹 + 上下文变量 + Tool 结果缓存 + 上下文窗口管理策略
- **Config**: 11 个配置项 (DeepSeek API 6 项 + Agent 2 项 + 日志 3 项) + from_env/validate 方法
- **AgentLogger**: 带 Agent 上下文的日志器 + 专用日志方法 (log_react_step/log_tool_call/log_llm_call)
- **完整目录结构**: 9 个 plan 文档 + 26 个源码文件 + changelog
- **依赖项**: httpx + pydantic + pydantic-settings

### 9. 实现路线图 (08_implementation_roadmap.md)

- **6 个 Phase** (共约 11-16 天):
  - Phase 1: 基础设施 (Config/Logger/DeepSeekV4Client)
  - Phase 2: Agent 基类与 ReAct (ContextStore/ReActParser/ToolManager/AgentRegistry/ReActEngine/BaseAgent)
  - Phase 3: 内置 Tool (FileTools/ShellTools/WebTools/AgentTool)
  - Phase 4: 特化 Agent (CodeAgent/DocAgent/SearchAgent/ShellAgent)
  - Phase 5: RootAgent 与入口 (SessionManager/RootAgent/main.py)
  - Phase 6: 文档与发布
- **依赖关系图**: ASCII 图展示各 Phase 内任务依赖
- **4 个关键技术要点**: ReAct Prompt 工程 / Tool 执行安全 / 错误处理与恢复 / Token 管理

## 技术要点覆盖

| issue1.txt 要求 | 对应计划文档位置 |
|----------------|------------------|
| 基于 Python3 开发 | `00_architecture_overview.md` §7 技术决策 |
| 仅支持 DeepSeek V4 API | `04_deepseek_client.md` 全文 |
| API 链接使用环境变量 | `04_deepseek_client.md` §2, `07_context_and_infra.md` §2 |
| BaseAgent — 完整 LLM 能力 | `01_base_agent.md` §2.2 (chat 方法), `04_deepseek_client.md` §3 (类设计) |
| BaseAgent — 完整 ReAct 结构 | `01_base_agent.md` §2.2 (run 方法), `02_react_engine.md` 全文 |
| RootAgent 继承 BaseAgent | `05_root_agent.md` §2 (类设计) |
| RootAgent 处理控制台输入 | `05_root_agent.md` §3 (REPL 流程) |
| 特化 Agent 继承 BaseAgent | `06_specialized_agents.md` §3-4 (4 个内置 + 扩展指南) |
| Tool 匹配/拉起/运行特化 Agent | `03_tool_system.md` §4 (AgentRegistry), §5 (AgentTool), §6 (匹配策略) |
| 计划文档放 agent_doc/plan | `agent_doc/plan/00-08` 全部文档 |
| 生成修改记录文档 | `changelog/change_record_issue1_agent.md` (本文档) |
| 代码必须加上详细注释 | `06_specialized_agents.md` §3.1 (CodeAgent system_prompt 明确要求) |

## 影响分析

- **影响范围**: 仅设计文档新增, 不影响已有代码
- **后续步骤**: 按 `08_implementation_roadmap.md` 中的 Phase 1-6 顺序实现
- **总预估工期**: 11-16 天 (约 2-3 周)
