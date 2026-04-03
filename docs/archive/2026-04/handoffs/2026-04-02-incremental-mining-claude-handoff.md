# 增量挖掘实现交接文档

**任务:** dep-mining-mvp-001 — 增量挖掘系统实现
**日期:** 2026-04-02
**From:** Claude
**To:** Codex

---

## 任务目标

将 MML 依赖挖掘系统从"按版本全量 batch-extract + generate"重构为"按文件增量挖掘"系统，支持贡献层、四层状态模型、算法版本隔离。

## 本次实现范围

按 `docs/plans/2026-04-02-mml-incremental-mining-design.md` (v3, Codex 已审通过) 完成全部 8 个 Task 的实现。

### Task 1: 数据库表结构
- 新增 `file_mining_record` 表（文件挖掘状态追踪）
- 新增 `candidate_contribution` 表（文件级贡献可替换）
- `dependency_candidate` 新增 4 列：`review_route`, `non_graph_reason`, `non_graph_reviewer`, `active_algorithm_version`

### Task 2: 候选引擎重构
- `candidate_engine.py` 新增 `generate_single_file_candidates()` — 单文件生成贡献级结果
- `candidate_engine.py` 新增 `aggregate_contributions()` — 多文件贡献汇总

### Task 3-5: 后端 API
- `POST /files/mine` — 选择多个文件挖掘，解析→生成→合并入候选池
- `POST /files/{file_id}/re-mine` — 重挖单文件（删旧贡献→重算→重新挖掘）
- `GET /files/mining-status` — 查询文件挖掘状态
- `POST /candidates/{id}/mark-non-graph` — 标记非图谱依赖
- `POST /candidates/{id}/revert` — 回退 graph→pending 或 non_graph→pending
- 更新 accept/reject 路由适配新列结构
- 新增 `_determine_review_route()` 和 `_recalculate_candidate_scores()` 辅助方法

### Task 6-7: 前端
- `dependency-mining.ts` — 更新接口定义，新增 5 个 API 函数，移除废弃函数
- `DependencyMining.vue` — 完全重写为左侧文件选择器 + 右侧三 tab（候选池/图谱库/非图谱库）布局

### Task 8: 集成测试 + 清理
- `test_full_incremental_pipeline` 端到端测试覆盖完整增量流程
- 旧路由标记为 DEPRECATED（保留兼容性）

## 不在本次范围内的内容

- 算法版本切换操作（§4.8）
- LLM 审核路由的自动处理
- 前端可视化图谱展示
- 性能优化（大批量文件场景）

## 改动文件清单

| 文件 | 变更类型 |
|------|----------|
| `backend/plugins/mml_manager/main.py` | 重构 — 新增表、路由、辅助方法 |
| `backend/plugins/mml_manager/candidate_engine.py` | 扩展 — 新增 2 个函数 |
| `backend/tests/test_dependency_mining.py` | 扩展 — 26 个测试 |
| `frontend/src/api/dependency-mining.ts` | 重写 — 新接口和 API 函数 |
| `frontend/src/views/plugins/DependencyMining.vue` | 重写 — 新布局 |

## 关键设计决策

1. **贡献层统一**: 所有挖掘结果（包括 graph/non_graph 状态的候选）都写入 `candidate_contribution`，不绕过事实层
2. **零贡献保护**: graph/non_graph 记录永不因零贡献被删除，零贡献时汇总分数置零
3. **状态收敛**: 主 status 仅 4 种（pending/graph/non_graph/rejected），审核路由拆为独立 `review_route` 字段
4. **算法版本隔离**: `active_algorithm_version` 控制汇总口径，只取激活版本的贡献

## 已执行验证

- 后端全量测试：107 passed, 0 failed（含 26 个增量挖掘测试）
- 前端 TypeScript 编译：`vue-tsc --noEmit` 通过
- 前端构建：`npm run build` 通过

## 已知风险

1. 旧路由 `/candidates/generate` 和 `/versions/{id}/batch-extract` 保留但标记为 DEPRECATED，部分旧测试仍依赖它们
2. `_recalculate_candidate_scores` 内联调用 `candidate_engine.aggregate_contributions`，若贡献表数据量大可能有性能问题
3. 前端 `handleMarkNonGraph` 使用 `window.prompt()` 收集原因，后续可改为 Naive UI Modal

## 提交记录

```
52eedf8 chore: mark deprecated batch mining routes (superseded by /files/mine)
06b1fdf feat: update frontend API module and redesign DependencyMining view with file selector and three-tab layout
a5092ae feat: add file mining API (mine, re-mine, mining-status) and candidate status model updates
9e795ed feat: add generate_single_file_candidates and aggregate_contributions to candidate_engine
a7f3f1b feat: add file_mining_record and candidate_contribution tables, new columns on dependency_candidate
```

## 审查重点（指定给 Codex）

1. **状态机完整性**: 验证 pending→graph、pending→non_graph、pending→rejected、graph→pending、non_graph→pending 五条转换是否严格按照设计文档实现
2. **零贡献保护**: 确认 re-mine 流程中 graph/non_graph 记录不会被误删
3. **贡献层统一**: 确认 graph/non_graph 状态的候选在挖掘时仍会记录贡献（不绕过事实层）
4. **汇总一致性**: 验证 `_recalculate_candidate_scores` 只取 `active_algorithm_version` 匹配的贡献
5. **前端状态同步**: 确认三个 tab 的数据源与后端 status 值正确对应
