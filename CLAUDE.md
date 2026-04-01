# CLAUDE.md

> 本文件是 Claude Code 的个人行为准则。其他 Agent 读取时请无视。

## 1. 先看哪里

Claude 在进入任务时，按以下顺序获取上下文：

1. 用户当前指令
2. `TEAM.md`
3. `COLLAB_TASKS.md` 中对应 `task-id` 的任务记录
4. 该任务关联的正式文档
5. `docs/messages/<task-id>.md` 中的最近协作消息
6. `README.md` 中的项目说明与开发命令

## 2. Claude 的核心职责

- 理解需求并澄清实现边界
- 产出实现计划
- 修改代码和相关实现文档
- 执行验证
- 向 Codex 交接
- 在审查问题解决后向用户交付

## 3. Claude 负责写哪些文件

- `docs/plans/*`
- `docs/handoffs/*claude-handoff.md`
- `docs/handoffs/*claude-fix.md`
- `backend/`、`frontend/` 中的实现代码

Claude 不负责创建或修改：

- `docs/analysis/*`
- `AGENTS.md`
- 管理员专属文档

## 4. Claude 如何使用共享文件

### 4.1 `COLLAB_TASKS.md`

Claude 只更新这些字段：

- `计划文档`
- `交接文档`
- `修复文档`
- 自己的责任字段
- `最新消息`（仅在自己刚发消息后更新）

Claude 不应主动覆盖：

- `状态`
- `当前阶段`
- `审查文档`
- 管理员备注

### 4.2 `AGENT_MESSAGES.md`

Claude 不在这里写长消息。这里只追加摘要索引。

### 4.3 `docs/messages/<task-id>.md`

Claude 的短沟通、补充说明、交接提醒、阻塞、问题，都写到任务消息文件里。

推荐格式：

```md
## MSG-20260402-153012-claude
- 时间：2026-04-02 15:30
- From：Claude
- To：Codex
- 类型：handoff-note
- 关联文件：
- 内容：
- 预期动作：
```

规则：

- 只追加，不改历史消息正文
- 若内容已沉淀为正式文档，追加一条 follow-up 说明去向

## 5. 正式交付要求

### 5.1 plan

路径：

- `docs/plans/YYYY-MM-DD-<task-slug>-impl-plan.md`

### 5.2 handoff

路径：

- `docs/handoffs/YYYY-MM-DD-<task-slug>-claude-handoff.md`

至少包含：

- 任务目标
- 本次实现范围
- 明确不在本次范围内的内容
- 改动文件清单
- 关键设计决策
- 已执行验证
- 未验证项
- 已知风险
- 指定给 Codex 的审查重点
- 管理员本轮直接介入记录

### 5.3 fix

路径：

- `docs/handoffs/YYYY-MM-DD-<task-slug>-claude-fix.md`

Claude 在修复审查问题后，必须单独写 fix，不得回写 review 结论。

## 6. Git 工作方式

- 开始实现前至少执行 `git status --short`
- 必要时查看相关文件 diff
- 暂存时必须逐文件 `git add <path>`
- 不使用 `git add .` 或 `git add -A`
- 不覆盖 Codex 或管理员未明确要求处理的改动

## 7. 协作原则

- 不把短沟通塞进正式文档
- 不在共享文件中重写整块内容，尽量做局部更新
- 不擅自修改 Codex 的 review 文档
- 不在问题未处置前宣称任务完成
- 若共享文件刚被别人更新，先重新读取再写入

