# Claude Code prompt 管理与注入机制解析

> 核验源码范围：`src/constants/prompts.ts`、`src/context.ts`、`src/utils/api.ts`、`src/services/api/claude.ts`、`src/query.ts`、`src/utils/attachments.ts`、`src/utils/messages.ts`、`src/memdir/*`。
>
> 结论先说：原文“三条管道：system / messages / tools”的大框架是对的，但若按当前 `src` 源码看，原文有几个关键误差：`git status` 属于 `system` 追加段而不是 `messages`；相关 memory 不是每次 API 调用前同步注入，而是用户 turn 开始时异步预取、工具循环后择机注入；tool definitions 的缓存策略也不能简单说“随 system prompt 一起缓存”。

---

## 1. 一次主模型请求的真实形态

Claude Code 最终调用 Anthropic Messages API 时，大体会形成三类输入：

```ts
anthropic.beta.messages.create({
  system: [
    { type: 'text', text: 'x-anthropic-billing-header: ...' },
    { type: 'text', text: 'You are Claude Code...' },
    { type: 'text', text: 'static instructions...', cache_control: ... },
    { type: 'text', text: 'session/memory/env/git/... dynamic sections', cache_control?: ... },
  ],
  messages: [
    { role: 'user', content: '<system-reminder>CLAUDE.md + date...</system-reminder>' },
    { role: 'user', content: '用户的真实输入' },
    { role: 'assistant', content: [{ type: 'tool_use', ... }] },
    { role: 'user', content: [{ type: 'tool_result', ... }] },
    { role: 'user', content: '<system-reminder>relevant memories / hooks / queued command...</system-reminder>' },
  ],
  tools: [
    { name: 'Bash', description: '...', input_schema: { ... }, cache_control?: ... },
    { name: 'Read', description: '...', input_schema: { ... }, cache_control?: ... },
  ],
})
```

这三类输入不是完全“互不相干”：

- `system` 和 `tools` 都参与 prompt caching，但 cache marker 的放置、作用域、MCP 工具影响会改变策略。
- 内部的 `AttachmentMessage` 会在 `normalizeMessagesForAPI()` 阶段变成 API 的 `user` message。
- 部分动态信息为了避免 bust cache，会从 system 挪到 attachment / delta attachment。

---

## 2. 管道 A：`system` 是系统提示块数组

主路径：

- `src/constants/prompts.ts:getSystemPrompt()` 构造基础 system prompt 字符串数组。
- `src/query.ts` 调用 `appendSystemContext(systemPrompt, systemContext)`，把 system context 追加进 system prompt。
- `src/services/api/claude.ts` 再 prepend attribution header 与 CLI system prompt prefix。
- `src/services/api/claude.ts:buildSystemPromptBlocks()` 把字符串数组拆成 Anthropic `TextBlockParam[]`，并按策略加 `cache_control`。

### 2.1 `getSystemPrompt()` 的主要组成

当前常规路径大致是：

1. 静态 instruction sections
   - Intro
   - System reminders 说明
   - Doing tasks
   - Actions
   - Using tools
   - Tone and style
   - Output efficiency

2. `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__`
   - 只在 `shouldUseGlobalCacheScope()` 开启时插入。
   - 该边界用于把前面的静态段标记为可 global cache，后面的动态段不使用 global cache。

3. 动态 sections
   - `session_guidance`
   - `memory`
   - `ant_model_override`
   - `env_info_simple`
   - `language`
   - `output_style`
   - `mcp_instructions`，注意这是 `DANGEROUS_uncachedSystemPromptSection`，因为 MCP 可能中途连接/断开。
   - `scratchpad`
   - `frc` / summarize tool results / token budget / brief 等 feature-gated section。

源码证据：`src/constants/prompts.ts:491-576`。

### 2.2 `systemContext` 也进入 `system`，不是 `messages`

这是原文最大的错误之一。

`getSystemContext()` 返回的是：

- `gitStatus`，包含会话开始时的 git status、当前 branch、main branch、recent commits 等。
- feature-gated 的 `cacheBreaker`。

它在 `query.ts` 中通过：

```ts
const fullSystemPrompt = asSystemPrompt(
  appendSystemContext(systemPrompt, systemContext),
)
```

追加到 system prompt 数组末尾。`appendSystemContext()` 做的事情也很直接：

