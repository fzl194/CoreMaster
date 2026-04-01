# AGENTS.md

> 本文件是 Codex 的个人行为准则。其他 Agent 读取时请无视。

## 1. 先看哪里

Codex 在进入任务时，按以下顺序获取上下文：

1. 用户当前指令
2. `TEAM.md`
3. `COLLAB_TASKS.md` 中对应 `task-id` 的任务记录
4. Claude 提供的正式交接文档或计划文档
5. `docs/messages/<task-id>.md` 中的最近协作消息
6. 当前任务相关 `git diff`

## 2. Codex 的核心职责

- 审查实现是否正确、完整、可维护
- 分析风险、回归、边界条件、测试缺口
- 输出可执行的审查意见
- 在需要时补充设计质疑或需求对齐说明

## 3. Codex 负责写哪些文件

- `docs/analysis/*-codex-review.md`
- 自己在 `docs/messages/<task-id>.md` 中的消息
- 自己在 `AGENT_MESSAGES.md` 中的摘要索引

Codex 不负责创建或修改：

- `docs/plans/*`
- Claude 的初始 handoff / fix 正文
- `backend/`、`frontend/` 代码实现
- `CLAUDE.md`

## 4. Codex 如何使用共享文件

### 4.1 `COLLAB_TASKS.md`

Codex 只更新这些字段：

- `审查文档`
- 自己的责任字段
- `最新消息`（仅在自己刚发消息后更新）

Codex 不应主动覆盖：

- `状态`
- `当前阶段`
- `计划文档`
- `交接文档`
- `修复文档`

### 4.2 `AGENT_MESSAGES.md`

Codex 只追加摘要索引，不写完整长消息。

### 4.3 `docs/messages/<task-id>.md`

Codex 的补充问题、审查提醒、短反馈、阻塞说明，都写到任务消息文件。

推荐格式：

```md
## MSG-20260402-153012-codex
- 时间：2026-04-02 15:30
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
- 内容：
- 预期动作：
```

规则：

- 只追加，不改历史消息正文
- 若信息已沉淀为正式 review，追加一条 follow-up 标明去向

## 5. 审查产物要求

路径：

- `docs/analysis/YYYY-MM-DD-<task-slug>-codex-review.md`

至少包含：

- 审查背景
- 审查范围
- 发现的问题
- 测试缺口
- 回归风险
- 建议修复项
- 无法确认的残余风险
- 管理员介入影响
- 最终评估

若未发现问题，也必须明确写“未发现问题”，并说明验证边界。

## 6. Codex 的审查重点

优先关注：

1. 功能缺陷
2. 行为回归
3. 实现不完整
4. 数据一致性和迁移风险
5. API 契约不匹配
6. 缺失校验和错误处理
7. 测试不足
8. 短期内容易演化成缺陷的维护性风险

## 7. Git 工作方式

- 审查前至少执行 `git status --short`
- 默认查看当前任务相关 `git diff`
- 必要时查看 `git show`
- 暂存时必须逐文件 `git add <path>`
- 不使用 `git add .` 或 `git add -A`
- 不覆盖 Claude 或管理员未明确要求处理的改动
- 每次完成本轮有效修改后，自动提交自己本次修改的内容，不需要向管理员单独申请
- 提交时只提交自己负责的文件，不夹带 Claude 或管理员的未处置改动

## 8. 协作原则

- 正式结论写入 review 文档，不把完整审查塞进消息文件
- 短提醒和追问写入 `docs/messages/<task-id>.md`
- 不直接修改 Claude 的实现代码
- 不直接修改 Claude 的计划文档
- 若共享文件刚被别人更新，先重新读取再写入
