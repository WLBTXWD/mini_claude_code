"""
上下文压缩 (对应 src/services/compact/compact.ts + autoCompact.ts)

自动检测 token 超限并生成摘要式压缩。
"""
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CompactResult:
    """压缩结果"""
    summary: str
    pre_compact_message_count: int
    post_compact_message_count: int = 1


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


class ContextCompactor:
    """上下文压缩器"""

    def __init__(
        self,
        auto_compact_threshold: int = 80000,
        auto_compact_buffer: int = 13000,
    ):
        self.auto_compact_threshold = auto_compact_threshold
        self.auto_compact_buffer = auto_compact_buffer
        self.consecutive_failures = 0
        self.max_consecutive_failures = 3

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """粗略估算 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 3  # 约 3 字符/token
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(str(block.get("text", ""))) // 3
        return total

    def should_auto_compact(self, messages: list[dict[str, Any]]) -> bool:
        """是否需要自动压缩"""
        if self.consecutive_failures >= self.max_consecutive_failures:
            return False  # 断路器

        estimated = self.estimate_tokens(messages)
        threshold = self.auto_compact_threshold - self.auto_compact_buffer
        return estimated > threshold

    def compact_messages(
        self,
        messages: list[dict[str, Any]],
        preserve_last_n: int = 5,
    ) -> list[dict[str, Any]]:
        """简单截断式压缩（保留摘要 + 最近 N 条消息）"""
        if len(messages) <= preserve_last_n + 10:
            return messages  # 不够多，不压缩

        # 保留系统消息 + 最近的消息
        system_msgs = [m for m in messages if m.get("role") == "system"]
        recent_msgs = messages[-(preserve_last_n):]

        # 构建摘要
        summary = f"[Context compacted. Previous {len(messages) - preserve_last_n - len(system_msgs)} messages summarized.]"

        compacted = [
            *system_msgs,
            {"role": "user", "content": f"<compact-summary>\n{summary}\n</compact-summary>"},
            *recent_msgs,
        ]
        return compacted

    async def compact_with_llm(
        self,
        messages: list[dict[str, Any]],
        llm_call: Any,
    ) -> CompactResult | None:
        """使用 LLM 进行摘要式压缩"""
        if self.consecutive_failures >= self.max_consecutive_failures:
            return None

        # 提取用户和助手的关键消息
        conversation_text = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            conversation_text.append(f"[{role}]: {content}")

        full_text = "\n\n".join(conversation_text[-50:])  # 最多最近50条
        compact_prompt = f"{COMPACT_PROMPT}\n\nConversation:\n{full_text}"

        try:
            # 调用 LLM 生成摘要
            response = await llm_call([
                {"role": "user", "content": compact_prompt}
            ])
            summary = response if isinstance(response, str) else response.get("content", "")
            return CompactResult(
                summary=summary,
                pre_compact_message_count=len(messages),
            )
        except Exception:
            self.consecutive_failures += 1
            return None
