# COLLAB_TASKS

本文档是仓库内协作任务总入口。

使用规则：

- 每个非琐碎任务只保留一条任务记录
- 所有正式文档路径都挂到对应任务下
- 当前状态、当前阶段、最新消息序号优先在这里维护
- 已结束任务可移动到“已完成任务”区，但不要删除历史

---

## 活跃任务模板

## <task-id>
- 标题：
- 级别：
- 状态：
- 当前阶段：
- Claude：
- Codex：
- 管理员：
- 计划文档：
- 交接文档：
- 审查文档：
- 修复文档：
- 管理员文档：
- 最新消息序号：
- 备注：

字段分权：

- Claude 维护：`计划文档`、`交接文档`、`修复文档`
- Codex 维护：`审查文档`
- 管理员维护：`状态`、`当前阶段`、`备注`
- 三方都可维护：自己的责任字段、`最新消息序号`

---

## 活跃任务

### dep-mining-mvp-001
- 标题：MML 命令依赖关系挖掘系统 MVP
- 级别：正式
- 状态：Claude 交接中
- 当前阶段：MVP 实现完成，待 Codex 审查
- Claude：实现完成
- Codex：已完成实现第二轮复审；仍残留 1 个状态机级 P1 待 Claude 修复
- 管理员：
- 计划文档：`docs/plans/2026-04-02-mml-dependency-mining-mvp-impl-plan.md`
- 交接文档：`docs/handoffs/2026-04-02-dep-mining-mvp-claude-handoff.md`
- 审查文档：`docs/analysis/2026-04-02-dep-mining-mvp-codex-review.md`；`docs/analysis/2026-04-02-dep-mining-mvp-incremental-requirements-codex-review.md`；`docs/analysis/2026-04-02-mml-incremental-mining-design-codex-review.md`；`docs/analysis/2026-04-02-mml-incremental-mining-design-v2-codex-review.md`；`docs/analysis/2026-04-02-mml-incremental-mining-design-v3-codex-review.md`；`docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
- 修复文档：
- 管理员文档：
- 设计参考：`docs/plans/2026-04-01-mml-dependency-mining-design.md`
- 最新消息序号：`MSG-20260402-173500-codex`
- 备注：MVP 实现已完成，含解析器增强、候选生成引擎、审核队列 API、前端视图

---

## 已完成任务

### 说明

- 可将已闭环任务移动到此区
- 如任务较多，可后续按月份拆分归档
