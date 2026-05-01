# 修改记录 — Issue #7

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue7 |
| 修改日期 | 2026-05-01 |
| 修改类型 | Crew 机制深度审查 (三轮) — 补全缺失定义、修复跨文档不一致、增强注释与错误处理、修复生命周期管理缺失 |
| 关联文档 | `agent_doc/plan/` (00, 01, 03, 06, 07, 08) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 Issue #6 新增的 Crew 团队编排机制进行两轮反复深度审查。

**第一轮**: 修复缺失的类定义、配置字段缺失、方法参数传递错误、事件定义格式错误、事件发布重复、依赖关系遗漏等问题。

**第二轮**: 修复模块依赖图与路线图遗漏 EventBus、文档节号跳跃与代码示例冲突、编排流程图不一致、Crew 事件负载缺失、异常处理缺失、success 语义模糊等问题，并为所有 Crew 相关数据模型和方法补充详细注释。

## 文件变更清单

### 修改文件 (第一轮)

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/03_tool_system.md` | 新增 §9.6 CrewTool 完整类定义；CrewLifecycleEvent 改为 Enum 类并添加枚举值；AgentCrew 文档错字修复；CrewOrchestrator 配置注释对齐 Config 字段名 |
| 2 | `agent_doc/plan/01_base_agent.md` | form_crew() 明确传递 lead_agent_name=self.name；launch_crew() 移除重复的事件发布职责 |
| 3 | `agent_doc/plan/07_context_and_infra.md` | Config 新增 Crew 配置段: crew_max_parallel, crew_max_iterations, crew_plan_temperature |
| 4 | `agent_doc/plan/08_implementation_roadmap.md` | 3.4a CrewTool 依赖新增 2.10 (BaseAgent)；依赖关系图同步更新 |

### 修改文件 (第二轮追加)

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 5 | `agent_doc/plan/03_tool_system.md` | CrewResult 新增 failed_members 字段并澄清 success 语义; _aggregate_results() 更新; 全部数据模型 (SubTask/CrewMember/AgentCrew) 和执行方法 (_execute_sequential/parallel/dag) 补充详细注释; §9.4 编排流程图新增 ContextStore 写入步骤; §9.3 新增 CrewEvent 负载数据类; §9.2 execute_crew()/plan_crew() 事件文档更新; §9.6 CrewTool.execute() 新增异常处理 |
| 6 | `agent_doc/plan/00_architecture_overview.md` | §5 模块依赖图: CrewOrchestrator → + EventBus |
| 7 | `agent_doc/plan/01_base_agent.md` | crew_orchestrator 属性注释扩展 |
| 8 | `agent_doc/plan/06_specialized_agents.md` | 修复节号跳跃 (§5.5→§7→§8 改为 §5.5→§6→§7); Crew 示例 register_tools() 明确标注为 §3.1 的扩展版本 |
| 9 | `agent_doc/plan/07_context_and_infra.md` | Crew 配置字段加详细注释; EventBus 文档补 CrewEvent 负载说明 |
| 10 | `agent_doc/plan/08_implementation_roadmap.md` | 任务 2.6a 依赖补全 1.4 (EventBus); 依赖关系图同步 |

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 5 | `agent_doc/changelog/change_record_issue7.md` | 本修改记录 |

## 详细变更内容

### 问题 1: CrewTool 类被广泛引用但从未定义

**发现**: 以下 6 处引用了 `CrewTool`，但没有任何文档包含其类定义：
- `06_specialized_agents.md` §7 示例代码: `self.tool_manager.register(CrewTool(agent=self))`
- `03_tool_system.md` §7 内置 Tool 表: `launch_crew` 条目
- `07_context_and_infra.md` 文件结构: `crew_tool.py`
- `00_architecture_overview.md` 文件结构: `crew_tool.py`
- `08_implementation_roadmap.md` 任务 3.4a: 实现 CrewTool 适配器
- `08_implementation_roadmap.md` 依赖关系图: `3.4a CrewTool`

对比 `AgentTool` 在 `03_tool_system.md` §6 中有完整的类定义（含 __init__ 和 execute 方法），`CrewTool` 完全缺失。

**修复**: 在 `03_tool_system.md` 新增 §9.6，定义完整的 `CrewTool(BaseTool)` 类:
- `name = "launch_crew"`
- `parameters_schema`: mission (required), strategy (可选, enum), max_parallel (可选, integer)
- `execute()`: 调用 `self._agent.launch_crew(mission, strategy, max_parallel)` → 转换 CrewResult 为 ToolResult
- 与 AgentTool 的互补关系在文档中明确说明

### 问题 2: Config 缺少 Crew 相关配置字段

**发现**: `CrewOrchestrator.__init__` 文档声明从 Config 读取 `max_parallel`、`crew_max_iterations`、`plan_temperature`，但 `07_context_and_infra.md` 的 Config 类中没有这些字段，导致实现者无法确定配置来源。

**修复**: 在 Config 的 Agent 段与上下文段之间新增 `# ── Crew ──` 配置段:
```python
crew_max_parallel: int = 4              # (CREW_MAX_PARALLEL)
crew_max_iterations: int = 3            # (CREW_MAX_ITERATIONS)
crew_plan_temperature: float = 0.4      # (CREW_PLAN_TEMPERATURE)
```
同步更新 CrewOrchestrator 配置注释，明确引用 Config 字段名。

