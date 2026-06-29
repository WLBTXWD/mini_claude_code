"""
记忆类型定义 (对应 src/memdir/memoryTypes.ts)

封闭四类型分类：user, feedback, project, reference
"""
import re
from dataclasses import dataclass

MEMORY_TYPES = ["user", "feedback", "project", "reference"]


@dataclass
class MemoryHeader:
    """记忆文件头部信息"""
    filename: str
    filepath: str
    mtime: float
    description: str = ""
    memory_type: str = "reference"


def parse_frontmatter(content: str) -> dict[str, str]:
    """解析 YAML frontmatter"""
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}

    frontmatter = {}
    for line in match.group(1).split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip().strip('"').strip("'")
    return frontmatter
