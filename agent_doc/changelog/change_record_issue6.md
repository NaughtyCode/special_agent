# 修改记录 — Issue #6

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue6 |
| 修改日期 | 2026-04-30 |
| 修改类型 | 架构设计 — 新增核心机制: Crew 团队编排 |
| 关联文档 | `agent_doc/plan/` (00, 01, 03, 06, 07, 08) |
| 修改人 | SpecialArchAgent |

## 修改概述

新增 **Crew 团队编排机制** 作为 Agent 框架的核心架构设计。任何特化 Agent 均可通过此机制成为 **CrewLeader**（团队领导），动态组建并领导一组自动匹配的特化 Agent 协同完成复杂多面任务。

命名: **Crew** (团队/班组)
- **CrewLeader**: 发起并领导 Crew 的 Agent（角色，非特定 Agent 类型）
- **CrewOrchestrator**: 团队编排引擎（Plan → Match → Execute → Aggregate）
- **AgentCrew**: 已组建的 Agent 团队
- **ExecutionStrategy**: 执行策略（SEQUENTIAL / PARALLEL / DAG）

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/03_tool_system.md` | 新增 §9 CrewOrchestrator 完整设计（含 SubTask, CrewMember, AgentCrew, CrewResult, ExecutionStrategy, CrewOrchestrator, CrewLifecycleEvent, 编排流程图, 与现有机制关系图） |
| 2 | `agent_doc/plan/01_base_agent.md` | 新增 agent_pool 和 crew_orchestrator 属性；新增 form_crew() 和 launch_crew() 方法；更新 __init__ 文档 |
| 3 | `agent_doc/plan/00_architecture_overview.md` | 核心设计目标新增 Crew 编排；架构分层图新增 CrewOrchestrator/AgentRegistry/AgentPool 层；层职责表更新；新增 §4.3 Crew 编排数据流；模块依赖图更新；文件结构新增 crew_orchestrator.py 和 crew_tool.py；技术决策表新增 Crew 编排条目 |
| 4 | `agent_doc/plan/06_specialized_agents.md` | 设计原则新增 Crew 协同；新增 §5.5 Crew 编排协作模式；新增 §7 Crew 使用示例（含 CrewTool 注册与执行流程代码） |
| 5 | `agent_doc/plan/07_context_and_infra.md` | 文件结构新增 crew_orchestrator.py 和 crew_tool.py；EventBus 事件类型新增 CrewLifecycleEvent；events.py 注释更新 |
| 6 | `agent_doc/plan/08_implementation_roadmap.md` | Phase 2 新增 2.6a CrewOrchestrator 任务；Phase 3 新增 3.4a CrewTool 任务；Phase 2 时间估算更新为 4-5 天；特化 Agent 任务描述新增 CrewLeader 角色；测试任务描述更新；依赖关系图更新；新增 §3.7 Crew 编排关键技术要点 |
| 7 | `agent_doc/plan/03_tool_system.md` §7 | 内置 Tool 列表新增 `launch_crew` 条目 |

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 8 | `agent_doc/changelog/change_record_issue6.md` | 本修改记录 |

## 详细变更内容

### 1. CrewOrchestrator 核心设计 (§3.9)

**SubTask** — 子任务数据模型:
- `task_id`, `description`, `required_tags` (Agent 匹配依据), `dependencies` (DAG 模式), `context`

**CrewMember** — 团队成员:
- `agent_name`, `agent_cls`, `agent_instance` (延迟实例化), `task`, `status`, `result`

**AgentCrew** — 团队容器:
- `crew_id`, `lead_agent_name`, `mission`, `members`, `status`, `created_at`

**CrewResult** — 聚合结果:
- `success`, `mission_summary` (LLM 汇总), `member_results`, `execution_order`, `token_usage`

**ExecutionStrategy** — 三种执行策略:
- `SEQUENTIAL`: 串行 — 前一完成才执行后一，结果作为 context 传递
- `PARALLEL`: 并行 — 并发执行无依赖成员 (受 max_parallel 限制)
- `DAG`: 依赖拓扑 — 按 SubTask.dependencies 排序，无依赖的可并行

**CrewOrchestrator** — 编排引擎:
- `plan_crew()`: LLM 分解 mission → SubTask[] + AgentRegistry 匹配 → AgentCrew
- `execute_crew()`: 按策略执行 Crew → 聚合 → CrewResult
- `_aggregate_results()`: LLM 汇总所有成员 final_answer → mission_summary

### 2. BaseAgent Crew 能力 (§2.3)

新增方法:
- `form_crew(mission) → AgentCrew`: 分解任务并组建团队（不执行）
- `launch_crew(mission, strategy, max_parallel) → CrewResult`: 一键组建并执行

每个特化 Agent 继承这些方法后自动获得 CrewLeader 能力。

### 3. 与现有机制的关系

| 机制 | 粒度 | 匹配方式 | 执行策略 | 结果 |
|------|------|----------|----------|------|
| AgentTool (§6) | 单个 Agent | 调用方指定名称 | 同步调用 | AgentResult |
| CrewOrchestrator (§9) | 一组 Agent | 自动按子任务匹配 | 串行/并行/DAG | CrewResult |

两者互补: AgentTool 用于简单委托，CrewOrchestrator 用于复杂多面任务。

### 4. 架构分层更新

Agent Framework Layer 新增三个组件:
- **CrewOrchestrator**: 团队编排引擎
- **AgentRegistry**: 为 CrewOrchestrator 提供 Agent 匹配能力
- **AgentPool**: 为 CrewOrchestrator 提供 Agent 实例复用

### 5. 事件体系扩展

新增 `CrewLifecycleEvent`:
- `PLANNED` / `STARTED` / `MEMBER_STARTED` / `MEMBER_COMPLETED` / `MEMBER_FAILED` / `COMPLETED` / `FAILED`

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 机制名称 | Crew (团队/班组) | 简短、直观、业界通用 (crewAI 等) |
| 角色名称 | CrewLeader (非特定 Agent 类型) | 任何特化 Agent 均可担任，无需新增 Agent 类型 |
| 编排引擎位置 | `agent/core/crew_orchestrator.py` | 核心机制，与 ReActEngine 同级 |
| Tool 适配 | CrewTool (独立于 AgentTool) | 语义不同 — launch_crew 暴露 mission/strategy 参数 |
| 执行策略 | 三种 (SEQUENTIAL/PARALLEL/DAG) | 覆盖串行、并发、依赖三种典型场景 |
| 任务分解 | LLM 驱动 | 利用 LLM 的语义理解能力分解复杂任务 |
| 结果聚合 | LLM 汇总 | 生成连贯的 mission_summary 而非简单拼接 |

## 影响分析

- **架构完整性**: Agent 框架从"单个 Agent 调用"升级为"团队协同编排"，覆盖简单委托到复杂多 Agent 协作的全场景
- **Agent 能力**: 每个特化 Agent 自动成为 CrewLeader，无需额外实现 — 通过 BaseAgent 继承获得
- **可扩展性**: ExecutionStrategy 可由用户扩展自定义策略
- **实现工作量**: 新增约 2 个核心文件 (crew_orchestrator.py + crew_tool.py)，Phase 2 增加约 1 天
