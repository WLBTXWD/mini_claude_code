"""
工具编排器 (对应 src/services/tools/toolOrchestration.ts)

负责工具执行的分区和调度：并发安全工具并行执行，非并发安全工具串行执行。
"""
import asyncio
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from .base import Tool, ToolResult, ToolUseContext
from .registry import find_tool_by_name


@dataclass
class MessageUpdate:
    """消息更新"""
    message: dict[str, Any] | None = None


class ToolOrchestrator:
    """工具编排器"""

    def __init__(self, max_concurrency: int = 10):
        self.max_concurrency = max_concurrency

    def partition_tool_calls(
        self,
        tool_use_blocks: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """
        分区工具调用：并发安全工具归入同一批次，非并发安全工具独占批次
        (对应 partitionToolCalls)
        """
        batches: list[list[dict[str, Any]]] = []
        current_batch: list[dict[str, Any]] = []

        for block in tool_use_blocks:
            tool_name = block["name"]
            tool = find_tool_by_name(tool_name)

            if tool is None:
                # 未知工具，单独批次
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                batches.append([block])
                continue

            try:
                input_model = tool.input_schema.model_validate(block["input"])
                is_safe = tool.is_concurrent_safe(input_model)
            except Exception:
                is_safe = False

            if is_safe:
                current_batch.append(block)
            else:
                # 非并发安全：关闭当前批次，创建独占批次
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                batches.append([block])

        if current_batch:
            batches.append(current_batch)

        return batches

    async def run_tools(
        self,
        tool_use_blocks: list[dict[str, Any]],
        context: ToolUseContext,
    ) -> AsyncGenerator[MessageUpdate, None]:
        """
        执行工具调用 (对应 runTools)
        分区后并发/串行执行
        """
        batches = self.partition_tool_calls(tool_use_blocks)

        for batch in batches:
            if len(batch) == 1:
                # 串行执行独占批次
                async for update in self._run_tool_serially(batch[0], context):
                    yield update
            else:
                # 并行执行并发批次
                semaphore = asyncio.Semaphore(self.max_concurrency)

                async def run_one(block: dict[str, Any]):
                    async with semaphore:
                        results = []
                        async for update in self._run_tool_serially(block, context):
                            results.append(update)
                        return results

                tasks = [run_one(block) for block in batch]
                all_results = await asyncio.gather(*tasks)
                for results in all_results:
                    for update in results:
                        yield update

    async def _run_tool_serially(
        self,
        block: dict[str, Any],
        context: ToolUseContext,
    ) -> AsyncGenerator[MessageUpdate, None]:
        """执行单个工具调用"""
        tool_name = block["name"]
        tool_use_id = block["id"]
        raw_input = block["input"]

        tool = find_tool_by_name(tool_name)
        if tool is None:
            yield MessageUpdate(message={
                "role": "tool",
                "tool_call_id": tool_use_id,
                "content": f"Tool not found: {tool_name}",
            })
            return

        result = await tool.execute(raw_input, context)
        yield MessageUpdate(
            message=tool.map_tool_result_to_block(result, tool_use_id),
        )
