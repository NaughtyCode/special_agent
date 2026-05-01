"""
代码搜索 Tool — 在代码库中搜索文件内容和文件模式。

支持:
- 正则表达式内容搜索
- 文件类型过滤
- 上下文行显示
"""

import os
import re
import time
from typing import Any

from src.tools.base_tool import BaseTool, ToolResult


class SearchCodeTool(BaseTool):
    """在代码文件中搜索匹配指定模式的内容。"""

    name: str = "search_code"
    description: str = (
        "在指定目录的代码文件中搜索匹配指定正则表达式模式的内容。"
        "支持文件类型过滤, 返回匹配行及上下文。"
    )
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "搜索的正则表达式模式",
            },
            "path": {
                "type": "string",
                "description": "搜索目录路径",
                "default": ".",
            },
            "glob": {
                "type": "string",
                "description": "文件名 glob 过滤器 (如 '*.py', '*.{ts,tsx}')",
            },
            "context_lines": {
                "type": "integer",
                "description": "匹配行前后显示的上下文行数",
                "default": 0,
            },
            "max_results": {
                "type": "integer",
                "description": "最大返回结果数",
                "default": 50,
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "是否区分大小写",
                "default": False,
            },
        },
        "required": ["pattern"],
    }
    tags: list[str] = ["search", "find", "code", "grep"]

    def __init__(self, project_root: str | None = None) -> None:
        """初始化 SearchCodeTool。"""
        self.project_root = project_root or os.getcwd()

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        搜索代码内容。

        Args:
            pattern: 正则表达式模式
            path: 搜索目录 (默认 ".")
            glob: 文件名 glob 过滤器
            context_lines: 上下文行数 (默认 0)
            max_results: 最大结果数 (默认 50)
            case_sensitive: 是否区分大小写 (默认 False)

        Returns:
            ToolResult
        """
        import fnmatch

        pattern = kwargs.get("pattern", "")
        search_path = kwargs.get("path", ".")
        glob_filter = kwargs.get("glob")
        context_lines = kwargs.get("context_lines", 0)
        max_results = kwargs.get("max_results", 50)
        case_sensitive = kwargs.get("case_sensitive", False)

        start = time.time()

        if not os.path.isabs(search_path):
            search_path = os.path.join(self.project_root, search_path)
        search_path = os.path.normpath(os.path.abspath(search_path))

        if not os.path.isdir(search_path):
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"搜索目录不存在: {search_path}",
                error=f"Directory not found: {search_path}",
                tool_name=self.name,
                duration_ms=duration,
            )

        # 编译正则
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"正则表达式无效: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )

        # 支持的文件扩展名 (代码文件)
        default_exts = {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
            ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
            ".kt", ".scala", ".r", ".sh", ".bash", ".zsh", ".sql",
            ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg",
            ".md", ".rst", ".txt", ".html", ".css", ".scss", ".less",
            ".xml", ".svg", ".vue", ".svelte",
        }

        results: list[str] = []
        matched_files = 0
        total_matches = 0

        try:
            for root, dirs, files in os.walk(search_path):
                # 跳过隐藏目录和常见忽略目录
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".") and d not in (
                        "node_modules", "__pycache__", "venv", ".venv",
                        ".git", "dist", "build", "target", ".next",
                    )
                ]

                for filename in files:
                    # glob 过滤器
                    if glob_filter and not fnmatch.fnmatch(filename, glob_filter):
                        continue

                    # 文件扩展名过滤 (仅搜索代码/文本文件)
                    ext = os.path.splitext(filename)[1].lower()
                    if ext not in default_exts and glob_filter is None:
                        continue

                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, search_path)

                    try:
                        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                            lines = f.readlines()

                        file_has_match = False
                        for i, line in enumerate(lines):
                            if total_matches >= max_results:
                                break

                            if regex.search(line):
                                if not file_has_match:
                                    file_has_match = True
                                    matched_files += 1

                                total_matches += 1

                                # 组装结果行
                                if context_lines > 0:
                                    start_ctx = max(0, i - context_lines)
                                    end_ctx = min(len(lines), i + context_lines + 1)
                                    ctx_text = "".join(
                                        f"  {j + 1}: {lines[j].rstrip()}\n"
                                        for j in range(start_ctx, end_ctx)
                                    )
                                    results.append(
                                        f"--- {rel_path}:{i + 1} ---\n{ctx_text}"
                                    )
                                else:
                                    results.append(
                                        f"{rel_path}:{i + 1}: {lines[i].rstrip()}"
                                    )

                    except (UnicodeDecodeError, PermissionError, OSError):
                        continue

                    if total_matches >= max_results:
                        break

                if total_matches >= max_results:
                    break

        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"搜索失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )

        duration = (time.time() - start) * 1000

        if not results:
            return ToolResult(
                success=True,
                output=f"未找到匹配 '{pattern}' 的结果 (搜索目录: {search_path})",
                data={"matches": 0},
                tool_name=self.name,
                duration_ms=duration,
            )

        # 截断
        if len(results) > max_results:
            results = results[:max_results]
            results.append(f"\n... [截断: 仅显示前 {max_results} 条结果]")

        output = f"搜索 '{pattern}' 的结果 ({total_matches} 条匹配, {matched_files} 个文件):\n\n" + "\n".join(results)
        duration = (time.time() - start) * 1000
        return ToolResult(
            success=True,
            output=output,
            data={
                "pattern": pattern,
                "matches": total_matches,
                "files": matched_files,
            },
            tool_name=self.name,
            duration_ms=duration,
        )
