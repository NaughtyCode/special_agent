# 修改记录 — Issue #7

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue7 |
| 修改日期 | 2026-05-01 |
| 修改类型 | Crew 机制深度审查 (九轮) — 补全缺失定义、修复跨文档不一致、增强注释与错误处理、修复生命周期管理缺失、修复类型不一致与执行细节缺失、修复运行时逻辑错误与资源管理缺陷、修复类型系统歧义与流程图逻辑错误、修复代码示例错误与边界条件校验缺失、修复计时字段与时序计算错误、修复 falsy 值判空 Bug 与深度传播缺失 |
| 关联文档 | `agent_doc/plan/` (00, 01, 03, 06, 07, 08) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 Issue #6 新增的 Crew 团队编排机制进行九轮反复深度审查。

**第一轮**: 修复缺失的类定义、配置字段缺失、方法参数传递错误、事件定义格式错误、事件发布重复、依赖关系遗漏等问题。

**第二轮**: 修复模块依赖图与路线图遗漏 EventBus、文档节号跳跃与代码示例冲突、编排流程图不一致、Crew 事件负载缺失、异常处理缺失、success 语义模糊等问题，并为所有 Crew 相关数据模型和方法补充详细注释。

**第三轮**: 修复生命周期状态管理缺失 (created_at 未初始化/无状态校验/无状态转换)、全部内置 Agent 缺少 CrewTool 注册、_aggregate_results 缺 failed_members 构建逻辑、form_crew 缺 available_agents 传递等问题。

**第四轮**: 修复类型系统不一致 (list_agents 返回 dict vs AgentMeta)、AgentTool 属性缺失、SubTask→agent.run() 参数映射未文档化、plan_crew JSON 解析失败处理缺失、CrewTool vs AgentTool 选择指南缺失等问题。

**第五轮**: 修复运行时逻辑错误 (strategy 解析未捕获异常)、线程安全文档缺失、execution_order 填充逻辑缺失、资源管理缺陷 (AgentPool acquire/release 无 finally)、AgentConfig Crew 覆写字段缺失、CrewMember 计时字段缺失、空 mission 校验缺失、PARALLEL 策略依赖警告缺失、聚合方法步骤编号重复等问题。

**第六轮**: 修复类型系统歧义 (member_results/failed_members 使用非唯一 agent_name 而非 task_id)、编排流程图逻辑错误 (form_crew + launch_crew 冗余调用)、DAG 循环依赖检测缺失、max_parallel 回退逻辑未文档化、CrewEvent 类型不精确、launch_crew 参数覆写解析顺序缺失等问题。

**第七轮**: 修复 execute_crew 代码示例变量名错误 (agent→member.agent_instance, task→member.task)、AgentPool factory 参数未文档化、CrewTool.execute() KeyError 未捕获、plan_crew 依赖引用校验缺失/Agent 匹配校验缺失、execute_crew 空成员列表未处理、DAG context 线程安全覆盖不全、task.context=None 时合并崩溃、AgentTool 与 CrewTool 错误处理不一致等问题。

**第八轮**: 修复 AgentCrew 缺少 completed_at 字段、total_duration_ms 使用错误计算方式 (sum of member durations 不适用于并发执行)、plan_crew 未文档化 crew_id 生成、execute_crew 未记录 completed_at、CrewTool JSON Schema 缺少 default 值、_execute_dag 未传递 max_parallel 导致无并发上限、_aggregate_results LLM 聚合失败未处理、Crew 嵌套递归风险未文档化等问题。

**第九轮**: 修复 max_parallel 参数使用 `or` 运算导致 0 值被错误回退、plan_crew 未文档化 SubTask UUID 生成与依赖重映射机制、agent_pool.acquire() 在 try 块外导致异常时成员静默丢失、total_duration_ms 可能因未设置 completed_at 产生负值、_execute_sequential 首个成员 context=None 行为未文档化、CrewResult 示例缺少 crew_id/total_duration_ms 字段、_execute_dag 波次模型并行槽位利用不足未说明、_execute_sequential 仅传递 final_answer 的简化设计未解释、agent_factory 未传播 call_depth 导致 Crew 嵌套深度保护失效、CrewOrchestrator 未存储 Config 引用等问题。

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
| **总计 (前三轮)** | **28** | |

### 第三轮影响分析

- **核心能力可用性**: 问题 20 的修复使所有内置 Agent 开箱即用地支持 Crew 编排, 无需用户手动配置。这是确保 "任何 Agent 均可成为 CrewLeader" 设计承诺的关键修复。
- **Crew 生命周期完整性**: 问题 18 (a-d) 的修复确保了 AgentCrew 的状态机正确运转, 防止了重复执行、时间戳未初始化等可能导致数据错误或资源泄漏的问题。
- **文档一致性**: 问题 21/24 消除了代码示例与主定义之间的冲突, 避免实现者引用冲突信息。
- **依赖正确性**: 问题 22 确保了路线图中的构建顺序与实际代码依赖一致, 避免实现阶段的顺序错误。

---

## 第四轮深度审查 (补充修复)

在对 Crew 机制进行第四次反复检查后，发现以下额外问题。本轮重点关注类型系统一致性、执行细节文档缺失、以及跨模块接口契约的正确性。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| D1 | `agent_doc/plan/03_tool_system.md` | AgentRegistry.list_agents() 返回类型从 list[dict] 修正为 list[AgentMeta] (修复与 plan_crew() 的类型不匹配); AgentTool.__init__ 补全 tags 和 requires_confirmation 属性初始化; _execute_sequential/_execute_parallel/_execute_dag 补充 SubTask→agent.run() 参数映射文档 + 成员 task 非空校验 + context 合并策略详细说明; plan_crew() 补充 LLM JSON 解析失败的重试与 CrewPlanError 错误处理; 新增 CrewPlanError 错误类; CrewTool 补充与 AgentTool 的 LLM 选择指南 |
| D2 | `agent_doc/plan/00_architecture_overview.md` | §4.3 plan_crew 流程图补充 created_at 初始化步骤 |
| D3 | `agent_doc/plan/06_specialized_agents.md` | §4 自定义 Agent 示例补充 CrewTool 注册 (含注释说明可选性) |

### 追加问题详情

#### 问题 25: AgentRegistry.list_agents() 与 plan_crew() 类型不匹配

**发现**: `AgentRegistry.list_agents()` 返回类型声明为 `list[dict]` (dict 含 name/description/tags), 但 `CrewOrchestrator.plan_crew()` 的 `available_agents` 参数类型声明为 `list[AgentMeta] | None`, 且 `BaseAgent.form_crew()` 直接传递 `self.agent_registry.list_agents()` 给 `plan_crew()`。

类型不一致导致:
- `plan_crew()` 无法从 dict 中获取 `agent_cls` 字段 (dict 中不存在此键)
- `plan_crew()` 需要 `agent_cls` 来构建 `CrewMember.agent_cls`, 以便后续延迟实例化
- 实现者需要做 dict→AgentMeta 转换, 增加不必要的复杂度

**修复**: `list_agents()` 返回类型改为 `list[AgentMeta]`, 文档更新。AgentMeta 是 AgentRegistry 内部缓存的元数据, 直接返回可保留 agent_cls 引用, 消除类型转换。

#### 问题 26: AgentTool 缺少必要属性初始化

**发现**: `AgentTool.__init__` 未初始化 `BaseTool` 要求的以下属性:
- `self.tags` — 必填, 用于 Tool 匹配时的标签筛选
- `self.requires_confirmation` — 必填, 用于安全策略判定

虽然 `AgentTool` 继承了 `BaseTool`, 但 `BaseTool` 使用类级别属性声明 (无默认值), 实例化时如果 `__init__` 不设置这些属性, 访问时会抛出 `AttributeError`。

对比 `CrewTool.__init__` 正确设置了这两个属性:
```python
self.tags = ["crew", "team", "orchestrate", "coordinate"]
self.requires_confirmation = False
```

**修复**: `AgentTool.__init__` 补充:
```python
self.tags = agent_meta.tags              # 继承 Agent 的标签
self.requires_confirmation = False       # Agent 拉起默认无需确认
```

#### 问题 27: SubTask→agent.run() 参数映射未文档化

