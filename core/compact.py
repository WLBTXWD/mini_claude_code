"""
上下文压缩 (对应 src/services/compact/compact.ts + autoCompact.ts)

自动检测 token 超限并生成摘要式压缩。
"""
from dataclasses import dataclass
import json
from typing import Any, Awaitable, Callable, Optional


@dataclass
class CompactResult:
    """压缩结果"""
    summary: str
    pre_compact_message_count: int
    post_compact_message_count: int
    pre_compact_token_count: int = 0
    post_compact_token_count: int = 0
    restored_file_count: int = 0


# 压缩提示 (简化版，对应 src/services/compact/prompt.ts)
COMPACT_PROMPT = """You are a conversation summarizer. Summarize the following conversation between an AI agent and a user.

<analysis>
Think about what's important to preserve for continuing the work.
</analysis>

<summary>
1. Primary Request and Intent: [The user's original request and overall goal]
2. Key Technical Concepts: [Important technical concepts, libraries, patterns]
3. Files and Code Sections: [Files that were read, edited, or written]
4. Errors and fixes: [Errors encountered and how they were fixed]
5. Problem Solving: [Problems solved and how]
6. All user messages: [Every message the user sent]
7. Pending Tasks: [Tasks not yet completed]
8. Current Work: [What was being done when conversation was cut]
9. Optional Next Step: [A single suggested next action]
</summary>"""


OLD_TOOL_RESULT_CLEARED = "[Old tool result content cleared]"