```ts
return [
  ...systemPrompt,
  Object.entries(context).map(([key, value]) => `${key}: ${value}`).join('\n'),
].filter(Boolean)
```

因此：

- `CLAUDE.md` 和当前日期：来自 `getUserContext()`，进入 `messages` 的开头。
- `git status`：来自 `getSystemContext()`，进入 `system` 的末尾。

源码证据：`src/context.ts:113-150`、`src/utils/api.ts:437-447`、`src/query.ts:449-451`。

### 2.3 system prompt 的 cache 策略

`splitSysPromptPrefix()` 里有三种主要模式：

1. 有 MCP tools 且需要跳过 global system prompt cache
   - attribution header：不缓存。
   - CLI prefix：`org` scope。
   - 其余 system：`org` scope。

2. global cache 开启且找到动态边界
   - attribution header：不缓存。
   - CLI prefix：不缓存。
   - boundary 前的静态段：`global` scope。
   - boundary 后的动态段：不缓存。

3. 默认模式
   - attribution header：不缓存。
   - CLI prefix：`org` scope。
   - 其余 system：`org` scope。

所以不能简单说“system 整个会话期间不变、后续都不消耗 input token”。更准确的说法是：

- 部分 system section 在进程/会话内通过 `systemPromptSection()` 缓存，避免每轮重算。
- API 侧 prompt caching 只对带 `cache_control` 的块生效。
- dynamic block、MCP 相关 block、attribution header 等可能不缓存或改变缓存策略。
- `systemContext` 的 git status 文案本身说明它是“conversation start snapshot”，但它仍在 system 中发送，并依赖 cache 策略降低重复成本。

源码证据：`src/utils/api.ts:300-435`、`src/services/api/claude.ts:3213-3237`。

---

## 3. 管道 B：`messages` 是对话、工具结果和附件归一化后的消息

主路径：

- `query.ts` 在调用模型前传入 `messages: prependUserContext(messagesForQuery, userContext)`。
- `services/api/claude.ts` 里先调用 `normalizeMessagesForAPI(messages, filteredTools)`。
- `utils/messages.ts:normalizeMessagesForAPI()` 会过滤 progress/system display-only 消息、合并连续 user message、规范化 tool_use/tool_result、把 attachment 转成 user message。

### 3.1 `getUserContext()` 会 prepend 成一个 meta user message

`getUserContext()` 返回：

- `claudeMd`：从 `CLAUDE.md` / memory files 相关机制中读取出的上下文。
- `currentDate`：`Today's date is YYYY-MM-DD.`

`prependUserContext()` 把它们包装成：

```xml
<system-reminder>
As you answer the user's questions, you can use the following context:
# claudeMd
...
# currentDate
Today's date is ...

IMPORTANT: this context may or may not be relevant...
</system-reminder>
```

这是 `messages` 数组最前面的 meta user message。

源码证据：`src/context.ts:152-188`、`src/utils/api.ts:449-470`、`src/query.ts:659-661`。

### 3.2 工具调用和工具结果在 messages 中循环

模型返回 assistant message，里面可能包含 `tool_use` block。Claude Code 执行工具后，把结果作为 user message 中的 `tool_result` block 放回上下文。下一次 API 调用时，这些历史都会经过 `normalizeMessagesForAPI()`。

需要注意：Anthropic Messages API 中 tool result 通常不是独立 `role: 'tool'`，而是 user message content 里的 `tool_result` block。原文用 `{role:'tool'}` 做示意不够准确。

源码证据：`src/query.ts` 工具循环、`src/utils/messages.ts:2094-2290`。

### 3.3 AttachmentMessage 会在 API 前转成 user messages

Claude Code 内部有很多 `AttachmentMessage`：

- relevant memories
- nested memory
- hooks 结果
- task notifications
- queued commands
- skill listing / invoked skills
- MCP instructions delta
- changed files
- todo/task reminders

这些不是直接等价于用户输入，而是在 `normalizeMessagesForAPI()` 中走：

```ts
case 'attachment': {
  const rawAttachmentMessage = normalizeAttachmentForAPI(message.attachment)
  ...
  result.push(...attachmentMessage)
}
```

很多 attachment 会通过 `wrapMessagesInSystemReminder()` 包成 meta user message。

源码证据：`src/utils/messages.ts:2269-2290`、`src/utils/messages.ts:3524+`。

