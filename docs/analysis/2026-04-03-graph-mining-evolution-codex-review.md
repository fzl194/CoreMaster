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

## 实施计划三次复审结果（2026-04-04 11:44）

### 1. Task 11 仍未给出真正的事件订阅动作，按当前正文实现时 graph_mining 不会收到任何生命周期事件

- 严重性：高
- 依据：
  - Task 11 标题写的是“mml_manager 触发 + graph_mining 订阅”，但正文只有 `mml_manager` 侧的 `emit("file.deleted", ...)` 示例，以及 `graph_mining` 侧一个 `_on_file_deleted` 函数片段（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1234-1274 行）。
  - 该段没有任何 `self.event_bus.on(...)` / `event_bus.on(...)` 注册语句，也没有展示 `file.content_replaced` / `ne_version.deleted` 的订阅注册。
- 风险：
  - 即使 `mml_manager` 正确发事件，`graph_mining` 端也不会有 handler 被挂上去，文件删除/替换后的清理链路仍然是断的。
  - 这会直接打破设计文档 §6.5 中最关键的跨插件一致性保证。
- 建议修复：
  - 在 Task 11 明确补上事件注册代码，例如：
    1. `self.event_bus = ctx.get_service(PluginEventBus)`
    2. `self.event_bus.on("file.deleted", self._on_file_deleted)`
    3. `self.event_bus.on("file.content_replaced", self._on_file_content_replaced)`
    4. `self.event_bus.on("ne_version.deleted", self._on_ne_version_deleted)`

### 2. Task 11 的 handler 签名与其所处上下文仍然矛盾，按正文字面实现会在第一次 emit 时抛参数错误

- 严重性：高
- 依据：
  - 文档明确写“在 `graph_mining/main.py` 的 `on_register` 中”，随后给出的示例是 `async def _on_file_deleted(self, payload): ...`（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1255-1260 行）。
  - 如果这是 `on_register` 里的局部函数，它不应该带 `self` 形参；而如果它是类方法，就不应表述为“在 on_register 中定义”。
  - 当前 `PluginEventBus.emit()` 设计是把单个 `payload` 传给 handler，因此局部函数若带 `self` 会在调用时直接缺参。
- 风险：
  - 这会让第一次处理 `file.deleted` 时直接抛 `TypeError`，而不是执行清理。
  - 由于 `PluginEventBus` 约定“handler 失败不阻塞主流程”，这个错误还可能被日志吞掉，留下静默的数据不一致。
- 建议修复：
  - 二选一明确写法：
    1. 把 `_on_file_deleted` 明确写成 `Plugin` 类方法，并在 `on_register` 中注册 `self._on_file_deleted`；
    2. 或者把它写成 `on_register` 内的局部函数 `async def _on_file_deleted(payload): ...`，不要带 `self` 参数。

### 3. Task 5 的“启动成功验证”仍然没有覆盖 lifespan 和插件注册阶段，无法发现这轮最关键的 worker / event_bus 接线错误

- 严重性：中
- 依据：
  - Task 5 的验证步骤仍然是 `python -c "import main; print('OK')"`（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 652-654 行）。
  - 这个命令只验证模块能 import，不会运行 FastAPI lifespan，因此不会执行 job 表初始化、`registry.register(JobWorker, worker)`、插件 `on_register`、也不会启动 worker。
- 风险：
  - 当前计划最脆弱的地方恰好是 lifespan 内的服务装配和插件注册顺序；而现有验证步骤对这些完全没有覆盖。
  - 结果是计划声称“接入主应用完成”，但最核心的接线错误要到更后面的任务甚至手动联调才会暴露。
- 建议修复：
  - 把验证改成至少能执行 lifespan 的方式，例如补一个最小启动测试，或使用 `TestClient(app)` / `asgi-lifespan` 跑一遍应用启动流程，再断言 `registry` 中能取到 `JobService`、`JobWorker`、`PluginEventBus`。

## 最终评估

- 结论：**实施计划 v3 仍未达到可执行基线，继续不放行**
- 原因：Claude 修掉了上一轮指出的字面问题，但 Task 11 的订阅动作和 handler 签名仍然没有闭合；这会让跨插件生命周期清理在真正执行时继续失效。

