"""
记忆系统 (对应 src/memdir/memdir.ts + memoryScan.ts + findRelevantMemories.ts)

文件级持久化记忆，支持扫描和相关性选择。
"""
import os
import time
from dataclasses import dataclass
from typing import Optional

from memory_types import MemoryHeader, MEMORY_TYPES, parse_frontmatter

MEMORY_DIR_NAME = ".mini_claude_code"
MEMORY_INDEX_NAME = "MEMORY.md"
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25000


@dataclass
class MemorySystem:
    """记忆系统管理器"""
    project_root: str

    @property
    def memory_dir(self) -> str:
        return os.path.join(self.project_root, MEMORY_DIR_NAME, "memory")

    @property
    def index_path(self) -> str:
        return os.path.join(self.memory_dir, MEMORY_INDEX_NAME)

    def ensure_memory_dir(self):
        """确保记忆目录存在"""
        os.makedirs(self.memory_dir, exist_ok=True)

    def load_memory_prompt(self) -> str | None:
        """加载记忆到系统提示 (对应 loadMemoryPrompt)"""
        self.ensure_memory_dir()

        if not os.path.exists(self.index_path):
            return None

        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None

        # 截断过大的索引
        lines = content.split("\n")
        if len(lines) > MAX_INDEX_LINES:
            lines = lines[:MAX_INDEX_LINES]
            content = "\n".join(lines) + "\n\n[Memory index truncated...]"

        if len(content.encode("utf-8")) > MAX_INDEX_BYTES:
            content = content[:MAX_INDEX_BYTES]

        prompt_parts = [
            "You have a persistent file-based memory.",
            f"Memory directory: {self.memory_dir}",
            "This directory already exists — write to it directly.",
            "",
            "## Memory Types",
            "- **user**: Who the user is (role, preferences)",
            "- **feedback**: Guidance on how you should work",
            "- **project**: Ongoing work, goals, constraints",
            "- **reference**: External resources, URLs, documentation",
            "",
            "### Current Memory Index:",
            content,
        ]
        return "\n".join(prompt_parts)

    def scan_memories(self) -> list[MemoryHeader]:
        """扫描所有记忆文件 (对应 scanMemoryFiles)"""
        self.ensure_memory_dir()
        memories: list[MemoryHeader] = []

        if not os.path.isdir(self.memory_dir):
            return memories

        for filename in os.listdir(self.memory_dir):
            if not filename.endswith(".md") or filename == MEMORY_INDEX_NAME:
                continue

            filepath = os.path.join(self.memory_dir, filename)
            try:
                stat = os.stat(filepath)
                with open(filepath, "r", encoding="utf-8") as f:
                    frontmatter_text = f.read(3000)  # 最多读前3000字符

                fm = parse_frontmatter(frontmatter_text)
                memories.append(MemoryHeader(
                    filename=filename,
                    filepath=filepath,
                    mtime=stat.st_mtime,
                    description=fm.get("description", ""),
                    memory_type=fm.get("type", "reference"),
                ))
            except Exception:
                continue

        memories.sort(key=lambda m: m.mtime, reverse=True)
        return memories[:200]

    def format_memory_manifest(self, memories: list[MemoryHeader]) -> str:
        """格式化记忆清单"""
        lines = []
        for m in memories:
            mod_time = time.strftime("%Y-%m-%d", time.localtime(m.mtime))
            lines.append(f"[{m.memory_type}] {m.filename} ({mod_time}): {m.description}")
        return "\n".join(lines)

    def get_memory_content(self, filename: str) -> Optional[str]:
        """读取单个记忆文件内容"""
        filepath = os.path.join(self.memory_dir, filename)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