### 问题 3: form_crew() 未传递 lead_agent_name

**发现**: `01_base_agent.md` 中 `form_crew(mission)` 调用 `crew_orchestrator.plan_crew()`，但 `plan_crew()` 的签名要求 `lead_agent_name: str` 参数。`form_crew()` 未传递此参数，导致 AgentCrew 不知道是哪个 Agent 发起了 Crew。

**修复**: 更新 `form_crew()` 文档，明确写入 `crew_orchestrator.plan_crew(mission, lead_agent_name=self.name)`。

### 问题 4: CrewLifecycleEvent 未定义为 Enum

**发现**: `03_tool_system.md` §9.3 中 `CrewLifecycleEvent` 定义为普通 class，仅用注释描述枚举值但无 `Enum` 继承和枚举成员。与其他事件类型（如 02 中的 `FinishReason(Enum)`、01 中的 `AgentState(Enum)`）格式不一致。

**修复**: 将 `class CrewLifecycleEvent:` 改为 `class CrewLifecycleEvent(Enum):`，添加全部 7 个枚举值：
`PLANNED`, `STARTED`, `MEMBER_STARTED`, `MEMBER_COMPLETED`, `MEMBER_FAILED`, `COMPLETED`, `FAILED`

### 问题 5: launch_crew() 重复声明事件发布

**发现**: `01_base_agent.md` 的 `launch_crew()` 文档声称"发布 CrewLifecycleEvent.COMPLETED / FAILED"，但 `CrewOrchestrator.execute_crew()` (步骤 5) 已经发布了这些事件。BaseAgent 层面重复发布会导致事件重复触发。

**修复**: 将 `launch_crew()` 步骤 4 从"发布 CrewLifecycleEvent.COMPLETED / FAILED"改为"返回聚合后的 CrewResult"，并在步骤 2 注明 `(execute_crew 内部发布 CrewLifecycleEvent 事件)`。

### 问题 6: 08 路线图 CrewTool 缺少 BaseAgent 依赖

**发现**: `08_implementation_roadmap.md` 中任务 3.4a CrewTool 的依赖列仅含 `2.3, 2.6a`。但 `CrewTool.__init__` 接受 `agent: BaseAgent` 参数并调用 `agent.launch_crew()`，因此必须依赖 2.10 (BaseAgent)。

**修复**: 任务 3.4a 依赖更新为 `2.3, 2.6a, 2.10`，依赖关系图同步更新。

### 问题 7: AgentCrew 文档错字

**发现**: `03_tool_system.md` AgentCrew 文档中 "由 CrewLeader 组件的一支 Agent 团队" — "组件"应为"组建"。

**修复**: "组件" → "组建"。

## 问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 缺失类定义 | 1 | CrewTool 类完全未定义 |
| 缺失配置字段 | 3 | Config 缺少 3 个 Crew 配置字段 |
| 方法参数错误 | 1 | form_crew() 未传递 lead_agent_name |
| 类型定义格式错误 | 1 | CrewLifecycleEvent 应为 Enum 而非普通 class |
| 重复逻辑 | 1 | launch_crew() 与 execute_crew() 重复发布事件 |
| 依赖关系遗漏 | 1 | 3.4a 缺少 BaseAgent 依赖 |
| 文档拼写错误 | 1 | "组件" → "组建" |
| **合计** | **9** | |

## 影响分析

