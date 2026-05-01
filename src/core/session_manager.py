"""
会话管理器 — 支持多会话切换与持久化。

所有会话保持在内存中, 可选持久化到磁盘 (JSON 文件)。
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.core.context_store import ContextStore
from src.core.models import TokenUsage

logger = logging.getLogger(__name__)


class SessionNotFoundError(Exception):
    """会话未找到时抛出。"""
    pass


@dataclass
class Session:
    """会话数据。"""
    session_id: str  # 会话唯一标识 (UUID)
    name: str  # 用户可读名称
    created_at: float  # 创建时间戳
    last_active_at: float  # 最后活跃时间戳
    context_store: ContextStore  # 对话上下文
    agent_results: list[Any] = field(default_factory=list)  # Agent 执行记录
    token_usage: TokenUsage = field(default_factory=TokenUsage)  # 会话 Token 累计
    metadata: dict[str, Any] = field(default_factory=dict)  # 扩展元数据


class SessionManager:
    """
    会话管理器 — 支持多会话切换与持久化。

    所有会话保持在内存中, 可选持久化到磁盘 (JSON 文件)。
    """

    def __init__(self, storage_path: str | None = None) -> None:
        """
        初始化会话管理器。

        Args:
            storage_path: 会话持久化路径 (None = 仅内存)
        """
        self._sessions: dict[str, Session] = {}
        self._current_session_id: str | None = None
        self._storage_path = storage_path

        # 若存在持久化文件, 恢复会话
        if storage_path and os.path.exists(storage_path):
            self._load_from_disk()

    def create_session(
        self,
        name: str | None = None,
        session_id: str | None = None,
    ) -> Session:
        """
        创建新会话, 自动生成 UUID。

        Args:
            name: 会话名称 (可选, 默认使用时间戳)
            session_id: 会话 ID (可选, 默认自动生成)

        Returns:
            Session 实例
        """
        sid = session_id or str(uuid.uuid4())
        sname = name or f"Session-{time.strftime('%Y%m%d-%H%M%S')}"

        # 需要 Config 实例来创建 ContextStore
        from src.infra.config import Config
        config = Config.from_env()

        session = Session(
            session_id=sid,
            name=sname,
            created_at=time.time(),
            last_active_at=time.time(),
            context_store=ContextStore(config),
        )

        self._sessions[sid] = session
        self._current_session_id = sid
        logger.info(f"Created session: {sname} ({sid})")
        return session

    def switch_session(self, session_id: str) -> Session:
        """
        切换到指定会话。

        Args:
            session_id: 目标会话 ID

        Returns:
            Session 实例

        Raises:
            SessionNotFoundError: 若会话不存在
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(f"会话 '{session_id}' 不存在")
        self._current_session_id = session_id
        session = self._sessions[session_id]
        session.last_active_at = time.time()
        logger.info(f"Switched to session: {session.name} ({session_id})")
        return session

    def get_current_session(self) -> Session:
        """
        获取当前会话。若不存在则自动创建。

        Returns:
            当前 Session 实例
        """
        if self._current_session_id and self._current_session_id in self._sessions:
            return self._sessions[self._current_session_id]
        return self.create_session()

    def list_sessions(self) -> list[Session]:
        """
        列出所有会话 (按最后活跃时间倒序)。

        Returns:
            Session 列表
        """
        return sorted(
            self._sessions.values(),
            key=lambda s: s.last_active_at,
            reverse=True,
        )

    def delete_session(self, session_id: str) -> None:
        """
        删除指定会话 (不能删除当前会话)。

        Args:
            session_id: 要删除的会话 ID

        Raises:
            ValueError: 若尝试删除当前会话
            SessionNotFoundError: 若会话不存在
        """
        if session_id == self._current_session_id:
            raise ValueError("不能删除当前会话, 请先切换到其他会话")
        if session_id not in self._sessions:
            raise SessionNotFoundError(f"会话 '{session_id}' 不存在")
        del self._sessions[session_id]
        logger.info(f"Deleted session: {session_id}")

    def clear_current_session(self) -> None:
        """清除当前会话的上下文, 保留会话元数据。"""
        session = self.get_current_session()
        session.context_store.clear()
        session.agent_results = []
        session.token_usage = TokenUsage()
        session.last_active_at = time.time()
        logger.info(f"Cleared session: {session.name}")

    def export_session(self, session_id: str) -> dict:
        """
        导出会话为可序列化字典 (用于持久化或分享)。

        Args:
            session_id: 会话 ID

        Returns:
            可序列化的 dict

        Raises:
            SessionNotFoundError: 若会话不存在
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(f"会话 '{session_id}' 不存在")

        session = self._sessions[session_id]
        return {
            "session_id": session.session_id,
            "name": session.name,
            "created_at": session.created_at,
            "last_active_at": session.last_active_at,
            "context_snapshot": session.context_store.export_snapshot(),
            "token_usage": {
                "prompt_tokens": session.token_usage.prompt_tokens,
                "completion_tokens": session.token_usage.completion_tokens,
                "total_tokens": session.token_usage.total_tokens,
            },
            "metadata": session.metadata,
        }

    def import_session(self, data: dict) -> Session:
        """
        从字典导入会话。

        Args:
            data: export_session() 导出的字典

        Returns:
            导入的 Session 实例
        """
        from src.infra.config import Config

        session = Session(
            session_id=data["session_id"],
            name=data["name"],
            created_at=data.get("created_at", time.time()),
            last_active_at=data.get("last_active_at", time.time()),
            context_store=ContextStore(Config.from_env()),
            token_usage=TokenUsage(
                prompt_tokens=data.get("token_usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("token_usage", {}).get("completion_tokens", 0),
                total_tokens=data.get("token_usage", {}).get("total_tokens", 0),
            ),
            metadata=data.get("metadata", {}),
        )

        if "context_snapshot" in data:
            session.context_store.import_snapshot(data["context_snapshot"])

        self._sessions[session.session_id] = session
        logger.info(f"Imported session: {session.name} ({session.session_id})")
        return session

    def save_to_disk(self) -> None:
        """持久化所有会话到磁盘 (若配置了 storage_path)。"""
        if not self._storage_path:
            return

        try:
            data = {
                sid: self.export_session(sid)
                for sid in self._sessions
            }
            os.makedirs(os.path.dirname(self._storage_path) or ".", exist_ok=True)
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved {len(self._sessions)} sessions to {self._storage_path}")
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    def _load_from_disk(self) -> None:
        """从磁盘加载会话 (内部方法)。"""
        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, session_data in data.items():
                try:
                    self.import_session(session_data)
                except Exception as e:
                    logger.warning(f"Failed to import session {sid}: {e}")
            logger.info(f"Loaded {len(self._sessions)} sessions from {self._storage_path}")
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")

    @property
    def session_count(self) -> int:
        """获取会话数量。"""
        return len(self._sessions)
