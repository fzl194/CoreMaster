# Claude Fix 文档 – graph-mining-evolution-001

## 修复时间
2026-04-04
## 修复人
Claude

## 修复范围

针对 Codex 审查的 4 个阻塞问题，分两轮完成修复。

### 修复项

| # | 问题 | 修复 |
|---|------|------|
| 1 | 旧库迁移缺失 | `_create_tables` 末尾添加 `ALTER TABLE ADD COLUMN`，`try/except pass` 幂等 |
| 2 | 文件更新后自动挖掘 | `_on_file_content_replaced` 改为清理贡献 + 标记 `mined=0`（状态 "changed"），不自动创建 job |
| 3 | 队列 API/页面缺失 | 后端新增 `GET /jobs`、`GET /jobs/{id}`、`POST /jobs/{id}/cancel`；前端新增独立"挖掘队列"Tab |
| 4 | 批量选择不工作 | 文件表格添加 `checked-row-keys` + `@update:checked-row-keys` 绑定到 `selectedFiles` |

### 改动文件

**后端**
- `backend/plugins/graph_mining/main.py`
  - `_create_tables`: 追加 ALTER TABLE 迁移（`llm_assessment_json`, `last_job_id`, `last_error`）
  - `_on_file_content_replaced`: 清理贡献 + 重置 `mined=0`，不自动挖
  - 新增 3 个路由: `GET /jobs`, `GET /jobs/{job_id}`, `POST /jobs/{job_id}/cancel`
  - `/files` API: 状态派生新增 "changed" 分支
- `backend/tests/test_graph_mining_integration.py`
  - `test_09`: 断言无自动挖掘 job、贡献已清理、文件状态为 "changed"

**前端**
- `frontend/src/api/graph-mining.ts`
  - `FileMiningInfo.mining_status` 类型新增 `"changed"`
  - 新增 `fetchJobs()`、`cancelJob()` 函数
- `frontend/src/views/plugins/GraphMining.vue`
  - 新增独立 Tab "挖掘队列"：任务列表 + 状态标签 + 进度 + 取消按钮
  - 队列 Tab 切入时自动 5s 轮询刷新，切出停止
  - 文件表格 checkbox 选择绑定到 `selectedFiles`
  - 开始挖掘后自动切到队列 Tab 并启动轮询

### 验证结果

- 后端: 10 passed / 0 failed
- 前端: `vue-tsc --noEmit` 通过，`npm run build` 通过
