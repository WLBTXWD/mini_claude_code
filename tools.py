"""
工具注册表 (对应 src/tools.ts 和具体工具实现)

内置工具：Bash, FileRead, FileWrite, FileEdit, Glob, Grep, WebFetch, TodoWrite
"""
import asyncio
import glob as glob_mod
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from tool import Tool, ToolResult, ToolUseContext


# ============================================================
# 输入 Schema 定义
# ============================================================

class BashInput(BaseModel):
    command: str = Field(description="The shell command to execute")
    timeout: int = Field(default=120000, description="Timeout in milliseconds")
    description: str = Field(default="", description="Brief description of what this does")


class FileReadInput(BaseModel):
    file_path: str = Field(description="Absolute path to the file to read")
    offset: int = Field(default=0, description="Line offset to start reading from")
    limit: int = Field(default=2000, description="Max number of lines to read")


class FileWriteInput(BaseModel):
    file_path: str = Field(description="Absolute path to the file to write")
    content: str = Field(description="Content to write")


class FileEditInput(BaseModel):
    file_path: str = Field(description="Absolute path to the file to edit")
    old_string: str = Field(description="Text to replace")
    new_string: str = Field(description="Replacement text")
    replace_all: bool = Field(default=False, description="Replace all occurrences")


class GlobInput(BaseModel):
    pattern: str = Field(description="Glob pattern to match files")
    path: str = Field(default=".", description="Directory to search in")


class GrepInput(BaseModel):
    pattern: str = Field(description="Regular expression pattern to search for")
    path: str = Field(default=".", description="File or directory to search in")
    glob: str = Field(default="", description="Glob pattern to filter files")


class WebFetchInput(BaseModel):
    url: str = Field(description="URL to fetch content from")
    prompt: str = Field(default="", description="Prompt to run on the fetched content")


class TodoWriteInput(BaseModel):
    todos: str = Field(description="JSON string of todo items array")


# ============================================================
# 工具实现
# ============================================================

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


class FileReadTool(Tool):
    def __init__(self):
        super().__init__(
            name="Read",
            description="""Reads a file from the local filesystem.
file_path must be an absolute path.
Reads up to 2000 lines by default. Use offset/limit for large files.
Results show line numbers starting at 1.""",
            input_schema=FileReadInput,
        )

    async def call(self, input_data: FileReadInput, context: ToolUseContext) -> ToolResult:
        path = input_data.file_path
        if not os.path.isabs(path):
            path = os.path.join(context.cwd, path)

        if not os.path.exists(path):
            return ToolResult(output=f"File not found: {path}", is_error=True)

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            if input_data.offset > 0:
                lines = lines[input_data.offset:]
            if len(lines) > input_data.limit:
                lines = lines[:input_data.limit]
                truncated = True
            else:
                truncated = False

            output = "".join(f"{i+1+input_data.offset}\t{line}" for i, line in enumerate(lines))
            if truncated:
                output += f"\n... (truncated, {len(lines)} lines shown)"

            # 更新读取状态
            context.read_file_state[path] = {
                "mtime": os.path.getmtime(path),
                "content_preview": output[:1000],
            }

            return ToolResult(output=output[:50000])
        except Exception as e:
            return ToolResult(output=f"Error reading file: {e}", is_error=True)


class FileWriteTool(Tool):
    def __init__(self):
        super().__init__(
            name="Write",
            description="""Writes a file to the local filesystem, overwriting if one exists.
Use for: creating new files, or fully replacing file contents.
For partial changes, use Edit instead.
file_path must be an absolute path.""",
            input_schema=FileWriteInput,
        )

    def is_concurrent_safe(self, parsed_input: FileWriteInput) -> bool:
        return False  # 写操作不能并发

    async def call(self, input_data: FileWriteInput, context: ToolUseContext) -> ToolResult:
        path = input_data.file_path
        if not os.path.isabs(path):
            path = os.path.join(context.cwd, path)

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(input_data.content)
            return ToolResult(output=f"File written successfully: {path}")
        except Exception as e:
            return ToolResult(output=f"Error writing file: {e}", is_error=True)


class FileEditTool(Tool):
    def __init__(self):
        super().__init__(
            name="Edit",
            description="""Performs exact string replacement in a file.
You must Read the file before editing.
old_string must match the file exactly, including indentation.
Use replace_all: true to replace every occurrence.""",
            input_schema=FileEditInput,
        )

    def is_concurrent_safe(self, parsed_input: FileEditInput) -> bool:
        return False  # 编辑不能并发

    async def call(self, input_data: FileEditInput, context: ToolUseContext) -> ToolResult:
        path = input_data.file_path
        if not os.path.isabs(path):
            path = os.path.join(context.cwd, path)

        if not os.path.exists(path):
            return ToolResult(output=f"File not found: {path}", is_error=True)

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            if input_data.replace_all:
                new_content = content.replace(input_data.old_string, input_data.new_string)
                count = content.count(input_data.old_string)
            else:
                count = content.count(input_data.old_string)
                if count == 0:
                    return ToolResult(
                        output=f"old_string not found in file. Did you Read the file first?",
                        is_error=True,
                    )
                if count > 1:
                    return ToolResult(
                        output=f"old_string found {count} times. Use replace_all: true or make old_string more specific.",
                        is_error=True,
                    )
                new_content = content.replace(input_data.old_string, input_data.new_string, 1)

            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)

            return ToolResult(output=f"File edited successfully: {path} ({count} occurrence(s))")
        except Exception as e:
            return ToolResult(output=f"Error editing file: {e}", is_error=True)