**发现**: 三种执行方法 (`_execute_sequential/parallel/dag`) 的文档描述均提及 "从 AgentPool 获取实例并执行", 但从未说明 `SubTask` 的字段如何映射到 `agent.run()` 的参数。实现者需要猜测:
- `task.description` → `agent.run(user_input)` 还是 `agent.run(context)`?
- `task.context` 字典如何传递?
- 多个依赖任务的结果如何在 context 中组织?

**修复**: 三个执行方法文档均补充明确的参数映射:
```
agent.run(user_input=task.description, context=task.context)
```
其中:
- `_execute_sequential`: context 合并策略 — 保留原有键, 新增 `"previous_result"` 和 `"previous_error"` 键
- `_execute_parallel`: 各成员使用各自的 task.context, 成员间不共享运行时 context
- `_execute_dag`: context 合并策略 — 保留原有键, 新增 `"dependency_results"` (dict[task_id, final_answer]) 和 `"dependency_errors"` (dict[task_id, error_message])

#### 问题 28: 执行方法缺少成员 task 非空校验

**发现**: `CrewMember.task` 类型为 `SubTask | None = None`, 但三种执行方法均未校验 task 是否为 None。若 `plan_crew()` 阶段因异常未正确分配 task, 执行阶段会出现 `AttributeError: 'NoneType' object has no attribute 'description'`, 错误信息不友好。

**修复**: 三种执行方法文档均补充前置条件:
"执行前校验: 每个 member.task 必须非 None, 否则抛出 ValueError (task 为 None 表示 plan_crew 阶段未正确分配子任务)"

#### 问题 29: plan_crew() 缺少 LLM JSON 解析失败的错误处理

**发现**: `plan_crew()` 调用 LLM 生成结构化 JSON 子任务列表, 但文档未说明 LLM 返回非 JSON 或空列表时的处理方式。LLM 输出不可靠是已知问题, 缺少重试和错误处理将导致不可恢复的 `JSONDecodeError` 向上传播。

**修复**: `plan_crew()` 内部流程补充:
- JSON 解析失败时, 进行最多 `crew_max_iterations` 次重试, 每次将解析错误反馈给 LLM 要求修正
- 全部重试耗尽仍失败则抛出 `CrewPlanError` (含 `raw_llm_output` 属性供调试)
- 新增 `CrewPlanError(Exception)` 错误类, 携带原始 LLM 输出

#### 问题 30: 自定义 Agent 示例缺少 CrewTool 注册

**发现**: `06_specialized_agents.md` §4 的自定义 Agent 示例 (`MyDomainAgent`) 展示了如何创建新 Agent, 但其 `register_tools()` 未包含 `CrewTool` 注册。鉴于框架设计原则明确声明 "任何特化 Agent 均可成为 CrewLeader", 示例应展示这一最佳实践。

**修复**: 示例的 `register_tools()` 新增 CrewTool 注册块 (含注释):
```python
# ── Crew 编排 Tool (推荐) ──
# 注册 CrewTool 使此 Agent 可作为 CrewLeader 发起团队协作。
# 若此 Agent 不需要领导团队, 可移除此行。
from agent.tools.crew_tool import CrewTool
self.tool_manager.register(CrewTool(agent=self))
```

#### 问题 31: CrewTool 与 AgentTool 触发条件缺少 LLM 选择指南

**发现**: LLM 在 ReAct 循环中同时面对两种拉起 Agent 的 Tool:
- `launch_<agent>` (AgentTool, 每个注册的 Agent 一个)
- `launch_crew` (CrewTool, 全局一个)

但设计文档未说明 LLM 应如何在这两者之间做出选择, 可能导致:
- LLM 对所有任务都调用 `launch_crew` (过度分解简单任务)
- LLM 对复杂任务逐个调用 `launch_<agent>` (不会分解, 效率低)

**修复**: `CrewTool` 文档新增 "LLM 选择指南", 明确使用场景:
- 简单单领域任务 → `launch_<agent>`
- 复杂多领域/多阶段任务 → `launch_crew`

该指南应写入 Agent 的 system_prompt 中 Tool 使用说明部分。

#### 问题 32: 00 架构图 plan_crew 流程图遗漏 created_at 初始化

**发现**: 在第三轮中为 `plan_crew()` 补充了 `created_at` 初始化步骤, 但 `00_architecture_overview.md` §4.3 的 Crew 编排流程概览图中未同步更新。架构总览作为项目的 "地图", 应反映最新的设计细节。

**修复**: §4.3 流程图中 "组建 AgentCrew (含 N 个 CrewMember)" → "组建 AgentCrew (含 N 个 CrewMember, 设置 created_at)"。

### 第四轮问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 类型系统不一致 | 1 | list_agents() 返回 dict vs AgentMeta |
| 属性初始化缺失 | 1 | AgentTool 缺 tags + requires_confirmation |
| 执行细节缺失 | 3 | 参数映射、task 校验、context 合并策略 (覆盖 3 个执行方法) |
| 错误处理缺失 | 1 | plan_crew() 缺 JSON 解析失败处理 |
| 文档/示例不完整 | 2 | 自定义 Agent 示例缺 CrewTool; CrewTool vs AgentTool 选择指南 |
| 跨文档不一致 | 1 | 架构总览图遗漏 created_at |
| **第四轮合计** | **9** | |

### 四轮累计修复统计

| 轮次 | 问题数 | 主要类型 |
|------|--------|----------|
| 第一轮 | 9 | 缺失定义、参数错误、类型错误、重复逻辑、依赖遗漏、拼写 |
| 第二轮 | 8 | 依赖遗漏、文档结构、跨文档不一致、缺失结构、异常处理、语义不清、注释 |
| 第三轮 | 11 | 生命周期管理缺失、功能集成缺失、文档冲突、参数传递、依赖遗漏、语义不明 |
| 第四轮 | 9 | 类型不一致、属性缺失、执行细节缺失、错误处理缺失、示例不完整、选择指南 |
| **总计** | **37** | |

### 第四轮影响分析

- **类型安全**: 问题 25 的修复消除了 `list_agents()` 与 `plan_crew()` 之间的隐式类型转换需求, AgentMeta 贯穿整个 Crew 编排链路, 确保 agent_cls 引用不丢失。
- **接口契约完整性**: 问题 27/28/29 补全了 SubTask 到 agent.run() 的映射约定, 实现者无需猜测参数传递方式, 且不同执行策略的 context 合并语义明确无歧义。
- **运行时健壮性**: 问题 29 的 JSON 重试机制 + CrewPlanError 确保了 LLM 输出不可靠时的优雅降级, 避免了未捕获异常导致 Agent 进入 ERROR 状态。
- **开发者体验**: 问题 30 使自定义 Agent 示例包含 CrewTool 注册, 新开发者复制示例即可获得完整的 CrewLeader 能力, 避免因遗漏注册而导致功能不可用。

---

## 第五轮深度审查 (补充修复)

在对 Crew 机制进行第五次反复检查后，发现以下额外问题。本轮重点关注运行时逻辑错误、资源管理缺陷、以及跨模块配置一致性问题。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| E1 | `agent_doc/plan/03_tool_system.md` | CrewTool.execute() 将 ExecutionStrategy() 解析移入 try/except 块内; _execute_dag 补充线程安全文档; 三种执行方法补充 execution_order 填充逻辑; _execute_sequential 补充首个成员上下文说明; 三种执行方法补充 per-member try/finally AgentPool acquire/release 模式; plan_crew() 新增空 mission 校验; _execute_parallel 新增依赖忽略警告; CrewMember 新增 started_at/completed_at 计时字段; _aggregate_results 补充 LLM 温度参数说明 + 修复步骤编号重复 |
| E2 | `agent_doc/plan/01_base_agent.md` | AgentConfig 新增 Crew 覆写字段 (crew_max_parallel_override, crew_strategy_override) |

### 追加问题详情

#### 问题 33: CrewTool.execute() strategy 解析未捕获异常

**发现**: `CrewTool.execute()` 中 `strategy = ExecutionStrategy(strategy_str)` 位于 try/except 块之前。若 LLM 传入非法的 strategy 字符串 (如 `"sequentiall"` 拼写错误), `ExecutionStrategy()` 构造函数将抛出 `ValueError`, 此异常不会被 try/except 捕获, 向上传播到 ReAct 循环导致 Agent 进入 ERROR 状态。

