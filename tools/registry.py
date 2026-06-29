"""工具注册表 — 管理所有可用工具"""
from .base import Tool
from .bash_tool import BashTool
from .file_tools import FileReadTool, FileWriteTool, FileEditTool
from .search_tools import GlobTool, GrepTool
from .web_tool import WebFetchTool
from .todo_tool import TodoWriteTool

_all_tools: list[Tool] = [
    BashTool(),
    FileReadTool(),
    FileWriteTool(),
    FileEditTool(),
    GlobTool(),
    GrepTool(),
    WebFetchTool(),
    TodoWriteTool(),
]


def get_all_tools() -> list[Tool]:
    """返回所有可用工具"""
    return _all_tools


def find_tool_by_name(name: str) -> Tool | None:
    for tool in _all_tools:
        if tool.name == name:
            return tool
    return None
