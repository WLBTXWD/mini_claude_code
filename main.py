"""
CLI 入口 (对应 src/main.tsx + entrypoints/cli.tsx)

解析参数，初始化会话，启动 REPL。
"""
import asyncio
import os
import sys
from typing import Optional

from llm import LLMClient
from agent import AgentLoop
from state import get_session, reset_session


# ============================================================
# 配置
# ============================================================

def load_config():
    """加载配置（从环境变量）"""
    session = get_session()

    session.api_key = os.environ.get(
        "DEEPSEEK_API_KEY",
        os.environ.get("DEEPSEEK_API_KEY", ""),
    )
    if not session.api_key:
        print("Error: Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable")
        sys.exit(1)

    session.base_url = os.environ.get(
        "DEEPSEEK_BASE_URL",
        os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    session.model = os.environ.get(
        "DEEPSEEK_MODEL",
        os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    )
    session.cwd = os.getcwd()
    session.project_root = _find_project_root(session.cwd)

    # 可选的 max_turns 控制
    max_turns = os.environ.get("MAX_TURNS", "10")
    if max_turns.isdigit():
        session.max_turns = int(max_turns)


def _find_project_root(start_path: str) -> str:
    """查找项目根目录（包含 .git 或 .mini_claude_code 的目录）"""
    current = os.path.abspath(start_path)
    while current != os.path.dirname(current):
        if os.path.exists(os.path.join(current, ".git")):
            return current
        if os.path.exists(os.path.join(current, ".mini_claude_code")):
            return current
        current = os.path.dirname(current)
    return start_path


# ============================================================
# REPL 主循环
# ============================================================

async def repl_loop():
    """REPL 主循环 (对应 REPL.tsx 的交互模式)"""
    print("=" * 60)
    print("  Mini Claude Code — Python Implementation")
    print("  Based on Claude Code 2.1.88 architecture analysis")
    print(f"  Model: {get_session().model}")
    print(f"  CWD: {get_session().cwd}")
    print("  Type 'exit' or 'quit' to exit, '/help' for commands")
    print("=" * 60)
    print()

    # 初始化 LLM 客户端和 Agent
    session = get_session()
    verify_ssl = False
    llm = LLMClient(
        api_key=session.api_key,
        base_url=session.base_url,
        model=session.model,
        verify_ssl=verify_ssl,
    )
    agent = AgentLoop(llm)

    # 加载系统上下文
    system_context = _get_system_context()
    if system_context:
        print(f"[System] Loaded context: {list(system_context.keys())}")
    print()

    # 消息历史（跨轮次持久化）
    conversation_history: list[dict] = []

    while True:
        try:
            user_input = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # 处理命令
        if user_input.startswith("/"):
            handled = await _handle_command(user_input, agent)
            if handled == "exit":
                break
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        # 构建消息（包含历史）
        user_message = user_input
        if conversation_history:
            # 注入历史摘要
            history_text = "\n".join(
                f"[Previous turn {i+1}]: {h.get('summary', '')}"
                for i, h in enumerate(conversation_history[-3:])
            )
            user_message = f"Previous conversation:\n{history_text}\n\nNew request: {user_input}"

        print()  # 换行，准备显示助手回复
        print("Assistant: ", end="", flush=True)

        # 运行 Agent
        total_output = ""
        result = None
        turn_info = ""

        async for event in agent.run(user_message, system_context):
            if isinstance(event, dict):
                if event.get("type") == "text":
                    print(event["content"], end="", flush=True)
                    total_output += event["content"]
                elif event.get("type") == "tool_execution_start":
                    print(f"\n  [Executing {event['count']} tool(s)...]")
                elif event.get("type") == "turn_complete":
                    turn_info = f"  [Turn {event['turn']} complete]"
                elif event.get("type") == "compact":
                    print(f"\n  [{event['message']}]")
            else:
                # 最终结果 (AgentResult)
                result = event
                if isinstance(result, dict) and "reason" in result:
                    break

        print()
        if turn_info:
            print(turn_info)

        if result:
            # 保存到历史
            conversation_history.append({
                "user": user_input[:200],
                "assistant": total_output[:200],
                "turns": getattr(result, "turn_count", 0),
                "summary": f"User asked: {user_input[:100]}..., Assistant responded with {len(total_output)} chars in {getattr(result, 'turn_count', 0)} turns",
            })
            print(f"\n[Completed: {getattr(result, 'reason', '?')}] "
                  f"Turns: {getattr(result, 'turn_count', 0)}")
            print(f"Tokens: {session.total_input_tokens} in / {session.total_output_tokens} out")
        print()


async def _handle_command(cmd: str, agent: AgentLoop) -> Optional[str]:
    """处理斜杠命令"""
    parts = cmd.split()
    command = parts[0].lower()

    if command in ("/exit", "/quit"):
        print("Goodbye!")
        return "exit"

    elif command == "/help":
        print("""
Available commands:
  /help          - Show this help
  /clear         - Clear conversation and reset session
  /compact       - Manually compact conversation context
  /memory        - Show memory directory and contents
  /model <name>  - Switch model (next session)
  /cost          - Show token usage and cost
  /exit          - Exit
""")
    elif command == "/clear":
        reset_session()
        load_config()
        print("Session cleared.")
    elif command == "/compact":
        print("Compacting context...")
        # compaction is handled automatically by agent loop
        print("Context will be compacted automatically when needed.")
    elif command == "/memory":
        from memory import MemorySystem
        session = get_session()
        mem = MemorySystem(session.project_root or session.cwd)
        mem.ensure_memory_dir()
        print(f"Memory directory: {mem.memory_dir}")
        memories = mem.scan_memories()
        if memories:
            print(f"\n{len(memories)} memories:")
            print(mem.format_memory_manifest(memories))
        else:
            print("No memories found.")
    elif command == "/cost":
        session = get_session()
        print(f"Input tokens:  {session.total_input_tokens:,}")
        print(f"Output tokens: {session.total_output_tokens:,}")
        print(f"Total turns:   {session.total_turns}")
        print(f"Model:         {session.model}")
    elif command == "/model" and len(parts) > 1:
        session = get_session()
        session.model = parts[1]
        print(f"Model set to: {session.model}")
    else:
        print(f"Unknown command: {command}")

    return None


def _get_system_context() -> dict[str, str]:
    """获取系统上下文 (对应 src/context.ts)"""
    context = {}

    # Git 状态
    try:
        import subprocess
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            context["git_branch"] = result.stdout.strip()

        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            changed = len([l for l in result.stdout.strip().split("\n") if l])
            if changed > 0:
                context["git_changes"] = f"{changed} file(s) modified"
    except Exception:
        pass

    # CLAUDE.md / README
    for fname in ["CLAUDE.md", "README.md"]:
        path = os.path.join(get_session().cwd, fname)
        if os.path.exists(path):
            context[f"has_{fname.lower().replace('.', '_')}"] = "yes"
            break

    # Platform
    context["platform"] = sys.platform
    context["date"] = __import__('datetime').date.today().isoformat()

    return context


# ============================================================
# 入口
# ============================================================

def main():
    """主入口"""
    load_config()

    try:
        asyncio.run(repl_loop())
    except KeyboardInterrupt:
        print("\nInterrupted. Goodbye!")


if __name__ == "__main__":
    main()
