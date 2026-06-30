# Claude Code 的上下文压缩逻辑

> 这篇文档按“它为什么要压缩、什么时候压缩、压缩时具体做什么、压缩后如何继续工作”的顺序来解释 Claude Code 的上下文压缩策略。参考源码主要包括 `src/query.ts`、`src/services/compact/autoCompact.ts`、`src/services/compact/compact.ts`、`src/services/compact/microCompact.ts`、`src/services/compact/prompt.ts` 和 `src/utils/messages.ts`。

## 1. 先说结论

Claude Code 的上下文压缩不是一个简单的“超过 token 阈值就总结历史”的功能。它更像一套分层的上下文管理系统。

它的核心目标有三个：

1. 尽量不要丢掉对继续写代码有用的信息。
2. 尽量不要让一次超长对话把模型上下文撑爆。
3. 尽量减少 prompt cache 被破坏带来的成本。

所以 Claude Code 不会一上来就把所有历史压成摘要。它会先尝试更轻量的处理，比如清理旧工具结果、折叠部分上下文；只有这些不够时，才启动完整的 LLM 摘要压缩。

可以把它理解成下面这条链路：

```text
完整历史
  -> 取最近一次 compact 之后的有效历史
  -> 控制过大的 tool result
  -> 清理旧工具结果 microcompact
  -> 尝试局部折叠 context collapse
  -> 如果仍接近上限，做 LLM 摘要压缩 autocompact
  -> 如果 API 仍报 prompt-too-long，再做 reactive compact 并重试
```

这条链路发生在 `query.ts` 中，也就是 Claude Code 每次准备调用主模型之前。

## 2. 分层触发地图

Claude Code 的压缩机制可以分成 6 层。它们不是同一时间触发，也不是同一种压缩强度。

最清晰的理解方式是：前三层发生在“调用模型之前”，第四层是“接近上下文上限时”，第五层是“API 已经报错后”，第六层是“压缩完成后的恢复层”。

```text
每次 query 进入模型前
  |
  |-- 第 1 层：compact boundary 切片
  |      触发时机：每次请求前都会执行
  |      作用：如果之前压缩过，只取最近一次压缩之后的消息
  |
  |-- 第 2 层：tool result budget
  |      触发时机：每次请求前都会检查
  |      作用：限制单个或一组工具结果过大
  |
  |-- 第 3 层：microcompact / context collapse
  |      触发时机：满足轻量压缩条件时
  |      作用：先清理旧工具结果，或局部折叠上下文
  |
  |-- 第 4 层：proactive autocompact
  |      触发时机：token 估算超过自动压缩阈值
  |      作用：启动 compact agent，把旧历史总结成 summary
  |
  v
调用主模型 API
  |
  |-- 第 5 层：reactive compact
  |      触发时机：API 返回 prompt-too-long 或媒体过大
  |      作用：压缩后重试当前 query
  |
  v
压缩成功后
  |
  |-- 第 6 层：post-compact restore
         触发时机：full compact / reactive compact 成功后
         作用：补回最近文件、plan、skills、agent 状态等关键上下文
```

这 6 层里，真正会调用 LLM 生成摘要的主要是第 4 层和第 5 层。前 3 层更像“瘦身”和“投影视图”，第 6 层则是“恢复工作现场”。

下面这张表把它们放在一起看：

| 层级 | 名称 | 触发时机 | 是否调用 LLM 摘要 | 主要处理对象 |
|---|---|---|---|---|
| 1 | compact boundary 切片 | 每次 query 前 | 否 | 已压缩过的旧历史 |
| 2 | tool result budget | 每次 query 前 | 否 | 超大的工具结果 |
| 3 | microcompact / context collapse | 满足轻量压缩条件时 | 通常否 | 旧工具结果、可折叠上下文 |
| 4 | proactive autocompact | token 超过自动压缩阈值 | 是 | 旧对话历史 |
| 5 | reactive compact | API 真实返回超限错误后 | 是 | 当前失败请求的上下文 |
| 6 | post-compact restore | full compact 成功后 | 否 | 文件、plan、skills、agent 状态 |

一个容易混淆的点是：`microcompact`、`context collapse`、`autocompact` 都发生在主模型调用之前，但它们的触发条件不同。

`microcompact` 关注的是“有没有旧工具结果可以清理”。它不一定等到 token 快爆才做，尤其 time-based microcompact 看的是缓存是否大概率过期。

`context collapse` 关注的是“有没有局部上下文可以折叠”。它的目标是避免过早进入 full compact。

`autocompact` 关注的是“整体 token 是否已经超过阈值”。它是主动摘要压缩，成本和信息损失都更大，所以排在更后面。