## 实施计划四次复审结果（2026-04-04 14:35）

### 1. Task 5 的 lifespan 验证示例仍然对不上当前代码骨架，按正文执行会直接失败，也无法证明启动链路真的跑通

- 严重性：高
- 依据：
  - v4 把验证步骤改成了 `backend/tests/test_lifespan.py`，但示例正文仍写成 `from core.plugin.registry import ServiceRegistry` 和 `ServiceRegistry.instance()`（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 667-673 行）。
  - 当前仓库里实际存在的是 [`backend/core/services/registry.py`](D:/mywork/CoreMaster/backend/core/services/registry.py)，只有普通 `ServiceRegistry` 类，没有 `core.plugin.registry` 模块，也没有 `instance()` 单例接口。
  - 现有集成测试触发生命周期的标准写法也是 `async with app.router.lifespan_context(app): ...`，而不是单独 `AsyncClient(transport=ASGITransport(app=app))` 后 `pass`（[`backend/tests/test_integration.py`](D:/mywork/CoreMaster/backend/tests/test_integration.py) 第 8-13 行）。
- 风险：
  - 按计划正文落地，测试会先因为错误 import / 错误 API 直接失败，根本到不了验证 `JobService`、`JobWorker`、`PluginEventBus` 装配的阶段。
  - 这意味着 Claude 声称已补强的“lifespan 启动验证”仍然没有真正锚定到当前代码库的启动方式，无法证明最关键的接线链路已受保护。
- 建议修复：
  - 把示例改成与现有仓库一致的写法：显式进入 `app.router.lifespan_context(app)`，然后从 `app.state.registry` 取 registry 并断言服务存在。
  - 删除 `core.plugin.registry` / `ServiceRegistry.instance()` 这类当前仓库不存在的接口引用。

### 2. Task 2 的 `JobService.create_job()` 仍然依赖当前 `DatabaseService` 不提供的返回值，核心基础设施任务一开始就会跑偏

- 严重性：高
- 依据：
  - 计划正文里 `JobService.create_job()` 仍写成 `cursor = await self.db.execute(...)` 后再取 `cursor.lastrowid`（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 247-251 行）。
  - 但当前 [`backend/core/services/database.py`](D:/mywork/CoreMaster/backend/core/services/database.py) 的 `DatabaseService.execute()` 明确只 `execute + commit`，返回值是 `None`，并不会把 cursor 暴露给调用方。
- 风险：
  - Claude 若按该计划直接实现，Task 2 会在最基础的 `create_job()` 路径上触发 `AttributeError: 'NoneType' object has no attribute 'lastrowid'`。
  - 这不是实现时可自由发挥的小细节，而是计划示例与现有公共服务接口直接冲突，会把后续 Task 3/5/9 全部建立在错误基线上。
- 建议修复：
  - 在计划里先明确二选一：
    1. 扩展 `DatabaseService`，新增返回 cursor / lastrowid 的接口；
    2. 或保持 `DatabaseService` 不变，改用额外查询（例如 `SELECT last_insert_rowid()`）或其他明确方式拿 `job_id`。
  - 在未补齐这一前提前，不建议进入执行。

### 3. Task 9 对 worker 归属的引用仍未完全同步，执行时会继续制造错位上下文

- 严重性：中
- 依据：
  - 当前 Task 9 仍写“实际挖掘由 mining_worker 异步执行（Task 11）”（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1072 行）。
  - 但 v2 之后的正文已经把共享领域服务拆到 Task 10a，把 `MiningWorker` 明确拆到 Task 10b；Task 11 负责的是跨插件事件集成，不是 worker 实现本身。
- 风险：
  - 这会让执行者在阅读 Task 9 时继续跳去 Task 11 找 worker 语义，重复制造我们前几轮一直在收敛的 Task 10/11 职责混淆。
- 建议修复：
  - 把 Task 9 里的引用同步为 Task 10b，并顺手全局扫一遍 Task 编号引用，保证正文、依赖图、消息结论一致。

## 本轮结论（2026-04-04 14:35）

