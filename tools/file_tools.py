"""文件操作工具：Read, Write, Edit"""
import os

from pydantic import BaseModel, Field

from .base import Tool, ToolResult, ToolUseContext


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
