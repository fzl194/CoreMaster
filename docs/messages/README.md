# docs/messages

本目录用于存放单任务对话记录。

原则：

- 一个任务一个文件：`docs/messages/<task-id>.md`
- Claude、Codex、管理员都在同一个任务文件里追加消息
- 只追加，不改历史正文
- 长沟通写这里；根目录 `AGENT_MESSAGES.md` 只保留摘要索引

推荐格式：

```md
# <task-id>

## MSG-20260402-153012-claude
- 时间：2026-04-02 15:30
- From：Claude
- To：Codex
- 类型：handoff-note | review-note | blocker | question | decision | status
- 关联文件：
- 内容：
- 预期动作：
```

修正规则：

- 如果上一条消息有误，不回改旧正文
- 追加一条新的 follow-up 说明修正内容
