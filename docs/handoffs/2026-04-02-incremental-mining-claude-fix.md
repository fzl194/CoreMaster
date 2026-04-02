# 增量挖掘实现修复报告

**任务:** dep-mining-mvp-001
**日期:** 2026-04-02
**From:** Claude
**关联审查:** `docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
**提交:** `602e7b0`

---

## 修复项

### Fix P1-3.1: mining-status 文件名字段契约

**问题:** 后端 `GET /files/mining-status` 返回 `fe.name`，前端读取 `file_name`，导致文件选择器显示空白。

**修复:** SQL 中将 `fe.name` 别名为 `fe.name as file_name`，与前端 `FileMiningStatus` 接口对齐。

**测试:** 新增 `test_mining_status_file_name_field` 验证返回数据包含 `file_name` 字段且值正确。

### Fix P1-3.2: 后端状态机未收死

**问题:** `accept/reject/mark-non-graph` 只挡同态重复，没挡 `non_graph→graph`、`graph→non_graph`、`graph→rejected`、`non_graph→rejected` 等非法直转。

**修复:** 三个端点显式校验允许的来源状态：
- `accept`: 只允许 `pending`、`auto_passed`、`llm_review`、`man_review`、`rejected` → `graph`
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

- 后端全量测试：113 passed, 0 failed（新增 6 个测试）
- 旧测试（含 deprecated 路由）全部兼容通过

## 未验证项

- 前端构建未重跑（本次改动仅涉及后端和测试，无前端变更）