- **可实现性**: CrewTool 类定义补全后，实现者无需猜测其接口和参数，直接参照 AgentTool 模式即可实现
- **配置完整性**: Config 包含 Crew 相关默认值，CrewOrchestrator 构造时可直接读取，无需硬编码
- **事件正确性**: 消除了事件重复发布问题，Crew 生命周期事件仅由 CrewOrchestrator 统一发布
- **依赖清晰性**: 路线图中的依赖关系与实际代码一致，实现顺序不会出现循环依赖

---

## 第二轮深度审查 (补充修复)

在对 Crew 机制进行反复检查后，发现以下额外问题并修复。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| A1 | `agent_doc/plan/03_tool_system.md` | CrewResult 新增 failed_members 字段, 澄清 success 判定语义; _aggregate_results() 更新; CrewOrchestrator/SubTask/CrewMember/AgentCrew/ExecutionStrategy 方法加详细注释; plan_crew() 文档补充 plan_temperature 使用说明; execute_crew() 文档更新事件负载描述; §9.4 编排流程图新增 ContextStore 写入步骤; §9.3 新增 CrewEvent 负载数据类; §9.6 CrewTool.execute() 新增异常处理 |
| A2 | `agent_doc/plan/00_architecture_overview.md` | §5 模块依赖图: CrewOrchestrator 依赖链补充 EventBus |
| A3 | `agent_doc/plan/01_base_agent.md` | crew_orchestrator 属性注释扩展, 说明核心能力 |
| A4 | `agent_doc/plan/06_specialized_agents.md` | 修复节号跳跃 (§5.5→§7→§8 改为 §5.5→§6→§7); §6 Crew 示例 register_tools() 明确标注为基础版本的扩展 |
| A5 | `agent_doc/plan/07_context_and_infra.md` | Crew 配置字段加详细注释 (用途与控制范围); EventBus 文档补充 CrewEvent 负载说明 |
| A6 | `agent_doc/plan/08_implementation_roadmap.md` | 任务 2.6a (CrewOrchestrator) 依赖补全 1.4 (EventBus); 依赖关系图同步更新 |

### 追加问题详情

#### 问题 8: 模块依赖图与路线图遗漏 EventBus 依赖

**发现**: `CrewOrchestrator.__init__()` 签名明确接收 `event_bus: EventBus` 参数并在执行过程中发布 Crew 生命周期事件。但:
- `00_architecture_overview.md` §5 模块依赖图中 CrewOrchestrator → AgentRegistry + AgentPool + LLMClient，缺少 EventBus
- `08_implementation_roadmap.md` 任务 2.6a 依赖仅列 `1.7, 2.6`，缺少 `1.4` (EventBus)

**修复**: 依赖图补全为 `CrewOrchestrator → AgentRegistry + AgentPool + LLMClient + EventBus`；任务 2.6a 依赖更新为 `1.4, 1.7, 2.6`；依赖关系图同步更新。

#### 问题 9: 06_specialized_agents.md 节号跳跃

**发现**: 文档从 §5.5 (Crew 编排) 直接跳到 §7 (Crew 使用示例)，再跳到 §8 (Agent 配置最佳实践)。§6 缺失。

**修复**: §7 → §6，§8 → §7，节号连续。

#### 问题 10: Crew 示例 register_tools() 与 §3.1 定义冲突

**发现**: §3.1 中 `CodeAgent.register_tools()` 注册 5 个基础 Tool (不含 CrewTool)。原 §7 (现 §6) 的 Crew 示例展示了包含 CrewTool 的完整 `register_tools()` 方法，但未说明这是 §3.1 版本的扩展。若实现者直接复制示例代码替换 §3.1 版本，将无意中丢失基础 Tool。

**修复**: 在示例代码中加标注 `# (以下为 §3.1 中 register_tools() 的扩展版本, 新增最后一行)`，并将基础 Tool 和 CrewTool 分组，明确扩展关系。

#### 问题 11: Crew 编排流程图缺少 ContextStore 写入步骤

**发现**: `BaseAgent.launch_crew()` 文档步骤 3 明确将 `CrewResult.mission_summary` 写入 ContextStore，但 `03_tool_system.md` §9.4 的编排流程图中未体现此步骤，导致两处文档不一致。

**修复**: §9.4 流程图在 Execute 和 Aggregate 之间新增步骤 4 "写入上下文: launch_crew() 将 CrewResult.mission_summary 写入 ContextStore"。

#### 问题 12: CrewLifecycleEvent 缺少事件负载数据结构

