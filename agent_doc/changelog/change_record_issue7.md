# 修改记录 — Issue #7

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue7 |
| 修改日期 | 2026-04-30 |
| 修改类型 | Crew 机制深度审查 (两轮) — 补全缺失定义、修复跨文档不一致、增强注释与错误处理 |
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
| **合计** | **17** | |