**修复**: 将 `ExecutionStrategy(strategy_str)` 解析移至 try/except 块内部, 使 `ValueError` 被捕获并返回 `ToolResult(success=False, error=...)` 反馈给 LLM, LLM 可自行修正。

#### 问题 34: _execute_dag 缺少线程安全文档

**发现**: `_execute_dag` 在并发执行就绪队列成员时, 多个线程同时读写 `crew.members[i].status`、`crew.members[i].result` 以及 `execution_order` 列表。若不加锁保护, 存在数据竞争风险:
- 两个线程同时判定某成员的依赖已满足, 导致重复执行
- execution_order 列表并发 append 导致顺序错乱或数据损坏

**修复**: `_execute_dag` 文档补充线程安全说明: 对 crew.members[i].status/result 的读写必须通过 threading.Lock 保护, 每个 CrewMember 使用独立锁, 或对就绪队列操作使用单一锁 + 原子状态更新。

#### 问题 35: execution_order 填充逻辑未文档化

**发现**: `CrewResult.execution_order: list[str]` 字段已定义 (存储 task_id 列表), 但三种执行方法均未说明如何填充此列表。实现者需自行推断每个方法应有的填充顺序:
- SEQUENTIAL: 按 members 列表顺序 (即 plan_crew 分解顺序)
- PARALLEL: 按提交顺序 (submit 顺序)
- DAG: 按拓扑完成顺序 (先完成的先记录)

**修复**: 三种执行方法文档均补充 `execution_order` 填充说明, 明确各策略下 task_id 的记录顺序。`_aggregate_results` 步骤 5 同步更新为从 results 提取 execution_order。

#### 问题 36: _execute_sequential 首个成员上下文未说明

**发现**: `_execute_sequential` 文档说明后续成员可通过 context 接收前一成员的结果, 但未说明第一个成员的 context 初始值是什么。实现者可能误以为需要特殊初始化。

**修复**: 补充说明: "第一个 (索引 0) 成员使用其原始的 task.context, 不做任何合并; 从第二个成员开始, 才将前一成员的结果合并到 context 中。"

#### 问题 37: AgentPool acquire/release 缺少 try/finally 保护

**发现**: 三种执行方法的代码示例中, `agent_pool.acquire()` 和 `agent_pool.release()` 之间没有 try/finally 保护。若 `agent.run()` 抛出异常, `agent_pool.release()` 不会被调用, 导致 Agent 实例泄漏 — 被 acquire 的实例永远不会归还到池中, 最终 AgentPool 耗尽。

**修复**: 三种执行方法均补充 per-member try/finally 代码模式:
```python
member.agent_instance = agent_pool.acquire(member.agent_name, ...)
try:
    member.status = "RUNNING"
    member.started_at = time.time()
    member.result = agent.run(task.description, task.context)
    member.status = "DONE"
except Exception as e:
    member.status = "FAILED"
    member.result = AgentResult(success=False, final_answer=str(e), ...)
finally:
    member.completed_at = time.time()
    agent_pool.release(member.agent_instance)
```

#### 问题 38: AgentConfig 缺少 Crew 覆写字段

**发现**: `AgentConfig` (定义于 `01_base_agent.md`) 支持覆写 LLM 模型/温度/迭代次数等参数, 但未提供 Crew 相关配置的覆写。当不同 Agent 需要不同的 Crew 执行策略或并行数时, 只能使用全局 Config, 无法实现 per-agent 调参。

**修复**: `AgentConfig` 新增:
```python
crew_max_parallel_override: int | None = None   # 覆写 Crew 最大并行数
crew_strategy_override: str | None = None       # 覆写默认执行策略
```
CrewOrchestrator 执行时优先读取 AgentConfig 覆写值, 回退到全局 Config。

#### 问题 39: CrewMember 缺少计时字段

**发现**: `CrewMember` 数据模型包含 `status` 和 `result` 字段, 但没有 `started_at` 和 `completed_at` 时间戳字段。这使得:
- 无法计算单个成员的执行耗时
- `CrewResult.total_duration_ms` 只能通过整个 Crew 的起止时间计算, 精度不足
- 事件负载 (CrewEvent) 无法携带 per-member 的 duration_ms

**修复**: `CrewMember` 新增 `started_at: float = 0.0` 和 `completed_at: float = 0.0` 字段, 在三种执行方法中于 try/finally 块中设置。

#### 问题 40: _aggregate_results LLM 温度参数未文档化

**发现**: `_aggregate_results` 步骤 3 调用 LLM 生成 mission_summary, 但未说明使用哪个温度参数。Config 中同时存在 `llm_temperature` (通用) 和 `crew_plan_temperature` (规划专用, 默认 0.4)。聚合任务属于总结性工作而非规划性工作, 若错误使用 `crew_plan_temperature` (0.4) 会导致输出过于机械, 而使用 `llm_temperature` (默认 0.7) 更适合自然语言总结。

**修复**: `_aggregate_results` 步骤 3 明确标注使用 `Config.llm_temperature` (默认 0.7) 而非 `plan_temperature`, 并说明原因: 聚合是总结性工作, 需要语言表达灵活性; plan_temperature 追求的是分解的结构稳定性。

#### 问题 41: plan_crew() 缺少空 mission 校验

**发现**: `plan_crew()` 未校验 `mission` 参数是否为空字符串。若调用方传入空 mission, LLM 将收到无意义的 prompt, 可能返回空列表或无关内容, 导致后续执行出现难以调试的错误。

**修复**: `plan_crew()` 前置条件新增: mission 必须非空且去除空白后长度 > 0, 否则抛出 `ValueError("mission must be non-empty")`。

#### 问题 42: _execute_parallel 未警告依赖被忽略

**发现**: `_execute_parallel` 以最大并发度执行所有成员, 不检查 `SubTask.dependencies`。若 plan_crew 阶段错误地为并行场景分配了依赖关系, 这些依赖会被静默忽略, 导致执行结果不符合预期。

**修复**: `_execute_parallel` 文档新增警告: "PARALLEL 策略忽略 SubTask.dependencies, 所有成员同时执行。若子任务之间存在实际依赖, 应使用 DAG 策略。plan_crew() 在选择 PARALLEL 策略时应确保分解出的 SubTask 无依赖关系。"

#### 问题 43: _aggregate_results 步骤编号重复

**发现**: `_aggregate_results` 方法文档中, 步骤 6 "判定整体 success" 和步骤 7 "构建并返回 CrewResult" 均被编号为 `6.`, 导致步骤编号重复。

**修复**: 将最后一个步骤的编号从 `6.` 修正为 `7.`。

### 第五轮问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 运行时逻辑错误 | 1 | CrewTool.execute() strategy 解析未捕获异常 |
| 线程安全文档缺失 | 1 | _execute_dag 并发写入无锁保护说明 |
| 执行细节缺失 | 2 | execution_order 填充逻辑、首个成员上下文说明 |
| 资源管理缺陷 | 1 | AgentPool acquire/release 无 try/finally |
| 配置缺失 | 1 | AgentConfig 缺 Crew 覆写字段 |
| 数据模型缺失 | 1 | CrewMember 缺计时字段 |
| 文档精确性 | 3 | 聚合温度参数、空 mission 校验、PARALLEL 依赖警告 |
| 编号错误 | 1 | _aggregate_results 步骤 6 重复 |
| **第五轮合计** | **11** | |

### 五轮累计修复统计

| 轮次 | 问题数 | 主要类型 |
|------|--------|----------|
| 第一轮 | 9 | 缺失定义、参数错误、类型错误、重复逻辑、依赖遗漏、拼写 |
| 第二轮 | 8 | 依赖遗漏、文档结构、跨文档不一致、缺失结构、异常处理、语义不清、注释 |
| 第三轮 | 11 | 生命周期管理缺失、功能集成缺失、文档冲突、参数传递、依赖遗漏、语义不明 |
| 第四轮 | 9 | 类型不一致、属性缺失、执行细节缺失、错误处理缺失、示例不完整、选择指南 |
| 第五轮 | 11 | 运行时逻辑错误、线程安全、资源管理缺陷、配置缺失、数据模型缺失、文档精确性 |
| **总计** | **48** | |

