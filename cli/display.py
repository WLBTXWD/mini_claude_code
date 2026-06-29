"""Message history display for /resume command.

Extracted from main.py: _display_message_history.
"""
import json

from .renderer import TerminalRenderer


def display_message_history(messages: list[dict]):
    """在终端渲染消息历史 (对应 Claude Code 的 resume 消息展示)"""
    renderer = TerminalRenderer()
    for i, m in enumerate(messages):
        role = m.get("role", "")
        content = m.get("content", "")
        tool_calls = m.get("tool_calls", [])

        if role == "user":
            # 用户消息：显示原文
            text = content if isinstance(content, str) else str(content)
            if len(text) > 500:
                text = text[:500] + "..."
            renderer.render_user(text)
            if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
                print()
            continue

        elif role == "assistant":
            thinking = m.get("_thinking", "")
            if thinking and isinstance(thinking, str):
                t = thinking[:800]
                if len(thinking) > 800:
                    t += "..."
                renderer.render_thinking(t)

            if content and isinstance(content, str):
                c = content[:800]
                if len(content) > 800:
                    c += "..."
                renderer.render_text(c)

            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "?")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except Exception:
                    args = {}
                renderer.render_tool_use(name, args)

            renderer.close_block()
            if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
                print()
            continue

        elif role == "tool":
            result_text = content if isinstance(content, str) else str(content)
            renderer.render_tool_result(result_text)
            if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
                print()
            continue

        # 消息间空行（user 消息前加空行以分组）
        if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
            print()
