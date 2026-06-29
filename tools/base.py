"""
工具基类 (对应 src/Tool.ts)

定义 Tool 接口契约：name, description, schema, call(),
is_concurrent_safe(), validate_input()
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """工具执行结果"""
    output: str = ""
    is_error: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class ToolUseContext:
    """工具执行上下文 (对应 src/Tool.ts 的 ToolUseContext)"""
    session_id: str
    cwd: str
    read_file_state: dict[str, Any] = field(default_factory=dict)
    abort_signal: bool = False
    set_abort: Optional[Callable] = None

    def abort(self):
        self.abort_signal = True


class Tool(ABC):
    """工具基类"""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: type[BaseModel],
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema

    def to_openai_schema(self) -> dict[str, Any]:
        """转换为 OpenAI tool schema"""
        schema = self.input_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }

    def validate_input(self, parsed_input: BaseModel, context: ToolUseContext) -> tuple[bool, str]:
        """验证输入 (子类可覆写)"""
        return True, ""

    def is_concurrent_safe(self, parsed_input: BaseModel) -> bool:
        """是否可并发执行 (子类可覆写)"""
        return True

    @abstractmethod
    async def call(
        self,
        input_data: BaseModel,
        context: ToolUseContext,
    ) -> ToolResult:
        """执行工具"""
        ...

    async def execute(
        self,
        raw_input: dict[str, Any],
        context: ToolUseContext,
    ) -> ToolResult:
        """完整执行流程：解析 → 验证 → 调用"""
        try:
            parsed = self.input_schema.model_validate(raw_input)
        except Exception as e:
            return ToolResult(
                output=f"Input validation error: {e}",
                is_error=True,
            )

        ok, msg = self.validate_input(parsed, context)
        if not ok:
            return ToolResult(output=msg, is_error=True)

        try:
            return await self.call(parsed, context)
        except Exception as e:
            return ToolResult(
                output=f"Tool execution error: {e}",
                is_error=True,
            )

    def map_tool_result_to_block(self, result: ToolResult, tool_use_id: str) -> dict[str, Any]:
        """映射工具结果到 API 期望的格式"""
        return {
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": result.output[:100000],  # 截断超大结果
        }
