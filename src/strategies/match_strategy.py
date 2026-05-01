"""
Tool 匹配策略体系 — 支持可注入的多级匹配策略。

策略链按优先级依次尝试:
1. ExactMatchStrategy: 精确名称匹配
2. FuzzyMatchStrategy: 关键词模糊匹配
3. SemanticMatchStrategy: 语义相似度匹配
4. AgentMatchStrategy: Agent 注册中心匹配
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Tool/Agent 匹配结果。"""
    tool_name: str | None = None  # 匹配到的 Tool 名称 (Tool 匹配时)
    agent_name: str | None = None  # 匹配到的 Agent 名称 (Agent 匹配时)
    score: float = 0.0  # 匹配得分 (0-1)
    strategy_used: str = ""  # 使用的匹配策略名称
    candidates: list[str] = None  # type: ignore  # 其他候选名称 (得分低于阈值的前 N 个)

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []

    @property
    def matched_name(self) -> str | None:
        """获取匹配到的名称 (Tool 名或 Agent 名)。"""
        return self.tool_name or self.agent_name

    @property
    def is_matched(self) -> bool:
        """是否匹配成功。"""
        return self.matched_name is not None and self.score > 0


class MatchStrategy(Protocol):
    """Tool 匹配策略接口 — 可替换实现。"""

    def match(
        self,
        action_name: str,
        action_input: dict,
        tool_registry: dict[str, Any],
        agent_registry: Any | None = None,
    ) -> MatchResult | None:
        """
        尝试匹配 Tool 或 Agent。

        Args:
            action_name: 待匹配的动作名称
            action_input: 动作参数
            tool_registry: Tool 注册表 {name: BaseTool}
            agent_registry: Agent 注册中心 (可选)

        Returns:
            MatchResult 或 None (未匹配)
        """
        ...


class MatchStrategyChain:
    """
    策略链 — 按优先级依次尝试多个策略。

    第一个成功的策略结果被采用。
    """

    def __init__(self, strategies: list[MatchStrategy]) -> None:
        """
        初始化策略链。

        Args:
            strategies: 策略列表, 按优先级排序
        """
        self._strategies = strategies

    def match(
        self,
        action_name: str,
        action_input: dict,
        tool_registry: dict[str, Any],
        agent_registry: Any | None = None,
    ) -> MatchResult:
        """
        按优先级依次尝试匹配, 返回第一个成功的结果。

        Args:
            action_name: 待匹配的动作名称
            action_input: 动作参数
            tool_registry: Tool 注册表
            agent_registry: Agent 注册中心 (可选)

        Returns:
            MatchResult, 若全部未匹配则返回 score=0 的空结果
        """
        for strategy in self._strategies:
            try:
                result = strategy.match(action_name, action_input, tool_registry, agent_registry)
                if result and result.is_matched:
                    logger.debug(
                        f"Match strategy '{strategy.__class__.__name__}' "
                        f"matched '{action_name}' → '{result.matched_name}' (score={result.score:.2f})"
                    )
                    return result
            except Exception as e:
                logger.warning(f"Match strategy '{strategy.__class__.__name__}' error: {e}")
                continue

        logger.debug(f"No match found for action '{action_name}'")
        return MatchResult(strategy_used="none")


class ExactMatchStrategy:
    """
    精确名称匹配 — 在 Tool 注册表中按名称精确查找。

    大小写不敏感, 连字符/下划线等价。
    """

    def match(
        self,
        action_name: str,
        action_input: dict,
        tool_registry: dict[str, Any],
        agent_registry: Any | None = None,
    ) -> MatchResult | None:
        """精确匹配 Tool 名称。"""
        # 标准化名称: 小写, 连字符/下划线替换
        normalized = action_name.lower().replace("-", "_").replace(" ", "_")

        # 直接查找
        for tool_name, tool in tool_registry.items():
            tool_normalized = tool_name.lower().replace("-", "_").replace(" ", "_")
            if tool_normalized == normalized:
                return MatchResult(
                    tool_name=tool_name,
                    score=1.0,
                    strategy_used="exact",
                )

        return None


class FuzzyMatchStrategy:
    """
    模糊匹配 — 对 Tool 名称/描述做关键词匹配。

    配置:
    - score_threshold: 最低匹配得分 (默认 0.3)
    - max_candidates: 返回候选数 (默认 5)
    """

    def __init__(self, score_threshold: float = 0.3, max_candidates: int = 5) -> None:
        """
        初始化模糊匹配策略。

        Args:
            score_threshold: 最低匹配得分阈值
            max_candidates: 最大候选数
        """
        self.score_threshold = score_threshold
        self.max_candidates = max_candidates

    def match(
        self,
        action_name: str,
        action_input: dict,
        tool_registry: dict[str, Any],
        agent_registry: Any | None = None,
    ) -> MatchResult | None:
        """
        模糊匹配 Tool。

        算法: 对 action_name 分词, 计算每个 Tool 的匹配得分:
        - 名称关键词命中加权 (×2)
        - 描述关键词命中加权 (×1)
        - 标签命中加权 (×1.5)
        """
        # 对 action_name 分词 (提取字母/数字序列)
        query_tokens = set(re.findall(r"[a-zA-Z0-9一-鿿]+", action_name.lower()))

        if not query_tokens:
            return None

        candidates: list[tuple[str, float]] = []

        for tool_name, tool in tool_registry.items():
            score = 0.0
            max_possible = 0.0

            # 名称匹配
            name_tokens = set(re.findall(r"[a-zA-Z0-9一-鿿]+", tool_name.lower()))
            name_overlap = len(query_tokens & name_tokens)
            if name_tokens:
                score += name_overlap * 2.0
                max_possible += len(query_tokens) * 2.0

            # 描述匹配
            desc = getattr(tool, "description", "")
            if desc:
                desc_tokens = set(re.findall(r"[a-zA-Z0-9一-鿿]+", desc.lower()))
                desc_overlap = len(query_tokens & desc_tokens)
                if desc_tokens:
                    score += desc_overlap * 1.0
                    max_possible += len(query_tokens) * 1.0

            # 标签匹配
            tags = getattr(tool, "tags", []) or []
            for tag in tags:
                tag_tokens = set(re.findall(r"[a-zA-Z0-9一-鿿]+", tag.lower()))
                tag_overlap = len(query_tokens & tag_tokens)
                score += tag_overlap * 1.5
                max_possible += len(query_tokens) * 1.5

            # 标准化得分
            normalized_score = score / max_possible if max_possible > 0 else 0.0

            if normalized_score >= self.score_threshold:
                candidates.append((tool_name, normalized_score))

        # 按得分降序排列
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:self.max_candidates]

        if not candidates:
            return None

        best_name, best_score = candidates[0]
        other_candidates = [name for name, _ in candidates[1:]]

        return MatchResult(
            tool_name=best_name,
            score=best_score,
            strategy_used="fuzzy",
            candidates=other_candidates,
        )


