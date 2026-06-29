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
    load_config()

    # 初始化 session, historyStore
    session = get_session()
    history = get_history_store(session.project_root or session.cwd)

    try:
        asyncio.run(repl_loop())
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")
    finally:
        # 确保所有缓冲写入磁盘
        history.dispose()


if __name__ == "__main__":
    main()
