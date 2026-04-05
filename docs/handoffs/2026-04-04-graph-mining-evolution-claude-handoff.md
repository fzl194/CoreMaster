# Handoff: graph-mining-evolution-001

- 时间：2026-04-04
- From：Claude
- To：Codex
- 类型：impl-complete-handoff
- 状态：已处置

## 任务目标

将图谱挖掘系统从 MVP 演进为正式框架：插件化拆分、通用异步任务框架、跨插件事件总线、6-state 候选状态机、前端重写。

## 本次实现范围

全部 20 个 Task，按实施计划 v10 执行完毕：

| Task | 内容 | 状态 |
|------|------|------|
| 1-3 | core/jobs 数据模型 + JobService + JobWorker | 完成 |
| 4 | core/events PluginEventBus | 完成 |
| 5 | 接入 main.py lifespan | 完成 |
| 6 | graph_mining 插件骨架 + schema | 完成 |
| 7 | 迁移 scorer 到 graph_mining/engine | 完成 |
| 8 | 挖掘评估 pipeline (hard_rules + scorers) | 完成 |
| 9-10 | graph_mining API 路由 + CandidateService + MiningWorker | 完成 |
| 11 | 跨插件事件集成 (mml_manager emit + graph_mining subscribe) | 完成 |
| 12 | mml_manager 瘦身，移除已迁移代码 | 完成 |
| 13 | 移除虚拟 dependency_mining 插件 | 完成 |
| 14-18 | 前端重写 (API层 + 路由 + 页面 + 清理旧页面) | 完成 |
| 19 | 集成测试 10 个用例 (§11 全覆盖) | 完成 |
| 20 | 全量回归 + 修复 | 完成 |

## 明确不在本次范围内的内容

- LLM 评估接入（UI 占位已就绪，真实 LLM 调用待后续）
- 前端图谱可视化
- 多算法版本切换 UI
- 批量操作 API（批量接受/拒绝）

## 改动文件清单

### 新建文件 (17)
- `backend/core/events/__init__.py`, `bus.py`
- `backend/core/jobs/__init__.py`, `models.py`, `service.py`, `worker.py`
- `backend/plugins/graph_mining/` (完整插件: main.py, plugin.toml, engine/*, services/*, workers/*)
- `backend/tests/test_core_events.py`, `test_core_jobs.py`, `test_lifespan.py`, `test_mining_pipeline.py`, `test_graph_mining_integration.py`
- `frontend/src/api/graph-mining.ts`
- `frontend/src/views/plugins/GraphMining.vue`

### 删除文件 (3)
- `backend/tests/test_dependency_mining.py`
- `frontend/src/api/dependency-mining.ts`
- `frontend/src/views/plugins/DependencyMining.vue`

### 修改文件 (5)
- `backend/main.py` — lifespan 集成 jobs/events，移除虚拟插件
- `backend/plugins/mml_manager/main.py` — 瘦身至 ~770 行，添加事件 emit
- `backend/plugins/order.toml` — 加载顺序调整
- `backend/tests/test_mml_manager.py` — 适配 cascade delete + 新服务注册
- `backend/tests/test_db_manager.py` — 新服务注册
- `frontend/src/router/index.ts` — 路由替换

## 关键设计决策

1. **插件加载用绝对导入** — `from plugins.graph_mining.services...` 而非相对导入，因为 `importlib.util.spec_from_file_location` 不支持包内相对导入
2. **事件 emit 时序** — emit BEFORE DB DELETE，handler 可能需要 ne_version_id
3. **CandidateService 单实例** — MiningWorker 和 event handlers 共用同一个实例，保证终态保护逻辑一致
4. **item_key 合约** — 裸 integer file_entry_id 存为 string 在 job_item.item_key
5. **6-state 候选模型** — pending / ready_for_review / graph / non_graph / rejected / (llm_reviewing 占位)

## 已执行验证

- 后端全量测试：**113 passed, 0 failed**
- 前端 build：**vue-tsc + vite build 成功**
- 集成测试覆盖 §11 全部 10 个验证点

## 未验证项

- 真实环境端到端冒烟（需启动 backend + frontend 服务）
- 大文件/多文件挖掘性能
- 并发挖掘 job 竞争条件

## 已知风险

- `file.content_replaced` 事件会自动创建新 mining job，如果 worker 未启动，job 会留在 queued 状态
- `ne_version.deleted` 事件清理 contribution 时，graph/non_graph 状态的候选会保留但分数归零

## 指定给 Codex 的审查重点

1. **CandidateService.recalculate() 终态保护逻辑** — §6.6 规则是否正确实现
2. **跨插件事件时序** — emit BEFORE DELETE 是否在所有路径上一致
3. **MiningWorker._mine_single_file()** — candidate upsert + contribution upsert 的并发安全性
4. **graph_mining/main.py 路由层** — 状态验证是否完备（pending_like 检查）
5. **前端 GraphMining.vue** — job polling 逻辑是否有内存泄漏风险（setTimeout 无 clearTimeout）
