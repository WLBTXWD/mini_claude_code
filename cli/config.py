"""Configuration loading — env vars and project root discovery.

Extracted from main.py: load_config + find_project_root.
"""
import os
import sys

from state.session import get_session


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
    session.project_root = find_project_root(session.cwd)

    # 可选的 max_turns 控制
    max_turns = os.environ.get("MAX_TURNS", "10")
    if max_turns.isdigit():
        session.max_turns = int(max_turns)


def find_project_root(start_path: str) -> str:
    """查找项目根目录（包含 .git 或 .mini_claude_code 的目录）"""
    current = os.path.abspath(start_path)
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, ".git")):
            return current
        if os.path.exists(os.path.join(current, ".mini_claude_code")):
            return current
        current = os.path.dirname(current)
    return start_path
