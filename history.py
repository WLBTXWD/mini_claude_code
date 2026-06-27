"""
历史记录持久化系统 (对应 src/utils/sessionStorage.ts)

存储位置: <项目根>/.mini_claude_code/<sessionId>.jsonl
格式: JSONL, 每行一个 JSON 对象, parentUuid → uuid 单链表
"""
import asyncio
import json
import os
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ============================================================
# 路径
# ============================================================

def _history_dir(project_root: str = ".") -> Path:
    return Path(project_root) / ".mini_claude_code"


def _session_path(session_id: str, project_root: str = ".") -> Path:
    return _history_dir(project_root) / f"{session_id}.jsonl"


# ============================================================
# 数据模型
# ============================================================

@dataclass
class HistoryEntry:
    """一条 JSONL 记录"""
    type: str                          # "user" | "assistant"
    message: dict[str, Any]
    parent_uuid: Optional[str] = None
    uuid: str = field(default_factory=lambda: str(uuid_mod.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str = ""
    # 仅 tool_result
    tool_use_result: Optional[dict[str, Any]] = None
    source_tool_assistant_uuid: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "parentUuid": self.parent_uuid,
            "type": self.type,
            "message": self.message,
            "uuid": self.uuid,
            "timestamp": self.timestamp,
            "sessionId": self.session_id,
        }
        if self.tool_use_result is not None:
            d["toolUseResult"] = self.tool_use_result
        if self.source_tool_assistant_uuid is not None:
            d["sourceToolAssistantUUID"] = self.source_tool_assistant_uuid
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HistoryEntry":
        return cls(
            type=data["type"],
            message=data["message"],
            parent_uuid=data.get("parentUuid"),
            uuid=data["uuid"],
            timestamp=data.get("timestamp", ""),
            session_id=data.get("sessionId", ""),
            tool_use_result=data.get("toolUseResult"),
            source_tool_assistant_uuid=data.get("sourceToolAssistantUUID"),
        )


# ============================================================
# 批量写入器 (对应 Claude Code src/utils/bufferedWriter.ts)
# ============================================================

class BatchedWriter:
    """异步批量写入器，100ms 防抖 (匹配 Claude Code FLUSH_INTERVAL_MS)。

    POSIX O_APPEND 对小于 PIPE_BUF (4096 bytes) 的行是原子操作，
    因此不需要显式文件锁。
    """

    def __init__(self, file_path: Path, flush_interval_ms: int = 100):
        self._path = file_path
        self._flush_interval_ms = flush_interval_ms
        self._buffer: list[str] = []
        self._timer_handle: Any = None
        self._loop: Any = None

    def write(self, line: str):
        """追加一行到缓冲区，调度延迟刷新"""
        self._buffer.append(line)
        self._schedule_flush()

    def _schedule_flush(self):
        if self._timer_handle is not None:
            return
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行中的事件循环，同步刷新
            self.flush()
            return
        self._timer_handle = self._loop.call_later(
            self._flush_interval_ms / 1000.0, self._on_timer
        )

    def _on_timer(self):
        self._timer_handle = None
        self.flush()

    def flush(self):
        """立即写入所有缓冲行到磁盘"""
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None
        if not self._buffer:
            return
        content = "".join(self._buffer)
        self._buffer = []
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(content)
        except FileNotFoundError:
            os.makedirs(os.path.dirname(str(self._path)), exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(content)

    def dispose(self):
        """释放写入器，刷新所有剩余缓冲"""
        self.flush()


# ============================================================
# 存储引擎
# ============================================================

class HistoryStore:
    """
    按 session 分文件的 JSONL 存储。

    每个 session 一个 <sessionId>.jsonl 文件，
    放在项目根目录的 .mini_claude_code/ 下。
    """

    def __init__(self, project_root: str = "."):
        self.project_root = project_root
        self._dir = _history_dir(project_root)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._last_uuid: Optional[str] = None
        self._writers: dict[str, BatchedWriter] = {}

    # ===================== 写入 =====================

    def _get_writer(self, session_id: str) -> BatchedWriter:
        """获取或创建 session 对应的 BatchedWriter"""
        if session_id not in self._writers:
            self._writers[session_id] = BatchedWriter(
                _session_path(session_id, self.project_root)
            )
        return self._writers[session_id]

    def _append_line(self, session_id: str, entry: HistoryEntry):
        writer = self._get_writer(session_id)
        line = json.dumps(entry.to_dict(), ensure_ascii=False)
        writer.write(line + "\n")

    def write_user_message(self, content: str, session_id: str) -> HistoryEntry:
        """记录用户消息"""
        entry = HistoryEntry(
            type="user",
            message={"role": "user", "content": content},
            parent_uuid=self._last_uuid,
            session_id=session_id,
        )
        self._append_line(session_id, entry)
        self._last_uuid = entry.uuid
        return entry

    def write_tool_result(
        self,
        tool_use_id: str,
        result_content: str,
        assistant_uuid: str,
        session_id: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> HistoryEntry:
        """记录工具执行结果 (外层 type=user, message.role=user)"""
        entry = HistoryEntry(
            type="user",
            message={
                "role": "user",
                "content": [{
                    "tool_use_id": tool_use_id,
                    "type": "tool_result",
                    "content": result_content,
                }],
            },
            parent_uuid=self._last_uuid,
            session_id=session_id,
            source_tool_assistant_uuid=assistant_uuid,
            tool_use_result=extra,
        )
        self._append_line(session_id, entry)
        self._last_uuid = entry.uuid
        return entry

    def write_assistant_blocks(
        self,
        message_id: str,
        model: str,
        content_blocks: list[dict[str, Any]],
        usage: dict[str, Any],
        stop_reason: str,
        session_id: str,
    ) -> list[HistoryEntry]:
        """
        记录 assistant 消息。每个 content block 单独一条 JSONL，
        共享同一个 message.id。模拟 Claude Code 流式持久化。
        """
        entries = []
        for block in content_blocks:
            entry = HistoryEntry(
                type="assistant",
                message={
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [block],
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                    "usage": usage,
                    "stop_details": None,
                },
                parent_uuid=self._last_uuid,
                session_id=session_id,
            )
            self._append_line(session_id, entry)
            self._last_uuid = entry.uuid
            entries.append(entry)
        return entries

    # ===================== 读取 =====================

    def load_session(self, session_id: str) -> list[HistoryEntry]:
        """加载一个 session 的全部记录"""
        path = _session_path(session_id, self.project_root)
        if not path.exists():
            return []
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(HistoryEntry.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError):
                    continue
        return entries

    def build_chain(self, entries: list[HistoryEntry]) -> list[HistoryEntry]:
        """
        沿 parentUuid 回溯，重建对话链。
        (对应 src/utils/sessionStorage.ts:buildConversationChain)
        """
        if not entries:
            return []
        idx = {e.uuid: e for e in entries}
        chain = []
        seen = set()
        cur = entries[-1]
        while cur:
            if cur.uuid in seen:
                break
            seen.add(cur.uuid)
            chain.append(cur)
            cur = idx.get(cur.parent_uuid) if cur.parent_uuid else None  # type: ignore[assignment]
        chain.reverse()
        return chain

    def get_messages_for_model(self, session_id: str, max_entries: int = 200) -> list[dict[str, Any]]:
        """
        获取模型中可见的消息列表（用于 resume）。
        将 JSONL 格式转换回 LLM API 兼容格式：
        - user 消息: {"role": "user", "content": "..."}
        - assistant 消息: {"role": "assistant", "content": ..., "tool_calls": [...]}
        - tool_result 消息: {"role": "tool", "tool_call_id": ..., "content": "..."}

        多个 assistant block (text/tool_use) 共享同一个 message.id，
        这里合并为单条 assistant message。
        """
        entries = self.load_session(session_id)
        if not entries:
            return []
        chain = self.build_chain(entries)

        result: list[dict[str, Any]] = []
        # 按 message.id 分组合并 assistant blocks
        pending_blocks: dict[str, list[dict[str, Any]]] = {}
        pending_meta: dict[str, dict[str, Any]] = {}

        for e in chain:
            if e.type == "user" and e.source_tool_assistant_uuid:
                # tool_result → 先 flush pending assistant (result 总是在 assistant 之后)
                self._flush_pending(result, pending_blocks, pending_meta)
                content_list = e.message.get("content", [])
                if isinstance(content_list, list) and len(content_list) > 0:
                    result.append({
                        "role": "tool",
                        "tool_call_id": content_list[0].get("tool_use_id", ""),
                        "content": content_list[0].get("content", ""),
                    })
            elif e.type == "user":
                # 普通 user 消息 → 先 flush 所有 pending assistant
                self._flush_pending(result, pending_blocks, pending_meta)
                content = e.message.get("content", "")
                if isinstance(content, str) and content:
                    result.append({
                        "role": "user",
                        "content": content,
                    })
            elif e.type == "assistant":
                # assistant content block → 按 message.id 分组
                msg_content = e.message.get("content", [])
                msg_id = e.message.get("id", "")
                if isinstance(msg_content, list) and len(msg_content) > 0:
                    block = msg_content[0]
                    if msg_id not in pending_blocks:
                        pending_blocks[msg_id] = []
                        pending_meta[msg_id] = e.message
                    pending_blocks[msg_id].append(block)

        # 最后 flush 剩余的 pending assistants
        self._flush_pending(result, pending_blocks, pending_meta)

        return result[-max_entries:] if len(result) > max_entries else result

    def _flush_pending(
        self,
        result: list[dict[str, Any]],
        pending_blocks: dict[str, list[dict[str, Any]]],
        pending_meta: dict[str, dict[str, Any]],
    ):
        """将缓存的 assistant blocks 合并为 LLM 格式并追加到 result"""
        for msg_id, blocks in pending_blocks.items():
            text_content = None
            thinking_content = None
            tool_calls = []
            for block in blocks:
                if block.get("type") == "thinking":
                    thinking_content = block.get("thinking", "")
                elif block.get("type") == "text":
                    text_content = block.get("text", "")
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
            clean_msg: dict[str, Any] = {
                "role": "assistant",
                "content": text_content,
            }
            if thinking_content:
                clean_msg["_thinking"] = thinking_content
            if tool_calls:
                clean_msg["tool_calls"] = tool_calls
            result.append(clean_msg)
        pending_blocks.clear()
        pending_meta.clear()

    # ===================== 会话管理 =====================

    def list_sessions(self) -> list[dict[str, Any]]:
        """列出所有历史会话"""
        sessions = []
        for f in sorted(self._dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            sid = f.stem
            stat = f.stat()
            # 读最后一行获取最近时间
            entries = self.load_session(sid)
            msg_count = len(entries)
            last_ts = ""
            last_msg = ""
            if entries:
                last_ts = entries[-1].timestamp
                for e in reversed(entries):
                    if e.type == "user" and isinstance(e.message.get("content"), str):
                        last_msg = e.message["content"][:150]
                        break
            sessions.append({
                "sessionId": sid,
                "fileSize": stat.st_size,
                "messageCount": msg_count,
                "lastTimestamp": last_ts,
                "lastMessage": last_msg,
            })
        return sessions

    def delete_session(self, session_id: str) -> bool:
        path = _session_path(session_id, self.project_root)
        if path.exists():
            path.unlink()
            return True
        return False

    # ===================== 缓冲区管理 =====================

    def flush(self, session_id: str):
        """强制刷新指定 session 的缓冲区（Agent 完成时调用）"""
        if session_id in self._writers:
            self._writers[session_id].flush()

    def flush_all(self):
        """刷新所有 session 的缓冲区（退出时调用）"""
        for w in self._writers.values():
            w.flush()

    def dispose(self):
        """释放所有写入器（退出时调用）"""
        self.flush_all()
        self._writers.clear()

    # ===================== 链尾管理 =====================

    def init_tail(self, session_id: str):
        """从已有 session 文件恢复链尾（用于 resume）"""
        entries = self.load_session(session_id)
        self._last_uuid = entries[-1].uuid if entries else None

    def reset_tail(self):
        self._last_uuid = None


# ============================================================
# 全局单例
# ============================================================

_store: Optional[HistoryStore] = None


def get_history_store(project_root: str = ".") -> HistoryStore:
    global _store
    if _store is None or _store.project_root != project_root:
        _store = HistoryStore(project_root)
    return _store