### 第五轮影响分析

- **运行时健壮性**: 问题 33 确保了 LLM 传入非法 strategy 值时优雅降级而非崩溃; 问题 37 的 try/finally 模式杜绝了 Agent 实例泄漏, 保证了 AgentPool 的长期稳定运行。
- **并发安全**: 问题 34 明确了 DAG 执行中的线程安全要求, 防止数据竞争导致的依赖解析错误或结果丢失。
- **可观测性**: 问题 35 (execution_order) 和问题 39 (CrewMember 计时字段) 使 Crew 执行的追踪和调试成为可能, 为未来的监控/审计功能奠定基础。
- **配置粒度**: 问题 38 使每个 Agent 可独立调整 Crew 策略和并行度, 与 AgentConfig 现有的模型/温度覆写形成一致的 per-agent 调参体系。
- **文档完整性**: 问题 40/41/42/43 消除了边界行为的不确定性, 实现者不再需要猜测聚合温度选择、空输入处理或并行策略的依赖行为。

---

## 第六轮深度审查 (补充修复)

在对 Crew 机制进行第六次反复检查后，发现以下额外问题。本轮重点关注类型系统歧义（非唯一标识符）、流程图逻辑错误、以及遗漏的边界条件处理。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| F1 | `agent_doc/plan/03_tool_system.md` | CrewResult.member_results 类型从 `list[tuple[str, AgentResult]]` 改为 `list[tuple[str, str, AgentResult]]` 新增 task_id (agent_name 非唯一, 同类型 Agent 结果无法区分); failed_members 类型从 `list[str]` 改为 `list[tuple[str, str]]` (agent_name, task_id); 三种执行方法返回类型同步更新; _aggregate_results 签名和步骤更新; CrewEvent.partial_results 裸 list 类型精确化; execute_crew 补充 max_parallel 回退逻辑文档 + 代码示例补全 started_at/completed_at 设置 + 事件文档补全 duration_ms/error_message; _execute_dag 新增循环依赖检测文档; _execute_parallel 补充失败处理说明和结果收集方式; CrewPlanError 场景新增循环依赖; §9.4 编排流程图重构为 launch_crew 一站式入口 |
| F2 | `agent_doc/plan/00_architecture_overview.md` | §4.3 Crew 编排流程图重构: form_crew + launch_crew 冗余调用 → launch_crew 一站式入口含内部 PLAN→EXECUTE→AGGREGATE 子步骤 |
| F3 | `agent_doc/plan/01_base_agent.md` | launch_crew() 新增 AgentConfig 覆写参数解析顺序文档 (crew_strategy_override → 参数 → 默认值) |
| F4 | `agent_doc/plan/06_specialized_agents.md` | §6 CrewResult 示例更新 member_results 为三元组格式 (agent_name, task_id, AgentResult), 新增 execution_order 和 failed_members 字段 |

### 追加问题详情

#### 问题 44: member_results 使用 agent_name 作为标识符存在歧义

**发现**: `CrewResult.member_results` 类型为 `list[tuple[str, AgentResult]]`, 其中 `str` 为 agent_name。但 Crew 允许同一类型的 Agent 处理多个子任务 (如 CodeAgent 同时负责后端和前端), agent_name 不唯一。

导致的问题:
- `member_results` 中两个 `("CodeAgent", AgentResult(...))` 无法区分谁对应哪个子任务
- `failed_members: list[str]` 存储 agent_name, 同样无法定位具体是哪个子任务失败
- `execution_order: list[str]` 使用 task_id, 但与 member_results 通过隐式位置对应, 脆弱易错

**修复**:
- `member_results` 改为 `list[tuple[str, str, AgentResult]]` — (agent_name, task_id, AgentResult), task_id 提供唯一标识
- `failed_members` 改为 `list[tuple[str, str]]` — (agent_name, task_id)
- 三种执行方法 (`_execute_sequential/parallel/dag`) 返回类型同步更新
- `_aggregate_results` 步骤 1 和 5 更新为从 tuple 中提取 task_id
- `CrewEvent.partial_results` 类型从裸 `list` 精确化为 `list[tuple[str, str, AgentResult]]`
- `06_specialized_agents.md` CrewResult 示例更新格式

#### 问题 45: 编排流程图 form_crew + launch_crew 冗余调用

**发现**: `00_architecture_overview.md` §4.3 和 `03_tool_system.md` §9.4 的编排流程图存在逻辑错误:

```
├─ 2. 调用 self.form_crew(mission)          ← 创建 AgentCrew
│     └─ plan_crew() → AgentCrew
│
├─ 3. 调用 self.launch_crew(mission, strategy)  ← 内部再次调用 form_crew()!
│     └─ execute_crew(crew, strategy)
```

`launch_crew()` 内部已调用 `form_crew()` (见 `01_base_agent.md` 步骤 1), 因此步骤 3 会创建第二个 AgentCrew, 步骤 2 的产物被丢弃。正确流程应展示 launch_crew 作为一站式入口, 内部依次完成 Plan → Execute → Aggregate。

**修复**: 两个文件的流程图均重构为:
```
├─ 2. 调用 launch_crew(mission, strategy)
│     ├─ 2a. PLAN: form_crew → plan_crew → AgentCrew
│     ├─ 2b. EXECUTE: execute_crew → 按策略执行
│     ├─ 2c. AGGREGATE: _aggregate_results
│     └─ 2d. 写入 ContextStore
```
并在 `03_tool_system.md` 末尾补充手动两步骤替代方案说明 (form_crew → 检查 → execute_crew)。

#### 问题 46: DAG 执行缺少循环依赖检测

**发现**: `_execute_dag` 算法步骤 2 为 "找出所有入度为 0 的成员", 但未考虑依赖图中存在环的情况。若 plan_crew 阶段因 LLM 输出错误导致 SubTask A 依赖 B 且 B 依赖 A, 拓扑排序将找不到入度为 0 的节点, 进入静默死锁或抛出索引越界错误。

**修复**:
- `_execute_dag` 新增步骤 2: "检测循环依赖: 若依赖图中存在环, 抛出 CrewPlanError('circular dependency detected in DAG')"
- `CrewPlanError` 文档典型场景新增 "SubTask.dependencies 中存在循环依赖"
- 后续步骤编号调整 (原 2→3, 3→4, ... 6→7)

#### 问题 47: execute_crew 中 max_parallel=None 回退逻辑未文档化

**发现**: `execute_crew()` 接受 `max_parallel: int | None = None`, 但 `_execute_parallel()` 要求 `max_parallel: int` (非可选)。当 LLM 调用 CrewTool 未提供 max_parallel 参数时, `None` 如何转换为有效 int 值未文档化, 实现者需自行推断回退逻辑。

**修复**: `execute_crew()` 步骤 4 补充 PARALLEL 分发逻辑:
```python
_execute_parallel(crew, max_parallel or self.max_parallel)
```
明确 `None` 时回退到 `self.max_parallel` (即 `Config.crew_max_parallel`, 默认 4)。

#### 问题 48: launch_crew 参数覆写解析顺序缺失

**发现**: `AgentConfig` 新增了 `crew_strategy_override` 和 `crew_max_parallel_override`, 但 `BaseAgent.launch_crew()` 未说明这三个来源 (AgentConfig 覆写、方法参数、全局 Config) 的优先级关系。

**修复**: `launch_crew()` 新增参数解析顺序文档:
- strategy: self.config.crew_strategy_override → 参数 strategy → ExecutionStrategy.SEQUENTIAL
- max_parallel: self.config.crew_max_parallel_override → 参数 max_parallel → Config.crew_max_parallel

#### 问题 49: execute_crew 代码示例未设置计时字段

**发现**: Round 5 为 `CrewMember` 新增了 `started_at` 和 `completed_at` 字段, 但 `execute_crew()` 步骤 5 的 per-member 执行代码示例中未设置这两个字段, 导致代码示例与数据模型定义不一致。

**修复**: 代码示例补充:
```python
member.started_at = time.time()    # 在 status = "RUNNING" 之后
member.completed_at = time.time()  # 在 finally 块中
```

