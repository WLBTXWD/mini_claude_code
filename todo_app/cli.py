"""命令行接口"""

import sys

from .storage import TodoStorage


def cmd_add(storage: TodoStorage, args: list[str]):
    if not args:
        print("用法: add <标题>")
        return
    title = " ".join(args)
    todo = storage.add(title)
    print(f"[✓] 已添加 #{todo.id}: {todo.title}")


def cmd_list(storage: TodoStorage, show_done: bool = True):
    todos = storage.list(show_done=show_done)
    if not todos:
        print("暂无待办事项。")
        return
    for t in todos:
        mark = "✓" if t.done else " "
        prio = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t.priority, "")
        due = f"  截止: {t.due_date}" if t.due_date else ""
        print(f"  [{mark}] #{t.id} {prio} {t.title}{due}")


def cmd_toggle(storage: TodoStorage, args: list[str]):
    if not args:
        print("用法: toggle <id>")
        return
    try:
        tid = int(args[0])
    except ValueError:
        print(f"无效 ID: {args[0]}")
        return
    result = storage.toggle(tid)
    if result:
        status = "完成" if result.done else "未完成"
        print(f"[✓] #{tid} 已标记为: {status}")
    else:
        print(f"[✗] 未找到 #{tid}")


def cmd_delete(storage: TodoStorage, args: list[str]):
    if not args:
        print("用法: delete <id>")
        return
    try:
        tid = int(args[0])
    except ValueError:
        print(f"无效 ID: {args[0]}")
        return
    if storage.delete(tid):
        print(f"[✓] 已删除 #{tid}")
    else:
        print(f"[✗] 未找到 #{tid}")


def cmd_update(storage: TodoStorage, args: list[str]):
    if len(args) < 1:
        print("用法: update <id> [--title TEXT] [--priority low|medium|high] [--due DATE]")
        return
    try:
        tid = int(args[0])
    except ValueError:
        print(f"无效 ID: {args[0]}")
        return

    kwargs = {}
    i = 1
    while i < len(args):
        if args[i] == "--title" and i + 1 < len(args):
            kwargs["title"] = args[i + 1]
            i += 2
        elif args[i] == "--priority" and i + 1 < len(args):
            kwargs["priority"] = args[i + 1]
            i += 2
        elif args[i] == "--due" and i + 1 < len(args):
            kwargs["due_date"] = args[i + 1]
            i += 2
        else:
            print(f"未知参数: {args[i]}")
            return

    result = storage.update(tid, **kwargs)
    if result:
        print(f"[✓] #{tid} 已更新")
    else:
        print(f"[✗] 更新失败")


def cmd_help():
    print("""Todo CLI - 命令行待办事项工具

命令:
  add <标题>              添加新待办
  list                    列出所有待办
  list --pending          仅列出未完成
  toggle <id>             切换完成状态
  delete <id>             删除待办
  update <id> [参数]      更新待办
      --title TEXT        新标题
      --priority LEVEL    low / medium / high
      --due DATE          截止日期
  help                    显示帮助
  exit                    退出
""")


def run_cli(storage: TodoStorage):
    print("Todo CLI (输入 help 查看帮助, exit 退出)")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "exit":
            print("再见!")
            break
        elif cmd == "add":
            cmd_add(storage, args)
        elif cmd == "list":
            if "--pending" in args:
                cmd_list(storage, show_done=False)
            else:
                cmd_list(storage)
        elif cmd == "toggle":
            cmd_toggle(storage, args)
        elif cmd == "delete":
            cmd_delete(storage, args)
        elif cmd == "update":
            cmd_update(storage, args)
        elif cmd == "help":
            cmd_help()
        else:
            print(f"未知命令: {cmd}，输入 help 查看帮助")
