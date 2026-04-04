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

## 实施计划复审结果（2026-04-04 10:13）

### 1. `JobWorker` 的注册链路没有闭合，Task 10 当前写法无法把 mining handler 挂到真实 worker 上

- 严重性：高
- 依据：
  - Task 5 只把 `worker = JobWorker(job_service)` 放到 `app.state.job_worker`，没有注册进 `ServiceRegistry`，而插件上下文只能通过 `ctx.get_service(...)` 访问 registry 内的服务（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 620-634 行；`backend/core/plugin/context.py` 第 12-16 行）。
  - Task 10 却要求在 `graph_mining/main.py` 的 `on_register` 中注册 handler，但示例代码只是 `ctx.register_service(type(mining_worker), mining_worker)`，这只会把 `MiningWorker` 实例放进 registry，并不会把 handler 注册到全局 `JobWorker`（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1162-1184 行）。
- 风险：
  - 按当前计划执行，`POST /mining/start` 能创建 job，但全局 worker 没有 `"mining"` handler，队列会停在 `queued`。
  - 计划文本本身在同一任务内先给出一种做法，再在注释里推翻为“最简方案”，会让 Claude 在执行阶段缺少唯一正确实现路径。
- 建议修复：
  - 在实施计划中明确唯一方案，例如：
    1. Task 5 把 `JobWorker` 注册进 `ServiceRegistry`；
    2. Task 10 明确使用 `ctx.get_service(JobWorker).register_handler("mining", mining_worker.handle)`；
    3. 删除 `ctx.register_service(type(mining_worker), mining_worker)` 这条误导性写法。

### 2. 跨插件生命周期清理的执行主体未抽出来，Task 11 依赖了并不存在于 `graph_mining/main.py` 的能力

- 严重性：高
- 依据：
  - Task 10 把 `_recalculate_candidate`、`_mine_single_file` 等复杂逻辑放在 `workers/mining_worker.py` 内（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1092-1156 行）。
  - 但 Task 11 又要求在 `graph_mining/main.py` 的事件 handler 中直接调用 `self._recalculate_candidate(...)`，而计划没有定义这些方法会出现在 `Plugin` 类上，也没有单独抽出可复用的 service（第 1224-1243 行）。
- 风险：
  - 文件删除/替换事件是当前数据一致性的关键入口。如果这部分逻辑没有明确 owner，实施时很容易出现一套重算逻辑在 worker 中、一套清理逻辑在 plugin 中，最后发生行为分叉或直接调用不存在的方法。
  - 这会把我们前面已经在设计层补齐的“生命周期清理链路”再次打回不确定状态。
- 建议修复：
  - 在实施计划里补一个共享的 `MiningDomainService` / `CandidateService` / `LifecycleService` 之类的任务，明确：
    1. worker 和事件 handler 共用同一套候选重算/终态保护逻辑；
    2. `graph_mining/main.py` 只负责注册路由和事件，不直接承载复杂领域逻辑；
    3. Task 10、11 的文件归属和调用关系重新写清。

### 3. Task 3 的示例实现本身不可运行，TDD 基线会被计划里的错误代码带偏

- 严重性：中
- 依据：
  - Task 3 的 `worker.py` 示例里使用了 `_json.dumps(...)`，但文件顶部既没有 `import json as _json`，也没有任何 `_json` 定义（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 452-454 行）。
  - 同一段计划又在注释里声称“`import json` 已在顶部”，与示例代码不一致（第 462 行）。
- 风险：
  - 这是计划文档里的直接可执行片段，不是纯描述。Claude 按计划逐 task 落地时，如果照抄这里的基线，会在最早的核心基础设施任务里引入显式运行错误。
  - 这类错误会污染“先写测试再实现”的节奏，因为失败将来自计划示例自身，而不是任务预期。
- 建议修复：
  - 修正文档中的实现片段，保证代码示例最少是语法和名字一致的可运行基线。