#### 问题 50: execute_crew 事件文档未提及 duration_ms 和 error_message

**发现**: `execute_crew()` 步骤 5 的事件发布说明仅列 "各携带 CrewEvent 负载含 crew_id, member_name, task_id", 但 `MEMBER_COMPLETED` 还携带 `duration_ms`, `MEMBER_FAILED` 还携带 `error_message`。

**修复**: 事件说明更新为:
"MEMBER_COMPLETED 携带 duration_ms=completed_at-started_at, MEMBER_FAILED 携带 error_message"

#### 问题 51: _execute_parallel 缺少失败处理和结果收集方式说明

**发现**: `_execute_parallel` 未说明:
- 某成员失败时是否影响其他并行成员
- 结果收集使用 `futures` 列表遍历还是 `as_completed()` (影响返回顺序)

**修复**: 补充失败处理说明 ("某成员失败不影响其他成员, 失败信息由 _aggregate_results 收集") 和结果收集方式 ("通过遍历 futures 列表而非 as_completed 收集, 保持提交顺序")。

### 第六轮问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 类型系统歧义 | 3 | member_results 缺 task_id、failed_members 非唯一、CrewEvent.partial_results 裸 list |
| 流程图逻辑错误 | 1 | form_crew + launch_crew 冗余调用 (涉及 2 个文件) |
| 边界条件缺失 | 2 | DAG 循环依赖检测、_execute_parallel 失败处理 |
| 文档缺口 | 4 | max_parallel 回退、launch_crew 覆写顺序、计时字段、事件字段 |
| 示例同步 | 1 | 06_specialized_agents.md CrewResult 示例 |
| **第六轮合计** | **11** | (问题 44 合并 3 个子问题) |

### 六轮累计修复统计

| 轮次 | 问题数 | 主要类型 |
|------|--------|----------|
| 第一轮 | 9 | 缺失定义、参数错误、类型错误、重复逻辑、依赖遗漏、拼写 |
| 第二轮 | 8 | 依赖遗漏、文档结构、跨文档不一致、缺失结构、异常处理、语义不清、注释 |
| 第三轮 | 11 | 生命周期管理缺失、功能集成缺失、文档冲突、参数传递、依赖遗漏、语义不明 |
| 第四轮 | 9 | 类型不一致、属性缺失、执行细节缺失、错误处理缺失、示例不完整、选择指南 |
| 第五轮 | 11 | 运行时逻辑错误、线程安全、资源管理缺陷、配置缺失、数据模型缺失、文档精确性 |
| 第六轮 | 11 | 类型歧义、流程图逻辑错误、边界条件缺失、文档缺口、示例同步 |
| 第七轮 | 10 | 代码示例错误、边界校验缺失、线程安全覆盖不全、错误处理不一致 |
| 第八轮 | 10 | 计时字段缺失、duration 计算错误、并发上限缺失、LLM 容错缺失、递归风险 |
| 第九轮 | 9 | Python 语义陷阱、UUID 生成规范缺口、异常传播缺陷、深度传播缺失 |
| **总计** | **88** | |

### 第六轮影响分析

- **类型安全**: 问题 44 的修复是框架正确性的关键 — 在无唯一标识符的情况下, 任何涉及同类型多 Agent 的 Crew 执行都会产生不可区分的结果, 导致调试和审计无法进行。task_id 的引入使每个结果可精确追溯到其子任务。
- **流程图正确性**: 问题 45 修复了一个会误导所有实现者的根本性错误 — 如果按原流程图实现, form_crew 会被调用两次, 第一次的结果被静默丢弃, 造成资源浪费和潜在的状态不一致。
- **运行时健壮性**: 问题 46 (循环依赖检测) 防止了 LLM 输出错误导致的静默死锁, 将不可恢复的错误转化为明确的 CrewPlanError 异常。
- **实现完备性**: 问题 47-51 填补了文档中的最终细节缺口, 确保实现者无需猜测任何边界行为。

---

## 第七轮深度审查 (补充修复)

在对 Crew 机制进行第七次反复检查后，发现以下额外问题。本轮重点关注代码示例的正确性、边界条件校验的完整性、以及异常处理的一致性。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| G1 | `agent_doc/plan/03_tool_system.md` | execute_crew 代码示例修复: agent→member.agent_instance, task→member.task; AgentPool factory 参数文档化; AgentResult 失败默认值显式化; CrewTool.execute() 将 mission 提取移入 try 块; plan_crew 新增 Agent 匹配校验 + 依赖引用校验; execute_crew 新增空成员列表校验 + 步骤重新编号; DAG 线程安全文档扩展覆盖 task.context; _execute_sequential/_execute_dag 补充 task.context=None 处理; AgentTool.execute() 新增 try/except (与 CrewTool 一致) |

### 追加问题详情

#### 问题 57: execute_crew 代码示例变量名错误

**发现**: `execute_crew()` 步骤 5 的 per-member 执行代码示例中:
- 第 1 行将 acquire 返回值赋值给 `member.agent_instance`
- 第 4 行却使用 `agent.run(...)` — 变量 `agent` 未定义
- `task.description` 和 `task.context` — 变量 `task` 未定义

正确应为 `member.agent_instance.run(member.task.description, member.task.context)`。

若实现者直接复制此代码, 将导致 `NameError`, Agent 实例虽已获取但从未被调用, 所有 CrewMember 结果为空。

**修复**: 代码示例全部修正为正确的变量引用路径, 并补充 `AgentPool.acquire` 的 `agent_factory` 参数文档。

#### 问题 58: AgentResult 失败构造的默认值隐藏

**发现**: 代码示例中 `AgentResult(success=False, final_answer=str(e), ...)` — `...` 隐藏了其他必填字段 (`iterations`, `token_usage`, `total_duration_ms`, `finish_reason`, `error`)。实现者可能遗漏这些字段, 导致返回不完整的 AgentResult。

**修复**: 将 `...` 替换为显式的默认值构造:
```python
AgentResult(success=False, final_answer=str(e),
    iterations=[], token_usage=TokenUsage(),
    total_duration_ms=0, finish_reason=FinishReason.ERROR,
    error=ToolExecutionError(str(e)))
```

#### 问题 59: CrewTool.execute() 中 mission 提取未受异常保护

**发现**: `mission = kwargs["mission"]` 位于 try/except 块之前。若 LLM 因 Function Calling schema 被忽略或其他原因未传递 `mission` 参数, `KeyError` 向上传播, 不会被 try/except 捕获, 导致 ReAct 循环崩溃而非优雅降级。

**修复**: 将 `mission = kwargs["mission"]` 及所有参数提取移入 try 块内部, 确保任何参数错误都被捕获并转换为失败 ToolResult。

#### 问题 60: plan_crew 缺少依赖引用完整性校验

**发现**: `plan_crew()` 将 LLM 返回的 JSON 解析为 SubTask 列表后, 直接构建 AgentCrew。但未校验:
- SubTask.dependencies 中引用的 task_id 是否存在于当前 SubTask 列表中
- 是否存在循环依赖 (A→B→A)

若 LLM 幻觉导致依赖引用不存在的 task_id, 或产生循环依赖, DAG 执行阶段会静默失败或无限循环。

**修复**: `plan_crew()` 在构建 AgentCrew 前新增步骤 4 "校验依赖完整性": 收集合法 task_id 集合 → 遍历检查每个 dependency 引用 → 不合法则抛出 CrewPlanError; DFS 检测循环依赖 → 存在环则抛出 CrewPlanError。

#### 问题 61: plan_crew 缺少 Agent 匹配成功校验

**发现**: `plan_crew()` 步骤 3 调用 `AgentRegistry.match_agent()` 但未校验匹配是否成功。若某 SubTask 的 `required_tags` 无任何 Agent 满足, `CrewMember.agent_cls` 将保持 None, 导致执行阶段 `agent_factory` 创建失败 (NoneType is not callable)。

**修复**: 步骤 3 补充: "若匹配失败 (无 Agent 满足 required_tags 或匹配得分低于阈值), 抛出 CrewPlanError"。

#### 问题 62: execute_crew 缺少空成员列表处理

