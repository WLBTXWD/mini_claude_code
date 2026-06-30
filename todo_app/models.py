"""Todo 数据模型"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Todo:
    id: int
    title: str
    done: bool = False
    priority: str = "medium"  # low, medium, high
    due_date: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "done": self.done,
            "priority": self.priority,
            "due_date": self.due_date,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Todo":
        return cls(**d)
