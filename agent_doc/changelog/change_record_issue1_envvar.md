# 修改记录 — Issue #1 (ANTHROPIC_* 环境变量配置更新)

## 基本信息

| 项目 | 内容 |
|------|------|
| 修改编号 | issue1-envvar |
| 修改日期 | 2026-05-01 |
| 修改类型 | 设计更新 — LLM API 环境变量命名体系变更 |
| 关联文档 | `agent_doc/issues/issue1.txt` |
| 修改人 | Claude Code |

## 修改概述

按 `issue1.txt` 要求, 将 DeepSeek V4 API 的环境变量配置从 `LLM_*` 命名体系迁移至 `ANTHROPIC_*` 命名体系。
同时新增 `ANTHROPIC_SMALL_FAST_MODEL` 和 `ANTHROPIC_CUSTOM_MODEL_OPTION` 两个可选配置项,
并将超时配置从秒 (`LLM_TIMEOUT`) 改为毫秒 (`API_TIMEOUT_MS`)。

## 环境变量变更对照

| 旧环境变量 (LLM_*) | 新环境变量 (ANTHROPIC_*) | 说明 |
|---|---|---|
| `LLM_API_KEY` | `ANTHROPIC_AUTH_TOKEN` | API 认证令牌, 命名从 KEY 改为 TOKEN |
| `LLM_BASE_URL` | `ANTHROPIC_BASE_URL` | API 基础地址, 默认值不变 |
| `LLM_MODEL` | `ANTHROPIC_MODEL` | 默认模型名称, 默认值不变 |
| `LLM_MAX_TOKENS` | (移除) | 改为内部配置, 默认 4096 |
| `LLM_TEMPERATURE` | (移除) | 改为内部配置, 默认 0.7 |
| `LLM_TIMEOUT` | `API_TIMEOUT_MS` | 请求超时, 单位从秒改为毫秒, 默认 60000 |
| `LLM_MAX_RETRIES` | (移除) | 改为内部配置, 默认 3 |
| `LLM_BASE_DELAY` | (移除) | 改为内部配置, 默认 1.0 |
| `LLM_MAX_DELAY` | (移除) | 改为内部配置, 默认 60.0 |
| (新增) | `ANTHROPIC_SMALL_FAST_MODEL` | 小型快速模型名称, 用于简单任务, 可选 |
| (新增) | `ANTHROPIC_CUSTOM_MODEL_OPTION` | 自定义模型选项, JSON 格式, 可选 |

## 文件变更清单

### 修改文件

| 序号 | 文件路径 | 变更说明 |
|------|----------|----------|
| 1 | `plan/04_deepseek_client.md` | OpenAICompatProvider 文档字符串: `LLM_*` → `ANTHROPIC_*`; 构造函数新增 `small_fast_model` 和 `custom_model_option` 参数; 环境变量配置表替换; API 请求格式示例更新; 使用示例更新 |
| 2 | `plan/07_context_and_infra.md` | Config 类文档字符串和字段注释: 所有 `LLM_*` 引用替换为 `ANTHROPIC_*`; 新增 `llm_small_fast_model` 和 `llm_custom_model_option` 字段; `from_env()` 方法文档重写, 详细列出环境变量映射关系; `validate()` 方法增加 JSON 格式校验说明 |
| 3 | `plan/00_architecture_overview.md` | 模块依赖图: `Config (llm_* 配置)` → `Config (ANTHROPIC_* 环境变量)` |
| 4 | `plan/08_implementation_roadmap.md` | 关键技术要点: `DEEPSEEK_*` 兼容说明 → `ANTHROPIC_*` 配置说明 |

### 新增文件

| 序号 | 文件路径 | 文件说明 |
|------|----------|----------|
| 1 | `changelog/change_record_issue1_envvar.md` | 本修改记录文件 |

## 详细变更内容

### 1. OpenAICompatProvider 环境变量配置 (04_deepseek_client.md)

**原设计 (provider-agnostic):**
```
LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_TOKENS,
LLM_TEMPERATURE, LLM_TIMEOUT, LLM_MAX_RETRIES
```

**新设计 (ANTHROPIC_* 命名体系):**
```
ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL,
ANTHROPIC_SMALL_FAST_MODEL, ANTHROPIC_CUSTOM_MODEL_OPTION, API_TIMEOUT_MS
```

