# graph-mining-evolution-001 Codex 审查报告

## 审查背景

- 任务 ID：`graph-mining-evolution-001`
- 审查对象：`docs/plans/2026-04-03-graph-mining-evolution-design.md`
- 审查时间：2026-04-03
- 审查目标：确认图谱挖掘体系从 MVP 向正式框架演进的设计是否覆盖当前代码事实、关键状态流转和后续实施边界。

## 审查范围

- 设计文档中的插件拆分、任务框架、数据模型、API 和前端方案
- 当前 `backend/plugins/mml_manager/main.py`
- 当前 `frontend/src/views/plugins/DependencyMining.vue`
- 当前相关测试 `backend/tests/test_dependency_mining.py`

## 发现的问题

### 1. `file_mining_record` 维持“不变”无法承载设计中的排队/执行/失败文件状态

- 严重性：高
- 设计依据：
  - 设计要求通过任务队列展示文件级状态，并在挖掘管理页区分“未挖掘 / 排队或挖掘中 / 已完成 / 失败”（`docs/plans/2026-04-03-graph-mining-evolution-design.md` 第 304、342、389-405 行）。
  - 但设计同时声明 `file_mining_record` “不变”（第 304 行）。
- 现状依据：
  - 当前 `file_mining_record` 只有 `mined`、`algorithm_version`、`command_count` 等字段，没有任务关联、运行态或失败态字段（`backend/plugins/mml_manager/main.py` 第 158-168 行）。
  - 当前文件状态接口也只返回这些静态字段（第 1446-1459 行）。
- 风险说明：
  - 如果仍保持该表不变，前端无法稳定区分“已入队但未开始”“执行中”“失败”“取消后未完成”等状态。
  - 右侧任务中心与左侧文件列表会各自依赖不同来源拼装状态，极易出现同一文件在列表中显示“未挖掘”，但在 job 中实际已排队或失败的 UI/数据不一致。
- 建议修复：
  - 在第一阶段补充文件级任务映射设计，至少明确以下其一：
    1. 扩展 `file_mining_record`，增加 `job_id`、`status`、`last_error`、`queued_at`、`started_at`、`finished_at`；
    2. 或单独新增 `mining_file_state` / `job_item` 到文件状态的稳定投影视图，并明确 `/files` 接口如何返回最终文件态。

### 2. 插件拆分后，文件删除/重挖等生命周期清理链路缺失，现有数据一致性会断掉

- 严重性：高
- 设计依据：
  - 设计要求 `graph_mining` 完全独立，并声明 `mml_manager` 不依赖 `graph_mining`，`graph_mining` 仅只读访问 `file_entry`、`command_instance`、`ne_version`（`docs/plans/2026-04-03-graph-mining-evolution-design.md` 第 88-92 行）。
  - 设计的表归属又把 `dependency_candidate`、`candidate_contribution`、`file_mining_record`、`graph_edge`、`graph_changelog` 迁给了 `graph_mining`（第 301-306 行）。
- 现状依据：
  - 当前文件重挖/清理逻辑发生在 `mml_manager` 内部，它会删除文件贡献、重算候选、同步清空图谱边证据，再重新执行单文件挖掘（`backend/plugins/mml_manager/main.py` 第 1369-1444 行）。
  - 当前实现里，文件生命周期事件是驱动图谱候选一致性的入口，而不是纯只读场景。
- 风险说明：
  - 一旦相关表和重算逻辑迁到 `graph_mining`，但 `mml_manager` 仍保持“不依赖 graph_mining”，文件删除、解绑、重挖、覆盖上传等入口将没有明确的跨插件通知机制。
  - 结果会是 `file_entry` / `command_instance` 已更新，但 `candidate_contribution`、`dependency_candidate`、`graph_edge` 仍保留旧证据，形成悬挂贡献和错误图谱状态。
- 建议修复：
  - 在设计中明确文件生命周期事件的归属与触发路径。至少需要以下其一：
    1. `mml_manager` 通过注册表调用 `graph_mining` 暴露的文件变更 hook；
    2. `core` 层提供领域事件总线，由 `graph_mining` 订阅文件删除/重挖事件；
    3. 明确文件重挖入口整体迁到 `graph_mining`，`mml_manager` 只保留原始文件 CRUD。

### 3. 候选新状态机没有定义“增量重挖下保留人工终态”的规则，容易回退人工决策

