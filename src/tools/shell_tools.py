"""
Shell 命令执行 Tool — 安全地执行系统命令。

安全机制:
- 命令白名单检查
- 危险命令模式检测
- 执行超时控制
- 输出截断
- requires_confirmation = True (危险操作需确认)
"""

import os
import re
import subprocess
import time
from typing import Any

from src.tools.base_tool import BaseTool, ToolResult


# 危险命令模式 (黑名单)
DANGEROUS_PATTERNS: list[str] = [
    r"rm\s+-rf\s+/",  # rm -rf /
    r"dd\s+if=",  # dd 磁盘操作
    r">\s*/dev/sd[a-z]",  # 写入磁盘设备
    r"mkfs\.",  # 格式化
    r":\(\)\s*\{\s*:\|:&\s*\};:",  # fork bomb
    r"chmod\s+777\s+/",  # 危险权限修改
    r"shutdown",  # 关机
    r"reboot",  # 重启
    r"wget.*\|.*sh",  # curl/wget 管道到 shell
    r"curl.*\|.*sh",
]


class RunShellTool(BaseTool):
    """在系统 Shell 中执行命令。"""

    name: str = "run_shell"
    description: str = (
        "在系统 Shell 中执行命令并返回输出。"
        "命令在子进程中执行, 带超时控制。"
        "危险命令会被自动检测并拒绝执行。"
    )
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 Shell 命令",
            },
            "timeout": {
                "type": "number",
                "description": "执行超时秒数, 默认 30 秒",
            },
            "working_dir": {
                "type": "string",
                "description": "工作目录, 默认为当前目录",
            },
        },
        "required": ["command"],
    }
    tags: list[str] = ["shell", "command", "run", "execute", "system"]
    requires_confirmation: bool = True  # Shell 命令默认需确认

    def __init__(
        self,
        allowed_commands: list[str] | None = None,
        project_root: str | None = None,
    ) -> None:
        """
        初始化 RunShellTool。

        Args:
            allowed_commands: 允许的命令白名单 (空 = 全部禁止, None = 全部允许)
            project_root: 项目根目录
        """
        self.allowed_commands = allowed_commands  # None = 全部允许
        self.project_root = project_root or os.getcwd()

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        执行 Shell 命令。

        Args:
            command: 要执行的 Shell 命令
            timeout: 执行超时秒数 (默认 30)
            working_dir: 工作目录

        Returns:
            ToolResult
        """
        command = kwargs.get("command", "")
        timeout = kwargs.get("timeout", 30.0)
        working_dir = kwargs.get("working_dir", self.project_root)

        start = time.time()

        # 安全检查: 危险命令检测
        danger_check = self._check_dangerous(command)
        if danger_check:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"命令被拒绝执行 (安全风险): {danger_check}",
                error=f"Blocked dangerous command: {danger_check}",
                tool_name=self.name,
                duration_ms=duration,
            )

        # 安全检查: 白名单检查
        if self.allowed_commands is not None:
            cmd_name = command.split()[0] if command.strip() else ""
            if cmd_name not in self.allowed_commands:
                duration = (time.time() - start) * 1000
                return ToolResult(
                    success=False,
                    output=f"命令 '{cmd_name}' 不在允许列表中。允许的命令: {self.allowed_commands}",
                    error=f"Command not in whitelist: {cmd_name}",
                    tool_name=self.name,
                    duration_ms=duration,
                )

        try:
            # 确定 Shell 类型
            if os.name == "nt":
                # Windows: 使用 cmd.exe
                shell_cmd = ["cmd.exe", "/c", command]
            else:
                # Unix: 使用 /bin/bash
                shell_cmd = ["/bin/bash", "-c", command]

            result = subprocess.run(
                shell_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
                env=os.environ.copy(),
            )

            # 合并 stdout 和 stderr
            output_parts: list[str] = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(f"[STDERR]\n{result.stderr}")

            output = "\n".join(output_parts) if output_parts else "(无输出)"

            # 截断过长输出
            max_chars = 10000
            if len(output) > max_chars:
                output = output[:max_chars] + f"\n\n... [输出截断, 原始长度: {len(output)} 字符]"

            duration = (time.time() - start) * 1000
            return ToolResult(
                success=result.returncode == 0,
                output=output,
                data={
                    "exit_code": result.returncode,
                    "stdout_len": len(result.stdout) if result.stdout else 0,
                    "stderr_len": len(result.stderr) if result.stderr else 0,
                },
                tool_name=self.name,
                duration_ms=duration,
            )

        except subprocess.TimeoutExpired:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"命令执行超时 (>{timeout}s): {command[:100]}",
                error=f"Command timeout after {timeout}s",
                tool_name=self.name,
                duration_ms=duration,
            )
        except Exception as e:
            duration = (time.time() - start) * 1000
            return ToolResult(
                success=False,
                output=f"命令执行失败: {e}",
                error=str(e),
                tool_name=self.name,
                duration_ms=duration,
            )

    def _check_dangerous(self, command: str) -> str | None:
        """
        检测危险命令模式。

        Returns:
            危险模式描述, 或 None (安全)
        """
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return f"检测到危险命令模式: {pattern}"
        return None