**发现**: CrewLifecycleEvent 作为 Enum 定义了事件类型，但 EventBus 发布事件时需要携带上下文数据 (如 crew_id, member_name, task_id)。其他事件类型 (AgentLifecycleEvent 等) 也无统一负载结构，但 Crew 事件因涉及多 Agent 协同，缺少负载数据将导致订阅者无法区分事件来源。

**修复**: 新增 `CrewEvent` 数据类，定义各事件类型携带的字段:
- PLANNED: crew_id, lead_agent_name, member_count
- STARTED: crew_id, strategy
- MEMBER_STARTED/COMPLETED/FAILED: crew_id, member_name, task_id, duration_ms, error_message
- COMPLETED: crew_id, total_duration_ms, token_usage
- FAILED: crew_id, error_message, partial_results

同步更新 `execute_crew()` 和 `plan_crew()` 文档，标注事件发布时携带 CrewEvent 负载；更新 `07_context_and_infra.md` EventBus 文档。

#### 问题 13: CrewTool.execute() 缺少异常处理

**发现**: `CrewTool.execute()` 直接调用 `self._agent.launch_crew()` 并包装结果，未处理可能的异常。若 launch_crew() 因 AgentPool 耗尽、LLM 调用超时等原因抛出异常，异常将向上传播到 ReAct 循环，导致整个 Agent 进入 ERROR 状态而非优雅降级。

**修复**: 用 try/except 包裹 launch_crew() 调用，捕获异常后返回失败的 ToolResult (success=False)，使 LLM 可在 Observation 中看到错误信息并选择重试或采用替代方案。

#### 问题 14: CrewResult.success 语义模糊，无部分失败追踪

**发现**: 原注释 `success: bool  # 整体是否成功 (全部子任务成功 = True)` 未说明:
- 部分成员失败时是否仍返回部分结果
- 调用方如何区分哪些成员成功、哪些失败
- DAG 模式下某分支失败是否导致整体失败

**修复**:
- `CrewResult` 新增 `failed_members: list[str]` 字段追踪失败成员
- `success` 注释扩展为判定规则: True = 全部成功; False = 任一成员失败，此时 mission_summary 含已完成部分 + 失败说明
- `_aggregate_results()` 文档更新为收集 failed_members 列表
- `_execute_sequential/parallel/dag` 方法文档补充失败处理行为说明

#### 问题 15: 代码注释不够详细

**发现**: Crew 相关数据模型和方法的注释偏简略，实现者可能无法从注释中理解设计意图和边界行为。

**修复**: 为以下类和方法补充详细注释:
- `SubTask`: 补充 task_id (UUID v4), description (应含输入/输出/验收标准), required_tags (匹配机制), dependencies (DAG 使用), context (传递机制)
- `CrewMember`: 补充生命周期状态转换说明 (PENDING→RUNNING→DONE/FAILED)
- `AgentCrew`: 补充生命周期 (ASSEMBLED→RUNNING→COMPLETED/FAILED), 各字段用途
- `CrewOrchestrator`: 补充设计原则 (无状态/策略可替换/LLM驱动/事件驱动)
- `_execute_sequential`: 补充失败不终止行为, 信息链传递
- `_execute_parallel`: 补充 ThreadPoolExecutor, 无 context 共享
- `_execute_dag`: 补充完整算法流程 (依赖图→拓扑排序→就绪队列→并发执行)
- `ExecutionStrategy`: 补充各策略的适用场景
- Config Crew 字段: 补充控制范围和推荐值

### 追加问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 依赖关系遗漏 | 2 | 模块依赖图 + 路线图 EventBus 遗漏 |
| 文档结构错误 | 2 | 节号跳跃 + register_tools() 冲突 |
| 跨文档不一致 | 1 | 编排流程图缺少 ContextStore 步骤 |
| 缺失数据结构 | 1 | CrewEvent 负载数据类 |
| 异常处理缺失 | 1 | CrewTool.execute() 无 try/except |
| 语义不明确 | 1 | CrewResult.success 判定规则 |
| 注释不够详细 | 8 | 数据模型 + 方法注释补充 |
| **第二轮合计** | **8** | (以问题计数, 注释问题合并为 1 项) |

### 累计修复统计 (第一轮 + 第二轮)

