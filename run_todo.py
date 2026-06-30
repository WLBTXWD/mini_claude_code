"""Todo CLI 入口"""

from todo_app import TodoStorage, run_cli

if __name__ == "__main__":
    storage = TodoStorage("todos.json")
    run_cli(storage)
