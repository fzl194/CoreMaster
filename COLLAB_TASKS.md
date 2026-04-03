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
- 备注：相关计划、交接、审查、修复、任务消息与任务级 Agent 摘要均已归档到 docs/archive/2026-04/dep-mining-mvp-001/；代码审查已放行，后端验证为 44 passed，前端 build 仅保留当前环境 spawn EPERM 的非阻塞备注。

字段分权：

- Claude 维护：`计划文档`、`交接文档`、`修复文档`
- Codex 维护：`审查文档`
- 管理员维护：`状态`、`当前阶段`、`备注`
- 三方都可维护：自己的责任字段、`最新消息序号`

---

## 活跃任务

- 暂无

## 已完成任务

### 说明

- 可将已闭环任务移动到此区
- 如任务较多，可后续按月份拆分归档

### dep-mining-mvp-001
- 标题：MML 命令依赖关系挖掘系统 MVP
- 级别：正式
- 状态：已闭环归档
- 当前阶段：实现、审查与归档完成
- Claude：已完成增量式依赖挖掘实现，并通过最终复审
- Codex：已完成最终代码审查、任务关闭与文档归档
- 管理员：已确认关闭任务并执行归档
- 计划文档：`docs/archive/2026-04/dep-mining-mvp-001/plans/`
- 交接文档：`docs/archive/2026-04/dep-mining-mvp-001/handoffs/`
- 审查文档：`docs/archive/2026-04/dep-mining-mvp-001/analysis/`
- 修复文档：`docs/archive/2026-04/dep-mining-mvp-001/handoffs/`
- 管理员文档：
- 设计参考：`docs/archive/2026-04/dep-mining-mvp-001/plans/2026-04-01-mml-dependency-mining-design.md`
- 最新消息序号：MSG-20260403-174500-codex
- 备注：相关计划、交接、审查、修复、任务消息与任务级 Agent 摘要均已归档到 docs/archive/2026-04/dep-mining-mvp-001/；代码审查已放行，后端验证为 44 passed，前端 build 仅保留当前环境 spawn EPERM 的非阻塞备注。
