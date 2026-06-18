"""
Agent Loop 核心 (对应 src/query.ts)

这是整个系统的"心脏"：turn-based 的无限循环
while True:
  1. 预处理(压缩检查)
  2. 调用模型(流式)
  3. 如果 tool_use → 执行工具 → continue
  4. 如果纯文本 → 返回结果

基于 AsyncGenerator 模式，yield 中间事件，return 最终状态。
"""
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal, Optional

from tool_orch import ToolOrchestrator, MessageUpdate
from tools import get_all_tools
from compact import ContextCompactor
from query_config import QueryConfig
from state import get_session


@dataclass
class AgentResult:
    """Agent 执行结果 (对应 Terminal)"""
    reason: Literal[
        "completed",
        "max_turns",
        "user_interrupted",
        "prompt_too_long",
        "model_error",
    ]
    error: Optional[str] = None
    turn_count: int = 0
    total_output: str = ""


@dataclass
class AgentState:
    """单轮迭代的不可变状态 (对应 query.ts 的 State)"""
    messages: list[dict[str, Any]] = field(default_factory=list)
    turn_count: int = 0
    total_output: str = ""
    tool_call_count: int = 0


class AgentLoop:
    """
    Agent 主循环 (对应 query() 函数)

    核心特征:
    - AsyncGenerator: yield 进度事件，return 最终结果
    - while True 循环：工具调用后自动 continue
    - 压缩集成：token 超限时自动压缩
    - 流式模型调用：实时输出 to 用户
    """

    def __init__(self, llm_client: Any):
        self.llm = llm_client
        self.orchestrator = ToolOrchestrator()
        self.compactor = ContextCompactor()
        self.session = get_session()

    async def run(
        self,
        user_message: str,
        system_context: Optional[dict[str, str]] = None,
    ) -> AsyncGenerator[Any, None]:
        """
        运行 Agent 循环

        Python 限制：async generator 不能 return value。
        因此最终结果通过 yield AgentResult(...) 返回，然后 bare return 退出。

        用法:
            async for event in agent.run("帮我写一个函数"):
                if isinstance(event, AgentResult):
                    print(f"Done: {event.reason}")
                    break
                elif isinstance(event, dict):
                    ...
        """
        config = QueryConfig(
            session_id=self.session.session_id,
            model=self.session.model,
            max_turns=self.session.max_turns,
            auto_compact_enabled=self.session.auto_compact_enabled,
        )

        # 初始状态
        state = AgentState(
            messages=[{"role": "user", "content": user_message}],
        )

        while True:
            # ================================================
            # 1. 预处理：自动压缩检查
            # ================================================
            if config.auto_compact_enabled and self.compactor.should_auto_compact(state.messages):
                compacted = self.compactor.compact_messages(state.messages)
                if compacted != state.messages:
                    yield {"type": "compact", "message": "Context automatically compacted"}
                    state.messages = compacted

            # ================================================
            # 2. 调用模型 (流式)
            # ================================================
            tools = get_all_tools()
            tool_schemas = [t.to_openai_schema() for t in tools]

            stream_content = ""
            tool_call_blocks: list[dict[str, Any]] = []
            final_event = None

            # 用于显示消息内容,避免发送给模型
            display_content = ""

            async for event in self.llm.chat_completion_stream(
                messages=state.messages,
                system_prompt=self._get_system_prompt(system_context),
                tools=tool_schemas,
                max_tokens=config.max_output_tokens,
            ):
                if event["type"] == "text_delta":
                    display_content += event["text"]
                    # 流式输出给用户
                    yield {"type": "text", "content": event["text"]}
                elif event["type"] == "final":
                    final_event = event
                    stream_content = event["content"]
                    tool_call_blocks = event["tool_calls"]

            if final_event is None:
                yield AgentResult(reason="model_error", error="No response from model")
                return

            # 更新 token 计数
            usage = final_event.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            if input_tokens:
                self.session.total_input_tokens += input_tokens
            if output_tokens:
                self.session.total_output_tokens += output_tokens

            # 添加到消息历史
            assistant_content = stream_content
            if tool_call_blocks:
                # 将 tool_calls 打包到 assistant message
                state.messages.append({
                    "role": "assistant",
                    "content": assistant_content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["input"]),
                            },
                        }
                        for tc in tool_call_blocks
                    ],
                })

                # ================================================
                # 3. 执行工具
                # ================================================
                yield {"type": "tool_execution_start", "count": len(tool_call_blocks)}

                from tool import ToolUseContext
                context = ToolUseContext(
                    session_id=config.session_id,
                    cwd=self.session.cwd,
                )

                async for update in self.orchestrator.run_tools(
                    tool_call_blocks, context
                ):
                    if update.message:
                        state.messages.append(update.message)
                        yield {"type": "tool_result", "message": update.message}

                state.turn_count += 1
                state.tool_call_count += len(tool_call_blocks)
                yield {"type": "turn_complete", "turn": state.turn_count}

                # 检查 max_turns
                if state.turn_count >= config.max_turns:
                    yield AgentResult(
                        reason="max_turns",
                        turn_count=state.turn_count,
                    )
                    return

                # continue 下一轮
                continue

            else:
                # ================================================
                # 4. 无工具调用 → 纯文本响应 → 完成
                # ================================================
                state.messages.append({
                    "role": "assistant",
                    "content": assistant_content,
                })
                state.turn_count += 1
                state.total_output = assistant_content

                self.session.total_turns += state.turn_count

                yield AgentResult(
                    reason="completed",
                    turn_count=state.turn_count,
                    total_output=assistant_content,
                )
                return

    def _get_system_prompt(
        self,
        system_context: Optional[dict[str, str]] = None,
    ) -> str | None:
        """获取系统提示"""
        from prompt import build_system_prompt
        from memory import MemorySystem

        memory = MemorySystem(self.session.project_root or self.session.cwd)
        memory_prompt = memory.load_memory_prompt()

        return build_system_prompt(
            cwd=self.session.cwd,
            model=self.session.model,
            memory_prompt=memory_prompt,
            system_context=system_context,
        )