| 轮次 | 问题数 | 主要类型 |
|------|--------|----------|
| 第一轮 | 9 | 缺失定义、参数错误、类型错误、重复逻辑、依赖遗漏、拼写 |
| 第二轮 | 8 | 依赖遗漏、文档结构、跨文档不一致、缺失结构、异常处理、语义不清、注释 |
| **合计 (前两轮)** | **17** | |

---

## 第三轮深度审查 (追加修复)

在对 Crew 机制进行第三次反复检查后，发现以下额外问题并修复。本轮重点关注跨文档一致性、生命周期状态管理缺失、以及特化 Agent 与 Crew 编排机制的集成完整性问题。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| C1 | `agent_doc/plan/00_architecture_overview.md` | §3 ASCII 架构图修复组件名称对齐 (Crew/Orchestrator 分离 → 统一对齐) |
| C2 | `agent_doc/plan/01_base_agent.md` | form_crew() 传递 available_agents 参数到 plan_crew(); launch_crew() 补充 AgentCrew 一次性语义说明 |
| C3 | `agent_doc/plan/03_tool_system.md` | plan_crew() 新增 available_agents=None 回退逻辑文档 + created_at 初始化; execute_crew() 新增 crew 状态校验 (ASSEMBLED 前置条件) + 生命周期状态转换 (RUNNING→COMPLETED/FAILED); _aggregate_results() 补充 failed_members 构建流程; 新增 CrewInvalidStateError 错误类型 |
| C4 | `agent_doc/plan/06_specialized_agents.md` | 全部 4 个内置 Agent (CodeAgent/DocAgent/SearchAgent/ShellAgent) 的 register_tools() 新增 CrewTool 注册 + 注释; §5.5 补充 "任何 Agent 均可担任 CrewLeader" 说明; §6 移除与 §3.1 冲突的扩展版 register_tools(), 改为引用主定义 |
| C5 | `agent_doc/plan/08_implementation_roadmap.md` | 任务 2.6a (CrewOrchestrator) 依赖补全 2.1 (数据模型); 依赖关系图同步更新 |

### 追加问题详情

#### 问题 16: 00 架构图 ASCII 组件名称对齐错误

**发现**: `00_architecture_overview.md` §3 的架构分层 ASCII 图中, BaseAgent 内部组件框的行内文本对齐不一致 — `Orchestrator` 和 `Registry` 及 `Pool` 的首字符顶着内框左边界, 而上一行 `Crew`、`Agent`、`Agent` 后有大量空格, 导致组件名称在视觉上被"撕裂"成两半:
```
│  │  │ Crew      │ │ Agent    │ │ Agent  │ │
│  │  │Orchestrator│ │Registry  │ │ Pool   │ │
```
正确的做法是将所有组件名称在框内右对齐/居中对齐, 使名称不被换行割裂。

**修复**: 调整每行空格, 使组件名称在各自框内左对齐一致:
```
│  │  │ Crew           │ │ Agent        │ │ Agent     │ │
│  │  │ Orchestrator   │ │ Registry     │ │ Pool      │ │
```

#### 问题 17: form_crew() 不传递 available_agents

**发现**: `01_base_agent.md` 中 `BaseAgent.form_crew()` 调用 `crew_orchestrator.plan_crew(mission, lead_agent_name=self.name)`, 但 `plan_crew()` 的 `available_agents` 参数被忽略。当调用方未传递 `available_agents` 时, plan_crew() 的行为 (从 agent_registry 获取全部 Agent 列表作为默认值) 未在文档中说明, 实现者需要猜测。

**修复**: 
- `form_crew()` 文档更新, 显式传递 `available_agents=self.agent_registry.list_agents()`
- `plan_crew()` 文档补充: "若 available_agents 为 None, 则默认从 self.agent_registry.list_agents() 获取全部已注册 Agent"

#### 问题 18: Crew 生命周期状态管理缺失

**发现**: `03_tool_system.md` 的 `CrewOrchestrator` 存在以下生命周期管理缺陷:

a) **created_at 未初始化**: `AgentCrew.created_at` 默认为 0.0, 但 `plan_crew()` 文档中未说明何时设置此时间戳, 导致 `total_duration_ms` 计算可能错误。

b) **execute_crew() 无状态校验**: `execute_crew()` 未校验 `crew.status`, 可能导致重复执行同一 Crew 实例或执行未完成规划的 Crew。AgentCrew 设计为一次性使用 (ASSEMBLED → RUNNING → COMPLETED/FAILED), 但缺乏执行前状态检查的防护。

