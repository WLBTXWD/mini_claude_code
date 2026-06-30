# 代码审查报告

> 审查日期：2026-06-30
> 审查范围：全项目源码（`main.py`, `core/`, `cli/`, `tools/`, `llm/`, `history/`, `memory/`, `state/`）

---

## 一、PRD 已有审查问题（2026-06-29，全部未修复）

### 高优先级（功能 / 安全 Bug）

| # | 问题 | 文件:行号 | 说明 |
|---|------|-----------|------|
| 1 | **压缩功能未接入 LLM 摘要** | `core/compact.py:73-94` | `compact_messages()` 只做简单截断 + 占位文本，`compact_with_llm()` 从未被调用。长对话截断后丢失大量上下文。 |
| 2 | **SSL 验证硬编码关闭** | `cli/repl.py:30` | `verify_ssl = False` 关闭所有 HTTPS 证书验证，API 密钥和对话内容可能被中间人窃取。 |
| 3 | **Grep glob 不支持 `**` 递归模式** | `tools/search_tools.py:77-78` | `fnmatch.fnmatch` 不识别 `**` 递归通配符，用户传 `glob="**/*.py"` 时不会匹配子目录文件。 |

### 中优先级（性能 / 设计）

| # | 问题 | 文件:行号 | 说明 |
|---|------|-----------|------|
| 4 | **MemorySystem 每轮重复创建和文件 IO** | `core/agent.py:298-302` | `_get_system_prompt()` 每次调用都 new `MemorySystem` 并读取 `MEMORY.md`，每轮多余一次磁盘 IO。 |
| 5 | **并发工具批次输出完全缓冲后才 yield** | `tools/orchestrator.py:89-100` | `asyncio.gather` 等所有任务完成才 yield，用户看到结果有额外延迟。应改用 `asyncio.Queue` 流式输出。 |
| 6 | **should_auto_compact + compact_messages 重复计算 token** | `core/agent.py:118-122` | `should_auto_compact()` 内部计算一次 token，通过后 `compact_messages()` 又做 O(n) list 比较。 |
| 7 | **load_config() 环境变量重复查找** | `cli/config.py:15-18` | `os.environ.get("DEEPSEEK_API_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))` 默认值做了无用功。 |

### 低优先级（代码质量 / 可维护性）

| # | 问题 | 文件:行号 | 说明 |
|---|------|-----------|------|
| 8 | **main.py 未使用的导入** | `main.py:11` | `list_sessions_cmd` 和 `do_resume` 被导入但从未使用。 |
| 9 | **httpx.AsyncClient 无生命周期管理** | `llm/client.py:37` | `httpx.AsyncClient` 实例在 `LLMClient` 析构时不会自动关闭，每次 new agent 泄漏连接。 |
| 10 | **延迟导入放在 while True 循环内** | `core/agent.py:227-228` | `from tools.base import ToolUseContext` 在循环内，应移至文件顶部。 |
| 11 | **get_messages_for_model 全量解析后才截断** | `history/store.py:341` | `max_entries` 截断在结果构建完成后，大 session resume 时有不必要的 CPU/内存开销。 |
| 12 | **parse_frontmatter 硬编码 3000 字符截断** | `memory/system.py:90` | YAML frontmatter 闭合标签在 3000 字符后会被截断，解析失败。应逐行读取到第二个 `---`。 |

---

## 二、本次审查新增问题

### 阻断性问题（程序无法正常运行或严重安全风险）

| # | 问题 | 文件:行号 | 说明 |
|---|------|-----------|------|
| 13 | **requirements.txt 缺少 httpx** | `requirements.txt` | `llm/client.py` 和 `tools/web_tool.py` 都 `import httpx`，但 `requirements.txt` 只有 `openai`、`pydantic`、`pyyaml`。安装后运行会 `ModuleNotFoundError`。 |

### 逻辑 Bug

| # | 问题 | 文件:行号 | 说明 |
|---|------|-----------|------|
| 14 | **MAX_TURNS 默认值冲突** | `cli/config.py:35` vs `state/session.py:23` | `config.py` 将环境变量 `MAX_TURNS` 默认值设为 `"10"`，覆盖了 `SessionState.max_turns = 100`。README 声称默认 100，实际运行默认 10。 |
| 15 | **AgentLoop 每轮重新创建，断路器失效** | `cli/repl.py:85` | 每次用户输入都 `AgentLoop(llm, history_store=history)`，导致 `ContextCompactor.consecutive_failures` 每轮重置为 0，断路器形同虚设。 |

