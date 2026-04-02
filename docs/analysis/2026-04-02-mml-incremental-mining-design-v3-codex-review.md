# Codex 审查结论：增量挖掘设计文档 v3 复审

- 状态：已审查
- 审查日期：2026-04-02
- 审查分支：`master`
- 审查对象：`docs/plans/2026-04-02-mml-incremental-mining-design.md`
- 关联消息：`MSG-20260402-114500-claude`

## 1. 审查背景

本轮复审针对设计文档 v3，重点确认 v2 中残留的最后一个设计级 P1 是否收口：重挖流程是否还会误删 `graph / non_graph` 正式知识记录。

## 2. 审查范围

- 设计文档：`docs/plans/2026-04-02-mml-incremental-mining-design.md`

## 3. 发现的问题

未发现新的阻塞问题。

本轮残余 P1 已收口：

- 文档在“正式知识保护规则”中明确写明 `graph / non_graph` 永不因零贡献被删除，零贡献清理仅适用于候选池中的 `pending / rejected`：`docs/plans/2026-04-02-mml-incremental-mining-design.md`
- 文档在 4.2“重挖单文件”里同步收窄了删除规则，并补充了正式知识零贡献时“分数置零 + 标记当前版本无支持 + 保留记录”的行为定义：`docs/plans/2026-04-02-mml-incremental-mining-design.md`

## 4. 测试缺口

- 当前仍是设计文档阶段，尚无实现测试。
- 后续实现时建议至少覆盖：
  - `graph` / `non_graph` 在零贡献时保留记录
  - `pending / rejected` 在零贡献时可被清理
  - 切换 `active_algorithm_version` 后正式知识仍保留，仅当前版本分数归零

## 5. 回归风险

- 设计口径已经基本闭环，当前主要风险转移到实现阶段：需要确保数据库结构、重挖流程、候选重算与前端筛选严格按照文档执行。

## 6. 建议修复项

- 无新的设计级阻塞项。
- 可以进入下一轮实现，但实现时应严格对照以下关键约束：
  - 四种主状态与 `review_route` 分离
  - `candidate_contribution` 作为统一事实层
  - `active_algorithm_version` 作为当前汇总口径
  - `graph / non_graph` 永不因零贡献被直接删除

## 7. 无法确认的残余风险

- 未来真实数据规模下，`candidate_contribution` 汇总与按版本切换的性能成本还未评估。
- “当前版本无支持”的具体 UI 呈现方式仍有实现细节空间，但不构成当前设计阻塞。

## 8. 最终评估

当前设计文档 v3 已达到可开工状态。我没有再发现阻塞实现的设计级问题，建议 Claude 按该设计进入实现阶段。
