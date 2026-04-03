# Codex 审查结论：增量挖掘设计文档首轮复审

- 状态：已审查
- 审查日期：2026-04-02
- 审查分支：`master`
- 审查对象：`docs/plans/2026-04-02-mml-incremental-mining-design.md`
- 关联消息：`MSG-20260402-101900-claude`

## 1. 审查背景

本轮审查只针对设计文档是否符合管理员新明确的业务规则，不涉及实现代码。审查基线是管理员与 Codex 已确认的三条口径：

- 主状态只能是 `pending / graph / non_graph / rejected`
- 文件挖掘结果是事实层，图谱/非图谱切换是决策层；所有文件挖掘结果都应记录
- 算法版本采用方案 A：历史可保留，但当前汇总只认一个激活算法版本，不能默认混算

## 2. 审查范围

- 设计文档：`docs/plans/2026-04-02-mml-incremental-mining-design.md`

## 3. 发现的问题

### P1：主状态模型仍未收敛，文档继续把 `auto_passed / llm_review / man_review` 当成业务状态

- 证据：
  - 状态图仍把候选池写成 `pending / auto_passed / llm_review / man_review`：`docs/plans/2026-04-02-mml-incremental-mining-design.md:44`
  - 状态定义表继续把这三项列为状态：`docs/plans/2026-04-02-mml-incremental-mining-design.md:68`
  - DDL 说明仍把它们写进 `dependency_candidate.status` 枚举：`docs/plans/2026-04-02-mml-incremental-mining-design.md:144`
  - 核心流程 4.1 仍按这些状态分支处理：`docs/plans/2026-04-02-mml-incremental-mining-design.md:181`
- 影响：
  - 与管理员已确认的“四种主状态”口径冲突。
  - 后续实现会继续把“审核路由”与“业务状态”混在一起，状态机仍然脏。
- 建议修复：
  - `status` 只保留 `pending / graph / non_graph / rejected`
  - 若还需要表达“自动通过/LLM/人工”，单独设计 `review_route` 或同类字段，不要继续并入 `status`

### P1：文件挖掘事实层仍未统一，`graph` / `non_graph` 命中的新结果没有完整进入统一记录层

- 证据：
  - 文档定义 `candidate_contribution` 为“文件对候选的贡献”，而不是“文件挖掘结果的统一事实层”：`docs/plans/2026-04-02-mml-incremental-mining-design.md:118`
  - 当命中已有 `graph_edge` 时，流程写的是“追加证据到 graph_edge.evidence_json”，而不是先沉淀统一文件结果：`docs/plans/2026-04-02-mml-incremental-mining-design.md:174`
  - 当命中 `non_graph` 时，流程写的是“跳过”：`docs/plans/2026-04-02-mml-incremental-mining-design.md:179`
- 影响：
  - 不符合管理员已确认的“所有文件挖掘结果都要记录上，而图谱边切换是独立决策层”。
  - `non_graph` 的新增命中会直接丢失；`graph` 的新增命中则绕过统一事实层，导致后续追溯口径不一致。
- 建议修复：
  - 先把“文件挖掘事实层”独立建模清楚，再决定候选池、图谱库、非图谱库如何消费它。
  - 即使关系当前处于 `graph` / `non_graph`，新文件命中也应先进入统一的文件级结果记录层；是否影响候选池或正式库，是后续决策层逻辑。

### P1：算法版本方案 A 没有落地，当前设计默认会混算不同算法版本的贡献

- 证据：
  - 文档只在 `file_mining_record` 里增加了 `algorithm_version` 字段：`docs/plans/2026-04-02-mml-incremental-mining-design.md:105`
  - 但汇总重算逻辑直接对 `contributions` 全量聚合，没有“当前激活算法版本”或“仅取同一算法版本贡献”的约束：`docs/plans/2026-04-02-mml-incremental-mining-design.md:246`
- 影响：
  - 一旦算法升级，旧算法和新算法贡献会直接混算，分数和证据口径不可比。
  - 这与管理员已同意的方案 A 冲突：历史可保留，但当前汇总不能默认混算。
- 建议修复：
  - 在设计文档中明确“当前汇总算法版本”的概念。
  - 候选池当前分数和排序只应基于激活算法版本的贡献；历史版本贡献保留追溯，但不直接并入当前汇总。

## 4. 测试缺口

- 由于这是设计文档阶段，尚无测试；但后续实现测试必须覆盖：
  - 四种主状态与审核路由字段的分离
  - `graph` / `non_graph` 下的新文件命中仍被记录
  - 算法版本切换后仅激活版本参与当前汇总

## 5. 回归风险

- 若不先收敛主状态模型，后续实现会再次把“审核路由”和“业务状态”耦合，导致接口和前端展示一起返工。
- 若不统一文件事实层，未来很难解释“这条图谱边/非图谱边有哪些文件贡献过证据”。
- 若不明确算法版本隔离规则，算法升级后候选分数会缺乏可解释性。

## 6. 建议修复项

- Claude 先修订设计文档，再进入实现。
- 修订重点：
  - `status` 收敛到四种主状态
  - 单独引入审核路由字段，而不是把 `auto_passed / llm_review / man_review` 混进 `status`
  - 重定义统一文件事实层，避免 `graph` / `non_graph` 命中绕过或丢失记录
  - 明确方案 A 的“激活算法版本”与汇总口径

## 7. 最终评估

当前设计文档已经走到了正确方向，但还没有达到可据此开工的程度。需要先修掉以上 3 个设计级 P1，才能进入下一轮实现。