class GlobTool(Tool):
    def __init__(self):
        super().__init__(
            name="Glob",
            description="""Fast file pattern matching. Supports glob patterns like "**/*.js".
Prefer Glob over `find` or `ls` for file searches.
Returns matching file paths sorted by modification time.""",
            input_schema=GlobInput,
        )

    async def call(self, input_data: GlobInput, context: ToolUseContext) -> ToolResult:
        search_path = input_data.path
        if not os.path.isabs(search_path):
            search_path = os.path.join(context.cwd, search_path)

        try:
            matches = glob_mod.glob(input_data.pattern, root_dir=search_path, recursive=True)
            matches = sorted(matches, key=lambda f: os.path.getmtime(os.path.join(search_path, f)), reverse=True)
            output = "\n".join(matches[:500])
            if not output:
                output = "No files found"
            return ToolResult(output=output[:50000])
        except Exception as e:
            return ToolResult(output=f"Error searching: {e}", is_error=True)


class GrepTool(Tool):
    def __init__(self):
        super().__init__(
            name="Grep",
            description="""Content search using regex patterns.
Prefer Grep over `grep`/`rg` in Bash.
Supports full regex syntax. Filter with glob pattern.""",
            input_schema=GrepInput,
        )

    async def call(self, input_data: GrepInput, context: ToolUseContext) -> ToolResult:
        search_path = input_data.path
        if not os.path.isabs(search_path):
            search_path = os.path.join(context.cwd, search_path)

        try:
            regex = re.compile(input_data.pattern)
            results = []

            if os.path.isfile(search_path):
                files_to_search = [search_path]
            else:
                glob_filter = input_data.glob or "**/*"
                files_to_search = []
                for root, _, files in os.walk(search_path):
                    for f in files:
                        filepath = os.path.join(root, f)
                        relpath = os.path.relpath(filepath, search_path)
                        # 简单 glob 匹配
                        if glob_mod.fnmatch.fnmatch(relpath, glob_filter) or glob_mod.fnmatch.fnmatch(f, glob_filter):
                            files_to_search.append(filepath)

            for filepath in files_to_search[:100]:
                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append(f"{filepath}:{i}: {line.rstrip()}")
                except Exception:
                    continue

            output = "\n".join(results[:250])
            if len(results) > 250:
                output += f"\n... ({len(results)} total matches, showing first 250)"
            if not output:
                output = "No matches found"
            return ToolResult(output=output[:50000])
        except re.error as e:
            return ToolResult(output=f"Invalid regex pattern: {e}", is_error=True)


class WebFetchTool(Tool):
    def __init__(self):
        super().__init__(
            name="WebFetch",
            description="""Fetches a URL and returns the content.
HTTP is upgraded to HTTPS.
Use for: reading documentation, API responses, web content.""",
            input_schema=WebFetchInput,
        )

    async def call(self, input_data: WebFetchInput, context: ToolUseContext) -> ToolResult:
        url = input_data.url
        if url.startswith("http://"):
            url = "https://" + url[7:]

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "MiniClaudeCode/1.0"})
                resp.raise_for_status()

                content = resp.text[:50000]
                return ToolResult(
                    output=content,
                    metadata={"status_code": resp.status_code, "url": str(resp.url)},
                )
        except Exception as e:
            return ToolResult(output=f"Error fetching URL: {e}", is_error=True)


class TodoWriteTool(Tool):
    def __init__(self):
        super().__init__(
            name="TodoWrite",
            description="""Use this to create and manage a structured task list.
Use proactively for complex multi-step tasks.
Each task has: subject (title), status (pending/in_progress/completed), description.""",
            input_schema=TodoWriteInput,
        )

    async def call(self, input_data: TodoWriteInput, context: ToolUseContext) -> ToolResult:
        return ToolResult(output=f"Tasks updated:\n{input_data.todos}")


# ============================================================
# 工具注册表
# ============================================================

_all_tools: list[Tool] = [
    BashTool(),
    FileReadTool(),
    FileWriteTool(),
    FileEditTool(),
    GlobTool(),
    GrepTool(),
    WebFetchTool(),
    TodoWriteTool(),
]


def get_all_tools() -> list[Tool]:
    """返回所有可用工具"""
    return _all_tools


def find_tool_by_name(name: str) -> Tool | None:
    for tool in _all_tools:
        if tool.name == name:
            return tool
    return None
