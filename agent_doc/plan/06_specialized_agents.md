# 特化 Agent 设计

## 1. 概述

特化 Agent 是继承自 `BaseAgent` 的具体实现，各自聚焦特定领域。每个特化 Agent 通过覆写 `system_prompt` 和 `register_tools` 即可获得专业能力。

## 2. 设计原则

1. **单一职责**: 每个 Agent 只处理一类任务，职责边界清晰
2. **最小覆写**: 只需定义 system_prompt + register_tools，ReAct 逻辑由基类统一提供
3. **Crew 协同**: 任何特化 Agent 均可成为 CrewLeader，动态组建并领导一组匹配的 Agent 协同完成复杂任务
4. **可组合**: RootAgent 可将多个特化 Agent 串行/嵌套组合完成复杂任务
5. **可扩展**: 新增 Agent 只需创建子类并注册，无需修改框架代码
6. **可配置**: 每个 Agent 可通过 AgentConfig 独立调参 (模型/温度/最大迭代数)

## 3. 内置特化 Agent

### 3.1 CodeAgent — 代码编写 Agent

```python
class CodeAgent(BaseAgent):
    """
    专门处理代码编写任务的 Agent。

    能力范围: 代码生成、代码审查、Bug 修复、重构建议、测试生成
    支持语言: Python / JavaScript / TypeScript / Go / Rust / Java 等 (由 LLM 决定)
    """

    name: str = "CodeAgent"
    description: str = (
        "代码编写与审查专家。擅长代码生成、代码审查、Bug 修复、重构建议和测试生成。"
        "支持多种编程语言，遵循最佳实践和设计模式。"
    )
    tags: list[str] = ["code", "programming", "debug", "refactor", "test"]

    @property
    def system_prompt(self) -> str:
        return """你是一个专业的代码编写 Agent。你的职责:
1. 根据用户需求编写高质量、可运行的代码
2. 遵循最佳实践和设计模式 (SOLID, DRY, KISS)
3. 代码必须包含详细注释 (注释说明 WHY 而非 WHAT)
4. 考虑错误处理和边界情况
5. 优先使用标准库和成熟的开源库
6. 在编写代码前, 先用 read_file 了解项目上下文
7. 代码生成后, 用 write_file 写入文件
8. 对于需要测试的代码, 主动生成对应的测试用例
9. 若不确定需求, 主动向用户确认而非猜测"""

    def register_tools(self) -> None:
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())
        self.tool_manager.register(SearchCodeTool())
        self.tool_manager.register(RunShellTool(requires_confirmation=True))
        self.tool_manager.register(ListFilesTool())

    # 可选: 覆盖默认配置
    def __init__(self, config: Config | None = None,
                 agent_config: AgentConfig | None = None) -> None:
        # CodeAgent 默认使用较低温度以提高代码质量
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.3,
                max_iterations=15
            )
        super().__init__(name=self.name, description=self.description,
                        config=config, agent_config=agent_config)
```

### 3.2 DocAgent — 文档编写 Agent

```python
class DocAgent(BaseAgent):
    """
    专门处理文档编写任务的 Agent。

    能力范围: 技术文档、API 文档、README 文件、设计文档、代码注释补全
    """

    name: str = "DocAgent"
    description: str = (
        "技术文档编写专家。擅长生成 API 文档、架构设计文档、README 文件，"
        "能查阅源代码并撰写准确的技术说明，确保文档与实现一致。"
    )
    tags: list[str] = ["doc", "documentation", "readme", "api", "manual"]

    @property
    def system_prompt(self) -> str:
        return """你是一个专业的技术文档编写 Agent。你的职责:
1. 根据代码和需求生成准确的技术文档
2. 使用清晰、简洁、结构化的语言
3. 文档采用 Markdown 格式, 遵循 GFM 规范
4. 包含代码示例和 API 参数说明 (参数名、类型、默认值、含义)
5. 先读取目标代码再写文档, 确保文档与实现一致
6. 对于大型项目, 先生成文档大纲请用户确认, 再逐步填充
7. 使用 Mermaid 语法绘制架构图/流程图 (如适用)"""

    def register_tools(self) -> None:
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())
        self.tool_manager.register(SearchCodeTool())
        self.tool_manager.register(ListFilesTool())
        self.tool_manager.register(WebSearchTool())  # 用于查找外部参考

    def __init__(self, config: Config | None = None,
                 agent_config: AgentConfig | None = None) -> None:
        # DocAgent 使用中等温度以平衡准确性和表达力
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.6,
                max_iterations=10
            )
        super().__init__(name=self.name, description=self.description,
                        config=config, agent_config=agent_config)
```

### 3.3 SearchAgent — 搜索 Agent