- 结论：**实施计划 v4 仍未达到可执行基线，继续不放行**
- 原因：
  - Task 5 的“启动验证”虽然改了方向，但正文示例仍引用当前仓库不存在的 registry 接口，也没有按现有测试基线正确进入 lifespan。
  - Task 2 的 `create_job()` 仍依赖当前 `DatabaseService` 不提供的 `lastrowid` 返回值，核心任务链路从一开始就不成立。
  - Task 9 的任务引用同步仍未完全收口，执行上下文继续存在错位风险。

## 实施计划五次复审结果（2026-04-04 15:20）

### 1. Task 11 仍然漏掉“文件夹递归删除”这条现有生命周期入口，graph_mining 清理链路在真实代码上仍然不完整

- 严重性：高
- 依据：
  - v5 虽然修掉了单文件 `file.deleted` / lifespan / `lastrowid` 的问题，但 Task 11 的事件方案正文仍只写“在文件删除路由中（`DELETE /entries/{entry_id}`）添加 `file.deleted` 事件”，示例 payload 也是单个 `file_entry_id`（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1266-1273 行）。
  - 当前真实 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py) 的 `DELETE /entries/{entry_id}` 不是单纯删文件：同一路由还承担“删除文件夹并递归删除其所有子文件/子目录”的职责，会先 `collect_ids()` 收集整棵子树，再批量删除所有 `file_entry`（第 397-455 行）。
  - 现有测试也明确覆盖了这一行为，见 [`backend/tests/test_mml_manager.py`](D:/mywork/CoreMaster/backend/tests/test_mml_manager.py) 的 `test_20_delete_folder_recursive`（第 497-540 行）。
- 风险：
  - 如果按当前 Task 11 文本直接执行，删除单个文件时也许能发一个 `file.deleted`，但删除文件夹时不会天然给每个后代文件都补齐 graph_mining 清理。
  - 结果是 `file_entry` / 磁盘文件已经被递归删掉，但 `candidate_contribution`、`file_mining_record` 以及后续候选聚合结果仍可能残留悬挂数据。
  - 这正是设计文档 §6.5 想解决的生命周期一致性问题；当前计划在真实代码入口上还没有闭环。
- 建议修复：
  - 在 Task 11 明确写出递归删除策略，至少二选一：
    1. `mml_manager` 在文件夹删除时先收集所有后代 `file_entry_id + ne_version_id`，对每个文件逐条 `emit("file.deleted", ...)`；
    2. 或新增批量事件/批量清理接口，由 `graph_mining` 一次性消费整批被删文件。
  - 同时补一条第一阶段集成测试，覆盖“删除含子文件的文件夹后 graph_mining 数据同步清理”。

## 本轮结论（2026-04-04 15:20）

- 结论：**实施计划 v5 仍未达到可执行基线，继续不放行**
- 原因：
  - Claude 修掉了上一轮指出的 Task 2、Task 5、Task 9 三个代码对照问题。
  - 但 Task 11 仍未覆盖当前 `mml_manager` 已存在且已有测试保护的“文件夹递归删除”入口，跨插件生命周期清理在真实代码路径上仍不完整。

## 实施计划六次复审结果（2026-04-04 15:50）

### 1. Task 11 新增的递归删除/版本删除测试要求没有同步到 Task 19 的正式测试矩阵，执行基线仍然分裂

