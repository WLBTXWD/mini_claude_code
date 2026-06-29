# 代码审查：优化建议

> 审查日期：2026-06-29  
> 审查范围：`main.py`, `core/`, `cli/`, `tools/`, `llm/`, `history/`, `memory/`, `state/`

---

## 高优先级（功能/Security Bug）

### 1. 压缩功能未接入 LLM 摘要

**文件**: `core/compact.py:73`  
**问题**: `compact_messages()` 只做了简单截断 + 占位文本，从未调用 `compact_with_llm()`。README 声称有"摘要式压缩"能力但实际上没有接入。

```python
# 当前实现只是字符串拼接
summary = f"[Context compacted. Previous {len(messages) - preserve_last_n - ...} messages summarized.]"
```

**影响**: 长对话截断后丢失大量上下文，LLM 拿不到有效摘要。  
**修复方向**: 在 `agent.py` 的压缩触发点接入 `compact_with_llm()`，或至少用 LLM 生成摘要后再替换。

---

### 2. SSL 验证被硬编码关闭

**文件**: `cli/repl.py:30`  
**问题**: 硬编码 `verify_ssl = False`，关闭了所有 HTTPS 连接的 SSL 证书验证。

```python
verify_ssl = False
llm = LLMClient(
    api_key=session.api_key,
    base_url=session.base_url,
    model=session.model,
    verify_ssl=verify_ssl,
)
```

**影响**: API 密钥和对话内容可能被中间人窃取。  
**修复方向**: 默认 `verify_ssl=True`，仅在内网/自签环境且用户显式配置时才关闭。

---

### 3. Grep 工具的 glob 过滤不支持 `**` 递归模式

**文件**: `tools/search_tools.py:77-78`  
**问题**: 使用 `fnmatch.fnmatch` 做 glob 过滤，但 `fnmatch` 不识别 `**` 递归通配符。

```python
if glob_mod.fnmatch.fnmatch(relpath, glob_filter) or glob_mod.fnmatch.fnmatch(f, glob_filter):
    files_to_search.append(filepath)
```

**影响**: 用户传 `glob="**/*.py"` 时不会匹配子目录中的文件，搜索结果不完整。  
**修复方向**: 改用 `pathlib.PurePath.match()` 或手动将 `**` 展开为正则 `.*`。

---

## 中优先级（性能/设计问题）

### 4. MemorySystem 每轮重复创建和文件 IO

**文件**: `core/agent.py:298-302`  
**问题**: `_get_system_prompt()` 每次调用都 new `MemorySystem` 并读取 `MEMORY.md`。

```python
def _get_system_prompt(self, system_context=None):
    memory = MemorySystem(self.session.project_root or self.session.cwd)  # 每轮 new
    memory_prompt = memory.load_memory_prompt()                            # 每轮 read disk
```

**影响**: 每个 turn 都做一次文件 IO，不必要的 syscall。  
**修复方向**: 在 `AgentLoop.__init__` 中创建一次 `MemorySystem` 并缓存 `memory_prompt`，或 `MemorySystem` 内部加缓存。

---

### 5. 并发工具批次的输出被完全缓冲后才 yield

**文件**: `tools/orchestrator.py:89-100`  
**问题**: 并发批次的 `asyncio.gather` 等所有任务完成才 yield 结果。

```python
async def run_one(block):
    results = []
    async for update in self._run_tool_serially(block, context):
        results.append(update)   # 全部缓冲
    return results

all_results = await asyncio.gather(*tasks)   # 等所有完成
for results in all_results:                   # 才开始 yield
    for update in results:
        yield update
```

**影响**: 用户看到工具结果有额外延迟，体验差。  
**修复方向**: 用 `asyncio.Queue` 或 `asyncio.as_completed` 流式输出，先完成先展示。

---

### 6. should_auto_compact + compact_messages 重复计算 token