```python
class SearchAgent(BaseAgent):
    """
    专门处理信息搜索任务的 Agent。

    能力范围: 代码搜索、网页搜索、信息检索、知识查询、资料收集
    """

    name: str = "SearchAgent"
    description: str = (
        "信息搜索专家。擅长代码库搜索、网页信息检索、知识查询，"
        "能快速定位关键信息和代码位置，并将结果整理为结构化报告。"
    )
    tags: list[str] = ["search", "find", "query", "lookup", "research"]

    @property
    def system_prompt(self) -> str:
        return """你是一个专业的信息搜索 Agent。你的职责:
1. 快速准确地定位用户需要的信息
2. 在代码库中搜索特定模式或符号 (使用 search_code)
3. 必要时搜索互联网获取最新信息 (使用 web_search + web_fetch)
4. 将搜索结果整理为清晰的结构化报告 (分类/去重/按相关性排序)
5. 对于模糊的搜索需求, 先确认搜索范围再执行"""

    def register_tools(self) -> None:
        self.tool_manager.register(SearchCodeTool())
        self.tool_manager.register(WebSearchTool())
        self.tool_manager.register(WebFetchTool())
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(ListFilesTool())

    def __init__(self, config: Config | None = None,
                 agent_config: AgentConfig | None = None) -> None:
        # SearchAgent 使用较低温度提高搜索精确度
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.4,
                max_iterations=8
            )
        super().__init__(name=self.name, description=self.description,
                        config=config, agent_config=agent_config)
```

### 3.4 ShellAgent — Shell 操作 Agent

```python
class ShellAgent(BaseAgent):
    """
    专门处理 Shell 命令执行任务的 Agent。

    能力范围: Shell 命令执行、环境检查、文件操作、进程管理、系统诊断
    """

    name: str = "ShellAgent"
    description: str = (
        "Shell 命令执行专家。擅长构建安全可靠的 Shell 命令，"
        "处理文件操作、环境配置和系统管理任务，执行前会解释影响。"
    )
    tags: list[str] = ["shell", "command", "run", "execute", "system"]

    @property
    def system_prompt(self) -> str:
        return """你是一个专业的 Shell 操作 Agent。你的职责:
1. 构建安全可靠的 Shell 命令
2. 避免危险的系统操作 (如 rm -rf /, dd, >/dev/sda 等)
3. 在执行前解释命令的作用和潜在影响
4. 使用绝对路径而非相对路径
5. 优先使用安全的方式完成任务 (如先备份再修改)
6. 对于破坏性操作, 必须先获得用户确认
7. 命令输出过长时, 使用截断并提示完整输出位置"""

    def register_tools(self) -> None:
        self.tool_manager.register(RunShellTool(requires_confirmation=True))
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())
        self.tool_manager.register(ListFilesTool())

    def __init__(self, config: Config | None = None,
                 agent_config: AgentConfig | None = None) -> None:
        # ShellAgent 使用最低温度确保命令的确定性和安全性
        if agent_config is None:
            agent_config = AgentConfig(
                llm_temperature_override=0.2,
                max_iterations=6
            )
        super().__init__(name=self.name, description=self.description,
                        config=config, agent_config=agent_config)
```

## 4. 扩展指南 — 创建自定义 Agent

```python
# 步骤 1: 定义新的 Agent 类
from agent.core.base_agent import BaseAgent
from agent.core.base_agent import AgentConfig

class MyDomainAgent(BaseAgent):
    """领域特化 Agent — 处理 X 领域的专业任务"""

    name: str = "MyDomainAgent"
    description: str = "专门处理 X 领域任务, 具备 Y 和 Z 的专业能力"
    tags: list[str] = ["domain-x", "expert"]

    @property
    def system_prompt(self) -> str:
        return """你是一个 X 领域的专业 Agent。你的职责:
1. ... (具体的行为规范)
2. ...
"""

    def register_tools(self) -> None:
        # 注册此 Agent 需要的 Tool
        self.tool_manager.register(MyCustomTool())
        # 复用框架内置 Tool
        from agent.tools.file_tools import ReadFileTool, WriteFileTool
        self.tool_manager.register(ReadFileTool())
        self.tool_manager.register(WriteFileTool())

    def __init__(self, config: Config | None = None,
                 agent_config: AgentConfig | None = None):
        if agent_config is None:
            agent_config = AgentConfig(
                max_iterations=15,           # 领域任务可能需要更多迭代
                llm_temperature_override=0.5 # 自定义温度
            )
        super().__init__(name=self.name, description=self.description,
                        config=config, agent_config=agent_config)

# 步骤 2: 注册到 RootAgent (两种方式)
# 方式 A: 在 RootAgent._register_builtin_agents() 中添加一行
#   self.agent_registry.register(MyDomainAgent)

# 方式 B: 放入插件目录, RootAgent 自动发现加载
#   将 my_domain_agent.py 放入 Config.plugin_directories 指定的目录

# 完成! 无需修改框架代码
```

## 5. Agent 协作模式

### 5.1 串行协作 (Sequential)
```
RootAgent → CodeAgent (生成后端代码)
         → DocAgent  (为生成的代码编写 API 文档)
         → ShellAgent (运行测试验证)
```

