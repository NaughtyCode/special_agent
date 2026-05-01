"""
网络 Tool — 网页搜索和内容获取。

安全机制:
- URL 协议白名单检查 (默认仅 https)
- 响应大小限制
- 超时控制
"""

import time
from typing import Any
from urllib.parse import urlparse

from src.tools.base_tool import BaseTool, ToolResult


class WebFetchTool(BaseTool):
    """获取网页内容 (HTTP GET)。"""

    name: str = "web_fetch"
    description: str = "获取指定 URL 的网页内容。仅支持 HTTPS 协议, 自动限制响应大小。"
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要获取的网页 URL",
            },
            "max_size": {
                "type": "integer",
                "description": "最大响应大小 (字节), 默认 1MB",
            },
        },
        "required": ["url"],
    }
    tags: list[str] = ["web", "fetch", "http", "network"]

    def __init__(self, allowed_schemes: list[str] | None = None) -> None:
        """
        初始化 WebFetchTool。

        Args:
            allowed_schemes: 允许的 URL 协议列表 (默认 ["https"])
        """
        self.allowed_schemes = allowed_schemes or ["https"]

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        获取网页内容。

        Args:
            url: 网页 URL
            max_size: 最大响应大小 (字节), 默认 1MB

        Returns:
            ToolResult
        """
        import urllib.request

        url = kwargs.get("url", "")
        max_size = kwargs.get("max_size", 1_000_000)  # 1MB default

        start = time.time()

        # URL 协议检查
        parsed = urlparse(url)
        if parsed.scheme not in self.allowed_schemes:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"不支持的 URL 协议: {parsed.scheme}。允许: {self.allowed_schemes}",
                error=f"Disallowed scheme: {parsed.scheme}",
                tool_name=self.name,
                duration_ms=duration,
            )

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "SpecialAgent/1.0 (WebFetch Tool)",
                    "Accept": "text/html,text/plain,*/*",
                },
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                # 检查 Content-Length
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_size:
                    duration = (time.time() - start) * 1000
                    return ToolResult(
                        success=False,
                        output=f"响应过大: {content_length} 字节 (限制: {max_size})",
                        error=f"Response too large: {content_length}",
                        tool_name=self.name,
                        duration_ms=duration,
                    )

                # 读取响应
                raw_data = response.read(max_size)
                content_type = response.headers.get("Content-Type", "")

                # 尝试解码
                encoding = "utf-8"
                if "charset=" in content_type:
                    encoding = content_type.split("charset=")[-1].strip()

                try:
                    text = raw_data.decode(encoding, errors="replace")
                except (UnicodeDecodeError, LookupError):
                    text = raw_data.decode("utf-8", errors="replace")

                # 如果是 HTML, 做简单的文本提取
                if "text/html" in content_type:
                    text = self._strip_html(text)

                # 截断
                max_chars = 10000
                if len(text) > max_chars:
                    text = text[:max_chars] + f"\n\n... [截断: 原始长度 {len(text)} 字符]"

                duration = (time.time() - start) * 1000
                return ToolResult(
                    success=True,
                    output=text,
                    data={
                        "url": url,
                        "status": response.status,
                        "content_type": content_type,
                        "size": len(raw_data),
                    },
                    tool_name=self.name,
                    duration_ms=duration,
                )

        except urllib.error.URLError as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"网络请求失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"获取网页失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )

    def _strip_html(self, html: str) -> str:
        """简单的 HTML 标签去除 (提取文本)。"""
        import re

        # 移除 script 和 style 标签及其内容
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', html)

        # 规范化空白
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n', text)

        return text.strip()


class WebSearchTool(BaseTool):
    """执行网页搜索 (占位实现 — 需要搜索引擎 API)。"""

    name: str = "web_search"
    description: str = (
        "执行网页搜索并返回结果。注意: 此 Tool 为占位实现, "
        "实际使用需要配置搜索引擎 API (如 Google Custom Search, Bing API 等)。"
    )
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索查询关键词",
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回结果数",
                "default": 5,
            },
        },
        "required": ["query"],
    }
    tags: list[str] = ["web", "search", "query", "internet"]

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        执行网页搜索 (占位)。

        实际项目中, 应接入真实的搜索引擎 API。
        此占位实现返回说明信息。

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            ToolResult
        """
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 5)

        start = time.time()
        duration = (time.time() - start) * 1000

        return ToolResult(
            success=True,
            output=(
                f"[WebSearch 占位] 搜索查询: '{query}'\n"
                f"请求结果数: {max_results}\n\n"
                "注意: WebSearch 为占位实现。要启用实际搜索功能, 请配置搜索引擎 API。\n"
                "支持的集成方式:\n"
                "1. Google Custom Search JSON API\n"
                "2. Bing Web Search API\n"
                "3. SerpAPI / Serper.dev\n"
                "4. DuckDuckGo Instant Answer API (非官方)\n\n"
                "请在 Config 中添加相应的 API Key 配置。"
            ),
            data={"query": query, "placeholder": True},
            tool_name=self.name,
            duration_ms=duration,
        )