---

## 4. 管道 C：`tools` 是工具定义数组，但缓存策略独立于 system 文本

主路径：

- `query.ts` 把 `toolUseContext.options.tools` 传给 `deps.callModel()`。
- `services/api/claude.ts` 过滤和构建 tool schema。
- `utils/api.ts:toolToAPISchema()` 把每个 Tool 转成 Anthropic tool schema。

工具 schema 包括：

- `name`
- `description`
- `input_schema`
- 可能的 tool-specific 字段，例如 defer loading / tool search 相关字段。
- 可能的 `cache_control`。

原文说“工具定义被包含在 prompt cache 前缀中 / 随 system prompt 一起缓存”太粗略。更准确地说：

- tools 是 API 的单独参数，不在 `system` 文本数组里。
- Anthropic 的 prompt cache 可以对 tools 里的某些位置加 cache marker。
- 当 MCP tools 存在时，Claude Code 可能禁用 system prompt 的 global cache strategy，因为 MCP tools 是 per-user/dynamic。
- tool search、deferred tools、MCP delta instructions 都会改变工具实际发送和提示方式。

源码证据：`src/services/api/claude.ts:1207-1246`、`src/services/api/claude.ts:1374-1397`、`src/utils/api.ts:119+`。

---

## 5. Memory 机制：要区分“memory prompt”“memory index”“relevant memory content”

原文把 memory 拆成三层是有价值的，但当前源码有更多条件分支。

### 5.1 `loadMemoryPrompt()` 进入 system 的 `memory` section

`getSystemPrompt()` 中：

```ts
systemPromptSection('memory', () => loadMemoryPrompt())
```

`loadMemoryPrompt()` 的行为取决于功能开关和运行模式：

- auto memory 关闭：返回 `null`。
- Kairos daily-log 模式：返回 daily log 风格的 memory prompt。
- team memory 开启：返回 combined team/auto memory prompt。
- 普通 auto memory：确保 memory dir 存在，然后返回 `buildMemoryLines(...)`。
- `tengu_moth_copse` / `skipIndex` 可能影响是否包含 MEMORY.md index。

所以不能绝对写成“system 中一定有 MEMORY.md 索引”。更准确是：system 里可能有 memory 使用说明和索引，取决于 auto memory / team memory / Kairos / feature gates。

源码证据：`src/constants/prompts.ts:491-496`、`src/memdir/memdir.ts:419-507`。

### 5.2 relevant memories 进入 messages，但不是每轮同步阻塞注入

当前源码不是“每轮 API 调用前同步 findRelevantMemories”。真实流程是：

1. 用户 turn 开始时，`query.ts` 调用 `startRelevantMemoryPrefetch(state.messages, state.toolUseContext)`。
2. `startRelevantMemoryPrefetch()` 找到最后一个真实 user message，过滤单词太短、auto memory 关闭、feature gate 未开、session memory byte 上限等情况。
3. 它异步启动 `getRelevantMemoryAttachments()`，内部调用 `findRelevantMemories()`。
4. 主模型先流式回复、执行工具。
5. 工具循环后，`query.ts` 检查 prefetch 是否已经 settled：
   - 如果已完成，则 `filterDuplicateMemoryAttachments()` 后把 relevant memories 作为 attachment message 注入。
   - 如果还没完成，则本轮不等待，下一次循环再试。

这意味着 relevant memory 注入是“非阻塞预取 + 工具后择机注入”，而不是“每轮 API 调用前一定注入”。

源码证据：`src/query.ts:300-304`、`src/query.ts:1592-1614`、`src/utils/attachments.ts:2334-2424`。

### 5.3 relevant memory 的选择与去重

`findRelevantMemories()` 做的是：

- 扫描 memory dir 的 headers。
- 排除 already surfaced 的路径。
- 用 Sonnet side query 从 manifest 里最多选择 5 个 filename。
- `MEMORY.md` 本身不作为 relevant memory 内容再选，因为它已属于 index / prompt 体系。

随后 `getRelevantMemoryAttachments()` 还会：

- 如果用户 @agent，则优先搜索该 agent 的 memory dir。
- 排除 `readFileState` 里已读过的文件。
- 排除已经 surfaced 的路径。
- 最多取 5 个。
- 读取文件内容时按 `MAX_MEMORY_LINES` / `MAX_MEMORY_BYTES` 截断。