### 5.2 嵌套协作 (Nested)
```
RootAgent → CodeAgent
              ├→ ShellAgent (运行测试)
              │    └→ CodeAgent (根据测试结果修复 Bug)
              └→ SearchAgent (查找参考实现)
```

### 5.3 路由器协作 (Router)
```
RootAgent (路由)
   ├→ 分析用户需求
   ├→ "帮我写一个 API" → CodeAgent
   ├→ "这个函数的文档怎么写" → DocAgent
   └→ "帮我搜索相关代码" → SearchAgent
```

### 5.4 并行轮询 (Parallel Poll) — 未来扩展
```
RootAgent
   ├→ SearchAgent (搜索方案 A)
   ├→ SearchAgent (搜索方案 B)
   └→ SearchAgent (搜索方案 C)
       │
       汇总比较 → 选择最佳方案
```

### 5.5 Crew 编排 (Crew Orchestration)
```
CodeAgent (CrewLeader)
   │
   ├─ 1. 识别: LLM 判断用户需求需多领域协作
   │    "帮我实现一个 REST API: 需要代码 + 文档 + 搜索参考 + 验证"
   │
   ├─ 2. Plan: form_crew(mission)
   │    ├→ LLM 分解:
   │    │    SubTask₁: "实现 API 代码"       → CodeAgent
   │    │    SubTask₂: "搜索最佳实践参考"     → SearchAgent
   │    │    SubTask₃: "编写 API 文档"       → DocAgent
   │    │    SubTask₄: "运行测试验证"         → ShellAgent
   │    └→ 组建 AgentCrew (4 members, status=ASSEMBLED)
   │
   ├─ 3. Execute: launch_crew(mission, strategy=DAG)
   │    ├→ SearchAgent (搜索参考) ──→ CodeAgent (实现代码)
   │    │                                  ├→ DocAgent (编写文档)
   │    │                                  └→ ShellAgent (运行测试)
   │    └→ 发布 CrewLifecycleEvent (每个成员)
   │
   ├─ 4. Aggregate: LLM 汇总所有成员结果
   │    └→ "API 已实现并通过测试, 文档已生成..."
   │
   ▼
返回 CrewResult.mission_summary 给用户
```

## 7. Crew 使用示例

任何特化 Agent 均可通过继承自 BaseAgent 的 `form_crew()` 和 `launch_crew()` 方法成为 **CrewLeader**，无需额外覆写。

```python
# 示例: CodeAgent 在 ReAct 循环中拉起 Crew 完成复杂需求
#
# 当用户输入 "帮我实现一个用户认证系统" 时,
# CodeAgent 的 LLM 识别到任务需多领域协作 (代码 + 文档 + 测试),
# 通过 Function Calling 调用 launch_crew:

# CodeAgent 在 register_tools() 中额外注册
def register_tools(self) -> None:
    self.tool_manager.register(ReadFileTool())
    self.tool_manager.register(WriteFileTool())
    self.tool_manager.register(SearchCodeTool())
    self.tool_manager.register(RunShellTool(requires_confirmation=True))
    self.tool_manager.register(ListFilesTool())
    # 注册 launch_crew 作为可用 Tool — LLM 可在 ReAct 中调用
    self.tool_manager.register(CrewTool(agent=self))

# CrewTool 将 launch_crew() 包装为 Tool,
# 使 LLM 可通过 Function Calling 发起 Crew 编排:
# {
#     "name": "launch_crew",
#     "arguments": {
#         "mission": "实现用户认证系统: 含登录/注册/密码重置",
#         "strategy": "dag",
#         "max_parallel": 4
#     }
# }

# 执行结果: CrewResult
# {
#     "success": true,
#     "mission_summary": "已完成用户认证系统实现:
#         1. CodeAgent 实现了 login/register/reset 三个端点
#         2. DocAgent 生成了 API 文档 (含参数说明)
#         3. ShellAgent 运行了 12 个测试用例全部通过
#         4. SearchAgent 提供了 bcrypt 最佳实践参考",
#     "member_results": [
#         ("SearchAgent", AgentResult(...)),
#         ("CodeAgent", AgentResult(...)),
#         ("DocAgent", AgentResult(...)),
#         ("ShellAgent", AgentResult(...))
#     ],
#     "token_usage": TokenUsage(prompt_tokens=8500, completion_tokens=3200, total_tokens=11700)
# }
```

## 8. Agent 配置最佳实践

| Agent | 推荐 temperature | 推荐 max_iterations | 备注 |
|-------|-----------------|--------------------|------|
| CodeAgent | 0.2-0.4 | 15 | 低温度提高代码准确性和一致性 |
| DocAgent | 0.5-0.7 | 10 | 中等温度兼顾准确性和表达力 |
| SearchAgent | 0.3-0.5 | 8 | 搜索需精确, 迭代次数不需太多 |
| ShellAgent | 0.1-0.3 | 6 | Shell 命令需高确定性 |
| RootAgent | 0.6-0.8 | 12 | 路由和规划任务需要一定创造性 |