**发现**: `execute_crew()` 未校验 `crew.members` 是否为空列表。若 `plan_crew()` 返回空 SubTask 列表 (LLM 输出 `[]` 且 JSON 解析成功), `execute_crew()` 将调用执行方法处理空列表:
- `_execute_sequential`: 空循环, 返回空 results
- `_execute_parallel`: ThreadPoolExecutor 无任务提交
- `_execute_dag`: 依赖图为空, 入度为 0 的节点集合为空 → 静默退出

空 Crew 应被明确拒绝而非静默 "成功"。

**修复**: `execute_crew()` 新增前置条件: `crew.members` 必须非空, 否则抛出 `ValueError("crew has no members to execute")`。

#### 问题 63: task.context 为 None 时合并操作崩溃

**发现**: `SubTask.context` 默认值为 `None`。在 `_execute_sequential` 中, 从第二个成员开始执行 `context["previous_result"] = ...` 合并操作 — 若 `task.context` 为 None, 对 None 做 item assignment 抛出 `TypeError`。

同样, `_execute_dag` 中合并 `dependency_results` 到下游成员 context 时也存在相同问题。

**修复**: 两个执行方法的 context 合并文档均补充: "若 task.context 为 None, 先初始化为空 dict {}"。

#### 问题 64: DAG 线程安全文档未覆盖 context 字段

**发现**: `_execute_dag` 线程安全文档仅覆盖 `crew.members[i].status` 和 `crew.members[i].result`。但在并发执行中, 当多个上游成员同时完成, 它们会并发地向同一个下游成员的 `task.context["dependency_results"]` 字典写入数据 — 这是一个明确的数据竞争点, 可能导致字典部分更新或损坏。

**修复**: 线程安全文档扩展覆盖 `crew.members[i].task.context`, 并补充 copy-on-write 实现建议。

#### 问题 65: AgentTool.execute() 与 CrewTool.execute() 错误处理不一致

**发现**: `CrewTool.execute()` 使用 try/except 包裹所有逻辑, 确保异常被捕获并转换为失败 ToolResult。但 `AgentTool.execute()` 直接调用 `agent_registry.launch()` 并将结果转换为 ToolResult, 无任何异常处理。若 AgentPool 耗尽或 Agent 执行超时, 异常直接向上传播到 ReAct 循环, 导致不一致的错误处理行为。

**修复**: `AgentTool.execute()` 新增 try/except 块, 与 `CrewTool.execute()` 保持一致的错误处理策略。

#### 问题 66: AgentPool.acquire 的 agent_factory 参数未文档化

**发现**: 代码示例中 `agent_pool.acquire(member.agent_name, ...)` 的 `...` 隐藏了 `agent_factory` 参数。`AgentPool.acquire` 签名为 `acquire(agent_name, agent_factory: Callable[[], BaseAgent])`, 其中 agent_factory 是零参数工厂函数, 需包含 Agent 构造所需的所有参数 (name, description, config 等)。实现者可能不清楚如何正确构造此工厂。

**修复**: 代码示例补充注释说明 agent_factory 的契约和构造方式, 并在 lambda 中包含从 agent_registry 获取 description 的完整示例。

### 第七轮问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 代码示例错误 | 3 | 变量名错误、默认值隐藏、factory 参数未文档化 |
| 异常处理缺失/不一致 | 2 | CrewTool KeyError、AgentTool 无 try/except |
| 边界校验缺失 | 3 | 依赖引用校验、Agent 匹配校验、空成员列表 |
| 线程安全覆盖不全 | 1 | DAG context 合并未加锁说明 |
| 空指针 (None) 处理 | 1 | task.context=None 时合并崩溃 |
| **第七轮合计** | **10** | |

### 第七轮影响分析

- **代码可复现性**: 问题 57-58 的修复使代码示例可直接被实现者复制使用, 不再包含未定义变量和隐藏的必填字段。
- **异常鲁棒性**: 问题 59/65 确保所有 Tool 执行路径的错误处理一致 — 无论是单个 Agent 拉起还是 Crew 编排, 异常都被捕获并优雅降级, 而非中断 ReAct 循环。
- **边界完备性**: 问题 60-62 补全了 plan→execute 链路上的 3 个关键校验点 (依赖完整性/匹配有效性/成员非空), 确保非法状态在最早的阶段被检测和拒绝。
- **并发安全**: 问题 64 将 context 字段纳入线程安全保护范围, 防止 DAG 并发执行时出现数据竞争导致的结果损坏。

---

## 第八轮深度审查 (补充修复)

在对 Crew 机制进行第八次反复检查后，发现以下额外问题。本轮重点关注时序计算的正确性、并发控制参数的完整性、以及异常场景下的容错机制。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| H1 | `agent_doc/plan/03_tool_system.md` | AgentCrew 新增 completed_at 字段; plan_crew 步骤 5 合并 created_at/crew_id 生成; execute_crew 新增 completed_at 设置步骤并进行步骤重编号; _aggregate_results 步骤 4 从 sum-of-member-durations 改为 crew.completed_at - crew.created_at wall-clock 计算; _execute_dag 新增 max_parallel 参数 (与 _execute_parallel 一致) + 就绪队列并发限制文档; _aggregate_results 步骤 3 新增 LLM 聚合失败降级策略; CrewTool max_parallel JSON Schema 新增 "default": 4 |
| H2 | `agent_doc/plan/01_base_agent.md` | launch_crew() 新增 Crew 嵌套递归风险文档与 call_depth 防护措施 |

### 追加问题详情

#### 问题 67: AgentCrew 缺少 completed_at 字段

**发现**: `AgentCrew` 有 `created_at: float` 用于记录创建时间，但缺少对应的 `completed_at` 字段。若需计算 Crew 执行的 wall-clock 总耗时，必须依赖外部计时或从 member 时间戳推算，缺乏权威的单一时间源。

**修复**: `AgentCrew` 新增 `completed_at: float = 0.0` 字段，由 `execute_crew()` 在所有成员执行完毕、调用 `_aggregate_results` 之前设置。

#### 问题 68: total_duration_ms 使用错误的计算方式

**发现**: `_aggregate_results` 步骤 4 原为 "计算 total_duration_ms (sum of all member durations)"。对 SEQUENTIAL 策略此计算近似正确，但对 PARALLEL 和 DAG 策略，将并发执行的成员耗时累加会严重高估实际耗时。例如 3 个成员并发执行各 10 秒，实际 wall-clock 时间约 10 秒，但 sum 为 30 秒。

**修复**: 改为 wall-clock 计算: `total_duration_ms = (crew.completed_at - crew.created_at) * 1000`。各成员独立耗时可通过 `member_results` 中每个 `AgentResult.total_duration_ms` 获取。

#### 问题 69: plan_crew 未文档化 crew_id 生成时机

**发现**: `AgentCrew.crew_id` 注释为 "UUID v4"，但 `plan_crew()` 的 7 个步骤中均未提及何时生成此 UUID。实现者需自行推断生成时机。

**修复**: `plan_crew()` 步骤 5 "构建 AgentCrew" 扩展为 3 个子步骤: 生成 crew_id (UUID v4) → 填充 CrewMember 列表 → 设置 created_at，合并了原有的 created_at 设置步骤。

#### 问题 70: execute_crew 未设置 crew.completed_at

**发现**: `execute_crew()` 负责整个 Crew 的执行生命周期，但从未记录执行完成的时间戳。缺少此时间戳导致两个问题: (1) 无法计算 wall-clock 总耗时; (2) Crew 生命周期不完整 (有始无终)。

**修复**: `execute_crew()` 新增步骤 7: "设置 crew.completed_at = time.time()"，在所有成员执行完成后、调用 `_aggregate_results` 之前设置。后续步骤编号相应调整 (8→9, 9→10, 10→11)。

#### 问题 71: CrewTool max_parallel JSON Schema 缺少 default 值

**发现**: `CrewTool.parameters_schema` 中 `max_parallel` 字段仅通过 `description` 文本说明 "(默认 4)"，但 JSON Schema 规范使用 `"default"` 键声明默认值。LLM 和 API 客户端通常通过 `"default"` 键而非 description 文本识别默认值。

