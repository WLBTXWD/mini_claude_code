"""Session listing and resume CLI helpers.

Extracted from main.py: _list_sessions_cmd + _do_resume.
"""
from history.store import HistoryStore
from state.session import get_session


def list_sessions_cmd(history: HistoryStore):
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


def do_resume(session_arg: str, history: HistoryStore):
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