源码证据：`src/memdir/findRelevantMemories.ts:18-75`、`src/utils/attachments.ts:2196-2241`、`src/utils/attachments.ts:2268-2321`。

### 5.4 relevant memories 最终如何进入 API

内部 attachment 类型是：

```ts
{ type: 'relevant_memories', memories: [...] }
```

到 `normalizeAttachmentForAPI()` 时变为多个 meta user message，每个 message 内容类似：

```text
Memory (saved ...): /path/to/memory.md:

<file content, maybe truncated>
```

然后被 `wrapMessagesInSystemReminder()` 包装。连续 user messages 还可能被 `normalizeMessagesForAPI()` 合并。

源码证据：`src/utils/messages.ts:3708-3721`、`src/utils/messages.ts:2269-2290`。

---

## 6. 正确版速查表

| 内容 | API 参数 | 内部来源 | 注入/刷新时机 | 备注 |
|---|---|---|---|---|
| 静态行为指令 | `system` | `getSystemPrompt()` 静态 sections | 每次构造请求都会传入，但部分由本地/服务端缓存降低成本 | boundary 前可 global cache |
| Session guidance | `system` | `getSessionSpecificGuidanceSection()` | system prompt 动态 section | 受启用工具、模式、feature gates 影响 |
| Memory 使用说明/索引 | `system` | `loadMemoryPrompt()` | system prompt `memory` section | 可能为 null；受 auto/team/Kairos/skipIndex 影响 |
| 环境信息 | `system` | `computeSimpleEnvInfo()` | system prompt 动态 section | cwd、platform、model 等 |
| Git status | `system` | `getSystemContext()` + `appendSystemContext()` | 会话开始快照，memoized | 不是 messages |
| CLAUDE.md | `messages` | `getUserContext()` + `prependUserContext()` | 会话上下文，memoized | meta user message / system-reminder |
| 当前日期 | `messages` | `getUserContext()` | 会话上下文，memoized | 日期 rollover 可能另有 attachment 机制 |
| 真实用户输入 | `messages` | REPL / SDK 输入处理 | 每 turn | 普通 user message |
| assistant 回复 | `messages` | API 响应历史 | 每 turn / tool loop | 可含 `tool_use` block |
| 工具结果 | `messages` | 工具执行结果 | tool loop | user message 中的 `tool_result` block，不是独立 `role:'tool'` |
| relevant memory 内容 | `messages` | `startRelevantMemoryPrefetch()` -> `findRelevantMemories()` -> attachment | 非阻塞预取，工具后如果 ready 才注入 | 最多 5 个，去重，可能截断 |
| hooks/task/queued 等提醒 | `messages` | attachments/hooks/tasks/queue | 条件触发 | 多数转成 meta user message |
| 工具定义 | `tools` | `toolToAPISchema()` | 每次请求构造 filtered tool schemas | 可参与 cache，但不是 system 文本 |

---

## 7. 对原文的审查结论

原文正确的地方：

- 用 `system / messages / tools` 三条管道理解整体结构是合理的。
- `getSystemPrompt()`、`buildSystemPromptBlocks()`、`prependUserContext()`、`toolToAPISchema()` 是关键路径。
- memory 要区分说明/索引/内容，这个方向是对的。
- relevant memories 最终确实通过 `<system-reminder>` 风格的 meta user message 进入上下文。

原文需要修正的地方：

- `git status` 不在 messages，而是 system prompt 末尾的 `systemContext`。
- system 不是“整个会话期间内容不变”的单一块；它有静态段、动态段、uncached MCP 段、append 的 systemContext，以及多种 cache scope。
- “只有第一次 API 调用计 input token”说法过度简化；实际取决于 cache_control、cache hit、动态 block、tools/MCP 策略。
- relevant memories 不是每轮 API 调用前同步注入，而是 turn-level async prefetch，工具循环后 ready 才注入。
- tool result 不是 `{ role: 'tool' }`，Anthropic Messages API 中通常是 user message 里的 `tool_result` block。
- tools 是单独 API 参数，不能说“包含在 system prompt 前缀中”；只能说 tools 也可参与 prompt caching，且会影响 system global cache 策略。
- `MEMORY.md` index 不是无条件进入 system；取决于 memory 系统启用状态和 feature gates。