**修复**: `max_parallel` 新增 `"default": 4`，与 description 独立。

#### 问题 72: _execute_dag 未接收 max_parallel 参数

**发现**: `execute_crew()` 向 `_execute_parallel` 传递了 `max_parallel`，但向 `_execute_dag` 未传递。DAG 就绪队列中的成员也需并发执行，无 `max_parallel` 限制意味着 ThreadPoolExecutor 可能创建与就绪队列大小相同的线程数，在最坏情况下等同于无限制。

**修复**:
- `_execute_dag` 签名新增 `max_parallel: int` 参数
- `execute_crew()` DAG 分发逻辑更新为 `_execute_dag(crew, max_parallel or self.max_parallel)`
- `_execute_dag` 步骤 4 明确 "使用 ThreadPoolExecutor(max_workers=max_parallel)"

#### 问题 73: _aggregate_results LLM 聚合失败无降级处理

**发现**: `_aggregate_results` 步骤 3 调用 LLM 生成 `mission_summary`。这是 Crew 执行的最后一步 — 所有成员已完成工作并产生结果。若此 LLM 调用因超时、限流等原因失败且无错误处理，整个 `_aggregate_results` 抛出异常，所有已完成成员的工作成果丢失。

**修复**: 步骤 3 新增降级策略: "若 LLM 调用失败, 降级为人工拼接 — mission_summary = '\n\n'.join([f'[{agent_name}] {result.final_answer}' for ...]) — 确保所有已完成成员工作不会因聚合失败而丢失。"

#### 问题 74: Crew 嵌套递归风险未文档化

**发现**: `launch_agent()` 通过 `call_depth` 机制防止无限 Agent 嵌套。但 `launch_crew()` 无等效保护。若 Crew 成员 Agent 也注册了 `CrewTool`，其 LLM 可能在子任务中再次调用 `launch_crew`，形成无限制的 Crew 嵌套递归，最终耗尽系统资源。

**修复**: `launch_crew()` 文档新增递归风险说明与防护措施:
- 入口处检查 `call_depth >= agent_max_call_depth`，超限抛出 `AgentDepthExceededError`
- 各执行方法为 CrewMember 构建 AgentConfig 时应设置 `call_depth = CrewLeader 的 depth + 1`，使限制向下传播

### 第八轮问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 计时字段缺失 | 2 | AgentCrew 缺 completed_at、execute_crew 未设置 |
| 计算逻辑错误 | 1 | total_duration_ms 用 sum 而非 wall-clock |
| 文档缺口 | 2 | crew_id 生成时机、Crew 递归风险 |
| 并发控制缺失 | 1 | _execute_dag 无 max_parallel |
| Schema 不完整 | 1 | max_parallel 缺 JSON Schema default |
| 容错机制缺失 | 1 | _aggregate_results LLM 失败无降级 |
| 步骤重编号 | 2 | plan_crew / execute_crew 步骤合并与重编号 |
| **第八轮合计** | **10** | |

### 第八轮影响分析

- **时序正确性**: 问题 67/68/70 的修复确保了 `total_duration_ms` 在所有执行策略下均反映真实的 wall-clock 时间。此前 PARALLEL/DAG 策略的时间统计存在系统性偏差，直接影响了性能监控和用户等待时间评估的准确性。
- **并发安全边界**: 问题 72 将 DAG 就绪队列的并发度纳入 `max_parallel` 控制，防止了因依赖图结构导致的无限制线程创建，与 PARALLEL 策略形成了统一的并发控制模型。
- **数据完整性**: 问题 73 的 LLM 聚合降级策略确保了最坏情况下已完成成员的工作不会丢失 — 用户至少能看到拼接的原始结果，而非空白错误信息。
- **系统稳定性**: 问题 74 的递归保护将 Crew 嵌套纳入与 Agent 嵌套相同的深度限制体系，防止了因 LLM 自发决策导致的无限递归和资源耗尽。

---

## 第九轮深度审查 (补充修复)

在对 Crew 机制进行第九次反复检查后，发现以下额外问题。本轮重点关注 Python 语义陷阱 (falsy 值)、规范缺口 (UUID 生成)、以及跨组件深度传播的完整性。

### 追加文件变更清单

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| I1 | `agent_doc/plan/03_tool_system.md` | execute_crew 将 `max_parallel or self.max_parallel` 修正为 `max_parallel if max_parallel is not None else self.max_parallel` (防止 0 被 falsy 回退); plan_crew 新增步骤 1 (LLM 输出临时标识符说明) + 步骤 2a (生成正式 UUID v4 + 依赖引用重映射); execute_crew 代码示例将 agent_pool.acquire 移入 try 块 (防止 acquire 异常时成员被静默跳过); _aggregate_results total_duration_ms 新增 max(0, ...) 防护; _execute_sequential 首个成员 context=None 行为文档化 + final_answer 简化设计说明; _execute_dag 新增波次模型并行槽位利用说明与连续流模型展望; AgentCrew 新增 crew_leader_call_depth 字段; plan_crew 签名新增 crew_leader_call_depth 参数 + 步骤 5 存储逻辑; execute_crew agent_factory 完善 AgentConfig 构造含 call_depth 传播; CrewOrchestrator 新增 config: Config 属性存储 |
| I2 | `agent_doc/plan/01_base_agent.md` | form_crew() 新增 crew_leader_call_depth=self.config.call_depth 传递; launch_crew() 递归风险防护措施更新为 form_crew → plan_crew → execute_crew 的深度传播链路 |
| I3 | `agent_doc/plan/06_specialized_agents.md` | §6 CrewResult 示例补充 crew_id 和 total_duration_ms 字段 |

### 追加问题详情

#### 问题 75: execute_crew 中 max_parallel 使用 `or` 运算导致 0 值被错误回退

**发现**: `execute_crew()` 步骤 5 使用 `max_parallel or self.max_parallel` 判空。Python 中 `0 or 4` 求值为 `4` (因为 `0` 是 falsy), 导致当调用方显式传入 `max_parallel=0` (意图禁止并行, 在 DAG 模式下串行执行就绪成员) 时, 值被静默替换为 Config 默认值 4。

**修复**: 将 `max_parallel or self.max_parallel` 改为 `max_parallel if max_parallel is not None else self.max_parallel`, 仅对 `None` 回退, 保留 `0` 作为合法值。

#### 问题 76: plan_crew 未文档化 SubTask UUID 生成与依赖引用重映射

**发现**: `SubTask.task_id` 注释要求 "UUID v4", 但 `plan_crew()` 步骤 2 直接将 LLM 返回的 JSON 解析为 SubTask 列表。LLM 无法可靠生成真正的 UUID v4 (通常输出 "task_1" 等简单标识符), 且 LLM 输出的临时标识符不能保证全局唯一性。此外, 若框架在步骤 5 替换 task_id 为真实 UUID, 则步骤 4 的依赖校验应在替换后进行, 而非替换前 — 但文档未描述替换步骤和依赖引用的重映射逻辑。

**修复**: plan_crew 内部流程重构:
- 步骤 1: Prompt 要求 LLM 使用临时标识符 (如 "task_1"), 明确告知 LLM 不要自行生成 UUID
- 步骤 2a (新增): 生成正式 UUID v4 替换临时符 → 构建映射表 → 重映射所有 dependencies 引用
- 步骤 4 补充说明: 校验针对已替换的正式 UUID

#### 问题 77: agent_pool.acquire() 位于 try 块外, 异常时成员静默丢失

**发现**: `execute_crew()` per-member 代码示例中, `agent_pool.acquire()` 在 try/except 块之外。若 acquire 因 AgentPool 耗尽或工厂函数抛出异常而失败:
- 异常向上传播, 未创建任何 AgentResult
- 该成员不会出现在 results 列表中
- SEQUENTIAL 策略下后续成员全部被跳过
- PARALLEL/DAG 策略下其他线程不受影响但该成员结果缺失
- crew.members 列表中该成员 status 保持 PENDING, 与 "所有成员已执行完毕" 的 crew 状态矛盾

**修复**: 代码示例重构为嵌套 try 结构 — 外层 try/except 包裹 agent_pool.acquire(), 捕获异常后将成员标记为 FAILED 并生成描述性 AgentResult, 然后 continue 到下一个成员; 内层 try/except/finally 包裹 agent.run() + agent_pool.release(), 仅在 acquire 成功时进入。

