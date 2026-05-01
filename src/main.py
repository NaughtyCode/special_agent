"""
SpecialAgent 程序入口 — 初始化 RootAgent 并启动 REPL 交互循环。

用法:
    python -m src.main           # 启动交互式 REPL
    python -m src.main "query"   # 单次查询模式

环境变量:
    ANTHROPIC_AUTH_TOKEN     — API 认证令牌 (必需)
    ANTHROPIC_BASE_URL        — API 基础地址
    ANTHROPIC_MODEL           — 默认模型名称
    详见 src/infra/config.py 中的完整配置列表。
"""

import sys


def main() -> None:
    """程序主入口 — 初始化并启动 RootAgent。"""
    from src.agents.root_agent import RootAgent
    from src.infra.config import Config, ConfigValidationError

    # 加载配置
    try:
        config = Config.from_env()
        config.validate()
    except ConfigValidationError as e:
        print(f"[配置错误] {e}")
        print("\n请设置所需的环境变量后重试。")
        print("必需: ANTHROPIC_AUTH_TOKEN")
        print("可选: ANTHROPIC_BASE_URL, ANTHROPIC_MODEL 等")
        sys.exit(1)

    # 创建 RootAgent
    agent = RootAgent(config=config)

    # 检查命令行参数
    if len(sys.argv) > 1:
        # 单次查询模式
        query = " ".join(sys.argv[1:])
        print(f"Processing: {query}")
        result = agent.process_once(query)
        print(agent._format_result_display(result))
    else:
        # 交互式 REPL 模式
        agent.start_repl()


if __name__ == "__main__":
    main()
