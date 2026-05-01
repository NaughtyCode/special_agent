# SpecialAgent Framework v1.0.0

基于 ReAct (Reasoning + Acting) 范式的多 Agent 智能协作框架。

## 核心特性

- **ReAct 引擎**: Thought → Action → Observation 推理-行动循环
- **多 Agent 协作**: Crew 编排, 支持 SEQUENTIAL / PARALLEL / DAG 三种执行策略
- **Agent 作为 Tool**: Agent 之间可相互调用, 组成嵌套代理网络
- **LLM 后端无关**: 通过 LLMProvider Protocol 抽象, 内置 OpenAI Compatible 实现
- **插件系统**: 动态加载自定义 Agent, 零侵入扩展
- **事件驱动**: EventBus 发布-订阅, 生命周期监控
- **上下文压缩**: 自动 Token 管理, 防止超出 LLM 窗口限制

## 快速开始

### 安装

```bash
pip install -r requirements.txt
```

### 环境变量

```bash
# 必需
export ANTHROPIC_AUTH_TOKEN="your-api-key"

# 可选 (有默认值)
export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
export ANTHROPIC_MODEL="deepseek-v4-pro"
export AGENT_MAX_ITERATIONS=10
```

### 使用

**交互式 REPL:**

```bash
python -m src.main
```

REPL 命令:
- `/help` — 显示帮助
- `/agents` — 列出可用 Agent
- `/tools` — 列出可用 Tool
- `/history` — 显示对话历史
- `/clear` — 清除当前上下文
- `/session <name>` — 切换会话
- `/sessions` — 列出所有会话
- `/stats` — 显示 Token 统计
- `/debug` — 切换调试模式
- `/exit` — 退出

**单次查询:**

```bash
python -m src.main "帮我分析项目代码结构"
```

### 创建自定义 Agent

```python
# plugins/my_agent.py
from src.core.base_agent import BaseAgent
from src.tools.file_tools import ReadFileTool

class MyCustomAgent(BaseAgent):
    name = "MyCustomAgent"
    description = "处理特定领域任务的自定义 Agent"
    tags = ["custom", "domain"]

    @property
    def system_prompt(self) -> str:
        return "你是一个专业的领域专家..."

    def register_tools(self) -> None:
        self.tool_manager.register(ReadFileTool())
```

## 架构

```
src/
├── infra/          # 基础设施 (Config, Logger)
├── events/         # 事件系统 (EventBus, Events)
├── llm/            # LLM 抽象层 (Provider, Client)
├── core/           # 核心引擎 (ReAct, Agent, Tool, Context)
├── crew/           # Crew 编排 (独立模块)
├── tools/          # 内置 Tool (File, Shell, Search, Web, Agent, Crew)
├── strategies/     # 匹配/压缩策略 (可注入)
├── agents/         # 特化 Agent (Code, Doc, Search, Shell)
└── main.py         # 入口点

plugins/            # 自定义 Agent 插件目录
tests/              # 自动化测试 (181 tests)
changelog/          # 修改记录文档
```

## 测试

```bash
pytest tests/ -v
# 181 tests passed
```

## 模块依赖

```
infra ──────────────────────────────┐
events ────────────────────────────┤
llm ───────────────────────────────┤
core (models) ─────────────────────┤
tools (base_tool) ─────────────────┤
strategies ────────────────────────┤
  ├── core (react_engine) ─────────┤
  ├── core (base_agent) ───────────┤
  ├── crew (models, orchestrator) ─┤
  ├── agents (specialized) ────────┤
  ├── core (session_manager) ──────┤
  └── main ────────────────────────┘
```

## License

Internal use.
