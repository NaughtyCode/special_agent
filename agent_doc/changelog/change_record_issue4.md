# 修改记录 — Issue #4

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue4 |
| 修改日期 | 2026-04-30 |
| 修改类型 | 计划审查 — 问题修复与定义补全 |
| 关联文档 | `agent_doc/plan/` (9 个文件) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 `agent_doc/plan/` 下的全部 9 个计划文档进行第四轮审查，修复发现的类型定义缺失、文件结构不一致、配置参数遗漏等问题。

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/00_architecture_overview.md` | 更新根级文件结构: 移除过期 doc/ 目录, 新增 requirements.txt 和 README.md |
| 2 | `agent_doc/plan/01_base_agent.md` | 新增 AgentState Enum 定义; 新增 ParsedAction dataclass; 修复 _handle_react_iteration 返回类型 |
| 3 | `agent_doc/plan/02_react_engine.md` | 新增 ParseMethod Enum 定义 |
| 4 | `agent_doc/plan/06_specialized_agents.md` | CodeAgent 补充 max_iterations=15 配置覆写 |

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 5 | `agent_doc/changelog/change_record_issue4.md` | 本修改记录 |

## 详细变更内容

### 问题 1: 00 文件结构图缺少根级文件, doc/ 目录过期

**发现**: `00_architecture_overview.md` 根级文件结构缺少 `requirements.txt` 和 `README.md`，而 `07_context_and_infra.md` 中包含这两个文件。此外 00 中有 `doc/` 目录 (参考文档/历史)，但 07 中不存在此目录，为过期引用。

**修复**: 将 00 根级文件结构末尾的 `└── doc/` 替换为 `├── requirements.txt` 和 `└── README.md`，与 07 保持一致。

### 问题 2: AgentState Enum 未定义为 Python 代码

**发现**: `01_base_agent.md` 中 BaseAgent 属性使用 `state: AgentState`，且多处引用 `AgentState.IDLE` / `RUNNING` / `DONE` 等枚举值，但 AgentState 仅以状态图 + 表格描述，缺少 `class AgentState(Enum)` 的 Python 代码定义。

**修复**: 在 §2.4 状态机图之前新增 `AgentState(Enum)` 类定义，包含全部 6 个状态枚举值及注释。

### 问题 3: ParsedAction 类型未定义

**发现**: `01_base_agent.md` 中 `_handle_react_iteration()` 方法的 `action` 参数类型标注为 `ParsedAction`，但该类型未在任何文档中定义。已有的 `ParsedReAct` (02) 是 ReActEngine 内部使用的完整解析结果，不适合作为 BaseAgent 内部方法的参数类型。

**修复**: 在 `01_base_agent.md` §2.6 AgentResult 之后新增 `@dataclass ParsedAction` 定义 (name, input 两个字段)，作为 BaseAgent 与 ReActEngine 之间的轻量数据传递结构。

### 问题 4: Observation 类型未定义

**发现**: `01_base_agent.md` 中 `_handle_react_iteration()` 返回值类型标注为 `Observation`，但该类型未在任何文档中定义。实际该方法处理 Action 执行后应返回结构化结果。

**修复**: 将返回类型从 `Observation` 改为 `ActionResult`（已在 `02_react_engine.md` §5.1 中定义）。

### 问题 5: ParseMethod Enum 未定义

**发现**: `02_react_engine.md` §5.1 中 `ParsedReAct.parse_method` 字段类型为 `ParseMethod`，注释标注 `# TEXT_REACT | FUNCTION_CALL | FALLBACK`，但 `ParseMethod` 枚举类未在文档中定义。

**修复**: 在 ParsedReAct dataclass 之前新增 `class ParseMethod(Enum)` 定义，包含 `TEXT_REACT`、`FUNCTION_CALL`、`FALLBACK` 三个枚举值。

### 问题 6: CodeAgent 未设置 max_iterations

**发现**: `06_specialized_agents.md` §3.1 CodeAgent.__init__ 仅设置 `llm_temperature_override=0.3`，未设置 `max_iterations`。但 §6 "Agent 配置最佳实践" 表中 CodeAgent 推荐 `max_iterations=15`。其他三个 Agent (DocAgent/SearchAgent/ShellAgent) 均已设置相应的 max_iterations 值。

**修复**: 在 CodeAgent 的 AgentConfig 中补充 `max_iterations=15`，与最佳实践表对齐。

## 问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 缺失类型定义 | 3 | AgentState, ParsedAction, ParseMethod |
| 未定义类型引用 | 1 | Observation → ActionResult |
| 文件结构不一致 | 1 | 00 缺少 requirements.txt/README.md, 含过期 doc/ |
| 配置参数缺失 | 1 | CodeAgent 缺少 max_iterations=15 |
| **合计** | **6** | |

## 影响分析

- **类型完整性**: 所有 9 个文档中引用的类型均已定义，不再存在"找不到定义"的类型引用
- **配置一致性**: 四个内置 Agent 的 AgentConfig 覆写与最佳实践表完全对齐
- **文件结构**: 00 与 07 的根级文件结构现已一致