`reactive compact` 则完全不同：它不是预防性动作，而是 API 已经失败后的补救动作。

## 3. 按时间线看一次 query

如果把 Claude Code 的一次主循环按时间顺序展开，它大概是这样：

```text
用户输入 / 工具结果进入 messages
  |
  v
query.ts 准备下一次模型请求
  |
  |-- 1. getMessagesAfterCompactBoundary()
  |      如果之前 compact 过，只拿 compact boundary 之后的消息
  |
  |-- 2. applyToolResultBudget()
  |      如果某些 tool result 太大，先做预算内替换或压缩
  |
  |-- 3. snipCompactIfNeeded()
  |      如果启用 HISTORY_SNIP，投影掉 snipped 历史
  |
  |-- 4. deps.microcompact()
  |      如果旧工具结果满足条件，做 microcompact
  |
  |-- 5. contextCollapse.applyCollapsesIfNeeded()
  |      如果启用 context collapse，尝试局部折叠
  |
  |-- 6. deps.autocompact()
  |      如果 token 超过阈值，做完整 summary compact
  |
  |-- 7. normalizeMessagesForAPI()
  |      把内部 message / attachment 归一化为 API 能理解的 messages
  |
  v
调用 Claude Messages API
  |
  |-- 成功：继续正常 tool loop 或输出最终回答
  |
  |-- prompt-too-long / media too large：
        先尝试 context collapse drain
        再尝试 reactive compact
        成功后回到 query.ts 开头重试当前请求
```

这条时间线里，最重要的分界点是“调用 API 之前”和“调用 API 之后”。

调用 API 之前的压缩叫 proactive，也就是提前预防。`microcompact`、`context collapse`、`autocompact` 都属于这一类。

调用 API 之后的压缩叫 reactive，也就是失败补救。只有当真实 API 返回可恢复的超限错误时，它才会发生。

所以完整顺序可以记成：

```text
先切片
再清工具结果
再轻量折叠
再主动摘要
然后调用模型
失败后再补救压缩
```

## 4. 模型看到的不是完整 transcript

Claude Code 会保存完整会话历史，但每次发给模型的不一定是完整历史。

在 `query.ts` 开头，它会先执行类似这样的逻辑：

```ts
let messagesForQuery = [...getMessagesAfterCompactBoundary(messages)]
```

意思是：如果之前发生过 compact，就从最近一个 `compact_boundary` 之后开始取消息。更早的原始消息不会再直接进入模型上下文，因为它们已经被摘要替代了。

`compact_boundary` 本身是一条 system 类型的边界消息，主要用于本地历史管理。它告诉系统：

- 这里发生过一次压缩。
- 这次压缩是手动还是自动触发的。
- 压缩前大约有多少 tokens。
- 压缩前最后一条消息是谁。

边界后面通常会跟一条 compact summary。之后模型继续工作时，看到的是“摘要 + 压缩后保留的最近上下文 + 重新注入的关键附件”，而不是压缩前的全部历史。

这就是 Claude Code 压缩逻辑的第一层：不是直接删除历史，而是在模型视角中用 summary 替换旧历史。

## 5. 自动压缩什么时候触发

自动压缩的阈值在 `autoCompact.ts` 里计算。它不是一个固定比例，而是基于模型上下文窗口动态算出来的。

大致公式是：

```text
有效上下文窗口 = 模型上下文窗口 - 摘要输出预留空间
自动压缩阈值 = 有效上下文窗口 - 13,000 tokens buffer
```

其中摘要输出预留空间最多是 20,000 tokens：

```text
reservedTokensForSummary = min(modelMaxOutputTokens, 20,000)
```

为什么要这样算？

因为压缩本身也要调用模型生成 summary。如果当前上下文已经完全贴着模型上限，压缩请求本身也可能失败。所以 Claude Code 会提前留出空间，保证 compact agent 有足够 token 写出摘要。

另外，它还会再留 13,000 tokens 的 buffer。这个 buffer 是给下一轮对话、系统提示、工具定义、用户上下文等动态内容留余量的。

所以 Claude Code 的自动压缩不是“满了才压”，而是“快满之前就压”。

## 6. 压缩前，先处理工具结果

Claude Code 对工具结果特别谨慎，因为 coding agent 的上下文经常不是被聊天内容撑爆，而是被工具输出撑爆。

比如：

- `Read` 读了一个很大的文件。
- `Bash` 输出了大量日志。
- `Grep` 返回了很多匹配结果。
- `WebFetch` 抓了很长的网页。

这些内容有时只在当下有用，过几轮之后就没必要完整保留。

所以在完整摘要压缩前，Claude Code 会先做 microcompact。它主要处理这些工具：

