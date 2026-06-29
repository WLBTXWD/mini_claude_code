"""REPL main loop — the interactive Read-Eval-Print Loop.

Extracted from main.py: repl_loop.
"""
from history import get_history_store
from llm.client import LLMClient
from core.agent import AgentLoop, AgentResult
from state.session import get_session

from .renderer import TerminalRenderer, format_tool_args
from .commands import handle_command
from .display import display_message_history
from .context import get_system_context


async def repl_loop():
    """REPL 主循环 (对应 REPL.tsx 的交互模式)"""
    print("=" * 60)
    print("  Mini Claude Code — Python Implementation")
    print("  Based on Claude Code 2.1.88 architecture analysis")
    print(f"  Model: {get_session().model}")
    print(f"  CWD: {get_session().cwd}")
    print("  Type 'exit' or 'quit' to exit, '/help' for commands")
    print("=" * 60)
    print()

    # 初始化 LLM 客户端和 Agent
    session = get_session()
    history = get_history_store()
    verify_ssl = False
    llm = LLMClient(
        api_key=session.api_key,
        base_url=session.base_url,
        model=session.model,
        verify_ssl=verify_ssl,
    )

    # 加载系统上下文
    system_context = get_system_context()
    if system_context:
        print(f"[System] Loaded context: {list(system_context.keys())}")
    print()

    session_messages: list[dict] = []

    while True:
        try:
            user_input = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # 处理命令
        if user_input.startswith("/"):
            handled = await handle_command(user_input, history)
            if handled == "exit":
                break
            if handled == "resume":
                # Session 已切换，重新加载上下文消息
                if history:
                    session_messages = history.get_messages_for_model(session.session_id)
                    print(f"\n[Switched to session {session.session_id[:8]}... "
                          f"— {len(session_messages)} messages]")
                    print("─" * 60)
                    display_message_history(session_messages)
                    print("─" * 60)
                    print()
                continue
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        print()  # 换行，准备显示助手回复

        # 运行 Agent (传入历史消息作为初始上下文)
        total_output = ""
        result = None
        renderer = TerminalRenderer()

        agent = AgentLoop(llm, history_store=history)
        async for event in agent.run(
            user_input,
            system_context,
            initial_messages=session_messages if session_messages else None,
        ):
            if isinstance(event, dict):
                if event.get("type") == "thinking":
                    renderer.render_thinking(event["content"])
                elif event.get("type") == "text":
                    chunk = event["content"]
                    total_output += chunk
                    renderer.render_text(chunk)

                elif event.get("type") == "tool_execution_start":
                    # 打印工具调用 — 与 display_message_history 一致
                    tool_calls = event.get("tool_calls", [])
                    for tc in tool_calls:
                        name = tc.get("name", "?")
                        raw_input = tc.get("input", {})
                        renderer.render_tool_use(name, raw_input)

                elif event.get("type") == "tool_result":
                    msg = event.get("message", {})
                    renderer.render_tool_result(str(msg.get("content", "")))

                elif event.get("type") == "turn_complete":
                    pass  # 不再打印 [Turn N complete]

                elif event.get("type") == "compact":
                    renderer.render_compact(event["message"])

            elif isinstance(event, AgentResult):
                result = event
                break

        renderer.close_block()
        print()
        if result:
            # 更新 session 消息 (从历史重新加载以获取最新消息)
            if history:
                session_messages = history.get_messages_for_model(session.session_id)
            print(f"[{getattr(result, 'reason', '?')}] "
                  f"turns: {getattr(result, 'turn_count', 0)}  |  "
                  f"tokens: {session.total_input_tokens} in / {session.total_output_tokens} out")
        print()
