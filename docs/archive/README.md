# Docs Archive

本文档说明仓库内 `docs/archive/` 的归档原则。

## 1. 归档触发

- 归档不是日常自动动作，必须由管理员显式指定后才能执行。
- Codex 负责执行归档，但不能自行决定归档时机。

## 2. 归档边界

- 只归档已结束、已闭环、当前不再工作的任务文档。
- `COLLAB_TASKS.md` 中仍处于“活跃任务”的文档不得归档。
- 当前实现、当前审查、当前设计正在使用的基线文档不得归档。

## 3. 归档对象

- 可归档：已结束任务对应的 `docs/analysis/*`、`docs/handoffs/*`、`docs/plans/*`、`docs/messages/*`
- 不直接删除任何正式文档；归档一律使用移动，不做清空
- 若同一主题仍被当前活跃任务引用，则保持原位，不归档

## 4. 归档路径

- 归档文件按月份放入 `docs/archive/YYYY-MM/`
- 在归档目录下按原类别保留子目录，例如：
  - `docs/archive/YYYY-MM/analysis/`
  - `docs/archive/YYYY-MM/handoffs/`
  - `docs/archive/YYYY-MM/plans/`
  - `docs/archive/YYYY-MM/messages/`

## 5. 执行原则

- 归档前先确认任务已结束，且不在当前活跃任务链路中
- 归档后保持文件名不变，避免丢失历史可追溯性
- 若共享索引或任务记录需要反映归档结果，应在同轮内同步更新