- `Read`
- shell / `Bash`
- `Grep`
- `Glob`
- `WebSearch`
- `WebFetch`
- `Edit`
- `Write`

microcompact 有两个重要思路。

第一种是 cached microcompact。它尽量不改本地消息，而是用 API 的 cache editing 能力删除旧工具结果对应的缓存内容。这样可以减少上下文成本，又尽量不破坏 prompt cache。

第二种是 time-based microcompact。如果距离上一次主线程 assistant 消息已经很久，比如超过 60 分钟，服务端 prompt cache 大概率已经过期。此时继续保护旧缓存意义不大，于是 Claude Code 会直接把旧工具结果内容替换为：

```text
[Old tool result content cleared]
```

它通常会保留最近几个工具结果，清掉更老的结果。这样做比完整摘要更轻，因为它不会重写整段对话，只是把旧工具输出变短。

## 7. Context collapse：比完整压缩更温和的一层

在某些构建中，Claude Code 还有一层 `context collapse`。

它发生在 autocompact 之前。源码注释里的理由很清楚：如果 collapse 已经能把上下文降到自动压缩阈值以下，那就不需要把整段历史压成一个 summary。

可以这么理解：

- full compact 是“把旧历史总结成一段摘要”。
- context collapse 是“把部分历史折叠成更短的视图”。

full compact 更激进，信息损失更大。context collapse 更细粒度，可以尽量保留结构化的上下文。因此 Claude Code 会优先尝试更温和的 collapse，再考虑完整摘要。

这体现了 Claude Code 的一个重要设计原则：能不 summary 就先不 summary，因为 summary 一旦生成，原始细节就从模型视角里消失了。

## 8. 真正的 full compact 怎么做

如果前面的轻量处理还不够，Claude Code 会进入完整压缩，也就是 `compactConversation()`。

完整压缩不是在当前主循环里随手拼一个摘要，而是启动一个专门的 compact agent。这个 compact agent 的任务只有一个：阅读当前对话，生成一份适合继续工作的详细 summary。

它不能使用工具。源码里有专门的限制：compact agent 必须只输出文本，不能调用 `Read`、`Bash`、`Grep` 等工具。这样可以避免压缩过程又引入新的工具循环。

完整压缩的大致流程是：

1. 统计压缩前 token 数。
2. 执行 `PreCompact` hooks，允许外部补充压缩指令。
3. 构造 compact prompt。
4. 调用 compact agent 生成 summary。
5. 如果 compact 请求本身也 prompt-too-long，就从最旧的 API round 开始截断并重试。
6. 生成 summary 后，清空一些旧的运行时状态，比如 read file state。
7. 创建 compact boundary。
8. 创建 compact summary message。
9. 生成压缩后的恢复附件。
10. 执行 `SessionStart` 和 `PostCompact` hooks。
11. 返回新的 post-compact messages。

这里最关键的是第 4 步和第 9 步：Claude Code 既生成摘要，也会补回一些摘要不适合承载的精确信息。

## 9. Summary 里必须保留什么

Claude Code 的 compact prompt 不是普通“帮我总结一下聊天记录”。它非常强调“下一轮能继续工作”。

summary 要覆盖这些内容：

- 用户的主要请求和真实意图。
- 关键技术概念、库、框架、代码模式。
- 读过、改过、创建过的文件。
- 关键代码片段、函数签名、文件路径。
- 遇到的错误和修复方式。
- 用户给过的反馈，尤其是纠正或改变方向的反馈。
- 所有用户消息，排除工具结果。
- 仍未完成的任务。
- 压缩发生前正在做什么。
- 如果有下一步，下一步必须直接服务于最近的用户请求。

这份 summary 的用途不是给人回顾，而是让模型在失去旧上下文后还能继续干活。

所以它会特别关注：

- 文件名。
- 代码位置。
- 修改原因。
- 当前状态。
- 用户明确要求。
- 尚未完成的动作。

这是 Claude Code 压缩策略和普通聊天摘要最大的区别。

## 10. 压缩后不只剩 summary

压缩结果不是只有一条 summary。`buildPostCompactMessages()` 定义了压缩后的消息顺序：

```text
compact boundary
compact summary
保留的最近原始消息
压缩后恢复附件
hook 产生的消息
```

其中恢复附件很重要。因为有些东西不能只靠 summary。

比如模型刚刚读过一个文件。如果只在 summary 里写“读过 app.py”，下一轮模型并不知道文件的具体内容。于是 Claude Code 会尝试把最近读过的文件重新作为 attachment 注入回来。

它会恢复的内容包括：