#### 问题 78: total_duration_ms 在 completed_at 未设置时产生负值

**发现**: `_aggregate_results` 步骤 4 计算 `(crew.completed_at - crew.created_at) * 1000`。若 `completed_at` 因异常执行路径未正确设置 (仍为默认值 0.0), 则结果为负数 (如 `-1715000000.0`), 写入 `CrewResult.total_duration_ms` 字段, 污染上层日志和监控。

**修复**: 改为 `max(0, (crew.completed_at - crew.created_at)) * 1000`, 并补充注释说明正常路径下 `completed_at` 由 `execute_crew` 步骤 7 保证设置。

#### 问题 79: _execute_sequential 首个成员 context=None 行为未文档化

**发现**: `_execute_sequential` 文档说明首个成员使用原始 task.context (不合并 previous_result), 但未说明若 task.context 为 None 时, agent.run() 的 context 参数收到 None 是否合法。实现者可能误以为需要特殊初始化一个空 dict。

**修复**: 补充说明 `agent.run()` 的 `context` 参数接受 `dict | None`, `None` 表示无上下文数据可用, 这是合法且预期的行为。

#### 问题 80: CrewResult 示例缺少 crew_id 和 total_duration_ms

**发现**: `06_specialized_agents.md` §6 的 CrewResult 示例 JSON 仅包含 `success`, `mission_summary`, `member_results`, `execution_order`, `failed_members`, `token_usage` 六个字段。但 `CrewResult` 数据类定义了 8 个字段, 缺少 `crew_id: str` 和 `total_duration_ms: float`。

**修复**: 示例补充 `"crew_id": "a1b2c3d4-..."` 和 `"total_duration_ms": 15234.5`。

#### 问题 81: _execute_dag 波次模型并行槽位利用不足未说明

**发现**: `_execute_dag` 算法采用 "波次" (wave) 模型 — 每轮收集所有就绪成员, 全部并发执行, 等待全部完成后才检查新就绪成员。若一波中某成员耗时远短于其他成员, 其下游成员 (依赖已满足) 在整个波次完成前无法开始, 导致并行槽位闲置。

**修复**: 新增 "执行模型说明" 段落, 解释波次模型的实现简单性与并行利用率的权衡, 并展望未来的连续流模型 (有界信号量 + 动态提交)。

#### 问题 82: _execute_sequential 仅传递 final_answer 的简化设计未解释

**发现**: `_execute_sequential` 仅将前一成员的 `final_answer` 字符串作为 `previous_result` 传递给下一成员, 而非完整的 `AgentResult` 对象。这意味着下游成员无法获取上游的 `token_usage`, `iterations` 等结构化数据。此设计选择有合理动机 (节省 context token, final_answer 是 LLM 最需要的输入), 但未在文档中解释。

**修复**: 新增 "设计说明" 段落, 解释仅传递 final_answer 的理由 (LLM 易理解, 节省 token), 并指引需要完整结构化数据时使用 DAG 策略并在 task.context 中显式包含所需字段。

#### 问题 83: agent_factory 未传播 call_depth, Crew 嵌套深度保护失效

**发现**: `launch_crew()` 文档声明了 Crew 嵌套递归防护措施, 要求 CrewMember 的 AgentConfig 设置 `call_depth = CrewLeader depth + 1`。但 `execute_crew()` per-member 代码示例中的 agent_factory lambda 仅传递 `name` 和 `description` 两个参数给 `member.agent_cls()`, 未传递 `config` 和 `agent_config`。

此问题的连锁影响:
- CrewMember Agent 实例使用默认 `AgentConfig(call_depth=0)`, 其 LLM 若再次调用 launch_crew, 入口处的 `call_depth >= agent_max_call_depth` 检查永远通过 (0 < 3), Crew 嵌套递归保护完全失效
- CrewMember Agent 也缺少全局 Config (LLM 端点/密钥等), 可能使用错误的默认配置

**修复**:
- `AgentCrew` 新增 `crew_leader_call_depth: int = 0` 字段
- `plan_crew()` 签名新增 `crew_leader_call_depth` 参数, 步骤 5 存储到 AgentCrew
- `form_crew()` 传递 `crew_leader_call_depth=self.config.call_depth`
- `CrewOrchestrator` 新增 `config: Config` 属性 (存储在 `__init__` 中)
- agent_factory lambda 补全: 传递 `config=self.config` + `agent_config=AgentConfig(call_depth=crew.crew_leader_call_depth + 1)`
- `launch_crew()` 递归防护文档更新为完整的深度传播链路

### 第九轮问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| Python 语义陷阱 | 1 | max_parallel `or` 运算吞没 0 值 |
| 规范缺口 | 1 | SubTask UUID 生成与依赖重映射机制 |
| 异常处理缺陷 | 2 | acquire 在 try 外 + total_duration_ms 负值 |
| 文档缺口 | 4 | 首个成员 context=None、波次模型限制、final_answer 简化设计、CrewResult 示例 |
| 深度传播缺失 | 1 | agent_factory 未传播 call_depth (含 CrewOrchestrator.config 修复) |
| **第九轮合计** | **9** | (问题 83 合并 4 个子修复) |

### 九轮累计修复统计

| 轮次 | 问题数 | 主要类型 |
|------|--------|----------|
| 第一轮 | 9 | 缺失定义、参数错误、类型错误、重复逻辑、依赖遗漏、拼写 |
| 第二轮 | 8 | 依赖遗漏、文档结构、跨文档不一致、缺失结构、异常处理、语义不清、注释 |
| 第三轮 | 11 | 生命周期管理缺失、功能集成缺失、文档冲突、参数传递、依赖遗漏、语义不明 |
| 第四轮 | 9 | 类型不一致、属性缺失、执行细节缺失、错误处理缺失、示例不完整、选择指南 |
| 第五轮 | 11 | 运行时逻辑错误、线程安全、资源管理缺陷、配置缺失、数据模型缺失、文档精确性 |
| 第六轮 | 11 | 类型歧义、流程图逻辑错误、边界条件缺失、文档缺口、示例同步 |
| 第七轮 | 10 | 代码示例错误、边界校验缺失、线程安全覆盖不全、错误处理不一致 |
| 第八轮 | 10 | 计时字段缺失、duration 计算错误、并发上限缺失、LLM 容错缺失、递归风险 |
| 第九轮 | 9 | Python 语义陷阱、UUID 生成规范缺口、异常传播缺陷、深度传播缺失 |
| **总计** | **88** | |

### 第九轮影响分析

- **并发控制正确性**: 问题 75 的修复确保了 `max_parallel=0` 可作为合法的 "禁止并发" 语义被正确处理, 而非被 Python 的 falsy 语义静默覆盖。此 bug 在场效应 — 所有使用 `or` 判空的 None-or-default 模式在涉及 0 值时均受影响。
- **标识符可靠性**: 问题 76 填补了 LLM 生成 UUID 的根本性不可靠问题。通过框架生成 UUID + 依赖引用重映射, SubTask 的 task_id 真正满足全局唯一性要求, 为分布式日志追踪和跨系统引用提供了可靠基础。
- **异常完整性**: 问题 77 修复了 acquire 失败时的静默丢失问题 — 此前一个 AgentPool 耗尽故障可能导致 CrewResult 中少一个成员而无人察觉, 现在会被显式记录到 failed_members 并反映在 mission_summary 中。
- **深度保护闭环**: 问题 83 是最关键的修复之一 — 此前 call_depth 传播链条在 agent_factory 处断裂, 导致所有 Crew 嵌套递归保护声明形同虚设 (CrewMember 始终使用 call_depth=0)。修复后 form_crew → plan_crew (存储) → execute_crew (工厂构造) 形成完整的深度传播链路, 与 launch_agent() 的深度保护形成一致的体系。
- **跨组件配置完整性**: CrewOrchestrator.config 属性的补全不仅服务于 call_depth 传播, 也确保了 CrewMember Agent 实例能正确继承全局 LLM 配置 (端点/密钥/模型), 避免了因缺失 Config 导致的 LLM 调用失败。
