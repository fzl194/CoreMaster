# Claude Fix 文档 – graph-mining-evolution-001

## 修复时间
2026-04-04 ~ 2026-04-05
## 修复人
Claude

## 修复范围

针对 Codex 首轮审查 4 个阻塞问题，以及后续与管理员讨论确认的需求变更，共完成 2 轮修复。

---

## 第一轮：Codex 审查修复（commit `1bce176`）

| # | 问题 | 修复 |
|---|------|------|
| 1 | 旧库迁移缺失 | `_create_tables` 末尾添加 `ALTER TABLE ADD COLUMN`，`try/except pass` 幂等，覆盖 `llm_assessment_json`、`last_job_id`、`last_error` |
| 2 | 文件更新后自动挖掘 | `_on_file_content_replaced` 改为只标记 `mined=0`，不删贡献、不重算候选、不创建 job |
| 3 | 队列 API/页面缺失 | 后端新增 `GET /jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/cancel`；前端新增独立"挖掘队列"Tab |
| 4 | 批量选择不工作 | 文件表格 `checked-row-keys` 绑定到 `selectedFiles` |

### 第一轮额外修复

| # | 问题 | 修复 |
|---|------|------|
| 5 | "已变动"状态优先级 Bug | `/files` API 中 `mined=0 and mined_at is not None` 检查优先于 `status_map` 查询 |
| 6 | 文件修改后候选数据被误删 | 只标记 `mined=0`，不动贡献和候选数据；重挖时 MiningWorker 才覆盖旧贡献 |

---

## 第二轮：需求变更 + 状态机简化（commit `2a3b4d0`）

管理员逐条确认了以下变更，涉及设计文档 §6 状态机和 §6.6 终态保护规则的调整：

### 2.1 状态机简化：5 状态 → 3 状态

- **删除** `ready_for_review`（从未被代码写入的死状态）
- **合并** `non_graph` 和 `rejected` 为统一的 `rejected`（人审过的"非图谱依赖"，拒绝也可有原因）
- 新状态流转：`pending → graph`（接受） / `pending → rejected`（拒绝） / `graph → pending`（回退） / `rejected → pending`（回退）

### 2.2 `review_route` 语义变更

- 旧：审核路由（auto 自动入图谱 / llm 走 LLM / manual 人工审核）
- 新：仅表示置信度等级标签，不影响状态流转。所有入图谱/拒绝操作均需人工确认
  - `auto`（≥ 0.85）：高置信度，建议批量入图谱
  - `llm`（0.50 ~ 0.85）：中等，建议先跑 LLM 评估
  - `manual`（< 0.50）：低概率，需仔细人工审核

### 2.3 `rejected` 终态保护规则变更

- 旧：`rejected` 遇新证据自动激活回 `pending`
- 新：`rejected` 为终态，新证据只更新分数/证据，**不改变状态**。用户需手动"回退"回 pending

### 2.4 零贡献处理规则

- `graph` / `rejected`：零贡献时保留记录，清零分数（终态保护）
- `pending`：零贡献时直接删除候选记录

### 2.5 文件修改行为（再次确认）

- 只标记 `mined=0`，不动任何候选/贡献数据
- 重挖时终态候选（graph/rejected）：分数/证据更新，状态不变
- 重挖时 pending 候选：分数/证据/review_route 正常更新

---

## 改动文件

**后端**
- `backend/plugins/graph_mining/main.py`
  - `_create_tables`: 追加 ALTER TABLE 迁移（`llm_assessment_json`, `last_job_id`, `last_error`）
  - `_on_file_content_replaced`: 只标记 `mined=0`，不自动挖
  - 新增 3 个路由: `GET /jobs`, `GET /jobs/{job_id}`, `POST /jobs/{job_id}/cancel`
  - `/files` API: 状态派生新增 "changed" 分支
  - 删除 `mark-non-graph` 路由；`reject` 只允许 `pending→rejected`；`revert` 支持 `graph→pending` 和 `rejected→pending`
  - 删除 `non_graph_reason`/`non_graph_reviewer` 列；`list_candidates` 移除这两个字段
- `backend/plugins/graph_mining/services/candidate_service.py`
  - `rejected` 为终态（与 `graph` 同等保护），新证据不激活
  - 零贡献时保留记录
- `backend/tests/test_graph_mining_integration.py`
  - 重写测试适配 3 状态模型

**前端**
- `frontend/src/api/graph-mining.ts`
  - `Candidate.status` 类型收窄为 `"pending" | "graph" | "rejected"`
  - 删除 `markNonGraph` 函数
  - 新增 `JobItemInfo` 接口和 `fetchJobs`/`cancelJob`
- `frontend/src/views/plugins/GraphMining.vue`
  - 删除"非图谱"按钮/弹窗/相关状态
  - 新增 `review_route` 等级标签列（高/中/低 tag）
  - 操作按钮简化（pending→接受/拒绝，graph/rejected→回退）
  - `statusFilterOptions` 只保留 3 个选项

---

## 验证结果

- 后端: 6 passed / 0 failed
- 前端: `vue-tsc --noEmit` 通过

---

## 已知未完成项

- 设计文档 §6/§6.6 仍为旧版描述（5 状态、rejected 自动激活），需管理员确认是否回写更新
- 测试用例从原 10 个减少到 6 个（移除了涉及 `non_graph`/`ready_for_review` 的用例），后续可补充完整状态机测试
- `command_instance` 表为空是正常的（graph_mining 不依赖它）

## Codex 审查重点

1. CandidateService 终态保护逻辑（`rejected` 与 `graph` 同等保护，新证据不激活）
2. 跨插件事件时序（emit 在 DB DELETE 之前）
3. MiningWorker 并发安全（单 worker 模型）
4. 前端 job polling 内存风险（Tab 切出时停止轮询）