**文件**: `core/agent.py:118-122`  
**问题**: `should_auto_compact()` 内部调用 `estimate_tokens()` 计算一次，通过后 `compact_messages()` 又做一次列表切片和比较。

```python
if config.auto_compact_enabled and self.compactor.should_auto_compact(state.messages):
    compacted = self.compactor.compact_messages(state.messages)
    if compacted != state.messages:  # list O(n) 比较
```

**影响**: 无谓的 O(n) 计算，每轮都有开销。  
**修复方向**: `should_auto_compact` 返回估算值，避免二次计算；用 `is` 或 flag 代替 list 比较。

---

### 7. `load_config()` 中环境变量重复查找

**文件**: `cli/config.py:15-18`  
**问题**: `os.environ.get` 的默认值参数重复了相同的查找。

```python
session.api_key = os.environ.get(
    "DEEPSEEK_API_KEY",
    os.environ.get("DEEPSEEK_API_KEY", ""),  # 默认值做了无用功
)
```

**影响**: 无实际影响，但代码意图不清。  
**修复方向**: 简化为 `os.environ.get("DEEPSEEK_API_KEY", "")`。

---

## 低优先级（代码质量 / 可维护性）

### 8. `main.py` 中存在未使用的导入

**文件**: `main.py:11`  
**问题**: `list_sessions_cmd` 和 `do_resume` 被导入但从未直接使用（由 `cli/commands.py` 调用）。

```python
from cli.sessions import list_sessions_cmd, do_resume  # 未使用
```

**修复方向**: 移除这两个导入。

---

### 9. httpx.AsyncClient 没有生命周期管理

**文件**: `llm/client.py:37`  
**问题**: `httpx.AsyncClient` 实例在 `LLMClient` 析构时不会自动关闭。

```python
http_client = httpx.AsyncClient(**http_client_kwargs)
self.client = AsyncOpenAI(http_client=http_client)
```

**影响**: 每次创建 `AgentLoop`（即在 REPL 中每轮都 new agent）会泄漏连接和文件描述符。  
**修复方向**: 实现 `aclose()` + 上下文管理器，或复用 `LLMClient` 实例而非每轮创建。

---

### 10. 延迟导入放在 `while True` 循环内部

**文件**: `core/agent.py:227-228`  
**问题**: `from tools.base import ToolUseContext` 在 `while True` 循环内。

```python
from tools.base import ToolUseContext  # 在 while True 内
context = ToolUseContext(...)
```

**影响**: 实际无性能影响（Python 导入有缓存），但不符合代码规范。  
**修复方向**: 移至文件顶部。

---

### 11. `get_messages_for_model` 截断时机不对

**文件**: `history/store.py:341`  
**问题**: `max_entries` 截断在结果构建完成后执行，意味着前面做了全量解析和合并。

```python
return result[-max_entries:] if len(result) > max_entries else result
```

**影响**: 大 session resume 时不必要的 CPU 和内存开销。  
**修复方向**: 在 `build_chain` 时即限制回溯深度，或加载 JSONL 时只读最后 N 行。

---

### 12. `parse_frontmatter` 可能读取不完整的 YAML

**文件**: `memory/system.py:90`  
**问题**: 只读取前 3000 字符，如果 YAML frontmatter 的 `---` 闭合标签在第 3000 字符之后，解析会失败。

```python
frontmatter_text = f.read(3000)  # 可能截断 --- 闭合标签
fm = parse_frontmatter(frontmatter_text)
```

**修复方向**: 逐行读取直到找到第二个 `---`，而非硬编码 3000 字符限制。

---

## 汇总

| 优先级 | 数量 | 核心问题 |
|--------|------|----------|
| 高 | 3 | SSL 安全、压缩功能未实现、Grep glob bug |
| 中 | 4 | 每轮重复 IO、并发缓冲延迟、冗余 token 计算、重复环境变量 |
| 低 | 5 | 未使用导入、AsyncClient 泄漏、延迟导入位置、截断时机、YAML 截断 |
