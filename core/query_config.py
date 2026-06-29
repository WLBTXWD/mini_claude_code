"""
查询配置 (对应 src/query/config.ts)

在查询开始时对可变状态拍快照，确保整个查询循环使用一致的配置。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryConfig:
    """不可变的查询配置快照"""
    session_id: str
    model: str
    max_turns: int = 100
    auto_compact_enabled: bool = True
    streaming_enabled: bool = True
    max_output_tokens: int = 16000
