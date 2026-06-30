"""JSON 文件持久化存储"""

import json
import os
from pathlib import Path

from .models import Todo


class TodoStorage:
    def __init__(self, filepath: str = "todos.json"):
        self.filepath = Path(filepath)
        self._ensure_file()

    def _ensure_file(self):
        if not self.filepath.exists():
            self.filepath.write_text("[]")

    def _read_all(self) -> list[dict]:
        return json.loads(self.filepath.read_text())

    def _write_all(self, todos: list[dict]):
        self.filepath.write_text(json.dumps(todos, indent=2, ensure_ascii=False))

    def list(self, show_done: bool = True) -> list[Todo]:
        todos = [Todo.from_dict(d) for d in self._read_all()]
        if not show_done:
            todos = [t for t in todos if not t.done]
        return todos

    def add(self, title: str) -> Todo:
        todos = self._read_all()
        new_id = max([t["id"] for t in todos], default=0) + 1
        todo = Todo(id=new_id, title=title)
        todos.append(todo.to_dict())
        self._write_all(todos)
        return todo

    def toggle(self, todo_id: int) -> Todo | None:
        todos = self._read_all()
        for t in todos:
            if t["id"] == todo_id:
                t["done"] = not t["done"]
                self._write_all(todos)
                return Todo.from_dict(t)
        return None

    def delete(self, todo_id: int) -> bool:
        todos = self._read_all()
        new_todos = [t for t in todos if t["id"] != todo_id]
        if len(new_todos) == len(todos):
            return False
        self._write_all(new_todos)
        return True

    def update(self, todo_id: int, **kwargs) -> Todo | None:
        valid_fields = {"title", "priority", "due_date"}
        updates = {k: v for k, v in kwargs.items() if k in valid_fields}
        if not updates:
            return None
        todos = self._read_all()
        for t in todos:
            if t["id"] == todo_id:
                t.update(updates)
                self._write_all(todos)
                return Todo.from_dict(t)
        return None
