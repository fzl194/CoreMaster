# CLAUDE.md

> 本文件是 Claude Code 的个人行为准则。其他 Agent 读取时请无视。

## 协作协议

遵守 [TEAM.md](./TEAM.md) 中的共享团队协议。

项目架构和开发命令参见 [README.md](./README.md)。

在完成实现后，必须提供一份可供 Codex 审查的交接说明；在 Codex 的问题被修复或被明确处置之前，不应将任务视为完成。

## 输出位置与命名约定

Claude 负责把计划、实现说明和交接材料写入 `docs/handoffs/`。

路径约定：

- 计划文档：`docs/plans/YYYY-MM-DD-<task-slug>-impl-plan.md`
- 交接文档：`docs/handoffs/YYYY-MM-DD-<task-slug>-claude-handoff.md`
- 修复文档：`docs/handoffs/YYYY-MM-DD-<task-slug>-claude-fix.md`

`claude-handoff` 文档至少包含：

- 任务目标
- 本次实现范围
- 明确不在本次范围内的内容
- 改动文件清单
- 关键设计决策
- 已执行验证
- 未验证项
- 已知风险
- 指定给 Codex 的审查重点
- 管理员本轮直接介入记录（如有）

## Git 职责

Claude 在开始实现前应至少检查：

- `git status --short`
- 必要时查看本任务相关文件的 `git diff`

Claude 在交接给 Codex 时，应在 handoff 文档中补充：

- 当前分支名
- 审查基线
- 建议 Codex 优先查看的 diff 范围
- 本次实现对应的关键提交，若尚未提交则明确写明"基于工作区改动审查"
- 管理员在当前分支上的相关提交或工作区改动（如有）

推荐补充字段：

```md
- 分支：
- 审查基线：
- 关键提交：
- 建议查看的 diff：
- 管理员相关改动：
```

## 文件边界

Claude 必须遵守 [TEAM.md](./TEAM.md) 中的文件归属表。具体来说：

- `docs/analysis/` 下的所有文件由 Codex 独占，Claude 不得创建、修改、暂存或提交。
- `docs/handoffs/*claude-handoff.md` 中状态标记和回写区域由 Codex 维护，Claude 只负责编写初始交接内容（首次创建时标记为 `待 Codex 审查`）。
- 当 Claude 根据 Codex 审查意见完成代码修复后，应产出独立的修复交付文档（如 `docs/handoffs/YYYY-MM-DD-<task-slug>-claude-fix.md`），由 Codex 去回写 handoff 状态和 review 结论。
- `git add` 时必须逐文件指定路径，**禁止**使用 `git add -A` 或 `git add .`，避免误提交对方的文件。
