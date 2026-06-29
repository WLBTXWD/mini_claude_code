"""System context gathering — git status, project files, platform info.

Extracted from main.py: _get_system_context.
"""
import datetime
import os
import subprocess
import sys

from state.session import get_session


def get_system_context() -> dict[str, str]:
    """获取系统上下文 (对应 src/context.ts)"""
    context = {}

    # Git 状态
    try:
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
    context["date"] = datetime.date.today().isoformat()

    return context
