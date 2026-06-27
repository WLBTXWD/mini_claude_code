# Changelog

## 2026-06-27

### Added
- **`/resume` 斜杠命令** — 可在 REPL 运行时切换历史 session，不需要通过 `--resume` CLI 参数
  - `/resume`（无参数）：列出最近 20 个会话，交互选择
  - `/resume <sessionId>`：短 UUID 前缀匹配，直接切换
  - 切换后自动刷新上下文消息，parentUuid 链正确续接

### Changed
- **实时交互展示统一为 `/resume` 风格** — `repl_loop()` 中的流式输出格式与 `_display_message_history()` 完全一致：
  - 文本首行 `Claude:`（绿色）前缀，续行 10 空格缩进
  - 工具调用 `[Tool] name(args)`（黄色），完整展示参数
  - 工具结果 `-> [ok, N chars]` 紧凑标记
  - 移除 `[Turn N complete]` 和静态 `Assistant: ` 前缀

### Changed
- **`/resume` 历史展示紧凑化** — 工具结果不再打印完整内容：
  - 成功：`-> [ok, N chars]`
  - 错误：`-> [error] <前80字符>`
  - 空结果：`-> [empty]`
  - 工具参数 > 60 字符的值完整展示（多行值 16 空格缩进）
  - 各轮次间用空行分组

### Changed
- **`agent.py`** — `tool_execution_start` 事件新增 `tool_calls` 字段，携带工具名和参数供 REPL 展示

---

## 2026-06-26

### Added
- **历史记录持久化系统** — 照搬 Claude Code 的 sessionStorage 实现：
  - `history.py` — `HistoryStore` 类：JSONL 格式，`parentUuid → uuid` 单链表
  - `BatchedWriter` — 100ms 防抖批量写入（匹配 Claude Code `FLUSH_INTERVAL_MS`）
  - Session Resume — `get_messages_for_model()` 将 JSONL 转回 LLM API 兼容格式
  - Content Block Split — 每个 assistant block (text/tool_use/thinking) 独立 JSONL 行
  - 存储位置：`<project>/.mini_claude_code/<sessionId>.jsonl`

### Added
- **CLI 参数** — `--resume [sessionId]`、`--list-sessions`、`--session <id>`

### Fixed
- **`state.py`** — `session_id` 从 8 字符截断改为完整 36 字符 UUID
- **`llm.py`** — 流式调用现在捕获 `usage`（prompt_tokens / completion_tokens）并透传到 `final` 事件

### Changed
- **`agent.py`** — 接入 `HistoryStore`：每个 user 消息、assistant block、tool result 自动写入 JSONL
  - 新增 `initial_messages` 参数支持 resume
  - 每次 Agent 完成时 `flush()` session 缓冲区

### Changed
- **`main.py`** — 接入 `HistoryStore`：
  - REPL 启动时从历史加载上下文消息（替换旧的 `conversation_history` 摘要注入）
  - `/clear` 刷新旧 session、生成新 session ID
  - `/memory` 同时展示保存的会话列表
  - 退出时 `history.dispose()` 刷新所有缓冲区