def _rough_tokens(text: str) -> int:
    """Conservative rough token estimate."""
    return max(1, len(text) // 3) if text else 0


class ContextCompactor:
    """上下文压缩器"""

    def __init__(
        self,
        auto_compact_threshold: int = 80000,
        auto_compact_buffer: int = 13000,
        preserve_last_n: int = 6,
        keep_recent_tool_results: int = 5,
        tool_result_clear_threshold_chars: int = 2000,
        max_restore_files: int = 5,
        max_restore_file_tokens: int = 5000,
    ):
        self.auto_compact_threshold = auto_compact_threshold
        self.auto_compact_buffer = auto_compact_buffer
        self.preserve_last_n = preserve_last_n
        self.keep_recent_tool_results = keep_recent_tool_results
        self.tool_result_clear_threshold_chars = tool_result_clear_threshold_chars
        self.max_restore_files = max_restore_files
        self.max_restore_file_tokens = max_restore_file_tokens
        self.consecutive_failures = 0
        self.max_consecutive_failures = 3

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """粗略估算 token 数"""
        return sum(self._estimate_message_tokens(msg) for msg in messages)

    def _estimate_message_tokens(self, msg: dict[str, Any]) -> int:
        total = _rough_tokens(str(msg.get("role", "")))
        total += self._estimate_content_tokens(msg.get("content", ""))

        if msg.get("role") == "tool":
            total += _rough_tokens(str(msg.get("tool_call_id", "")))

        for call in msg.get("tool_calls", []) or []:
            total += _rough_tokens(str(call.get("id", "")))
            function = call.get("function", {})
            total += _rough_tokens(str(function.get("name", "")))
            total += _rough_tokens(str(function.get("arguments", "")))

        return total

    def _estimate_content_tokens(self, content: Any) -> int:
        if content is None:
            return 0
        if isinstance(content, str):
            return _rough_tokens(content)
        if isinstance(content, list):
            total = 0
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        total += _rough_tokens(str(block.get("text", "")))
                    elif "content" in block:
                        total += self._estimate_content_tokens(block.get("content"))
                    else:
                        total += _rough_tokens(json.dumps(block, ensure_ascii=False))
                else:
                    total += _rough_tokens(str(block))
            return total
        if isinstance(content, dict):
            return _rough_tokens(json.dumps(content, ensure_ascii=False))
        return _rough_tokens(str(content))

    def should_auto_compact(self, messages: list[dict[str, Any]]) -> bool:
        """是否需要自动压缩"""
        if self.consecutive_failures >= self.max_consecutive_failures:
            return False  # 断路器

        estimated = self.estimate_tokens(messages)
        threshold = self.auto_compact_threshold - self.auto_compact_buffer
        return estimated > threshold

    def microcompact_tool_results(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        """Clear older large tool results while preserving recent ones."""
        tool_indexes = [
            idx for idx, msg in enumerate(messages)
            if msg.get("role") == "tool"
        ]
        keep_indexes = set(tool_indexes[-self.keep_recent_tool_results:])
        cleared = 0
        compacted: list[dict[str, Any]] = []

        for idx, msg in enumerate(messages):
            if idx not in tool_indexes or idx in keep_indexes:
                compacted.append(msg)
                continue

            content = msg.get("content", "")
            if (
                isinstance(content, str)
                and content != OLD_TOOL_RESULT_CLEARED
                and len(content) >= self.tool_result_clear_threshold_chars
            ):
                next_msg = dict(msg)
                next_msg["content"] = OLD_TOOL_RESULT_CLEARED
                compacted.append(next_msg)
                cleared += 1
            else:
                compacted.append(msg)

        return compacted, cleared

    async def compact_with_llm_to_messages(
        self,
        messages: list[dict[str, Any]],
        llm_call: Callable[[list[dict[str, Any]]], Awaitable[Any]],
        read_file_state: Optional[dict[str, Any]] = None,
    ) -> tuple[list[dict[str, Any]], CompactResult] | None:
        """Generate a compact summary and return model-ready post-compact messages."""
        if self.consecutive_failures >= self.max_consecutive_failures:
            return None
        if len(messages) <= self.preserve_last_n:
            return None

        pre_tokens = self.estimate_tokens(messages)
        recent_msgs = [dict(msg) for msg in messages[-self.preserve_last_n:]]
        summary_input = messages[:-self.preserve_last_n]
        full_text = self._format_conversation(summary_input)
        compact_prompt = f"{COMPACT_PROMPT}\n\nConversation:\n{full_text}"

        try:
            response = await llm_call([
                {"role": "user", "content": compact_prompt}
            ])
            summary = self._extract_summary(response)
            if not summary:
                raise ValueError("Compaction returned an empty summary")

            compacted = [
                self.create_summary_message(summary),
                *self.create_file_restore_messages(read_file_state or {}),
                *recent_msgs,
            ]
            self.consecutive_failures = 0
            result = CompactResult(
                summary=summary,
                pre_compact_message_count=len(messages),
                post_compact_message_count=len(compacted),
                pre_compact_token_count=pre_tokens,
                post_compact_token_count=self.estimate_tokens(compacted),
                restored_file_count=len(compacted) - 1 - len(recent_msgs),
            )
            return compacted, result
        except Exception:
            self.consecutive_failures += 1
            return None

    def compact_messages(
        self,
        messages: list[dict[str, Any]],
        preserve_last_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback placeholder compaction kept for compatibility."""
        preserve = preserve_last_n or self.preserve_last_n
        if len(messages) <= preserve + 10:
            return messages

        recent_msgs = messages[-preserve:]
        summary = (
            f"[Context compacted. Previous {len(messages) - preserve} "
            "messages summarized.]"
        )
        return [
            self.create_summary_message(summary),
            *recent_msgs,
        ]

    def _format_conversation(self, messages: list[dict[str, Any]]) -> str:
        conversation_text = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = self._stringify_content(msg.get("content", ""))
            if msg.get("role") == "tool":
                role = f"tool:{msg.get('tool_call_id', '')}"
            if msg.get("tool_calls"):
                content = (
                    f"{content}\nTool calls: "
                    f"{json.dumps(msg.get('tool_calls'), ensure_ascii=False)}"
                ).strip()
            conversation_text.append(f"[{role}]: {content}")
        return "\n\n".join(conversation_text[-80:])

    def _stringify_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text") or block.get("content") or block))
                else:
                    parts.append(str(block))
            return "\n".join(parts)
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        return str(content)

    def _extract_summary(self, response: Any) -> str:
        if isinstance(response, str):
            return response.strip()
        if isinstance(response, dict):
            content = response.get("content", "")
            if isinstance(content, str):
                return content.strip()
        return str(response).strip() if response else ""

    def create_summary_message(self, summary: str) -> dict[str, Any]:
        return {
            "role": "user",
            "content": f"<compact-summary>\n{summary}\n</compact-summary>",
        }

    def create_file_restore_messages(
        self,
        read_file_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Create post-compact file context messages from recent Read tool state."""
        if not read_file_state:
            return []

        items = sorted(
            read_file_state.items(),
            key=lambda item: item[1].get("timestamp", 0) if isinstance(item[1], dict) else 0,
            reverse=True,
        )[:self.max_restore_files]

        messages = []
        for path, state in items:
            if not isinstance(state, dict):
                continue
            content = state.get("content") or state.get("content_preview") or ""
            if not content:
                continue
            max_chars = self.max_restore_file_tokens * 3
            if len(content) > max_chars:
                content = content[:max_chars] + "\n[File context truncated after compaction]"
            messages.append({
                "role": "user",
                "content": (
                    "<system-reminder>\n"
                    "Recent file context restored after compaction.\n"
                    f"File: {path}\n\n{content}\n"
                    "</system-reminder>"
                ),
            })
        return messages
