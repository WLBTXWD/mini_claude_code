"""
CLI 入口 (对应 src/main.tsx + entrypoints/cli.tsx)

解析参数，初始化会话，启动 REPL。
"""
import argparse
import asyncio
import os
import sys
from typing import Optional

from llm import LLMClient
from agent import AgentLoop, AgentResult
from state import get_session, reset_session
from history import get_history_store, HistoryStore


# ============================================================
# 配置
# ============================================================

def load_config():
    """加载配置（从环境变量）"""
    session = get_session()

    session.api_key = os.environ.get(
        "DEEPSEEK_API_KEY",
        os.environ.get("DEEPSEEK_API_KEY", ""),
    )
    if not session.api_key:
        print("Error: Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable")
        sys.exit(1)

    session.base_url = os.environ.get(
        "DEEPSEEK_BASE_URL",
        os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    session.model = os.environ.get(
        "DEEPSEEK_MODEL",
        os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    session.cwd = os.getcwd()
    session.project_root = _find_project_root(session.cwd)

    # 可选的 max_turns 控制
    max_turns = os.environ.get("MAX_TURNS", "10")
    if max_turns.isdigit():
        session.max_turns = int(max_turns)


def _find_project_root(start_path: str) -> str:
    """查找项目根目录（包含 .git 或 .mini_claude_code 的目录）"""
    current = os.path.abspath(start_path)
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, ".git")):
            return current
        if os.path.exists(os.path.join(current, ".mini_claude_code")):
            return current
        current = os.path.dirname(current)
    return start_path


# ============================================================
# REPL 主循环
# ============================================================

async def repl_loop(history: HistoryStore | None = None):
    """REPL 主循环 (对应 REPL.tsx 的交互模式)"""
    print("=" * 60)
    print("  Mini Claude Code — Python Implementation")
    print("  Based on Claude Code 2.1.88 architecture analysis")
    print(f"  Model: {get_session().model}")
    print(f"  CWD: {get_session().cwd}")
    if history:
        print(f"  Session: {get_session().session_id[:8]}...")
    print("  Type 'exit' or 'quit' to exit, '/help' for commands")
    print("=" * 60)
    print()

    # 初始化 LLM 客户端和 Agent
    session = get_session()
    verify_ssl = False
    llm = LLMClient(
        api_key=session.api_key,
        base_url=session.base_url,
        model=session.model,
        verify_ssl=verify_ssl,
    )
    agent = AgentLoop(llm, history_store=history)

    # 加载系统上下文
    system_context = _get_system_context()
    if system_context:
        print(f"[System] Loaded context: {list(system_context.keys())}")
    print()

    # 从当前 session 历史加载上下文消息 (用于跨轮次上下文)
    session_messages: list[dict] = []
    if history:
        session_messages = history.get_messages_for_model(session.session_id)

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
            handled = await _handle_command(user_input, agent, history)
            if handled == "exit":
                break
            if handled == "resume":
                # Session 已切换，重新加载上下文消息
                if history:
                    session_messages = history.get_messages_for_model(session.session_id)
                    print(f"\n[Switched to session {session.session_id[:8]}... "
                          f"— {len(session_messages)} messages]")
                    print("─" * 60)
                    _display_message_history(session_messages)
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
        at_line_start = True        # 下一个 text 增量需要前缀
        is_first_line = True        # 首行用 Claude: 前缀，续行用空格缩进

        async for event in agent.run(
            user_input,
            system_context,
            initial_messages=session_messages if session_messages else None,
        ):
            if isinstance(event, dict):
                if event.get("type") == "text":
                    chunk = event["content"]
                    total_output += chunk

                    while chunk:
                        if at_line_start:
                            if is_first_line:
                                print("\033[1;32mClaude:\033[0m ", end="", flush=True)
                                is_first_line = False
                            else:
                                # 续行缩进 10 空格，与 _display_message_history 一致
                                print(" " * 10, end="", flush=True)
                            at_line_start = False

                        nl = chunk.find("\n")
                        if nl == -1:
                            print(chunk, end="", flush=True)
                            break
                        else:
                            before = chunk[:nl + 1]
                            print(before, end="", flush=True)
                            at_line_start = True
                            chunk = chunk[nl + 1:]

                elif event.get("type") == "tool_execution_start":
                    # 打印工具调用 — 与 _display_message_history 一致
                    tool_calls = event.get("tool_calls", [])
                    for tc in tool_calls:
                        name = tc.get("name", "?")
                        raw_input = tc.get("input", {})
                        parts = []
                        for k, v in list(raw_input.items())[:3]:
                            vs = str(v)
                            if "\n" in vs:
                                parts.append(f"{k}=\n{' ' * 16}{vs.replace(chr(10), chr(10) + ' ' * 16)}")
                            else:
                                parts.append(f"{k}={vs}")
                        args_str = ", ".join(parts)
                        if len(args_str) > 300:
                            args_str = args_str[:300] + "..."
                        print(f"\n  \033[1;33m[Tool]\033[0m {name}({args_str})")
                    at_line_start = True  # 工具调用后下一行 text 需要前缀

                elif event.get("type") == "tool_result":
                    msg = event.get("message", {})
                    result_text = str(msg.get("content", ""))
                    result_len = len(result_text)
                    if result_text.startswith("Error") or result_text.startswith("Tool execution error"):
                        brief = result_text[:80].replace("\n", " ")
                        print(f"  \033[0;31m  -> [error]\033[0m {brief}")
                    elif result_len == 0:
                        print(f"  \033[0;34m  -> [empty]\033[0m")
                    else:
                        print(f"  \033[0;34m  -> [ok, {result_len} chars]\033[0m")
                    at_line_start = True

                elif event.get("type") == "turn_complete":
                    pass  # 不再打印 [Turn N complete]

                elif event.get("type") == "compact":
                    print(f"\n  [{event['message']}]")
                    at_line_start = True

            elif isinstance(event, AgentResult):
                result = event
                break

        print()
        if result:
            # 更新 session 消息 (从历史重新加载以获取最新消息)
            if history:
                session_messages = history.get_messages_for_model(session.session_id)
            print(f"[{getattr(result, 'reason', '?')}] "
                  f"turns: {getattr(result, 'turn_count', 0)}  |  "
                  f"tokens: {session.total_input_tokens} in / {session.total_output_tokens} out")
        print()


