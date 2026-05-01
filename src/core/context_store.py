"""
上下文存储 — 管理对话历史和 Agent 工作记忆。

职责:
- 存储完整的消息历史 (system / user / assistant / tool)
- 存储每次 ReAct 迭代的轨迹
- 管理上下文变量 (供 Tool 和 Agent 共享)
- 支持上下文窗口管理 (可注入压缩策略, 防止超出 LLM Token 限制)
"""

import hashlib
import json
import logging
import time
from typing import Any

from src.core.models import Message, ReActStep, TokenUsage, ToolCall
from src.infra.config import Config
from src.strategies.compress_strategy import HybridStrategy

logger = logging.getLogger(__name__)


class ContextStore:
    """
    上下文存储 — 管理对话历史和 Agent 工作记忆。

    职责:
    - 存储完整的消息历史 (system / user / assistant / tool)
    - 存储每次 ReAct 迭代的轨迹
    - 管理上下文变量 (供 Tool 和 Agent 共享)
    - 支持上下文窗口管理 (可注入压缩策略, 防止超出 LLM Token 限制)
    """

    def __init__(self, config: Config, compress_strategy: Any = None) -> None:
        """
        初始化上下文存储。

        Args:
            config: Config 实例
            compress_strategy: 压缩策略实例, 默认使用 HybridStrategy
        """
        self._messages: list[Message] = []
        self._react_steps: list[ReActStep] = []
        self._variables: dict[str, Any] = {}
        self._tool_results: dict[str, Any] = {}  # key = tool_name + args_hash
        self._system_message: Message | None = None

        self.max_context_tokens: int = getattr(config, "context_max_tokens", 64000)
        self.compress_strategy = compress_strategy or HybridStrategy()

    # ── 消息操作 ─────────────────────────────────────

    def add_message(
        self,
        role: str,
        content: str,
        name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        """
        添加一条消息到历史。

        Args:
            role: 消息角色 (system/user/assistant/tool)
            content: 消息内容
            name: 可选发送者名称
            tool_call_id: Tool 调用 ID (role="tool" 时)
            tool_calls: Assistant 的 tool_calls (role="assistant" 时)
        """
        msg = Message(
            role=role,  # type: ignore
            content=content,
            name=name,
            tool_call_id=tool_call_id,
            tool_calls=tool_calls,
        )

        # 保存 system message 引用
        if role == "system":
            self._system_message = msg

        self._messages.append(msg)

    def get_messages(self, last_n: int | None = None) -> list[Message]:
        """
        获取消息历史。

        Args:
            last_n: 若指定, 只返回最近 N 条

        Returns:
            Message 列表
        """
        if last_n is not None:
            return self._messages[-last_n:]
        return list(self._messages)

    def get_messages_for_llm(self) -> list[Message]:
        """
        获取适合发送给 LLM 的消息列表。

        自动调用 compress_strategy 确保 Token 不超限。

        Returns:
            压缩后的消息列表
        """
        if not self._messages:
            return []

        # 估算 token 数
        estimated = self.estimate_tokens()

        if estimated > self.max_context_tokens:
            logger.info(
                f"Context tokens ({estimated}) exceed limit ({self.max_context_tokens}), "
                f"applying compression"
            )
            return self.compress_strategy.compress(
                self._messages,
                self._system_message,
                self.max_context_tokens,
            )

        return list(self._messages)

    def estimate_tokens(self) -> int:
        """
        估算当前消息历史的 Token 数。

        使用 tiktoken (若可用) 或启发式算法 (字符数 / 4)。

        Returns:
            估算的 Token 数
        """
        total_chars = sum(len(msg.content) for msg in self._messages)
        # 尝试使用 tiktoken
        try:
            import tiktoken

            encoding = tiktoken.get_encoding("cl100k_base")
            full_text = "\n".join(msg.content for msg in self._messages)
            return len(encoding.encode(full_text))
        except (ImportError, Exception):
            pass

        # 启发式: 字符数 / 4 (中英文混合估算)
        return int(total_chars / 4)

    def clear(self) -> None:
        """清除所有历史 (保留 system_message 引用)。"""
        system_msg = self._system_message
        self._messages = []
        self._react_steps = []
        self._variables = {}
        self._tool_results = {}
        if system_msg:
            self._messages.append(system_msg)

    # ── ReAct 轨迹 ───────────────────────────────────

    def add_react_step(self, step: ReActStep) -> None:
        """
        记录一次 ReAct 迭代。

        Args:
            step: ReActStep 实例
        """
        self._react_steps.append(step)

    def get_react_trajectory(self) -> list[ReActStep]:
        """
        获取完整的 ReAct 轨迹。

        Returns:
            ReActStep 列表
        """
        return list(self._react_steps)

    def get_last_n_steps(self, n: int) -> list[ReActStep]:
        """
        获取最近 N 次迭代轨迹。

        Args:
            n: 获取最近 N 步

        Returns:
            最近 N 个 ReActStep
        """
        return self._react_steps[-n:]

    # ── 变量操作 ─────────────────────────────────────

    def set_variable(self, key: str, value: Any) -> None:
        """
        设置上下文变量 (跨 Tool / Agent 共享)。

        Args:
            key: 变量名
            value: 变量值
        """
        self._variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """
        获取上下文变量。

        Args:
            key: 变量名
            default: 默认值 (若 key 不存在)

        Returns:
            变量值或默认值
        """
        return self._variables.get(key, default)

    def get_all_variables(self) -> dict[str, Any]:
        """
        获取所有上下文变量 (快照副本)。

        Returns:
            所有变量的副本
        """
        return dict(self._variables)

    # ── Tool 结果缓存 ────────────────────────────────

    def cache_tool_result(self, tool_name: str, args: dict, result: Any) -> None:
        """
        缓存 Tool 执行结果 (相同 tool_name + 相同 args 可直接复用)。

        Args:
            tool_name: Tool 名称
            args: 调用参数
            result: ToolResult 实例
        """
        cache_key = f"{tool_name}:{self._hash_args(args)}"
        self._tool_results[cache_key] = result

    def get_cached_result(self, tool_name: str, **kwargs: Any) -> Any | None:
        """
        查找缓存的 Tool 结果 (用于幂等调用优化)。

        Args:
            tool_name: Tool 名称
            **kwargs: 调用参数

        Returns:
            缓存的 ToolResult 或 None
        """
        cache_key = f"{tool_name}:{self._hash_args(kwargs)}"
        return self._tool_results.get(cache_key)

    def _hash_args(self, args: dict) -> str:
        """对参数字典做 hash (用于缓存 key)。"""
        args_str = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.md5(args_str.encode()).hexdigest()[:12]

    # ── 导出/导入 ─────────────────────────────────────

    def export_snapshot(self) -> dict:
        """
        导出上下文快照 (用于会话持久化或跨 Agent 传递)。

        Returns:
            可序列化的 dict
        """
        return {
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "name": m.name,
                    "tool_call_id": m.tool_call_id,
                }
                for m in self._messages
            ],
            "variables": dict(self._variables),
            "react_step_count": len(self._react_steps),
            "timestamp": time.time(),
        }

    def import_snapshot(self, snapshot: dict) -> None:
        """
        从快照恢复上下文。

        Args:
            snapshot: export_snapshot() 导出的快照 dict
        """
        self.clear()
        for msg_data in snapshot.get("messages", []):
            self.add_message(
                role=msg_data["role"],
                content=msg_data["content"],
                name=msg_data.get("name"),
                tool_call_id=msg_data.get("tool_call_id"),
            )
        self._variables = dict(snapshot.get("variables", {}))
        logger.debug(f"Imported context snapshot with {len(self._messages)} messages")
