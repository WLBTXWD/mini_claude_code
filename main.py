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
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        print()  # 换行，准备显示助手回复
        print("Assistant: ", end="", flush=True)

        # 运行 Agent (传入历史消息作为初始上下文)
        total_output = ""
        result = None
        turn_info = ""

        async for event in agent.run(
            user_input,
            system_context,
            initial_messages=session_messages if session_messages else None,
        ):
            if isinstance(event, dict):
                if event.get("type") == "text":
                    print(event["content"], end="", flush=True)
                    total_output += event["content"]
                elif event.get("type") == "tool_execution_start":
                    print(f"\n  [Executing {event['count']} tool(s)...]")
                elif event.get("type") == "turn_complete":
                    turn_info = f"  [Turn {event['turn']} complete]"
                elif event.get("type") == "compact":
                    print(f"\n  [{event['message']}]")
            elif isinstance(event, AgentResult):
                # 最终结果 (AgentResult)
                result = event
                break

        print()
        if turn_info:
            print(turn_info)

        if result:
            # 更新 session 消息 (从历史重新加载以获取最新消息)
            if history:
                session_messages = history.get_messages_for_model(session.session_id)
            print(f"\n[Completed: {getattr(result, 'reason', '?')}] "
                  f"Turns: {getattr(result, 'turn_count', 0)}")
            print(f"Tokens: {session.total_input_tokens} in / {session.total_output_tokens} out")
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
