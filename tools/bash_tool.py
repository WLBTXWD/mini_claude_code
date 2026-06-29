"""Bash 工具 — 执行 Shell 命令"""
import asyncio

from pydantic import BaseModel, Field

from .base import Tool, ToolResult, ToolUseContext


class BashInput(BaseModel):
    command: str = Field(description="The shell command to execute")
    timeout: int = Field(default=120000, description="Timeout in milliseconds")
    description: str = Field(default="", description="Brief description of what this does")


class BashTool(Tool):
    def __init__(self):
        super().__init__(
            name="Bash",
            description="""Execute a shell command in the terminal.
IMPORTANT: Prefer dedicated tools (Read, Edit, Glob, Grep) over Bash when possible.
Use Bash for: running tests, installing dependencies, git operations, build commands.
Always provide a clear description of what the command does.
Use absolute paths. The working directory persists across calls.""",
            input_schema=BashInput,
        )

    def is_concurrent_safe(self, parsed_input: BashInput) -> bool:
        # 只读命令可并发
        return parsed_input.command.startswith(("ls ", "cat ", "head ", "tail ", "wc ", "grep ", "find ", "which "))

    async def call(self, input_data: BashInput, context: ToolUseContext) -> ToolResult:
        timeout_sec = input_data.timeout / 1000
        try:
            proc = await asyncio.create_subprocess_shell(
                input_data.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += "\n[stderr]\n" + stderr.decode("utf-8", errors="replace")
            if not output.strip():
                output = f"Command completed with exit code {proc.returncode} (no output)"

            return ToolResult(
                output=output[:50000],
                is_error=proc.returncode != 0,
                metadata={"exit_code": proc.returncode, "command": input_data.command},
            )
        except asyncio.TimeoutError:
            return ToolResult(
                output=f"Command timed out after {timeout_sec}s",
                is_error=True,
            )
