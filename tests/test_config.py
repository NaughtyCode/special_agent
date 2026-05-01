"""
Config 配置管理单元测试。

测试覆盖:
- 从环境变量加载配置
- 配置默认值
- 配置校验 (validate)
- to_provider_kwargs 导出
"""

import os
import unittest

from src.infra.config import Config, ConfigValidationError


class TestConfig(unittest.TestCase):
    """Config 配置管理测试。"""

    def setUp(self) -> None:
        """保存原始环境变量, 设置测试环境。"""
        self._saved_env = {}
        for key in (
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "API_TIMEOUT_MS",
            "AGENT_MAX_ITERATIONS",
            "ANTHROPIC_CUSTOM_MODEL_OPTION",
        ):
            self._saved_env[key] = os.environ.get(key)
            if key in os.environ:
                del os.environ[key]

    def tearDown(self) -> None:
        """恢复原始环境变量。"""
        for key, value in self._saved_env.items():
            if value is not None:
                os.environ[key] = value
            elif key in os.environ:
                del os.environ[key]

    def test_default_values(self) -> None:
        """测试: 默认值正确。"""
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "test-key"
        config = Config.from_env()

        self.assertEqual(config.llm_base_url, "https://api.deepseek.com/anthropic")
        self.assertEqual(config.llm_model, "deepseek-v4-pro")
        self.assertEqual(config.llm_max_tokens, 4096)
        self.assertEqual(config.llm_temperature, 0.7)
        self.assertEqual(config.agent_max_iterations, 10)
        self.assertEqual(config.agent_max_consecutive_failures, 3)
        self.assertEqual(config.crew_max_parallel, 4)

    def test_from_env_llm_config(self) -> None:
        """测试: LLM 配置从环境变量正确加载。"""
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "my-api-key"
        os.environ["ANTHROPIC_BASE_URL"] = "https://custom.api.com"
        os.environ["ANTHROPIC_MODEL"] = "custom-model"
        os.environ["API_TIMEOUT_MS"] = "30000"

        config = Config.from_env()

        self.assertEqual(config.llm_api_key, "my-api-key")
        self.assertEqual(config.llm_base_url, "https://custom.api.com")
        self.assertEqual(config.llm_model, "custom-model")
        self.assertEqual(config.llm_timeout, 30.0)

    def test_from_env_agent_config(self) -> None:
        """测试: Agent 配置从环境变量正确加载。"""
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "test-key"
        os.environ["AGENT_MAX_ITERATIONS"] = "20"

        config = Config.from_env()
        self.assertEqual(config.agent_max_iterations, 20)

    def test_validate_missing_api_key(self) -> None:
        """测试: 缺少 API Key 时校验失败。"""
        config = Config()
        config.llm_api_key = ""

        with self.assertRaises(ConfigValidationError) as ctx:
            config.validate()
        self.assertIn("ANTHROPIC_AUTH_TOKEN", str(ctx.exception))

    def test_validate_invalid_base_url(self) -> None:
        """测试: 无效 base_url 时校验失败。"""
        config = Config()
        config.llm_api_key = "test-key"
        config.llm_base_url = "ftp://invalid.url"

        with self.assertRaises(ConfigValidationError) as ctx:
            config.validate()
        self.assertIn("ANTHROPIC_BASE_URL", str(ctx.exception))

    def test_validate_temperature_range(self) -> None:
        """测试: temperature 范围校验。"""
        config = Config()
        config.llm_api_key = "test-key"
        config.llm_temperature = 3.0  # 超出 0-2 范围

        with self.assertRaises(ConfigValidationError) as ctx:
            config.validate()
        self.assertIn("temperature", str(ctx.exception).lower())

    def test_validate_negative_timeout(self) -> None:
        """测试: 负超时值校验。"""
        config = Config()
        config.llm_api_key = "test-key"
        config.llm_timeout = -1.0

        with self.assertRaises(ConfigValidationError):
            config.validate()

    def test_validate_valid_config(self) -> None:
        """测试: 有效配置通过校验。"""
        config = Config()
        config.llm_api_key = "test-key"

        # 不应抛出异常
        try:
            config.validate()
        except ConfigValidationError:
            self.fail("validate() 不应该对有效配置抛出异常")

    def test_to_provider_kwargs(self) -> None:
        """测试: to_provider_kwargs 导出正确。"""
        config = Config()
        config.llm_api_key = "my-key"
        config.llm_base_url = "https://api.example.com"
        config.llm_model = "test-model"

        kwargs = config.to_provider_kwargs()

        self.assertEqual(kwargs["api_key"], "my-key")
        self.assertEqual(kwargs["base_url"], "https://api.example.com")
        self.assertEqual(kwargs["model"], "test-model")
        self.assertIn("max_tokens", kwargs)
        self.assertIn("temperature", kwargs)

    def test_custom_model_option_valid_json(self) -> None:
        """测试: 有效的自定义模型选项 JSON。"""
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "test-key"
        os.environ["ANTHROPIC_CUSTOM_MODEL_OPTION"] = '{"top_k": 50, "top_p": 0.9}'

        config = Config.from_env()
        self.assertEqual(config.llm_custom_model_option, '{"top_k": 50, "top_p": 0.9}')

    def test_plugin_directories_parsing(self) -> None:
        """测试: 插件目录从逗号分隔字符串解析。"""
        os.environ["ANTHROPIC_AUTH_TOKEN"] = "test-key"
        os.environ["PLUGIN_DIRS"] = "/path/one,/path/two, /path/three"

        config = Config.from_env()
        self.assertEqual(len(config.plugin_directories), 3)
        self.assertIn("/path/one", config.plugin_directories)
        self.assertIn("/path/two", config.plugin_directories)


if __name__ == "__main__":
    unittest.main()
