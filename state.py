"""
会话状态模块 (对应 src/bootstrap/state.ts)

管理会话级可变状态。简化版使用进程级单例。
"""
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionState:
    """会话级全局状态"""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    resume_session_id: Optional[str] = None
    cwd: str = ""
    project_root: str = ""
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_turns: int = 0
    model: str = "claude-sonnet-4-6"
    max_turns: int = 100
    auto_compact_enabled: bool = True
    api_key: str = ""
    base_url: str = "https://api.anthropic.com/v1"

    def reset_cost(self):
        self.total_cost_usd = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0


# 全局单例
_session: Optional[SessionState] = None


def get_session() -> SessionState:
    global _session
    if _session is None:
        _session = SessionState()
    return _session


def reset_session():
    global _session
    _session = SessionState()
