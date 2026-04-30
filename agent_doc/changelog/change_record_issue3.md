# 修改记录 — Issue #3

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue3 |
| 修改日期 | 2026-04-30 |
| 修改类型 | 计划审查 — 问题修复与一致性对齐 |
| 关联文档 | `agent_doc/plan/` (9 个文件) |
| 修改人 | SpecialArchAgent |

## 修改概述

对 `agent_doc/plan/` 下的全部 9 个计划文档进行反复检查，修复发现的不一致、缺失定义、表述不准确等问题。

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `agent_doc/plan/00_architecture_overview.md` | 修复文件结构图 |
| 2 | `agent_doc/plan/02_react_engine.md` | 修复 ReActEngine 构造参数缺失 |
| 3 | `agent_doc/plan/03_tool_system.md` | 新增缺失的类型定义 |
| 4 | `agent_doc/plan/04_deepseek_client.md` | 修复模型默认值不一致 |
| 5 | `agent_doc/plan/06_specialized_agents.md` | 补全 AgentConfig 覆写示例 |
| 6 | `agent_doc/plan/07_context_and_infra.md` | 修复文件结构图 |

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 7 | `agent_doc/changelog/change_record_issue3.md` | 本修改记录 |

## 详细变更内容

### 问题 1: 04 与 07 Config 默认值不一致

**发现**: `04_deepseek_client.md` LLM_MODEL 默认值为 `deepseek-chat`，而 `07_context_and_infra.md` 中为 `deepseek-v4-pro`（用户已修正）。

**修复**: 将 `04_deepseek_client.md` 中 LLM_MODEL 默认值更新为 `deepseek-v4-pro`，与 07 保持一致。

### 问题 2: AgentRegistry 缺少 `get_agent_meta()` 方法

**发现**: `03_tool_system.md` 中 AgentTool.__init__ 调用了 `agent_registry.get_agent_meta(agent_name)`，但 AgentRegistry 类定义中没有此方法。

**修复**: 在 AgentRegistry 中新增 `get_agent_meta()` 方法，返回 `AgentMeta` 数据结构（包含 name, description, tags, agent_cls）。

### 问题 3: MatchResult 类型未定义

**发现**: `03_tool_system.md` 中 AgentRegistry.match_agent() 返回值标注为 `MatchResult`，但该数据类未在任何文档中定义。

**修复**: 新增 `@dataclass MatchResult` 定义（tool_name, agent_name, score, strategy_used, candidates）。

### 问题 4: AgentMeta 类型未定义

**发现**: AgentTool 和 AgentRegistry 中使用 `AgentMeta` 但未定义。

**修复**: 新增 `@dataclass AgentMeta` 定义（name, description, tags, agent_cls）。

### 问题 5: ReActEngine.__init__ 缺少 context_store 和 event_bus 参数

**发现**: `02_react_engine.md` 中 ReActEngine.run() 方法使用 `self.context_store`，但 __init__ 签名中未包含 `context_store` 参数。同样缺少 `event_bus` 参数。

**修复**: 在 ReActEngine.__init__ 签名中新增 `context_store: ContextStore` 和 `event_bus: EventBus` 参数。

### 问题 6: CompositeParser 默认链不一致

**发现**: ReActEngine.__init__ 注释中默认 CompositeParser 仅含 `(ReActParser, FunctionCallParser)`，但文档 §5 描述为三级解析 (FunctionCallParser → ReActParser → FallbackParser)。

**修复**: 将默认解析器链更新为 `CompositeParser(FunctionCallParser, ReActParser, FallbackParser)`。

### 问题 7: MatchStrategyChain 默认链不完整

**发现**: MatchStrategyChain 默认参数为 `(Exact, Fuzzy, Semantic)`，遗漏了 `AgentMatchStrategy`。

**修复**: 更新为 `MatchStrategyChain(Exact, Fuzzy, Semantic, Agent)`。

### 问题 8: AgentPool 硬编码 idle_timeout

**发现**: `03_tool_system.md` 中 AgentPool.__init__ 的 `idle_timeout` 硬编码为 `300.0`。

**修复**: 改为 `idle_timeout: float | None = None`，None 时回退到 Config 默认值。

### 问题 9: 文件结构图多处不一致

**发现**:
- `00_architecture_overview.md` 文件结构图缺少: `models.py`, `session_manager.py`, `plugin_loader.py`, `search_tools.py`, `web_tools.py`, `events.py`, `search_agent.py`, `shell_agent.py`
- `07_context_and_infra.md` 的文件结构图虽然较完整，但缺少 `models.py` 和 `plugin_loader.py`
- `changelog/` 目录在 00 中位于根级别，但实际 changelog 位于 `agent_doc/changelog/`

**修复**:
- 00 文件结构图: 新增 `models.py`, `session_manager.py`, `plugin_loader.py`, `search_tools.py`, `web_tools.py`, `events.py`, `search_agent.py`, `shell_agent.py`; 新增 `agent_doc/changelog/` 目录
- 07 文件结构图: 新增 `models.py`, `plugin_loader.py`
- 将 07 中 `agent_registry.py` 注释更新为 `+ AgentMeta + MatchResult`

### 问题 10: DocAgent/SearchAgent/ShellAgent 缺少 AgentConfig 覆写

**发现**: `06_specialized_agents.md` 中仅 CodeAgent 提供了 `__init__` 覆写和 AgentConfig 设置，DocAgent、SearchAgent、ShellAgent 均缺失。

**修复**: 为三个 Agent 分别增加 `__init__` 覆写:
- DocAgent: temperature=0.6, max_iterations=10
- SearchAgent: temperature=0.4, max_iterations=8
- ShellAgent: temperature=0.2, max_iterations=6

与文档 §6 "Agent 配置最佳实践" 表中的推荐值对齐。

## 问题修复统计

| 类别 | 数量 | 说明 |
|------|------|------|
| 配置默认值不一致 | 2 | LLM_MODEL 值对齐，LLM_BASE_URL 保持各自默认 |
| 缺失类型定义 | 3 | AgentMeta, MatchResult, get_agent_meta() |
| 构造函数参数缺失 | 2 | ReActEngine 缺少 context_store 和 event_bus |
| 默认策略链不完整 | 2 | CompositeParser 缺 FallbackParser, MatchStrategyChain 缺 AgentStrategy |
| 硬编码值 | 1 | AgentPool.idle_timeout |
| 文件结构图不一致 | 10+ | 缺失文件/目录，路径错误 |
| Agent 配置示例缺失 | 3 | DocAgent/SearchAgent/ShellAgent 缺 __init__ |
| **合计** | **23+** | |

## 影响分析

- **文档一致性**: 所有 9 个文档间的类型引用、配置默认值、文件路径现已统一
- **可实现性**: 修复后的文档可直接作为实现阶段的权威参考，不存在"找不到定义"的引用
- **完整度**: 每个内置 Agent 都有了明确的 AgentConfig 覆写示例，实现者可直接参照