## 实施计划二次复审结果（2026-04-04 11:37）

### 1. Task 11 的事件清理示例仍然没有形成可执行的重算链路，当前片段会产出错误分数或直接引入坏代码

- 严重性：高
- 依据：
  - 当前 Task 11 的 `graph_mining` 事件 handler 示例在删除贡献后，直接执行 `await self.candidate_service.recalculate(row["candidate_id"], "v1")`，没有先计算 `ne_version_id` 对应的 `total_mined`（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1258-1269 行）。
  - 紧接着又出现一行游离且缩进错误的 `total_mined = await self.candidate_service.get_total_mined(payload.get("ne_version_id"))`，它既不在循环前，也没有被传给 `recalculate`（第 1271 行）。
  - 同一份计划里，Task 10 的 worker 路径明确要求 `recalculate(cand_id, alg_ver, total_mined)` 先拿到总文件数再重算（第 1182-1185 行），说明这里的 Task 11 已经和共享服务契约失配。
- 风险：
  - 文件删除/替换正是我们前面最强调的数据一致性入口。如果这里按当前计划实现，候选分数会在错误分母下重算，或者开发时被这段坏示例直接带偏。
  - 这不是描述层的小瑕疵，而是会影响核心清理链路正确性的阻塞问题。
- 建议修复：
  - 在 Task 11 明确改成：
    1. 先取 `ne_version_id = payload["ne_version_id"]`
    2. 删除 contribution / file_mining_record
    3. `total_mined = await self.candidate_service.get_total_mined(ne_version_id)`
    4. 再循环 `await self.candidate_service.recalculate(candidate_id, "v1", total_mined)`
  - 并删除当前缩进错误的游离代码片段。

### 2. Task 3 仍然声称已修复 `_json.dumps`，但正文示例顶部依然没有 `import json`

- 严重性：中
- 依据：
  - Task 3 的 `worker.py` 示例现在把 `_json.dumps` 改成了 `json.dumps`（第 457 行），但该代码块顶部仍只有 `import asyncio` 和 `import logging`，没有 `import json`（第 408-413 行）。
  - 文档注释却写“上面 handler 调用中 `import json` 已在顶部”，与正文不一致（第 466 行）。
- 风险：
  - 这会让 Claude 在最早的基础设施任务中继续遇到 `NameError`，说明“已闭环”的修复并未真正落到文本基线。
- 建议修复：
  - 在 Task 3 代码块顶部补上 `import json`，并重新核对正文与注释一致。

### 3. 任务引用和依赖图仍未完全同步到 v2，执行时会继续制造错位上下文

- 严重性：中
- 依据：
  - Task 9 仍写着“实际挖掘由 mining_worker 异步执行（Task 11）”，但 v2 已把共享领域服务和 mining worker 调整到 Task 10（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1045 行、1080 行）。
  - 依赖图和总计仍写 “Task 10 (worker)” 且 “预估 Tasks: 20 个”，没有体现新增的 10a 子任务和重新划分后的关键依赖（第 1697-1724 行）。
  - 协作消息中宣称“3 项问题已闭环”，但计划正文仍存在上述未同步内容，说明当前版本还不是稳定的执行基线。
- 风险：
  - 这类错位会在后续执行时让人按照错误 task 编号跳读文档，尤其在长计划、多次提交的情况下，容易把 Task 10/11 的职责再次混淆。
- 建议修复：
  - 把 Task 9 中对 worker 的引用改成当前正确编号。
  - 把依赖图和总计同步到 v2 的任务结构，至少保证编号引用与正文一致。

## 最终评估

- 结论：**实施计划仍需继续修订，暂不建议进入执行**
- 原因：v2 修掉了上一轮的一部分问题，但 Task 11 的清理重算链路仍然不正确，Task 3 的代码基线也没有真正修干净；若现在放行，执行仍会在核心基础设施和生命周期清理上偏航。
