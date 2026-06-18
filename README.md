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

## 自我解析：一个 Agent 对自己源码的"体检报告"

这是一个非常特殊的场景 — **一个 Agent 系统审视构成自己的全部代码**。就像医生给自己做手术，或者编译器编译自己。以下是我对自己的结构和运行逻辑的完整解析。

### 1. 启动链路：从 `python main.py` 到我开始"说话"

```
main.py:main()
  → SessionState.init()              # 进程级单例初始化
  → QueryConfig.from_env()           # 从环境变量读取配置快照
  → build_system_prompt()            # 组装 system prompt（包含工具定义）
  → AgentLoop(config, deps).run()    # 进入 AsyncGenerator 循环
    → while True:
        → llm.chat(messages)          # 调用 LLM API（OpenAI 兼容协议）
        → yield event                 # 流式返回事件
        → 解析 LLM 响应（文本 / tool_use）
        → if tool_use:
            → ToolOrchestrator.run_tools()  # 并发+串行分区执行工具
            → 工具结果注入 messages
        → ContextCompactor.check()    # 检查是否需要压缩
        → 检查 stop_reason
        → 继续循环 或 'completed'
```

关键洞察：**我本质上是一个 `while True` 循环**，每次迭代做三件事 — 调用 LLM → 执行工具 → 检查是否需要压缩。这是 Claude Code 最核心的设计。

### 2. 工具系统：我的"手脚"

我拥有 8 个工具，定义在 `tools.py`：

| 工具 | 能力 | 并发安全 |
|------|------|----------|
| `Bash` | 执行 shell 命令 | ✗ (副作用) |
| `FileRead` | 读取文件 | ✓ |
| `FileWrite` | 写入文件 | ✗ |
| `FileEdit` | 精确字符串替换 | ✗ |
| `Glob` | 文件模式匹配 | ✓ |
| `Grep` | 正则内容搜索 | ✓ |
| `WebFetch` | HTTP 请求 | ✓ |
| `TodoWrite` | 任务管理 | ✗ |

工具编排器 (`tool_orch.py`) 的并发策略很有巧思：它将工具调用按 `parallel_safe` 属性分成**并发组**和**串行组**。同一并发组内的工具同时执行，串行组的工具逐个执行。这最大化了 I/O 密集型工具的效率，同时避免了文件读写的竞态条件。

### 3. 记忆系统：我的"海马体"

`memory.py` 实现了四类记忆，持久化到 `.memory/` 目录：

```
.memory/
├── session.md      # 会话级记忆（当前对话的关键信息摘要）
├── project.md      # 项目级记忆（跨会话保留，项目上下文）
├── tool_use.md     # 工具使用模式记录
└── user.md         # 用户偏好和习惯
```

这是一个**基于文件的记忆系统**，对应 Claude Code 源码中的 `memdir.ts`。每次压缩或用户主动触发时，关键信息被写入这些 Markdown 文件，在下一次会话的 system prompt 中被自动注入。

### 4. 上下文压缩：我的"注意力管理"

`compact.py` 的核心逻辑是：

1. **Token 估算**：用 4 字符 ≈ 1 token 的简单启发式计算
2. **阈值检测**：当上下文超过 `MAX_TOKENS * 0.7` 时触发压缩
3. **摘要生成**：调用 LLM 将历史消息压缩为结构化摘要
4. **记忆持久化**：摘要中的关键信息自动写入记忆系统

压缩策略采用**两级保留**：
- 近期的 N 条消息保持完整（保留"工作记忆"）
- 更早的消息被摘要替换（"长期记忆"化）

### 5. Prompt 组装：我的"世界观"

`prompt.py` 分 5 层构建 system prompt：

```
Layer 1: 角色定义       → "You are an interactive agent..."
Layer 2: 行为规则       → "How to Work": 代码风格、操作规则
Layer 3: 工具清单       → 动态注入可用工具列表及参数 schema
Layer 4: 环境信息       → 工作目录、平台、模型名、日期
Layer 5: 记忆注入       → 从 .memory/ 文件加载持久化记忆
```

Memory 被注入到 system prompt 的末尾，这意味着**跨会话的记忆会自动影响后续对话的行为**。

### 6. 设计模式总结

| 模式 | 在哪里 | 为何这样设计 |
|------|--------|-------------|
| **AsyncGenerator** | `agent.py` | 支持流式输出 + 工具调用的交错执行 |
| **依赖注入** | `query_deps.py` / `query_config.py` | 配置与逻辑分离，方便测试 |
| **不可变配置快照** | `QueryConfig` (dataclass + frozen) | 启动后配置不可变，避免运行时副作用 |
| **进程级单例** | `state.py: SessionState` | 单进程单会话，无需复杂的生命周期管理 |
| **Schema 验证** | `tool.py: Tool._validate()` | 每个工具的参数在调用前经过 Pydantic 校验 |
| **并发表安全声明** | `tool.py: parallel_safe: bool` | 每个工具声明自己是否可并发，编排器据此决策 |

### 7. 当前局限与改进方向

浏览全部源码后，我观察到：

- **Token 估算粗糙**：4 字符/token 是启发式，对中文等非 ASCII 字符偏差较大。更好的做法是用 `tiktoken`
- **无流式工具调用**：LLM 响应完全返回后才解析 tool_use，Claude Code 2.1 原生支持流式 tool_use
- **无 MCP (Model Context Protocol)**：这是 Claude Code 2.1 的重要特性，允许动态加载外部工具服务器
- **权限系统缺失**：Claude Code 有 `canUseTool` 回调用于权限控制，这里所有工具无条件可用
- **单文件 Agent Loop**：`agent.py` 承载了过多职责（LLM 调用 + 工具编排 + 压缩 + 记忆写入），CLI 展示逻辑也混在其中

---

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