async def _handle_command(cmd: str, agent: AgentLoop, history: HistoryStore | None = None) -> Optional[str]:
    """处理斜杠命令"""
    parts = cmd.split()
    command = parts[0].lower()

    if command in ("/exit", "/quit"):
        if history:
            history.flush_all()
        print("Goodbye!")
        return "exit"

    elif command == "/help":
        print("""
Available commands:
  /help          - Show this help
  /clear         - Clear conversation and reset session
  /resume [id]   - Resume a previous session (list if no id)
  /compact       - Manually compact conversation context
  /memory        - Show memory directory and saved sessions
  /model <name>  - Switch model (next session)
  /cost          - Show token usage and cost
  /exit          - Exit
""")
    elif command == "/clear":
        session = get_session()
        old_id = session.session_id
        if history:
            history.flush(old_id)
        reset_session()
        load_config()
        if history:
            history.reset_tail()
        print(f"Session cleared. Previous session saved as {old_id[:8]}...")
    elif command == "/resume":
        if not history:
            print("History system not available.")
            return None
        sessions = history.list_sessions()
        if not sessions:
            print("No saved sessions found.")
            return None

        target_id: Optional[str] = None
        if len(parts) > 1:
            # /resume <sessionId> — 直接恢复
            search = parts[1]
            # 支持短 UUID 前缀匹配
            matches = [s for s in sessions if s['sessionId'].startswith(search)]
            if len(matches) == 1:
                target_id = matches[0]['sessionId']
            elif len(matches) > 1:
                print(f"Ambiguous prefix '{search}'. Matching sessions:")
                for m in matches:
                    print(f"  {m['sessionId'][:36]}  {m['messageCount']} msgs  {m['lastMessage'][:60]}")
                return None
            else:
                print(f"No session found with id starting with '{search}'.")
                return None
        else:
            # /resume 无参数 — 列出会话让用户选择
            print(f"{'#':>3}  {'Session ID':<38} {'Msgs':>5}  {'Preview'}")
            print("-" * 85)
            for i, s in enumerate(sessions[:20]):
                sid = s['sessionId'][:36]
                count = s['messageCount']
                preview = s['lastMessage'][:50]
                # 标记当前 session
                marker = " <-- current" if s['sessionId'] == get_session().session_id else ""
                print(f"{i+1:>3}  {sid:<38} {count:>5}  {preview}{marker}")
            print()
            try:
                choice = input("Enter session number (or Enter to cancel): ").strip()
            except (KeyboardInterrupt, EOFError):
                return None
            if not choice:
                return None
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(sessions):
                    target_id = sessions[idx]['sessionId']
                else:
                    print(f"Invalid number. Choose 1-{len(sessions)}.")
                    return None
            else:
                print("Invalid input.")
                return None

        if not target_id:
            return None

        # 不能 resume 当前 session
        if target_id == get_session().session_id:
            print("Already in this session.")
            return None

        # 切换 session
        old_id = get_session().session_id
        if history:
            history.flush(old_id)
        get_session().session_id = target_id
        if history:
            history.init_tail(target_id)
        print(f"Switched from {old_id[:8]}... to {target_id[:8]}...")
        print(f"({history.load_session(target_id).__len__()} messages loaded)")
        return "resume"
    elif command == "/compact":
        print("Compacting context...")
        # compaction is handled automatically by agent loop
        print("Context will be compacted automatically when needed.")
    elif command == "/memory":
        from memory import MemorySystem
        session = get_session()
        mem = MemorySystem(session.project_root or session.cwd)
        mem.ensure_memory_dir()
        print(f"Memory directory: {mem.memory_dir}")
        memories = mem.scan_memories()
        if memories:
            print(f"\n{len(memories)} memories:")
            print(mem.format_memory_manifest(memories))
        else:
            print("No memories found.")
        # 同时显示会话历史
        if history:
            sessions = history.list_sessions()
            if sessions:
                print(f"\n--- Saved Sessions ({len(sessions)} total) ---")
                for s in sessions[:5]:
                    sid = s['sessionId'][:8]
                    count = s['messageCount']
                    preview = s['lastMessage'][:80]
                    print(f"  {sid}...  {count} msgs  |  {preview}")
    elif command == "/cost":
        session = get_session()
        print(f"Input tokens:  {session.total_input_tokens:,}")
        print(f"Output tokens: {session.total_output_tokens:,}")
        print(f"Total turns:   {session.total_turns}")
        print(f"Model:         {session.model}")
    elif command == "/model" and len(parts) > 1:
        session = get_session()
        session.model = parts[1]
        print(f"Model set to: {session.model}")
    else:
        print(f"Unknown command: {command}")

    return None


