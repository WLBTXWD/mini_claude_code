"""TodoWrite 工具 — 任务管理"""
from pydantic import BaseModel, Field

from .base import Tool, ToolResult, ToolUseContext


class TodoWriteInput(BaseModel):
    todos: str = Field(description="JSON string of todo items array")


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
