# 修改记录 — Issue #5

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue5 |
| 修改日期 | 2026-04-30 |
| 修改类型 | 计划审查 — 概念纠错与跨文档一致性对齐 |
| 关联文档 | `agent_doc/plan/` (9 个文件) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 `agent_doc/plan/` 下的全部 9 个计划文档进行第五轮审查，发现并修复概念层错误、未定义类型引用、事件名称不一致等问题。

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/00_architecture_overview.md` | ReAct 流程图中匹配策略列表: `FunctionCall` 改为 `AgentMatch` |
| 2 | `agent_doc/plan/01_base_agent.md` | `_record_error` 文档注释: `ErrorEvent` 改为 `AgentLifecycleEvent.ERROR` |
| 3 | `agent_doc/plan/02_react_engine.md` | `_check_termination` 返回类型: `TerminationDecision` 改为 `FinishReason` |
| 4 | `agent_doc/plan/06_specialized_agents.md` | 扩展指南示例 `__init__` 补充缺失的类型标注 |

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 5 | `agent_doc/changelog/change_record_issue5.md` | 本修改记录 |

## 详细变更内容

### 问题 1: 00 匹配策略列表含概念错误 — FunctionCall 是解析策略不是匹配策略

**发现**: `00_architecture_overview.md` §4.1 ReAct 循环流程图中，匹配策略列表第四条为 `Strategy.FunctionCall → 原生 FC 模式`。但根据 `02_react_engine.md` 的设计：
- **OutputParser** (解析体系) 负责处理 Function Calling: `CompositeParser(FunctionCallParser, ReActParser, FallbackParser)` — FC 模式在 LLM 输出解析阶段使用
- **MatchStrategy** (匹配体系) 负责 Tool/Agent 匹配: `MatchStrategyChain(Exact, Fuzzy, Semantic, Agent)` — 四个策略均用于匹配 action_name 到具体 Tool/Agent

FunctionCall 属于解析层而非匹配层，将其列在匹配策略中会造成概念混淆。

**修复**: 将 `Strategy.FunctionCall → 原生 FC 模式` 改为 `Strategy.AgentMatch → Agent 匹配`，与 02 文档的 MatchStrategyChain 默认策略链对齐。

### 问题 2: 01 _record_error 引用不存在的事件类型 ErrorEvent

**发现**: `01_base_agent.md` 中 `_record_error()` 方法的 docstring 写为"记录错误并发布 ErrorEvent"。根据 `07_context_and_infra.md` EventBus 定义，事件类型为 `AgentLifecycleEvent`（含 INITIALIZED / STARTED / COMPLETED / ERROR / SPAWNED / STOPPED 枚举值），不存在独立的 `ErrorEvent` 类型。

**修复**: 将 docstring 中的 `ErrorEvent` 改为准确的 `AgentLifecycleEvent.ERROR`。

### 问题 3: 02 _check_termination 返回未定义类型 TerminationDecision

**发现**: `02_react_engine.md` §3 ReActEngine 内部方法 `_check_termination()` 的返回类型标注为 `TerminationDecision | None`，但 `TerminationDecision` 类未在任何文档中定义。

分析该方法语义：检查循环是否应终止，若终止则返回终止原因，否则返回 None 继续循环。该文档 §7 已定义 `FinishReason(Enum)` 包含全部终止原因（DONE / MAX_ITERATIONS / CONSECUTIVE_FAILURES / STOPPED / LLM_UNRECOVERABLE），语义完全吻合。

**修复**: 将返回类型从 `TerminationDecision | None` 改为 `FinishReason | None`，docstring 同步更新。

### 问题 4: 06 扩展指南示例缺少类型标注

**发现**: `06_specialized_agents.md` §4 扩展指南中 `MyDomainAgent.__init__` 的参数写为 `config=None, agent_config=None`，无类型标注。而同一文档中 CodeAgent/DocAgent/SearchAgent/ShellAgent 的 `__init__` 均使用完整类型标注 `config: Config | None = None, agent_config: AgentConfig | None = None`。作为面向开发者的参考示例，缺少类型标注会降低代码质量。

**修复**: 补充类型标注 `config: Config | None = None, agent_config: AgentConfig | None = None`，与文档内其他 Agent 保持一致。

## 问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 概念层错误 | 1 | FunctionCall 错误归类为匹配策略 |
| 未定义类型引用 | 1 | TerminationDecision 不存在 |
| 事件名称不一致 | 1 | ErrorEvent vs AgentLifecycleEvent.ERROR |
| 类型标注缺失 | 1 | 扩展指南示例缺少类型标注 |
| **合计** | **4** | |

## 影响分析

- **概念准确性**: ReAct 流程图中匹配策略与解析策略现已正确分层，避免实现者混淆
- **类型完整性**: `_check_termination` 的返回类型引用已指向实际定义的 `FinishReason` 枚举
- **事件命名一致性**: 01 与 07 之间的事件名称引用已统一
- **示例代码质量**: 扩展指南示例的类型标注与其他 Agent 代码保持一致

## 五轮审查趋势

| 轮次 | 发现问题数 | 主要类型 |
|------|-----------|----------|
| Issue #2 | 30+ | 硬编码、缺失类型、配置缺失、扩展点 |
| Issue #3 | 23+ | 默认值不一致、缺失类型定义、参数缺失、文件结构 |
| Issue #4 | 6 | 类型定义补全、配置参数遗漏 |
| Issue #5 | 4 | 概念纠错、未定义类型引用、命名不一致 |

问题数量逐轮递减，问题类型从结构性缺陷收敛到概念层精度问题。
