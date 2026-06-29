"""搜索工具：Glob, Grep"""
import glob as glob_mod
import os
import re

from pydantic import BaseModel, Field

from .base import Tool, ToolResult, ToolUseContext


class GlobInput(BaseModel):
    pattern: str = Field(description="Glob pattern to match files")
    path: str = Field(default=".", description="Directory to search in")


class GrepInput(BaseModel):
    pattern: str = Field(description="Regular expression pattern to search for")
    path: str = Field(default=".", description="File or directory to search in")
    glob: str = Field(default="", description="Glob pattern to filter files")


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
