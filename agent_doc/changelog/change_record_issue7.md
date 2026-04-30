# 修改记录 — Issue #7

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue7 |
| 修改日期 | 2026-04-30 |
| 修改类型 | Crew 机制深度审查 — 补全缺失定义与修复跨文档不一致 |
| 关联文档 | `agent_doc/plan/` (01, 03, 06, 07, 08) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 Issue #6 新增的 Crew 团队编排机制进行反复深度审查，发现并修复了缺失的类定义、配置字段缺失、方法参数传递错误、事件定义格式错误、事件发布重复、依赖关系遗漏等问题。

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/03_tool_system.md` | 新增 §9.6 CrewTool 完整类定义；CrewLifecycleEvent 改为 Enum 类并添加枚举值；AgentCrew 文档错字修复；CrewOrchestrator 配置注释对齐 Config 字段名 |
| 2 | `agent_doc/plan/01_base_agent.md` | form_crew() 明确传递 lead_agent_name=self.name；launch_crew() 移除重复的事件发布职责 |
| 3 | `agent_doc/plan/07_context_and_infra.md` | Config 新增 Crew 配置段: crew_max_parallel, crew_max_iterations, crew_plan_temperature |
| 4 | `agent_doc/plan/08_implementation_roadmap.md` | 3.4a CrewTool 依赖新增 2.10 (BaseAgent)；依赖关系图同步更新 |

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
