"""Slash command handler — /help, /clear, /resume, /compact, /memory, /cost, /model, /exit.

Extracted from main.py: _handle_command.
"""
from typing import Optional

from core.agent import AgentLoop
from history.store import HistoryStore
from state.session import get_session, reset_session

from .config import load_config
from .display import display_message_history


async def handle_command(cmd: str, history: HistoryStore | None = None) -> Optional[str]:
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
        from memory.system import MemorySystem
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