class SemanticMatchStrategy:
    """
    语义匹配 — 对 Tool 描述和 action 意图做语义相似度比对。

    可选依赖: sentence-transformers (轻量嵌入模型)
    回退方案: 基于 TF-IDF 的关键词重叠度
    """

    def __init__(self, score_threshold: float = 0.5) -> None:
        """
        初始化语义匹配策略。

        Args:
            score_threshold: 最低匹配得分阈值
        """
        self.score_threshold = score_threshold

    def match(
        self,
        action_name: str,
        action_input: dict,
        tool_registry: dict[str, Any],
        agent_registry: Any | None = None,
    ) -> MatchResult | None:
        """
        语义匹配 Tool。

        当前使用简化的 TF-IDF 关键词重叠度作为回退方案。
        若安装了 sentence-transformers, 则使用嵌入相似度。
        """
        # 构建查询文本: action_name + action_input 中的值
        query_parts = [action_name]
        for key, value in action_input.items():
            if isinstance(value, str):
                query_parts.append(value)
        query_text = " ".join(query_parts)

        best_score = 0.0
        best_tool: str | None = None
        candidates: list[tuple[str, float]] = []

        for tool_name, tool in tool_registry.items():
            # 构建 Tool 文本: name + description + tags
            tool_parts = [tool_name]
            desc = getattr(tool, "description", "")
            if desc:
                tool_parts.append(desc)
            tags = getattr(tool, "tags", []) or []
            tool_parts.extend(tags)
            tool_text = " ".join(tool_parts)

            # 基于 TF-IDF 的关键词重叠度
            score = self._jaccard_similarity(query_text, tool_text)

            if score > best_score:
                best_score = score
                best_tool = tool_name

            if score >= self.score_threshold:
                candidates.append((tool_name, score))

        candidates.sort(key=lambda x: x[1], reverse=True)

        if best_tool and best_score >= self.score_threshold:
            other = [name for name, _ in candidates[1:6]]
            return MatchResult(
                tool_name=best_tool,
                score=best_score,
                strategy_used="semantic",
                candidates=other,
            )

        return None

    def _jaccard_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的 Jaccard 相似度 (基于词级 token)。"""
        tokens1 = set(re.findall(r"[a-zA-Z0-9]+", text1.lower()))
        tokens2 = set(re.findall(r"[a-zA-Z0-9]+", text2.lower()))

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0


class AgentMatchStrategy:
    """
    Agent 匹配 — 在 AgentRegistry 中匹配特化 Agent。

    当 Tool 匹配失败时, 尝试将 action_name 作为 Agent 名称匹配。
    """

    def match(
        self,
        action_name: str,
        action_input: dict,
        tool_registry: dict[str, Any],
        agent_registry: Any | None = None,
    ) -> MatchResult | None:
        """
        在 AgentRegistry 中匹配 Agent。

        Args:
            action_name: 待匹配的动作名称
            action_input: 动作参数
            tool_registry: Tool 注册表
            agent_registry: AgentRegistry 实例

        Returns:
            MatchResult 或 None
        """
        if agent_registry is None:
            return None

        normalized = action_name.lower().replace("-", "_").replace(" ", "_")

        # 尝试按名称精确匹配 Agent
        try:
            agent_meta = agent_registry.get_agent_meta(action_name)
            if agent_meta:
                return MatchResult(
                    agent_name=action_name,
                    score=1.0,
                    strategy_used="agent_exact",
                )
        except Exception:
            pass

        # 尝试模糊匹配 Agent
        try:
            agent_list = agent_registry.list_agents()
            for meta in agent_list:
                meta_normalized = meta.name.lower().replace("-", "_").replace(" ", "_")
                if meta_normalized == normalized:
                    return MatchResult(
                        agent_name=meta.name,
                        score=0.9,
                        strategy_used="agent_fuzzy",
                    )
                # 关键词匹配
                name_tokens = set(re.findall(r"[a-zA-Z0-9]+", meta_normalized))
                query_tokens = set(re.findall(r"[a-zA-Z0-9]+", normalized))
                if name_tokens and query_tokens:
                    overlap = len(name_tokens & query_tokens) / len(query_tokens)
                    if overlap > 0.5:
                        return MatchResult(
                            agent_name=meta.name,
                            score=overlap,
                            strategy_used="agent_fuzzy",
                        )
        except Exception:
            pass

        return None