def _display_message_history(messages: list[dict]):
    """在终端渲染消息历史 (对应 Claude Code 的 resume 消息展示)"""
    for i, m in enumerate(messages):
        role = m.get("role", "")
        content = m.get("content", "")
        tool_calls = m.get("tool_calls", [])

        if role == "user":
            # 用户消息：显示原文
            text = content if isinstance(content, str) else str(content)
            if len(text) > 500:
                text = text[:500] + "..."
            # 多行缩进对齐
            for li, line in enumerate(text.split("\n")):
                if li == 0:
                    print(f"  \033[1;36mYou:\033[0m  {line}")
                else:
                    print(f"          {line}")

        elif role == "assistant":
            # Assistant 消息：显示文本 + tool_calls
            if content and isinstance(content, str):
                c = content[:800]
                if len(content) > 800:
                    c += "..."
                for li, line in enumerate(c.split("\n")):
                    if li == 0:
                        print(f"  \033[1;32mClaude:\033[0m {line}")
                    else:
                        print(f"          {line}")
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "?")
                    try:
                        import json
                        args = json.loads(func.get("arguments", "{}"))
                    except Exception:
                        args = {}
                    # 完整展示参数，多行值也做缩进
                    parts = []
                    for k, v in list(args.items())[:3]:
                        vs = str(v)
                        if "\n" in vs:
                            # 多行值：key 占一行，值缩进在后续行
                            parts.append(f"{k}=\n{' ' * 16}{vs.replace(chr(10), chr(10) + ' ' * 16)}")
                        else:
                            parts.append(f"{k}={vs}")
                    args_str = ", ".join(parts)
                    # 工具调用行本身可能很长，截断到 300 字符
                    if len(args_str) > 300:
                        args_str = args_str[:300] + "..."
                    print(f"  \033[1;33m[Tool]\033[0m {name}({args_str})")

        elif role == "tool":
            # 工具结果 → 紧凑状态标记，不展示完整内容
            result_text = content if isinstance(content, str) else str(content)
            result_len = len(result_text)

            # 分类：错误 / 文件创建 / 空结果 / 普通成功
            if result_text.startswith("Error") or result_text.startswith("Tool execution error"):
                # 错误 — 保留前 80 字符的错误信息
                brief = result_text[:80].replace("\n", " ")
                print(f"  \033[0;31m  -> [error]\033[0m {brief}")
            elif result_len == 0:
                print(f"  \033[0;34m  -> [empty]\033[0m")
            else:
                # 成功 — 只显示长度，不显示内容
                print(f"  \033[0;34m  -> [ok, {result_len} chars]\033[0m")

        # 消息间空行（user 消息前加空行以分组）
        if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
            print()


