"""
全局配置管理 — 从环境变量读取所有配置。

LLM 相关配置使用 ANTHROPIC_* 命名体系的环境变量。
API_TIMEOUT_MS 以毫秒为单位, 内部自动转换为秒。
"""

import json
import os
from dataclasses import dataclass, field


class ConfigValidationError(Exception):
    """配置校验失败时抛出。"""

    pass


@dataclass
class Config:
    """
    全局配置管理 — 从环境变量读取所有配置。

    所有 LLM 相关字段使用 ANTHROPIC_* 命名体系的环境变量。
    API_TIMEOUT_MS 以毫秒为单位, 内部自动转换为秒。
    """

    # ── LLM Provider ────────────────────────────────
    llm_api_key: str = ""  # API 认证令牌 (ANTHROPIC_AUTH_TOKEN, 必需)
    llm_base_url: str = "https://api.deepseek.com/anthropic"  # API 基础地址 (ANTHROPIC_BASE_URL)
    llm_model: str = "deepseek-v4-pro"  # 默认模型名称 (ANTHROPIC_MODEL)
    llm_small_fast_model: str | None = None  # 小型快速模型 (ANTHROPIC_SMALL_FAST_MODEL, 可选)
    llm_custom_model_option: str | None = None  # 自定义模型选项 (ANTHROPIC_CUSTOM_MODEL_OPTION, 可选)
    llm_max_tokens: int = 4096  # 最大生成 Token 数
    llm_temperature: float = 0.7  # 采样温度 0-2
    llm_timeout: float = 60.0  # 请求超时秒数 (由 API_TIMEOUT_MS / 1000 转换)
    llm_max_retries: int = 3  # 最大重试次数
    llm_retry_base_delay: float = 1.0  # 重试基础延迟秒
    llm_retry_max_delay: float = 60.0  # 重试最大延迟秒

    # ── Agent ───────────────────────────────────────
    agent_max_iterations: int = 10  # ReAct 最大迭代次数 (AGENT_MAX_ITERATIONS)
    agent_max_consecutive_failures: int = 3  # 连续 Tool 失败上限 (AGENT_MAX_CONSECUTIVE_FAILURES)
    agent_max_call_depth: int = 3  # Agent 嵌套调用最大深度 (AGENT_MAX_CALL_DEPTH)
    agent_tool_execution_timeout: float = 30.0  # Tool 执行超时秒 (AGENT_TOOL_TIMEOUT)
    agent_default_name: str = "RootAgent"  # 默认 Agent 名称

    # ── Crew ────────────────────────────────────────
    crew_max_parallel: int = 4  # Crew 最大并行成员数 (CREW_MAX_PARALLEL)
    crew_max_iterations: int = 3  # Crew 任务分解最大 LLM 迭代 (CREW_MAX_ITERATIONS)
    crew_plan_temperature: float = 0.4  # Crew 任务分解时的 LLM 温度 (CREW_PLAN_TEMPERATURE)

    # ── 上下文 ──────────────────────────────────────
    context_max_tokens: int = 64000  # 上下文窗口 Token 上限 (CONTEXT_MAX_TOKENS)
    context_compress_strategy: str = "hybrid"  # 压缩策略: sliding | summarize | hybrid

    # ── 插件 ────────────────────────────────────────
    plugin_directories: list[str] = field(default_factory=list)  # Agent 插件目录 (PLUGIN_DIRS, 逗号分隔)

    # ── 日志 ────────────────────────────────────────
    log_level: str = "INFO"  # 日志级别 (LOG_LEVEL)
    log_file: str | None = None  # 日志文件路径 (LOG_FILE)
    log_format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_llm_calls: bool = False  # 是否记录 LLM 调用详情 (LOG_LLM_CALLS)

    # ── 安全 ────────────────────────────────────────
    security_allowed_directories: list[str] = field(default_factory=list)  # 允许的文件目录白名单
    security_allowed_commands: list[str] = field(default_factory=list)  # 允许的 Shell 命令白名单
    security_confirm_dangerous: bool = True  # 危险操作是否需确认
    security_max_file_size_mb: float = 10.0  # 单文件最大大小

    @classmethod
    def from_env(cls) -> "Config":
        """
        从环境变量加载所有配置。

        LLM 相关环境变量 (ANTHROPIC_* 命名体系):
        - ANTHROPIC_AUTH_TOKEN → llm_api_key (必需)
        - ANTHROPIC_BASE_URL → llm_base_url
        - ANTHROPIC_MODEL → llm_model
        - ANTHROPIC_SMALL_FAST_MODEL → llm_small_fast_model (可选)
        - ANTHROPIC_CUSTOM_MODEL_OPTION → llm_custom_model_option (可选, JSON 格式)
        - API_TIMEOUT_MS → llm_timeout (毫秒转秒)
        """
        config = cls()

        # LLM Provider 配置
        config.llm_api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        config.llm_base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
        config.llm_model = os.environ.get("ANTHROPIC_MODEL", "deepseek-v4-pro")
        config.llm_small_fast_model = os.environ.get("ANTHROPIC_SMALL_FAST_MODEL") or None
        config.llm_custom_model_option = os.environ.get("ANTHROPIC_CUSTOM_MODEL_OPTION") or None

        # API 超时 (毫秒 → 秒)
        api_timeout_ms = int(os.environ.get("API_TIMEOUT_MS", "60000"))
        config.llm_timeout = api_timeout_ms / 1000.0

        # Agent 配置
        config.agent_max_iterations = int(os.environ.get("AGENT_MAX_ITERATIONS", "10"))
        config.agent_max_consecutive_failures = int(os.environ.get("AGENT_MAX_CONSECUTIVE_FAILURES", "3"))
        config.agent_max_call_depth = int(os.environ.get("AGENT_MAX_CALL_DEPTH", "3"))
        config.agent_tool_execution_timeout = float(os.environ.get("AGENT_TOOL_TIMEOUT", "30.0"))
        config.agent_default_name = os.environ.get("AGENT_DEFAULT_NAME", "RootAgent")

        # Crew 配置
        config.crew_max_parallel = int(os.environ.get("CREW_MAX_PARALLEL", "4"))
        config.crew_max_iterations = int(os.environ.get("CREW_MAX_ITERATIONS", "3"))
        config.crew_plan_temperature = float(os.environ.get("CREW_PLAN_TEMPERATURE", "0.4"))

        # 上下文配置
        config.context_max_tokens = int(os.environ.get("CONTEXT_MAX_TOKENS", "64000"))
        config.context_compress_strategy = os.environ.get("CONTEXT_COMPRESS_STRATEGY", "hybrid")

        # 插件目录
        plugin_dirs = os.environ.get("PLUGIN_DIRS", "")
        if plugin_dirs:
            config.plugin_directories = [d.strip() for d in plugin_dirs.split(",") if d.strip()]

        # 日志配置
        config.log_level = os.environ.get("LOG_LEVEL", "INFO")
        config.log_file = os.environ.get("LOG_FILE") or None
        config.log_llm_calls = os.environ.get("LOG_LLM_CALLS", "").lower() == "true"

        # 安全配置
        allowed_dirs = os.environ.get("SECURITY_ALLOWED_DIRS", "")
        if allowed_dirs:
            config.security_allowed_directories = [d.strip() for d in allowed_dirs.split(",") if d.strip()]
        allowed_cmds = os.environ.get("SECURITY_ALLOWED_COMMANDS", "")
        if allowed_cmds:
            config.security_allowed_commands = [c.strip() for c in allowed_cmds.split(",") if c.strip()]
        config.security_confirm_dangerous = os.environ.get("SECURITY_CONFIRM_DANGEROUS", "true").lower() == "true"
        config.security_max_file_size_mb = float(os.environ.get("SECURITY_MAX_FILE_SIZE_MB", "10.0"))

        return config

    def validate(self) -> None:
        """
        校验必要配置项:
        - llm_api_key 不为空
        - llm_base_url 格式合法 (必须是 http/https URL)
        - llm_timeout > 0
        - llm_temperature 在 0-2 范围内
        - llm_max_tokens > 0
        """
        if not self.llm_api_key:
            raise ConfigValidationError(
                "ANTHROPIC_AUTH_TOKEN 环境变量未设置, LLM API 认证令牌为必需项"
            )

        if not self.llm_base_url.startswith(("http://", "https://")):
            raise ConfigValidationError(
                f"ANTHROPIC_BASE_URL 格式不合法: {self.llm_base_url}, 必须以 http:// 或 https:// 开头"
            )

        if self.llm_timeout <= 0:
            raise ConfigValidationError(
                f"API_TIMEOUT_MS 必须为正数, 当前值转换后为: {self.llm_timeout}s"
            )

        if not 0 <= self.llm_temperature <= 2:
            raise ConfigValidationError(
                f"llm_temperature 必须在 0-2 范围内, 当前值: {self.llm_temperature}"
            )

        if self.llm_max_tokens <= 0:
            raise ConfigValidationError(
                f"llm_max_tokens 必须为正数, 当前值: {self.llm_max_tokens}"
            )

        # 校验 llm_custom_model_option 若为 JSON 字符串则必须合法
        if self.llm_custom_model_option:
            try:
                json.loads(self.llm_custom_model_option)
            except json.JSONDecodeError as e:
                raise ConfigValidationError(
                    f"ANTHROPIC_CUSTOM_MODEL_OPTION 不是合法的 JSON: {e}"
                )

    def to_provider_kwargs(self) -> dict:
        """导出为 LLMProvider 构造函数所需的参数字典。"""
        kwargs: dict = {
            "api_key": self.llm_api_key,
            "base_url": self.llm_base_url,
            "model": self.llm_model,
            "small_fast_model": self.llm_small_fast_model,
            "custom_model_option": self.llm_custom_model_option,
            "max_tokens": self.llm_max_tokens,
            "temperature": self.llm_temperature,
            "timeout": self.llm_timeout,
            "max_retries": self.llm_max_retries,
        }
        return kwargs
