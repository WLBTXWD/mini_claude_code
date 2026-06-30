"""Session-level prompt management for the terminal REPL."""
from __future__ import annotations

import datetime
import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Any

from memory.system import MemorySystem

from .prompt import build_system_prompt

MAX_PROJECT_CONTEXT_CHARS = 12000


@dataclass(frozen=True)
class PromptContext:
    """Cached prompt inputs for one interactive terminal session."""

    system_prompt: str
    user_context: dict[str, str]
    system_context: dict[str, str]


class PromptManager:
    """Builds and reuses Claude Code-style prompt layers for one REPL session."""

    def __init__(self, context: PromptContext):
        self.context = context

    @property
    def system_prompt(self) -> str:
        return self.context.system_prompt

    @property
    def user_context(self) -> dict[str, str]:
        return self.context.user_context

    @property
    def system_context(self) -> dict[str, str]:
        return self.context.system_context

    @classmethod
    def from_session(cls, session: Any) -> "PromptManager":
        project_root = session.project_root or session.cwd
        memory_prompt = MemorySystem(project_root).load_memory_prompt()
        system_context = collect_system_context(project_root, session.cwd)
        user_context = collect_user_context(project_root)
        system_prompt = build_system_prompt(
            cwd=session.cwd,
            model=session.model,
            memory_prompt=memory_prompt,
            system_context=system_context,
        )
        return cls(PromptContext(
            system_prompt=system_prompt,
            user_context=user_context,
            system_context=system_context,
        ))

    def prepend_user_context(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return API messages with cached user context prepended.

        The reminder is not persisted in conversation history; it is only added
        to the request sent to the model.
        """
        if not self.user_context:
            return list(messages)
        return [
            {"role": "user", "content": format_user_context_reminder(self.user_context)},
            *messages,
        ]

    def loaded_context_keys(self) -> dict[str, list[str]]:
        return {
            "system": list(self.system_context.keys()),
            "user": list(self.user_context.keys()),
        }


def collect_system_context(project_root: str, cwd: str) -> dict[str, str]:
    """Collect a session-start system snapshot."""
    context: dict[str, str] = {
        "platform": platform.platform(),
        "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC", ""),
    }

    branch = _run_git(["branch", "--show-current"], cwd=project_root or cwd)
    if branch:
        context["git_branch"] = branch

    status = _run_git(["status", "--short"], cwd=project_root or cwd)
    if status:
        context["git_status"] = status
    elif branch is not None:
        context["git_status"] = "(clean)"

    recent = _run_git(["log", "--oneline", "-n", "5"], cwd=project_root or cwd)
    if recent:
        context["recent_commits"] = recent

    return {k: v for k, v in context.items() if v}


def collect_user_context(project_root: str) -> dict[str, str]:
    """Collect session-start user/project context."""
    context: dict[str, str] = {
        "currentDate": f"Today's date is {datetime.date.today().isoformat()}.",
    }

    claude_md = _read_project_file(project_root, "CLAUDE.md")
    if claude_md:
        context["claudeMd"] = claude_md
        return context

    readme = _read_project_file(project_root, "README.md")
    if readme:
        context["readme"] = readme

    return context


def format_user_context_reminder(user_context: dict[str, str]) -> str:
    sections = []
    for key, value in user_context.items():
        if value:
            sections.append(f"# {key}\n{value}")
    joined = "\n\n".join(sections)
    return (
        "<system-reminder>\n"
        "As you answer the user's questions, you can use the following session-start context.\n"
        f"{joined}\n\n"
        "IMPORTANT: this context may or may not be relevant to the current task. "
        "Do not mention it unless it matters.\n"
        "</system-reminder>"
    )


def _read_project_file(project_root: str, filename: str) -> str | None:
    path = os.path.join(project_root, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(MAX_PROJECT_CONTEXT_CHARS + 1)
    except OSError:
        return None
    if len(content) > MAX_PROJECT_CONTEXT_CHARS:
        return content[:MAX_PROJECT_CONTEXT_CHARS] + "\n\n[Project context truncated...]"
    return content


def _run_git(args: list[str], cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
