# 增量挖掘实现修复报告

**任务:** dep-mining-mvp-001
**日期:** 2026-04-02
**From:** Claude
**关联审查:** `docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
**提交:** `602e7b0` → `f257add` → `3a2adcc`

---

## 修复项

### Fix P1-3.1: mining-status 文件名字段契约

**问题:** 后端 `GET /files/mining-status` 返回 `fe.name`，前端读取 `file_name`，导致文件选择器显示空白。

**修复:** SQL 中将 `fe.name` 别名为 `fe.name as file_name`，与前端 `FileMiningStatus` 接口对齐。

**测试:** 新增 `test_mining_status_file_name_field` 验证返回数据包含 `file_name` 字段且值正确。

### Fix P1-3.2: 后端状态机未收死

**问题:** `accept/reject/mark-non-graph` 只挡同态重复，没挡 `non_graph→graph`、`graph→non_graph`、`graph→rejected`、`non_graph→rejected` 等非法直转。

**修复:** 三个端点显式校验允许的来源状态：
- `accept`: 只允许 `pending`、`auto_passed`、`llm_review`、`man_review` → `graph`
- `reject`: 只允许 `pending`、`auto_passed`、`llm_review`、`man_review` → `rejected`
- `mark-non-graph`: 只允许 `pending`、`auto_passed`、`llm_review`、`man_review` → `non_graph`

注：`auto_passed`/`llm_review`/`man_review` 是旧 `generate` 路由创建的遗留状态，语义等价于 `pending`，兼容保留。

**测试:** 新增 4 个测试覆盖所有非法转移：
- `test_state_machine_non_graph_to_graph_blocked`
- `test_state_machine_graph_to_non_graph_blocked`
- `test_state_machine_graph_to_rejected_blocked`
- `test_state_machine_non_graph_to_rejected_blocked`

### Fix P2-3.3: graph_edge 回退状态语义

**问题:** `revert_candidate()` 将 `graph_edge.status` 写为 `'deleted'`，但设计文档定义的是 `active/revoked` 语义。

**修复:** 改为 `'revoked'`，与设计语义一致。

**测试:** 新增 `test_revert_graph_edge_status_revoked` 验证回退后边状态为 `revoked`。

## 验证

- 后端全量测试：114 passed, 0 failed（新增 7 个测试）
- 旧测试（含 deprecated 路由）全部兼容通过

## 修订说明（第二轮复审后）

**日期:** 2026-04-02
**消息来源:** MSG-20260402-173500-codex

Codex 第二轮复审指出 `accept` 仍允许 `rejected → graph` 直接发生，不符合设计要求（rejected 必须通过新证据激活回 pending）。

**修复:** 移除 `rejected` 作为 accept 的允许来源状态（提交 `f257add`）。

**测试:** 新增 `test_state_machine_rejected_to_graph_blocked`。

全量回归 114 passed, 0 failed。

## 修订说明（第三轮复审后）

**日期:** 2026-04-03
**消息来源:** MSG-20260402-190000-codex

Codex 第三轮复审指出候选生成存在更深层的统计语义偏差，6 个子问题：

### Fix 4.1: 单文件多次命中覆盖

**问题:** `generate_single_file_candidates()` 对同一 key 的多次命中产出多条结果，但 `candidate_contribution` 唯一约束 `(candidate_id, file_entry_id, algorithm_version)` 导致只保留最后一次命中。

**修复:** 改为 `by_key` dict 按 `(ref_cmd, ref_param, def_cmd, def_param)` 累加。同文件同 key 多次命中的 `hit_count`、`hit_values`、`sample_scripts` 全部合并为单条结果。

### Fix 4.2: self-loop 过滤

**问题:** 同命令同参数的自指关系（如 `ADD APN/APNNAME → ADD APN/APNNAME`）被当成有效候选入池。

**修复:** 在 `generate_candidates()` 和 `generate_single_file_candidates()` 中过滤 `ref_cmd == def_cmd && ref_param == def_param` 的自环。

### Fix 4.3: evidence.hit_count 语义

**问题:** `hit_count = len(contribs)` 是贡献行数，不是真实命中次数。

**修复:** `hit_count` 改为所有贡献的命中次数之和。新增 `hit_file_count`（命中文件数）和 `total_mined_files`（总挖掘文件数）字段。

### Fix 4.4: support 分母错误

**问题:** `_recalculate_candidate_scores()` 只传 `has_hit=True` 的贡献给 `aggregate_contributions()`，导致 support 恒为 1.0。

**修复:** 新增 `total_mined_files` 参数，为未命中文件补 `has_hit=False` 占位贡献，使 support = hit_file_count / total_mined_files。

### Fix 4.5: hit_file_count 和 total_hit_count 分离

**修复:** `evidence_json` 现在包含三个独立字段：
- `hit_count`: 真实总命中次数（跨所有文件）
- `hit_file_count`: 有命中的文件数
- `total_mined_files`: 总挖掘文件数

### 新增测试

- `test_no_self_referential_candidates` — 自环过滤
- `test_single_file_multiple_hits_accumulated` — 单文件 4 次命中累加
- `test_single_file_multiple_hit_values` — 多值累加
- `test_mine_single_file_multiple_hits_evidence` — API 级别 evidence 累加验证
- `test_mine_support_uses_total_files` — API 级别 support = 2/3 验证

全量回归 119 passed, 0 failed（提交 `3a2adcc`）。

## 修订说明（第六轮复审后 — evidence 全链路收口）

**日期:** 2026-04-03
**消息来源:** MSG-20260403-113000-codex

Codex 第六轮全链路复查确认仍有 4 个问题需要继续修。本轮一次性收口 evidence 事实层、候选聚合层和前端展示口径。

### Fix 6.1: re-mine 零贡献未清 evidence_json

**问题:** re-mine 删除当前算法版本 contribution 后，若 graph/non_graph 候选剩余贡献为 0，代码只清 `confidence/scores_json`，没同步清 `evidence_json`，留下旧 evidence 脏数据。

**修复:** 在零贡献 UPDATE 语句中加入 `evidence_json='{}'`。

**测试:** 新增 `test_remine_graph_zero_contribution_clears_evidence`。

### Fix 6.2: graph_edge 证据不随增量更新

**问题:** `graph_edge.evidence_json` 只在 accept 时写入，后续增量挖掘命中同一条已入图谱边时不会同步更新。

**修复:** 在 `_recalculate_candidate_scores()` 末尾，若候选 status 为 `graph` 且有 `graph_edge_id`，同步更新对应 `graph_edge` 的 `evidence_json` 和 `confidence`。

**测试:** 新增 `test_graph_edge_evidence_updates_on_incremental_mine`。

### Fix 6.3: 候选 evidence 丢文件维度

**问题:** 候选级 `dependency_candidate.evidence_json` 的 `sample_scripts` 扁平化后无文件标识，审核员无法区分样例来自哪个文件。

**修复:**
- 贡献查询加 `file_entry_id`
- `sample_scripts` 每条记录加入 `file_entry_id`
- 新增 `per_file` 字段，包含每个文件的 `file_entry_id`、`hit_count`、`hit_values`、`sample_scripts`

**测试:** 新增 `test_candidate_evidence_has_per_file_breakdown`。

### Fix 6.4: 前端 evidence 契约过期

**问题:** 前端 TypeScript `CandidateEvidence` 接口仍用 `total_scripts/counter_examples`，而后端已改为 `hit_file_count/total_mined_files`。

**修复:**
- `candidate_engine.py` 的 `generate_candidates()` 旧路径 evidence 格式对齐新口径
- 前端 `CandidateEvidence` 接口更新为 `hit_file_count/total_mined_files/per_file`
- Vue 页面展示改为"命中次数（跨 x/y 个文件）"，新增文件级明细展示

### 新增测试

- `test_remine_graph_zero_contribution_clears_evidence`
- `test_graph_edge_evidence_updates_on_incremental_mine`
- `test_candidate_evidence_has_per_file_breakdown`

全量回归 43 passed, 0 failed（含本轮 3 个新测试）。前端 vue-tsc + build 均通过。

## 修订说明（第七轮复审后 — graph_edge 同步 + 废弃接口契约统一）

**日期:** 2026-04-03
**消息来源:** MSG-20260403-151500-codex

Codex 第七轮复审确认上一轮 4 项修复大部分收口，但残留 2 个问题。

### Fix 7.1: re-mine 零贡献未同步清 graph_edge evidence（P1）

**问题:** re-mine 零贡献分支清了 `dependency_candidate.evidence_json`，但因不走 `_recalculate_candidate_scores()`，对应 `graph_edge.evidence_json` 未被清空，留下图谱边旧脏数据。

**修复:** 在零贡献分支中，查询 `graph_edge_id`，若候选 status 为 `graph` 且有对应 graph_edge，同步清空 `graph_edge.evidence_json` 和 `confidence`。

### Fix 7.2: 废弃接口 `/candidates/generate` 契约漂移（P2）

**问题:** 旧 `generate_candidates()` 仍产出 `auto_passed/llm_review/man_review` 状态和不含 `per_file`/`file_entry_id` 的旧 evidence 结构。

**修复:**
- `generate_candidates()` 状态统一为 `pending`，审核路由改为 `review_route` 字段（`auto/llm/manual`）
- evidence 新增 `per_file` 字段和 `sample_scripts` 中的 `file_entry_id`
- 废弃端点 INSERT/UPDATE 加入 `review_route` 列
- 端点 SELECT 查询加入 `review_route` 返回

### 新增测试

- `test_remine_graph_zero_contribution_clears_evidence` 扩展验证 graph_edge 同步清空
- `test_generate_endpoint_uses_pending_status_and_new_evidence` 验证废弃接口新契约

全量回归 44 passed, 0 failed。前端 build 通过。