### 设计缺陷

| # | 问题 | 文件:行号 | 说明 |
|---|------|-----------|------|
| 16 | **HistoryStore 全局单例切换项目时泄漏** | `history/store.py:450-454` | `get_history_store()` 在 `project_root` 匹配时复用，但旧 project 的 `BatchedWriter` 不会被 dispose，可能导致缓冲区丢失。 |
| 17 | **SessionState 动态注入字段** | `cli/sessions.py:53` | `session._resume_messages` 通过 `# type: ignore[attr-defined]` 注入到 dataclass，不是正式定义的字段，容易在后续维护中出问题。 |

### 工程规范

| # | 问题 | 说明 |
|---|------|------|
| 18 | **__pycache__ 混入仓库** | 大量 `.pyc` 文件散布在项目目录中（含 Python 3.9 和 3.10 缓存），`__pycache__/` 目录被 Git 跟踪。 |
| 19 | **缺少 .gitignore** | 没有 `.gitignore` 文件，`__pycache__/`、`*.pyc`、`src_code/` 等均应被忽略。 |
| 20 | **src_code/ 目录与项目代码混杂** | `src_code/` 存放了 `claude-code-2.1.88.tgz` 源码，体积大且不应与项目代码混在同一仓库。 |

---

## 三、README 与实际结构不一致

README 描述的架构是单文件结构（`agent.py`、`tool.py`、`tools.py` 等），但实际代码已拆分为多模块结构：

```
实际文件结构                    README 描述
─────────────────────────────────────────────────
core/agent.py                  agent.py
tools/base.py                  tool.py
tools/*_tool.py + registry.py  tools.py
tools/orchestrator.py          tool_orch.py
memory/system.py + types.py    memory.py / memory_types.py
history/store.py               history.py
core/compact.py                compact.py
core/prompt.py                 prompt.py
core/query_config.py           query_config.py
core/query_deps.py             query_deps.py
llm/client.py                  llm.py
state/session.py               state.py
cli/repl.py + commands.py + ... main.py (已拆分)
```

**建议**：更新 README 中的文件结构表格以匹配实际模块布局。

---

## 四、PRD 待办项（来自 `prd/todo.txt`）

以下功能尚未实现，说明项目仍处于早期开发阶段：

- 流式工具调用（目前 LLM 响应完全返回后才解析 tool_use）
- Compact 代码重写
- 子 Agent 调用机制
- 权限系统（harness）
- 文件追踪 / 复原（worktree）
- 日志和追踪系统

---

## 五、建议修复顺序

### 第一梯队（阻断性，立即修复）
1. `requirements.txt` 补充 `httpx` — 否则 `pip install` 后无法运行
2. `cli/config.py` 将 `MAX_TURNS` 默认值从 `"10"` 改回 `"100"` — 与 README 一致
3. `cli/repl.py` 打开 SSL 验证（`verify_ssl = True`）— 安全风险

### 第二梯队（功能性 Bug，近期修复）
4. Grep glob 改用 `pathlib.PurePath.match()` 支持 `**` 递归匹配
5. 在 Agent Loop 中接入 `compact_with_llm()` 实现真正的 LLM 摘要压缩
6. MemorySystem 在 AgentLoop 初始化时缓存，避免每轮 IO

### 第三梯队（性能优化）
7. 并发工具批次改为 `asyncio.Queue` 流式输出
8. `should_auto_compact` 缓存 token 估算值，避免重复计算
9. `get_messages_for_model` 限制回溯深度减少解析开销

### 第四梯队（代码质量，可推迟）
10-20. 清理未使用导入、修复 AsyncClient 泄漏、添加 `.gitignore`、更新 README 等

---

## 统计

| 优先级 | 数量 | 核心问题 |
|--------|------|----------|
| 阻断 | 3 | httpx 缺失、MAX_TURNS 默认值错误、SSL 关闭 |
| 高 | 3 | 压缩未接入 LLM、SSL 验证关闭、Grep glob bug |
| 中 | 4 | 重复 IO、并发缓冲、重复计算、环境变量冗余 |
| 低 | 10 | 未使用导入、连接泄漏、缓存污染、工程规范等 |
| **合计** | **20** | |