- 严重性：中
- 依据：
  - v6 在 Task 11 中补充了 3 条集成测试要求：单文件删除清理、删除含子文件的文件夹后全后代清理、版本删除批量清理（`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1360-1364 行）。
  - 但 Task 19 的正式测试矩阵仍停留在旧版本，只列了 7 条用例，其中仍只有笼统的“文件删除触发清理”，没有把“文件夹递归删除全后代清理”和“版本删除批量清理”列为独立测试项（第 1701-1708 行），运行期望也仍写着 `Expected: 7 passed`（第 1737-1738 行）。
- 风险：
  - Claude 这轮新增的闭环要求只存在于 Task 11 段落说明里，没有真正沉到统一的测试任务矩阵中。
  - 后续执行者按 Task 19 落测试时，仍然可能只补单文件删除清理，而漏掉刚刚确认必须覆盖的目录递归删除和版本删除链路。
  - 这类“正文补了，测试总表没同步”的问题，在长计划和多轮修订中会持续制造错读。
- 建议修复：
  - 把 Task 19 的测试表同步到 v6 基线，至少显式新增：
    1. `删除含子文件的文件夹 → 所有后代清理生效`
    2. `删除版本 → 该版本下批量清理链路生效`
  - 同步更新 `Expected: N passed` 的计数，保证 Task 11 和 Task 19 描述一致。

## 本轮结论（2026-04-04 15:50）

- 结论：**实施计划 v6 仍未达到可执行基线，继续不放行**
- 原因：
  - Claude 已补上 Task 11 的递归删除思路，本轮不再重复前一轮的生命周期入口问题。
  - 但新增要求没有同步进入 Task 19 的正式测试矩阵和通过计数，执行基线仍然分裂。

## 实施计划七次全量复审结果（2026-04-04 16:25）

> 本轮不再只追上一轮修补点，而是按“计划正文 ↔ 设计文档 ↔ 当前代码/测试基线”做了一次全量代码对照复审。以下问题为当前可确认的剩余阻塞项。

### 1. `job_item.item_key` 的编码约定仍然自相矛盾，任务状态派生链路按当前正文无法同时成立

- 严重性：高
- 依据：
  - 设计文档与 Task 9 都写 `/files` 状态派生通过 `item_key=file_entry_id` 关联 `job_item` 与文件（`docs/plans/2026-04-03-graph-mining-evolution-design.md` 第 348 行；`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md` 第 1072-1074 行）。
  - 但 Task 2/Task 10 的示例又把 `item_key` 当成 `"file:1"` 这种带前缀字符串：Task 2 测试直接创建 `["file:1", "file:2"]`，Task 10 handler 也写死 `int(item["item_key"].replace("file:", ""))`（实施计划第 173、204、1192 行）。
- 风险：
  - 如果 `item_key` 真实存成 `"file:1"`，Task 9 的 `/files` JOIN/派生逻辑按 `item_key=file_entry_id` 就无法直接命中。
  - 如果 `item_key` 真实存成纯数字字符串/整数，Task 10b 的 `replace("file:", "")` 又是多余且误导的另一套契约。
  - 这会直接影响文件状态展示、worker 消费和取消/进度链路，是异步任务框架的基础契约问题。
- 建议修复：
  - 在设计文档、Task 9、Task 10、测试里统一 `item_key` 契约。
  - 推荐二选一并全局收口：
    1. 统一为纯 `file_entry_id` 字符串/整数，worker 直接 `int(item["item_key"])`；
    2. 或统一为 `file:{id}`，并在 `/files` 状态派生处明确写出解析/映射方式，而不是写“item_key=file_entry_id”。

### 2. `ne_version.deleted` 事件及对应测试要求与当前 `mml_manager` 的真实删除语义冲突，按现状根本没有可触发入口

- 严重性：高
- 依据：
  - 设计文档和实施计划都把 `ne_version.deleted` 作为正式生命周期事件，Task 11/Task 19 还要求覆盖“删除版本 → 批量清理”链路（设计文档第 393 行；实施计划第 1327-1341、1705-1706 行）。
  - 但当前真实 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py) 的 `DELETE /ne-versions/{ne_id}` 在存在任何关联文件时直接返回 400“该网元版本下存在关联文件，无法删除”（第 267-278 行）。
  - 现有 [`backend/tests/test_mml_manager.py`](D:/mywork/CoreMaster/backend/tests/test_mml_manager.py) 也只覆盖“无文件时删除成功”，没有“带文件版本可删除”的入口（第 140-174 行）。
- 风险：
  - 当前计划把“版本删除批量清理”当成第一阶段必测链路，但现有代码事实里根本没有这样的可执行入口。
  - 后续实现者会在“是修改 `mml_manager` 删除语义，还是删除该事件/测试要求”之间摇摆，计划无法指导唯一实现。
- 建议修复：
  - 在计划中明确二选一：
    1. 第一阶段修改 `mml_manager.delete_ne_version`，允许删除带文件版本，并补对应级联/事件发射；
    2. 或删除/降级 `ne_version.deleted` 的第一阶段要求，把它移到后续阶段。

### 3. 最终测试迁移链路仍未闭合，`test_dependency_mining.py` 的去向没有任何正式任务承接

- 严重性：高
- 依据：
  - Task 12 明确写“挖掘相关测试因路径变更需迁移到新测试文件”（实施计划第 1409-1410 行）。
  - 当前仓库里真实存在一个庞大的 [`backend/tests/test_dependency_mining.py`](D:/mywork/CoreMaster/backend/tests/test_dependency_mining.py)，其大量测试都直接打到 `/api/plugins/mml_manager` 下的 `/files/mine`、`/files/mining-status`、`/candidates/*`、`/re-mine` 等旧挖掘路由。
  - 但 Task 19 只新增 `test_graph_mining_integration.py`，没有任何 task 明确修改/拆分/删除旧的 `test_dependency_mining.py`；Task 20 却又要求 `pytest tests/ -v` 全通过（第 1757-1758 行）。
- 风险：
  - 一旦 Task 12 按计划把挖掘路由从 `mml_manager` 删掉，现有 `test_dependency_mining.py` 将成批失败。
  - 这不是“后续顺手处理”的小问题，而是最终回归目标与任务拆分本身未闭合。
- 建议修复：
  - 增加一个显式测试迁移任务，至少明确：
    1. 哪些用例迁移到 `test_graph_mining_integration.py`；
    2. 哪些保留在 `test_mml_manager.py`；
    3. `test_dependency_mining.py` 是重写、拆分还是删除。

### 4. Task 5 的 worker 生命周期管理仍有缺口，按正文实现会留下未受控后台任务

- 严重性：中
- 依据：
  - Task 5 启动 worker 的示例是 `asyncio.create_task(worker.start())`，但没有保存 task handle；清理阶段只有 `await worker.stop()`（实施计划第 639-646 行）。
  - 当前仓库大量测试通过 `app.router.lifespan_context(app)` 反复启动/关闭应用（例如 [`backend/tests/test_integration.py`](D:/mywork/CoreMaster/backend/tests/test_integration.py) 第 8-13 行）。
- 风险：
  - 仅设置 `_running=False` 而不等待后台 task 退出，容易在 shutdown 后留下仍处于 sleep / query 循环中的 worker。
  - 在测试环境里这会导致“应用已退出但后台任务仍访问 db/registry”的竞态，表现为 flaky 测试、pending task warning 或关闭时序问题。
- 建议修复：
  - 在 lifespan 中保存 `worker_task = asyncio.create_task(worker.start())` 到 `app.state` 或局部变量。
  - shutdown 时先 `await worker.stop()`，再显式 `await worker_task`，确保退出链路闭合。

### 5. 新测试示例与现有 pytest-asyncio 基线不一致，且夹具片段本身还残留未定义变量

- 严重性：中
- 依据：
  - 实施计划里的 `job_db` 和 `setup_env` 都写成 `@pytest.fixture` + `async def ...`（第 154、1718 行）。
  - 当前仓库现有异步 fixture 全部使用 `@pytest_asyncio.fixture`（见 [`backend/tests/test_integration.py`](D:/mywork/CoreMaster/backend/tests/test_integration.py)、[`backend/tests/test_mml_manager.py`](D:/mywork/CoreMaster/backend/tests/test_mml_manager.py)、[`backend/tests/test_dependency_mining.py`](D:/mywork/CoreMaster/backend/tests/test_dependency_mining.py) 等）。
  - 同时 Task 19 的 `setup_env` 片段里 `yield {"db": db, "plugin": plugin}` 使用了未定义的 `plugin` 变量（实施计划第 1728-1733 行）。
- 风险：
  - 这会让实施者在编写新测试时直接沿用一套与当前仓库风格/运行方式不一致的 fixture 基线。
  - `plugin` 未定义则是直接的示例错误，会把最早的测试骨架再次带偏。
- 建议修复：
  - 将新测试示例统一改为 `pytest_asyncio.fixture` 风格。
  - 修正文中 `setup_env` 片段，至少把 plugin 实例化/注册步骤写完整，或删除未定义的 `plugin` 返回值。

## 本轮结论（2026-04-04 16:25）

- 结论：**实施计划 v7 仍未达到可执行基线，继续不放行**
- 说明：
  - v7 已闭环我上一轮指出的 Task 19 测试矩阵同步问题。
  - 但经过本轮全量复审，当前仍至少存在 5 个可确认的剩余阻塞项，涉及基础契约、生命周期语义、测试迁移和生命周期管理，不能进入执行阶段。