c) **execute_crew() 无状态转换**: `execute_crew()` 文档未说明在执行开始/结束时更新 crew.status, 导致 AgentCrew 实例在执行后仍显示为 ASSEMBLED, 违反其生命周期设计。

d) **missing error type**: 缺少 `CrewInvalidStateError` 错误类型来表示非法的 Crew 状态操作。

**修复**:
- `plan_crew()` 新增步骤 5: 设置 `crew.created_at = time.time()`
- `execute_crew()` 新增:
  - 前置条件校验: crew.status 必须为 ASSEMBLED, 否则抛出 `CrewInvalidStateError`
  - 执行开始: 设置 `crew.status = "RUNNING"`
  - 执行完成: 设置 `crew.status = "COMPLETED"` 或 `"FAILED"`
- 新增 `CrewInvalidStateError(Exception)` 类定义, 说明典型触发场景

#### 问题 19: _aggregate_results() 缺少 failed_members 构建逻辑

**发现**: `CrewResult` 在第 A1 轮中新增了 `failed_members: list[str]` 字段, 但 `_aggregate_results()` 方法文档仅用文字描述"收集 failed_members 列表", 未给出具体的遍历判定和填充步骤, 实现者不清楚:
- 以什么条件判定成员失败 (AgentResult.success == False + AgentResult.error != None)
- 失败成员的 AgentResult 是否仍参与 mission_summary 汇总
- failed_members 列表与 member_results 列表的关系

**修复**: `_aggregate_results()` 文档扩展为 6 步详细流程:
1. 遍历 results 拆分成功/失败成员
2. 失败成员记录到 failed_members, 提取 error 作为上下文
3. 拼接所有结果 (含失败信息) 为 LLM 汇总上下文
4. LLM 生成 mission_summary
5. 计算 total_duration_ms 和 total_token_usage
6. 判定 success: failed_members 为空则 True, 非空则 False

#### 问题 20: 所有内置 Agent 缺少 CrewTool 注册

**发现**: `06_specialized_agents.md` §3.1-§3.4 的 4 个内置特化 Agent (CodeAgent/DocAgent/SearchAgent/ShellAgent) 在 `register_tools()` 中均未注册 `CrewTool(agent=self)`。

核心矛盾: 框架设计明确声明 **"任何特化 Agent 均可成为 CrewLeader"** (见 00_architecture_overview.md §2, 01_base_agent.md crew_orchestrator 属性注释, 06_specialized_agents.md §2 设计原则), 但没有内置 Agent 注册了 CrewTool。这意味着:

- 所有内置 Agent 无法通过 Function Calling 发起 Crew 编排 — LLM 在 ReAct 循环中看不到 `launch_crew` Tool
- 虽然 `BaseAgent` 提供了 `form_crew()` / `launch_crew()` 方法可供编程调用, 但 LLM 驱动的自主 Crew 组建能力完全缺失
- 用户必须手动在每个 Agent 子类中注册 CrewTool 才能启用此核心能力, 违背"开箱即用"的设计意图

**修复**:
- CodeAgent/CodeAgent/DocAgent/SearchAgent/ShellAgent 的 `register_tools()` 方法均添加:
  ```python
  # ── Crew 编排 Tool ──
  # 注册 CrewTool 使此 Agent 可通过 Function Calling 发起 Crew 编排,
  # 成为 CrewLeader 动态组建 Agent 团队完成复杂任务。
  self.tool_manager.register(CrewTool(agent=self))
  ```
- 添加注释说明注册意图

#### 问题 21: §6 Crew 示例 register_tools() 与主定义代码冲突

**发现**: 在问题 20 修复前, `06_specialized_agents.md` 存在两处 `register_tools()` 定义:
- §3.1 (主定义): 注册 5 个基础 Tool, 不含 CrewTool
- §6 (示例): 注册 5 个基础 Tool + CrewTool, 标注为 "扩展版本"

问题 20 修复后, 主定义已包含 CrewTool, §6 的 "扩展版本" 标注反而会产生误导 — 建议用户额外扩展一个已有功能。

**修复**: §6 移除重复的 `register_tools()` 代码块, 改为说明:
"所有内置 Agent 已在 register_tools() 中注册了 CrewTool(agent=self), 因此均可通过 Function Calling 发起 Crew 编排, 开箱即用地充当 CrewLeader。"

#### 问题 22: 08 路线图 CrewOrchestrator 缺少数据模型依赖