- 严重性：中
- 设计依据：
  - 设计把候选状态机改为 `pending -> llm_reviewing -> ready_for_review -> graph/non_graph/rejected`，并描述挖掘管线会在分流后直接进入 `ready_for_review` 或 `llm_reviewing`（`docs/plans/2026-04-03-graph-mining-evolution-design.md` 第 175-199、261-293 行）。
  - 但文档没有说明已有 `graph` / `non_graph` / `rejected` 候选在新证据进入时如何保留、重激活或只更新证据。
- 现状依据：
  - 当前实现会在候选重复出现时保留 `graph` / `non_graph` / `rejected` 终态，只更新置信度和证据（`backend/plugins/mml_manager/main.py` 第 849-867 行）。
  - 当前增量重挖还会在有新证据时仅重新激活 `rejected`，而不是无差别回退所有人工终态（第 1334-1345 行）。
  - 现有测试也显式要求 `graph` 状态在重挖移除证据后仍保留，只把证据和置信度清零（`backend/tests/test_dependency_mining.py` 第 1142-1157 行）。
- 风险说明：
  - 如果第一阶段按新状态机直接重写而没有兼容规则，增量挖掘可能把人工已确认的 `graph` / `non_graph` 候选重新打回 `ready_for_review`，或让 LLM 路由覆盖人工结论。
  - 这会直接破坏当前 MVP 已建立的人工终审语义。
- 建议修复：
  - 在设计文档中单列“增量重挖与人工终态保护”规则，至少明确：
    1. `graph` / `non_graph` 在新证据到来时只更新事实层，不自动改状态；
    2. `rejected` 是否仍沿用“新证据可自动激活”；
    3. `ready_for_review` 与 `review_route` 的职责边界，避免状态机和分流字段双重表达。

## 测试缺口

- 设计尚未定义第一阶段必须补齐的任务框架测试矩阵，尤其缺少：
  - job 取消后 `job_item` 与文件状态的一致性测试
  - 文件删除/重挖触发 graph_mining 清理的跨插件集成测试
  - 已审核候选在增量重挖后保持终态的回归测试
- 前端方案缺少文件列表状态与任务中心一致性的联调验收标准。

## 回归风险

- 文件级异步化后，旧的同步 `/files/mine` 语义与新的 job 模型并存期间，最容易出现状态不同步。
- 插件拆分如果没有补领域事件或 hook，文件生命周期相关的一致性回归风险最高。
- 状态机扩展如果不先补规则，人工审核结果被重挖覆盖的风险高于 UI 重构风险。

## 建议修复项

1. 先补“文件状态模型”与 `/files` 返回契约，再开始前端任务中心设计。
2. 在设计中增加“文件生命周期事件 -> graph_mining 清理/重算”的正式链路，不要只保留只读依赖描述。
3. 在设计中增加“增量重挖对 graph/non_graph/rejected 的处理规则”和对应测试要求。

## 无法确认的残余风险

- 当前设计未展开数据库迁移顺序，无法确认插件拆分时旧库升级脚本是否会出现窗口期不一致。
- 第二阶段 LLM job 与候选状态更新是否需要事务边界，文档尚未定义。

## 管理员介入影响

- 设计文档已标注“经管理员逐节审核通过”，说明当前方案已获得阶段性认可。
- 但上述问题属于“已批准设计仍缺少实现前约束”的范畴，建议在进入实施计划前补齐，否则后续计划会建立在不完整前提上。

## 修订复审结果（2026-04-03 21:00）

- 复审对象：`docs/plans/2026-04-03-graph-mining-evolution-design.md` v2
- 复审结论：上一轮提出的 3 个设计缺口已在文档正文中闭环：
  - 文件状态模型已补充到 §6.4，明确 `file_mining_record` 演进字段、文件状态派生规则和 `/files` 返回契约。
  - 跨插件生命周期已补充到 §6.5，明确由 `core.events` 承接 `file.deleted`、`file.content_replaced`、`ne_version.deleted` 事件，以及 graph_mining 的清理职责。
  - 增量重挖终态保护已补充到 §6.6，明确 `graph` / `non_graph` 保持终态、`rejected` 可被新证据激活，并补齐了第一阶段必须覆盖的测试要求。
- 残余说明：
  - 文档存在两个 `## 11` 章节标题，属于编号层面的编辑问题，不影响当前设计语义，也不构成阻塞。
  - 数据库迁移脚本和第二阶段 LLM 事务边界仍未展开，但属于后续实施计划和实现阶段需要继续细化的事项，不阻塞当前进入实施计划。

## 最终评估

- 结论：**复审通过，可进入实施计划**
- 原因：Claude 已按审查意见在原设计文档上完成增量修订，当前版本已补齐进入实施计划所需的关键设计约束。后续重点转入任务拆分、迁移顺序和测试落地。
