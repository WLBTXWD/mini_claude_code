"""
CLI 入口 (对应 src/main.tsx + entrypoints/cli.tsx)

解析参数，初始化会话，启动 REPL。
"""
import argparse
import asyncio

from cli.config import load_config
from cli.repl import repl_loop
from cli.sessions import list_sessions_cmd, do_resume
from state.session import get_session
from history.store import get_history_store


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
        list_sessions_cmd(history)
        return

    # --resume
    if args.resume:
        do_resume(args.resume, history)

    try:
        asyncio.run(repl_loop(history))
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")
    finally:
        # 确保所有缓冲写入磁盘
        history.dispose()


if __name__ == "__main__":
    main()