**发现**: `08_implementation_roadmap.md` 任务 2.6a (CrewOrchestrator) 的依赖列为 `1.4, 1.7, 2.6`, 但 `CrewOrchestrator` 的实现需要以下数据模型:
- `SubTask`, `CrewMember`, `AgentCrew`, `CrewResult`, `CrewEvent` (定义在 2.1 数据模型任务中)
- `ExecutionStrategy` (定义在 2.1 或 CrewOrchestrator 自身中)

虽然部分数据模型可能随 CrewOrchestrator 一起实现, 但 `AgentCrew`/`CrewResult` 被 `BaseAgent` (2.10) 引用, `CrewEvent` 被 `EventBus` (1.4) 引用, 因此这些共享数据模型应归入 2.1 任务提前定义。

**修复**: 任务 2.6a 依赖更新为 `1.4, 1.7, 2.1, 2.6`; 依赖关系图同步更新。

#### 问题 23: launch_crew() 未说明重复执行行为

**发现**: `BaseAgent.launch_crew()` 文档未说明:
- 每次调用是否创建全新的 AgentCrew (通过 form_crew)
- AgentCrew 是否可重复执行
- 若用户先调用 form_crew() 再手动调用 execute_crew(), 再调用 launch_crew() 会发生什么

这导致实现者和使用者对 Crew 的复用语义存在歧义。

**修复**: `launch_crew()` 文档新增注意事项:
"此方法每次调用都会通过 form_crew() 创建全新的 AgentCrew, 不会复用之前的 Crew。AgentCrew 是一次性的 (执行后状态变为 COMPLETED/FAILED, 不可重复执行)。"

#### 问题 24: §5.5 示例未说明 CodeAgent 非特例

**发现**: `06_specialized_agents.md` §5.5 "Crew 编排" 直接以 "CodeAgent (CrewLeader)" 作为示例, 但缺乏说明: 此示例以 CodeAgent 为代表, 任何特化 Agent 均可担任此角色。

新读者可能误以为只有 CodeAgent 能做 CrewLeader。

**修复**: 在流程图前新增一行说明:
"以下以 CodeAgent 作为 CrewLeader 为例 — 任何已注册 CrewTool 的特化 Agent 均可担任此角色。"

### 第三轮问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 生命周期管理缺失 | 4 | created_at 未初始化, execute_crew() 无状态校验/转换, 缺 CrewInvalidStateError |
| 方法实现不完整 | 2 | _aggregate_results() 缺 failed_members 构建逻辑, form_crew() 缺 available_agents 传递 |
| 功能集成缺失 | 1 | 全部 4 个内置 Agent 缺 CrewTool 注册 (核心能力无法启用) |
| 文档冲突/不一致 | 2 | §6 register_tools() 与 §3.1 冲突, §5.5 未说明 CrewLeader 普适性 |
| 依赖关系遗漏 | 1 | 08 路线图 2.6a 缺 2.1 数据模型依赖 |
| 语义不明 | 2 | launch_crew() 未说明一次性语义, ASCII 图组件名撕裂 |
| **第三轮合计** | **11** | (问题 18 合并 4 个子问题) |

### 三轮累计修复统计

| 轮次 | 问题数 | 主要类型 |
|------|--------|----------|
| 第一轮 | 9 | 缺失定义、参数错误、类型错误、重复逻辑、依赖遗漏、拼写 |
| 第二轮 | 8 | 依赖遗漏、文档结构、跨文档不一致、缺失结构、异常处理、语义不清、注释 |
| 第三轮 | 11 | 生命周期管理缺失、功能集成缺失、文档冲突、参数传递、依赖遗漏、语义不明 |
| **总计** | **28** | |

### 第三轮影响分析

- **核心能力可用性**: 问题 20 的修复使所有内置 Agent 开箱即用地支持 Crew 编排, 无需用户手动配置。这是确保 "任何 Agent 均可成为 CrewLeader" 设计承诺的关键修复。
- **Crew 生命周期完整性**: 问题 18 (a-d) 的修复确保了 AgentCrew 的状态机正确运转, 防止了重复执行、时间戳未初始化等可能导致数据错误或资源泄漏的问题。
- **文档一致性**: 问题 21/24 消除了代码示例与主定义之间的冲突, 避免实现者引用冲突信息。
- **依赖正确性**: 问题 22 确保了路线图中的构建顺序与实际代码依赖一致, 避免实现阶段的顺序错误。
