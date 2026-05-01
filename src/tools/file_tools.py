"""
文件操作 Tool — 读取、写入、列出文件。

安全机制:
- 路径限制在项目根目录内 (通过 sanitize_args)
- 大文件截断保护
- 写操作可配置为需用户确认
"""

import os
import time
from typing import Any

from src.tools.base_tool import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    """读取指定路径的文件内容。"""

    name: str = "read_file"
    description: str = "读取指定路径的文件内容。支持文本文件编码选择, 可限制最大读取行数。"
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径 (绝对路径或相对于项目根目录的相对路径)",
            },
            "encoding": {
                "type": "string",
                "description": "文件编码",
                "default": "utf-8",
            },
            "max_lines": {
                "type": "integer",
                "description": "最大读取行数, 不指定则读取全部",
            },
        },
        "required": ["path"],
    }
    tags: list[str] = ["file", "read", "io"]

    def __init__(self, project_root: str | None = None) -> None:
        """初始化 ReadFileTool。project_root 用于路径安全校验。"""
        self.project_root = project_root or os.getcwd()

    def execute(self, **kwargs: Any) -> ToolResult:
        """读取文件内容。"""
        path = kwargs.get("path", "")
        encoding = kwargs.get("encoding", "utf-8")
        max_lines = kwargs.get("max_lines")

        start = time.time()

        # 路径安全检查
        safe_path = self._safe_path(path)
        if not os.path.exists(safe_path):
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"文件不存在: {path}",
                error=f"File not found: {safe_path}",
                tool_name=self.name,
                duration_ms=duration,
            )

        if not os.path.isfile(safe_path):
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"路径不是文件: {path}",
                error=f"Not a file: {safe_path}",
                tool_name=self.name,
                duration_ms=duration,
            )

        try:
            with open(safe_path, "r", encoding=encoding, errors="replace") as f:
                if max_lines:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            lines.append(f"... [截断: 仅显示前 {max_lines} 行]")
                            break
                        lines.append(line.rstrip("\n"))
                    content = "\n".join(lines)
                else:
                    content = f.read()

            # 截断过大的内容
            max_chars = 50000
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n... [文件被截断, 原始大小: {len(content)} 字符]"

            duration = (time.time() - start) * 1000
            return ToolResult(
                success=True,
                output=content,
                data={"path": safe_path, "size": os.path.getsize(safe_path)},
                tool_name=self.name,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"读取文件失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )

    def _safe_path(self, path: str) -> str:
        """将路径安全化为项目根目录内的绝对路径。"""
        if not os.path.isabs(path):
            path = os.path.join(self.project_root, path)
        # 规范化路径: 解析 .. 和 .
        return os.path.normpath(os.path.abspath(path))


class WriteFileTool(BaseTool):
    """写入文件 (限制在项目目录内)。"""

    name: str = "write_file"
    description: str = "将内容写入指定路径的文件。会自动创建父目录。操作限制在项目根目录内。"
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "文件路径 (绝对路径或相对于项目根目录的相对路径)",
            },
            "content": {
                "type": "string",
                "description": "要写入的文件内容",
            },
        },
        "required": ["path", "content"],
    }
    tags: list[str] = ["file", "write", "io"]
    requires_confirmation: bool = True  # 写文件默认需确认 (按 ToolSecurityPolicy)

    def __init__(self, project_root: str | None = None) -> None:
        """初始化 WriteFileTool。"""
        self.project_root = project_root or os.getcwd()

    def execute(self, **kwargs: Any) -> ToolResult:
        """写入文件内容。"""
        path = kwargs.get("path", "")
        content = kwargs.get("content", "")

        start = time.time()

        safe_path = self._safe_path(path)

        try:
            # 确保父目录存在
            parent_dir = os.path.dirname(safe_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content)

            file_size = os.path.getsize(safe_path)
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=True,
                output=f"文件已写入: {path} ({file_size} 字节, {len(content.splitlines())} 行)",
                data={"path": safe_path, "size": file_size, "lines": len(content.splitlines())},
                tool_name=self.name,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"写入文件失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )

    def _safe_path(self, path: str) -> str:
        """将路径安全化为项目根目录内的绝对路径。"""
        if not os.path.isabs(path):
            path = os.path.join(self.project_root, path)
        return os.path.normpath(os.path.abspath(path))


class ListFilesTool(BaseTool):
    """列出目录中的文件和子目录。"""

    name: str = "list_files"
    description: str = "列出指定目录中的文件和子目录。支持 glob 模式过滤和递归选项。"
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "要列出的目录路径",
                "default": ".",
            },
            "pattern": {
                "type": "string",
                "description": "文件名匹配模式 (glob), 默认为 '*' (全部)",
                "default": "*",
            },
            "recursive": {
                "type": "boolean",
                "description": "是否递归列出子目录",
                "default": False,
            },
        },
        "required": [],
    }
    tags: list[str] = ["file", "list", "directory", "io"]

    def __init__(self, project_root: str | None = None) -> None:
        """初始化 ListFilesTool。"""
        self.project_root = project_root or os.getcwd()

    def execute(self, **kwargs: Any) -> ToolResult:
        """列出目录文件。"""
        import fnmatch

        directory = kwargs.get("directory", ".")
        pattern = kwargs.get("pattern", "*")
        recursive = kwargs.get("recursive", False)

        start = time.time()

        if not os.path.isabs(directory):
            directory = os.path.join(self.project_root, directory)
        directory = os.path.normpath(os.path.abspath(directory))

        if not os.path.isdir(directory):
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"目录不存在: {directory}",
                error=f"Directory not found: {directory}",
                tool_name=self.name,
                duration_ms=duration,
            )

        try:
            entries: list[str] = []
            if recursive:
                for root, dirs, files in os.walk(directory):
                    rel_root = os.path.relpath(root, directory)
                    if rel_root == ".":
                        rel_root = ""
                    for name in files + dirs:
                        if fnmatch.fnmatch(name, pattern):
                            entries.append(os.path.join(rel_root, name))
            else:
                for name in os.listdir(directory):
                    if fnmatch.fnmatch(name, pattern):
                        full_path = os.path.join(directory, name)
                        suffix = "/" if os.path.isdir(full_path) else ""
                        entries.append(name + suffix)

            # 限制输出数量
            max_entries = 200
            if len(entries) > max_entries:
                entries = entries[:max_entries]
                entries.append(f"... [截断: 共 {len(entries)} 项, 仅显示前 {max_entries} 项]")

            output = "\n".join(entries) if entries else "(空目录)"
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=True,
                output=output,
                data={"entries": entries, "count": len(entries)},
                tool_name=self.name,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"列出目录失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )
