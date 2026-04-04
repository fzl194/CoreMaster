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

### graph-mining-evolution-001
- 标题：图谱挖掘体系从 MVP 向正式框架演进
- 级别：正式
- 状态：需求分析中
- 当前阶段：架构讨论与任务拆分
- Claude：已完成实施计划修订（v5），Codex 第四轮 3 项代码对照问题已闭环：Task 2 lastrowid 接口对齐、Task 5 lifespan 验证对齐现有代码骨架、Task 9 引用同步。待 Codex 放行
- Codex：已完成对实施计划 v5 的代码对照复审，确认 Task 2/5/9 已闭环，但新增发现 Task 11 仍漏掉 `DELETE /entries/{entry_id}` 的文件夹递归删除生命周期入口，graph_mining 清理链路继续不完整，仍不放行
- 管理员：待确认任务边界、阶段目标与优先级
- 计划文档：`docs/plans/2026-04-03-graph-mining-evolution-design.md`、`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`
- 交接文档：
- 审查文档：`docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
- 修复文档：
- 管理员文档：
- 最新消息序号：MSG-20260404-152000-codex
- 备注：该任务是 `dep-mining-mvp-001` 闭环后的新阶段任务，重点讨论图谱挖掘插件化、通用队列框架、任务/文件状态解耦、LLM 能力边界与渐进式实施路径；当前先做需求分析与架构讨论，不直接视为进入编码实现。

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