def _get_system_context() -> dict[str, str]:
    """获取系统上下文 (对应 src/context.ts)"""
    context = {}

    # Git 状态
    try:
        import subprocess
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            context["git_branch"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            changed = len([l for l in result.stdout.strip().split("\n") if l])
            if changed > 0:
                context["git_changes"] = f"{changed} file(s) modified"
    except Exception:
        pass

    # CLAUDE.md / README
    for fname in ["CLAUDE.md", "README.md"]:
        path = os.path.join(get_session().cwd, fname)
        if os.path.exists(path):
            context[f"has_{fname.lower().replace('.', '_')}"] = "yes"
            break

    # Platform
    context["platform"] = sys.platform
    context["date"] = __import__('datetime').date.today().isoformat()

    return context


# ============================================================
# CLI 辅助
# ============================================================

def _list_sessions_cmd(history: HistoryStore):
    """列出所有历史会话"""
    sessions = history.list_sessions()
    if not sessions:
        print("No saved sessions found.")
        return
    print(f"{'Session ID':<38} {'Msgs':>5}  {'Last Updated':<22}  Preview")
    print("-" * 100)
    for s in sessions:
        sid = s['sessionId'][:36]
        count = s['messageCount']
        ts = s['lastTimestamp'][:19].replace("T", " ") if s['lastTimestamp'] else "N/A"
        preview = s['lastMessage'][:60]
        print(f"{sid:<38} {count:>5}  {ts:<22}  {preview}")


def _do_resume(session_arg: str, history: HistoryStore):
    """加载指定 session 用于 resume"""
    session = get_session()

    if session_arg == "__LATEST__":
        sessions = history.list_sessions()
        if not sessions:
            print("No saved sessions found. Starting fresh.")
            return
        session_id = sessions[0]["sessionId"]
        print(f"Resuming latest session: {session_id[:8]}...")
    else:
        session_id = session_arg

    entries = history.load_session(session_id)
    if not entries:
        print(f"Session {session_id[:8]}... not found or empty. Starting fresh.")
        return

    # 恢复链尾以继续追加
    history.init_tail(session_id)

    # 设置 session 状态
    session.resume_session_id = session_id
    session.session_id = session_id

    # 加载消息供 Agent 使用
    resume_messages = history.get_messages_for_model(session_id)
    session._resume_messages = resume_messages  # type: ignore[attr-defined]

    print(f"Resumed session {session_id[:8]}... ({len(resume_messages)} messages loaded)")


# ============================================================
# 入口
# ============================================================

def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="Mini Claude Code — Python Implementation",
    )
    parser.add_argument(
        "--resume", type=str, nargs="?", const="__LATEST__",
        help="Resume a previous session (default: latest)",
    )
    parser.add_argument(
        "--list-sessions", action="store_true",
        help="List all saved sessions and exit",
    )
    parser.add_argument(
        "--session", type=str,
        help="Specify a custom session ID",
    )
    args = parser.parse_args()

    load_config()

    # 初始化 HistoryStore
    session = get_session()
    history = get_history_store(session.project_root or session.cwd)

    # 自定义 session ID
    if args.session:
        session.session_id = args.session
        history.reset_tail()

    # --list-sessions
    if args.list_sessions:
        _list_sessions_cmd(history)
        return

    # --resume
    if args.resume:
        _do_resume(args.resume, history)

    try:
        asyncio.run(repl_loop(history))
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")
    finally:
        # 确保所有缓冲写入磁盘
        history.dispose()


if __name__ == "__main__":
    main()