- 最近读过的文件，最多 5 个。
- 每个恢复文件最多 5,000 tokens。
- 文件恢复总预算最多 50,000 tokens。
- 当前 plan 文件。
- plan mode 状态。
- 已经 invoked 的 skills。
- 仍在运行或已完成但结果未取回的异步 agent 状态。
- deferred tools、agent listing、MCP instructions 的增量说明。

这说明 Claude Code 并不把 summary 当成万能容器。它知道有些信息应该摘要，有些信息应该原样或近似原样恢复。

## 11. 如果压缩也失败怎么办

Claude Code 明确考虑了“压缩本身也会失败”的情况。

最常见的是：原始上下文太大，导致 compact agent 的请求也 prompt-too-long。

这种情况下，它会进行有限重试：从最旧的 API round 开始截断一部分历史，再重新请求 summary。这样虽然会丢掉一部分最旧内容，但比完全卡死要好。

它还有连续失败熔断：

```text
自动压缩连续失败 3 次后，本 session 不再反复尝试自动压缩
```

这样可以避免某些不可恢复会话无限执行：

```text
尝试压缩 -> 失败 -> 下一轮又尝试压缩 -> 再失败 -> 无限消耗 API 调用
```

另外，`compact` 自己、`session_memory` 自己这类特殊 query source 不会触发自动压缩。否则会出现“压缩代理自己又被压缩”的死锁。

## 12. Reactive compact：报错之后的补救

即使 proactive autocompact 没有触发，API 真实请求仍然可能返回 prompt-too-long。

原因很简单：本地 token 估算不一定精确，而且最终请求还包括 system prompt、tools、user context、attachments 等内容。

Claude Code 对这类错误有一个 reactive recovery 机制。

在 streaming loop 中，如果遇到可恢复的 prompt-too-long 或媒体过大错误，它不会立刻把错误展示给用户，而是先把错误暂存起来。请求结束后，它会尝试恢复：

1. 如果启用了 context collapse，先 drain 已 staged 的 collapse。
2. 如果还是不行，再尝试 reactive compact。
3. reactive compact 成功后，用压缩后的 messages 替换当前 state。
4. 然后 `continue`，重新执行当前 query。
5. 如果恢复失败，才把错误展示给用户并退出。

这就是为什么 Claude Code 有时能在上下文超限后自动“缓一口气”继续跑，而不是直接把 prompt-too-long 扔给用户。

不过它也会防止死循环。`hasAttemptedReactiveCompact` 会记录本轮是否已经做过 reactive compact。如果压缩后仍然超限，就不再无限重试。

## 13. 和 prompt cache 的关系

Claude Code 的压缩逻辑和 prompt cache 绑得很紧。

它不是只关心“上下文够不够放”，还关心“这样处理会不会让缓存成本暴涨”。

几个例子：

- compact agent 优先通过 forked agent 复用主对话的 prompt cache。
- cached microcompact 使用 cache edits，而不是直接改本地消息。
- time-based microcompact 只在缓存大概率过期后才直接清理旧内容。
- 压缩成功后会通知 cache break detection，避免把正常的 cache read 下降误判为异常。
- 压缩后会重置 cache read baseline。

这背后的思路是：长对话不仅有上下文窗口问题，也有成本问题。压缩策略必须同时照顾两者。

## 14. 用一句话概括整个流程

Claude Code 的上下文压缩逻辑可以概括为：

```text
先尽量清理低价值的大块内容；
再尽量用局部折叠保留细节；
最后才用 LLM summary 替换旧历史；
压缩后再把继续工作必需的精确信息补回来；
如果真实 API 仍然超限，就做一次 reactive compact 并重试。
```

它不是“删除历史”，而是“重构模型接下来需要看的上下文”。

## 15. 对本项目的启发

本项目当前的 `core/compact.py` 已经有了压缩器雏形，但还更接近简单截断：

- `should_auto_compact()` 会估算 token。
- `compact_messages()` 会保留最近几条消息。
- `compact_with_llm()` 有摘要 prompt，但主循环还没有真正接入它。

如果要向 Claude Code 靠拢，最值得先做的不是一次性复刻所有高级功能，而是补齐最关键的闭环：

```text
超过阈值
  -> 调用 LLM 生成 summary
  -> 创建 compact boundary
  -> 用 summary 替换旧历史
  -> 保留最近 N 条原始消息
  -> 恢复最近读过的关键文件
  -> 继续当前 query
```

然后再逐步加：

1. tool result microcompact。
2. prompt-too-long reactive compact。
3. 基于模型上下文窗口的动态阈值。
4. 连续失败熔断。
5. query source guard。
6. post-compact hooks 和自定义 compact instructions。

最小可行版本只要先做到“真实 LLM 摘要 + compact boundary + 最近消息保留 + 最近文件恢复”，就已经比现在的占位式截断可靠很多。
