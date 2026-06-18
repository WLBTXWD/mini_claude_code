# Mini Claude Code

基于 Claude Code 2.1.88 源码逆向分析的最小 Python 实现。

## 架构设计

保留 Claude Code 最核心的设计思想：

1. **Agent Loop (AsyncGenerator)**: `agent.py` — `while True` 循环 + `async for` 事件流
2. **Tool System**: `tool.py` + `tools.py` — Tool 基类、Schema 验证、并发安全声明
3. **Tool Orchestrator**: `tool_orch.py` — 并发/串行分区执行
4. **Memory System**: `memory.py` + `memory_types.py` — 文件级持久化，四类型分类
5. **Context Compaction**: `compact.py` — 自动 token 检测 + 摘要压缩
6. **Prompt Assembly**: `prompt.py` — 分层构建系统提示
7. **Dependency Injection**: `query_deps.py` + `query_config.py`
8. **Session State**: `state.py` — 进程级单例

## 安装

```bash
pip install -r requirements.txt
```

## 配置

设置环境变量：

```bash
# 使用 Anthropic API (推荐)
export ANTHROPIC_API_KEY="sk-ant-..."
export ANTHROPIC_BASE_URL="https://api.anthropic.com/v1"
export ANTHROPIC_MODEL="claude-sonnet-4-6"

# 或使用 OpenAI 兼容 API
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL="gpt-4o"
```

可选配置：

```bash
export MAX_TURNS=50  # 最大轮次，默认 100
```

## 运行

```bash
python main.py
```

## 使用示例

```
> 帮我写一个 Python 的快速排序函数

Assistant: 这是快速排序的实现：

```python
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)
```

[Completed: completed] Turns: 1

> 在 src/ 目录下创建一个 utils.py 文件

Assistant:
[Executing 1 tool(s)...]
[Turn 1 complete]

已创建 src/utils.py 文件。

[Completed: completed] Turns: 1
```

## 命令

- `/help` — 显示帮助
- `/clear` — 清除会话
- `/compact` — 压缩上下文
- `/memory` — 查看记忆
- `/model <name>` — 切换模型
- `/cost` — 查看用量
- `/exit` — 退出

## 文件结构

```
mini_claude_code/
├── main.py          # CLI 入口 + REPL
├── agent.py         # Agent Loop 核心
├── tool.py          # Tool 基类
├── tools.py         # 内置工具 (Bash, FileRead, FileWrite, FileEdit, Glob, Grep, WebFetch, TodoWrite)
├── tool_orch.py     # 工具编排器 (并发/串行分区)
├── memory.py        # 记忆系统 (文件级持久化)
├── memory_types.py  # 记忆类型定义
├── compact.py       # 上下文压缩
├── prompt.py        # 提示组装
├── query_config.py  # 查询配置 (不可变快照)
├── query_deps.py    # 依赖注入接口
├── llm.py           # LLM 客户端 (OpenAI 兼容)
├── state.py         # 会话状态 (进程级单例)
└── requirements.txt
```

## 与 Claude Code 源码的对应关系

| 本实现 | Claude Code 源码 |
|--------|-----------------|
| `agent.py: AgentLoop.run()` | `src/query.ts: query() / queryLoop()` |
| `tool.py: Tool` | `src/Tool.ts` |
| `tools.py: get_all_tools()` | `src/tools.ts: getTools()` |
| `tool_orch.py: ToolOrchestrator.run_tools()` | `src/services/tools/toolOrchestration.ts: runTools()` |
| `memory.py: MemorySystem` | `src/memdir/memdir.ts + memoryScan.ts` |
| `compact.py: ContextCompactor` | `src/services/compact/compact.ts + autoCompact.ts` |
| `prompt.py: build_system_prompt()` | `src/constants/prompts.ts: getSystemPrompt()` |
| `query_config.py: QueryConfig` | `src/query/config.ts` |
| `query_deps.py: QueryDeps` | `src/query/deps.ts` |
| `llm.py: LLMClient` | `src/services/api/claude.ts` |
| `state.py: SessionState` | `src/bootstrap/state.ts` |