构造函数新增参数:
- `small_fast_model: str | None` — 来自 `ANTHROPIC_SMALL_FAST_MODEL`, 简单任务可选快速模型
- `custom_model_option: str | None` — 来自 `ANTHROPIC_CUSTOM_MODEL_OPTION`, JSON 格式自定义选项

超时单位变更:
- 旧: `timeout: float = 60.0` (秒)
- 新: `timeout: float = 60.0` (秒, 由 `API_TIMEOUT_MS` 毫秒值 / 1000 转换)

### 2. Config 类字段更新 (07_context_and_infra.md)

新增字段:
- `llm_small_fast_model: str | None = None` — 来自 `ANTHROPIC_SMALL_FAST_MODEL`
- `llm_custom_model_option: str | None = None` — 来自 `ANTHROPIC_CUSTOM_MODEL_OPTION`

字段注释更新:
- 每个字段注释明确标注对应的 `ANTHROPIC_*` 环境变量名称
- `llm_timeout` 注释说明其值由 `API_TIMEOUT_MS` 除以 1000 转换而来
- `llm_api_key` 注释说明来自 `ANTHROPIC_AUTH_TOKEN`

`from_env()` 方法完整文档化:
- 列出 6 个环境变量到 Config 字段的映射关系
- 说明 `llm_custom_model_option` 的 JSON 解析逻辑
- 说明 `API_TIMEOUT_MS` 的毫秒转秒逻辑

`validate()` 方法增强:
- 校验 `llm_api_key` 不为空 (来自 `ANTHROPIC_AUTH_TOKEN`)
- 校验 `llm_base_url` 为合法 http/https URL
- 校验 `llm_timeout` > 0
- 新增 `llm_custom_model_option` JSON 合法性校验

### 3. 环境变量使用示例更新

```python
config = Config.from_env()
provider = OpenAICompatProvider(
    api_key=config.llm_api_key,                   # ANTHROPIC_AUTH_TOKEN
    base_url=config.llm_base_url,                 # ANTHROPIC_BASE_URL
    model=config.llm_model,                       # ANTHROPIC_MODEL
    small_fast_model=config.llm_small_fast_model, # ANTHROPIC_SMALL_FAST_MODEL
    custom_model_option=config.llm_custom_model_option, # ANTHROPIC_CUSTOM_MODEL_OPTION
    timeout=config.llm_timeout,                   # API_TIMEOUT_MS / 1000
)
```

## 需求覆盖

| issue1.txt 要求 | 对应计划文档位置 |
|---|---|
| `ANTHROPIC_SMALL_FAST_MODEL` 环境变量 | `04_deepseek_client.md` §3 构造参数, §5 环境变量表; `07_context_and_infra.md` §§3 Config 字段 |
| `ANTHROPIC_MODEL` 环境变量 | `04_deepseek_client.md` §3 构造参数, §5 环境变量表; `07_context_and_infra.md` §§3 Config 字段 |
| `ANTHROPIC_CUSTOM_MODEL_OPTION` 环境变量 | `04_deepseek_client.md` §3 构造参数, §5 环境变量表; `07_context_and_infra.md` §§3 Config 字段 |
| `ANTHROPIC_BASE_URL` 环境变量 | `04_deepseek_client.md` §3 构造参数, §5 环境变量表, §7 API 格式; `07_context_and_infra.md` §§3 Config 字段 |
| `ANTHROPIC_AUTH_TOKEN` 环境变量 | `04_deepseek_client.md` §3 构造参数, §5 环境变量表, §7 API 格式; `07_context_and_infra.md` §§3 Config 字段 |
| `API_TIMEOUT_MS` 环境变量 | `04_deepseek_client.md` §3 构造参数, §5 环境变量表; `07_context_and_infra.md` §§3 Config 字段 |
| 生成完整修改记录文档 | 本文档 (`changelog/change_record_issue1_envvar.md`) |
| 代码必须加上详细注释 | 所有代码块中的字段/参数均有详细注释, 标注环境变量来源与默认值 |

## 影响分析

- **影响范围**: 设计文档层面变更, 涉及 4 个 plan 文档的环境变量引用
- **兼容性**: 不向后兼容旧的 `LLM_*` 和 `DEEPSEEK_*` 环境变量前缀
- **后续步骤**: 实现阶段需按新环境变量名称编写 `config.py`、`openai_compat.py` 等源码
- **安全性**: `ANTHROPIC_AUTH_TOKEN` 替代 `LLM_API_KEY`, 语义更明确, 不含 "KEY" 敏感词
