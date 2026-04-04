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

---

## 实施计划八次全量复审结果（2026-04-04 17:05）

本轮按“Claude 最新消息（v8）→ 实施计划正文 → 设计文档 → 当前代码/测试基线”重新做了一次全量对照，不再只追上一轮修补点。v8 的确闭环了 v7 中的多项问题，但当前仍有 4 个剩余阻塞项，继续不放行。

### 1. Task 19 的 `setup_env` fixture 示例仍然是直接不可执行的错误骨架

- 严重性：高
- 依据：
  - 当前 [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1727) 的 `setup_env` 仍保留两个连续 `yield`：
    - [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1752)
    - [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1753)
  - Claude 在最新消息中声明“`setup_env` 中删除未定义的 `plugin` 变量，yield 改为 `{\"db\": db, \"registry\": registry}`”，但正文并未同步，第二个 `yield {"db": db, "plugin": plugin}` 还在。
- 风险：
  - 这不是风格问题，而是 pytest fixture 级别的硬错误；实施者照正文抄写会直接得到错误测试基线。
  - 同时也说明 v8 的“已修复”声明与当前有效正文不一致。
- 建议修复：
  - 把 `setup_env` 收口为单个 `yield`。
  - 若需要同时暴露 `plugin`，就一次性返回同一个 dict；不要保留第二个 `yield`。

### 2. `file.content_replaced` 仍未满足设计文档要求的“清理旧贡献 + 触发重算”

- 严重性：高
- 依据：
  - 设计文档明确要求 [`docs/plans/2026-04-03-graph-mining-evolution-design.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-design.md#L392) 的 `file.content_replaced` 事件语义是“删除旧 contribution、触发该文件在 graph_mining 层面的重算”。
  - 但实施计划当前 handler 仍只是：
    - [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1326)
    - `await self._on_file_deleted(payload)`
  - 当前真实代码里的内容替换入口 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L596) 到 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L611) 也只是改写磁盘内容和 `file_size/updated_at`，并不存在自动重挖逻辑。
- 风险：
  - 按当前计划执行后，文件内容替换只会清空旧贡献和 `file_mining_record`，不会为新内容重新建立候选和贡献。
  - 这与设计文档声明的事件语义不一致，也会让“内容替换后 graph_mining 状态如何恢复”处于悬空状态。
- 建议修复：
  - 明确 `file.content_replaced` 的唯一执行路径：
    1. 要么事件处理内显式重新排队/重挖该文件；
    2. 要么修改设计文档和测试预期，承认第一阶段只做清理、不自动重算。
  - 同步补上对应测试，而不是只验证删除链路。

### 3. `ne_version.deleted` 虽补了注释，但正文仍保留分支决策，没有收口到唯一可执行方案

- 严重性：高
- 依据：
  - 实施计划当前仍写明：
    - 若保留第一阶段，则需要同时修改 `mml_manager` 的删除语义；
    - “如果管理员认为第一阶段不应修改删除语义，也可将 `ne_version.deleted` 事件及其订阅/测试降级到第二阶段”
    - 见 [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1279)
  - 当前真实代码 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L267) 到 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L278) 仍然是在有文件时直接返回 400。
  - 现有测试 [`backend/tests/test_mml_manager.py`](D:/mywork/CoreMaster/backend/tests/test_mml_manager.py#L159) 也明确把“带文件版本删除被拒绝”作为基线。
- 风险：
  - v8 看似“补了说明”，但没有替计划选定唯一实现路线。
  - 后续执行者仍无法判断第一阶段到底应修改删除语义，还是应删除/下放 `ne_version.deleted` 相关实现和测试要求。
- 建议修复：
  - 在实施计划中直接定稿，不要保留“或降级到第二阶段”的开放分支。
  - 若保留第一阶段级联删除，就必须同步修改相关现有测试基线；若不保留，就删掉 Task 11/Task 19 对该事件的第一阶段要求。

### 4. 旧挖掘测试迁移链路仍未真正收口，Task 12 继续保留“重写或删除”的双分支表述

- 严重性：中
- 依据：
  - Task 12 现在虽然补了 `test_dependency_mining.py` 的去向说明，但正文仍写“重写为指向 `graph_mining` 插件的新测试，**或** 合并到 `test_graph_mining_integration.py` 后删除”，见 [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1409) 到 [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1413)。
  - 当前真实 [`backend/tests/test_dependency_mining.py`](D:/mywork/CoreMaster/backend/tests/test_dependency_mining.py#L81) 仍整文件绑定 `/api/plugins/mml_manager`，并大量调用旧挖掘路由，如 [`backend/tests/test_dependency_mining.py`](D:/mywork/CoreMaster/backend/tests/test_dependency_mining.py#L718) 的 `/files/mine`。
  - Task 20 仍要求全量 `pytest tests/ -v` 通过，见 [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1779)。
- 风险：
  - 这比 v7 好了一步，但仍不是闭环，因为正式计划依然没有为旧测试文件给出唯一处置路径。
  - 一旦开始删 `mml_manager` 旧挖掘路由，执行者仍要临场决定是保留文件重写，还是合并后删除。
- 建议修复：
  - 直接在 Task 12/Task 19 中固定一种方案，并把责任归属写死。
  - 推荐明确到文件级别，例如“`test_dependency_mining.py` 全量迁入 `test_graph_mining_integration.py` 后删除”，或“保留该文件，仅改前缀和断言基线”。

## 本轮结论（2026-04-04 17:05）

- 结论：**实施计划 v8 仍未达到可执行基线，继续不放行**
- 说明：
  - v8 已闭环 `item_key` 契约统一、worker 生命周期闭合、fixture 装饰器风格修正等前序问题。
  - 但当前正文里仍存在 1 个直接不可执行的测试骨架错误，外加 3 个尚未收口为唯一执行路径的契约/迁移问题。
  - 在这些问题统一收口前，不建议进入编码执行阶段。

---

## 实施计划九次全量复审结果（2026-04-04 17:45）

本轮重新按“v9 消息声明 → 实施计划正文 → 设计文档 → 当前代码/测试基线”做了全量对照。v9 已实质闭环我上一轮指出的 4 个阻塞项，但正文里仍残留 1 个新的测试基线不一致问题，当前继续不放行。

### 1. Task 19 测试矩阵把同一条用例重复登记了两次，`Expected: 10 passed` 与表格本身不一致

- 严重性：中
- 依据：
  - Task 19 当前测试表中“文件内容替换后自动重挖”被连续写了两次：
    - [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1753)
    - [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1754)
  - 但同一任务下的运行预期仍写的是 [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1790) `Expected: 10 passed`。
- 风险：
  - 这会让正式测试矩阵再次出现“表格条目数”和“预期通过数”不一致的问题。
  - 后续执行者无法判断这是 10 条测试里有 1 条重复描述，还是本来还想补第 11 条不同用例但写重了标题。
- 建议修复：
  - 删除重复的一行，或将其中一行改成另一条独立测试要求。
  - 同步保持 Task 19 的表格条目数与 `Expected: 10 passed` 一致。

## 本轮结论（2026-04-04 17:45）

- 结论：**实施计划 v9 仍未达到可执行基线，继续不放行**
- 说明：
  - v9 已闭环 `setup_env` 单 yield、`file.content_replaced` 自动重排队、`ne_version.deleted` 单一路径、旧测试迁移单一路径等前序阻塞项。
  - 当前剩余问题只剩 Task 19 测试矩阵自身的一处重复登记；修完后才适合放行。

---

## 实施计划十次全量复审结果（2026-04-04 18:10）

本轮重新按“v10 消息声明 → 实施计划正文 → 设计文档 → 当前代码/测试基线”做了收尾式全量对照。v10 已修掉我上一轮指出的 Task 19 测试矩阵重复项，同时修订说明区也已去重；本轮未再发现新的阻塞问题。

### 未发现新的阻塞问题

- 核对结果：
  - Task 19 测试矩阵已去掉重复的“文件内容替换后自动重挖”条目，当前 10 条测试要求与 [`docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`](D:/mywork/CoreMaster/docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md#L1789) 的 `Expected: 10 passed` 一致。
  - v9 已闭环的关键问题在 v10 中保持成立：`setup_env` 单 yield、`file.content_replaced` 自动重排队、`ne_version.deleted` 第一阶段单一路径、`test_dependency_mining.py` 迁移后删除等均未回退。
  - 修订说明区的版本记录目前也已收口到单条 v8、单条 v10，没有再出现重复条目。
- 验证边界：
  - 本轮仍是基于计划正文、设计文档、当前代码和现有测试基线的静态一致性审查。
  - 尚未进入实际编码实现，因此这里的“放行”只表示“实施计划已达到可执行基线”，不代表实现代码已被验证通过。

## 本轮结论（2026-04-04 18:10）

- 结论：**实施计划 v10 已达到可执行基线，放行**
- 说明：
  - 截至当前正文版本，前序所有阻塞项均已闭环，本轮未发现新的剩余问题。
  - 可以进入后续执行阶段；下一轮重点应转向真实实现代码、迁移落地和测试执行结果，而不是继续修改计划文档。

---

## 实现代码审查结果（2026-04-04 22:20）

本轮按“Claude 16 个实现提交链 → 最终生效代码 → 用户现场症状 → 原始需求”做实现审查。重点不再是计划文本，而是当前代码是否满足以下原始要求：

1. 文件管理插件只负责文件管理，不自动挖掘；文件更新后应在图谱挖掘中标记“已变动/建议重挖”。
2. 图谱挖掘插件第一屏应按网元展示文件，并支持批量选择文件后手动发起挖掘。
3. 文件挖掘队列应是独立 Tab，动态展示运行中/已完成文件状态；与“选择待挖掘文件”的第一页分离。

### 1. 旧库迁移链路缺失，现有数据库会在候选管理页直接报错 `no such column: llm_assessment_json`

- 严重性：高
- 对应症状：
  - 用户已复现：前端点击“候选管理”报 `network error`，后端报 `sqlite3.OperationalError: no such column: llm_assessment_json`。
- 依据：
  - [`backend/plugins/graph_mining/main.py`](D:/mywork/CoreMaster/backend/plugins/graph_mining/main.py#L49) 只用 `CREATE TABLE IF NOT EXISTS` 定义了新表结构，其中新增了 `llm_assessment_json`、`last_job_id`、`last_error`。
  - 但当前代码没有任何针对旧表的 `ALTER TABLE` 迁移；旧结构仍来自 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L84)，它只补了 `review_route`、`non_graph_reason`、`non_graph_reviewer`、`active_algorithm_version`，没有补 `llm_assessment_json`、`last_job_id`、`last_error`。
  - 候选列表接口又在 [`backend/plugins/graph_mining/main.py`](D:/mywork/CoreMaster/backend/plugins/graph_mining/main.py#L261) 直接查询 `llm_assessment_json`。
- 影响：
  - 这会让“已有 MVP 数据库升级到新实现”这一主路径直接失败；候选管理页无法打开。
  - Claude 的测试都基于新建库，没覆盖真实升级场景，因此 113 个测试通过不能证明线上库可用。
- 建议修复：
  - 在插件注册或正式迁移脚本中补齐旧表增量迁移，至少包括 `dependency_candidate.llm_assessment_json` 与 `file_mining_record.last_job_id/last_error`。
  - 增加“从旧 MVP 库启动新版本”的升级测试。

### 2. 文件更新后被直接自动重挖，违背“文件管理不自动挖掘，只提示建议重挖”的原始需求

- 严重性：高
- 对应症状：
  - 用户反馈“我都没挖掘，结果显示文件已经挖掘了”“文件一上传/更新后数据库里已经有边了”。
- 依据：
  - 文件管理插件在 [`backend/plugins/mml_manager/main.py`](D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L625) 的内容更新接口里，写完文件后立即发出 `file.content_replaced` 事件。
  - 图谱挖掘插件在 [`backend/plugins/graph_mining/main.py`](D:/mywork/CoreMaster/backend/plugins/graph_mining/main.py#L562) 处理该事件时，会先清旧贡献，再直接 `create_job("mining", ...)` 自动入队。
  - 当前文件状态模型 [`backend/plugins/graph_mining/main.py`](D:/mywork/CoreMaster/backend/plugins/graph_mining/main.py#L188) 只有 `unmined/queued/running/completed/failed`，并没有“文件已变动/建议重新挖掘”的展示语义。
- 影响：
  - 文件管理插件已经越权承担图谱挖掘触发职责，和“文件管理只做文件管理”的要求相反。
  - 用户无法先看到“该文件已变动，建议重挖”，而是系统擅自创建挖掘任务并可能产出新边。
- 建议修复：
  - 去掉 `file.content_replaced -> 自动 create_job` 这条链路。
  - 改为记录文件“已变动/待重挖”状态，并只在图谱挖掘页提醒用户手动选择后批量重挖。

### 3. 队列需求没有真正实现：当前没有独立队列 Tab，也没有可用的 jobs API 支撑动态状态页

- 严重性：高
- 对应需求：
  - 用户明确要求“文件挖掘应该有一个队列，这是单独的一个 tab 页，这个页需要展示正在运行或者已经完成挖掘的文件状态，会动态更新”。
- 依据：
  - 当前前端只有 [`frontend/src/views/plugins/GraphMining.vue`](D:/mywork/CoreMaster/frontend/src/views/plugins/GraphMining.vue#L15) 的 3 个 Tab：`文件管理 / 候选管理 / 图谱边`，没有独立“挖掘队列”页。
  - 前端虽然声明了 `fetchJob()`，但它请求的是 [`frontend/src/api/graph-mining.ts`](D:/mywork/CoreMaster/frontend/src/api/graph-mining.ts#L100) `/plugins/graph_mining/jobs/{id}`。
  - 后端 [`backend/plugins/graph_mining/main.py`](D:/mywork/CoreMaster/backend/plugins/graph_mining/main.py) 并没有实现任何 `jobs` 路由，因此轮询在第一次请求就会失败。
- 影响：
  - 当前实现只能“尝试创建任务”，却不能展示真实队列，更不能展示多个文件/多个任务的动态状态。
  - 这和“前端不卡住，但能看到独立队列状态页”的目标不一致。
- 建议修复：
  - 补齐独立队列 Tab。
  - 补齐 `jobs` 列表/详情 API，以及按文件粒度返回 `job_item` 动态状态的接口契约。
  - 将“文件选择页”和“队列状态页”彻底拆开，而不是只在第一页顶部挂一个当前任务标签。

### 4. 图谱挖掘第一页连“手动批量选择文件后挖掘”都没有真正打通

- 严重性：高
- 对应需求：
  - 用户要求图谱挖掘第一页按网元展示文件，并支持批量选择对应文件进行挖掘。
- 依据：
  - 前端按钮状态依赖 [`frontend/src/views/plugins/GraphMining.vue`](D:/mywork/CoreMaster/frontend/src/views/plugins/GraphMining.vue#L19) 的 `selectedFiles.length`。
  - 但当前表格只声明了选择列 [`frontend/src/views/plugins/GraphMining.vue`](D:/mywork/CoreMaster/frontend/src/views/plugins/GraphMining.vue#L27)，没有 `checked-row-keys` / `on-update:checked-row-keys` 之类的绑定把勾选结果写回 [`frontend/src/views/plugins/GraphMining.vue`](D:/mywork/CoreMaster/frontend/src/views/plugins/GraphMining.vue#L147) 的 `selectedFiles`。
  - `handleStartMining()` 又只读取这个从未更新的状态 [`frontend/src/views/plugins/GraphMining.vue`](D:/mywork/CoreMaster/frontend/src/views/plugins/GraphMining.vue#L320)。
- 影响：
  - 用户即使在表格里勾选文件，前端也拿不到所选文件 ID，批量启动挖掘的主流程实际上没有闭合。
  - 这与“用户手动批量选择文件进行挖掘”的核心需求直接冲突。
- 建议修复：
  - 把表格勾选结果显式绑定到 `selectedFiles`。
  - 增加至少一个前端测试或端到端冒烟，验证“勾选两文件 -> 点击开始挖掘 -> 请求体包含两个 file_ids”。

## 测试缺口（实现阶段）

- 当前后端集成测试基于全新测试库，未覆盖旧库升级，因此没发现 `llm_assessment_json` 缺列问题。
- 当前验证没有任何前端交互级测试，没覆盖：
  - 文件勾选是否真的写回 `selectedFiles`
  - 队列页是否存在
  - `/plugins/graph_mining/jobs/{id}` 是否真实可用
- 现有实现还把“文件更新后自动重挖”写成了集成测试期望，说明测试基线本身已偏离原始需求。

## 回归风险（实现阶段）

- 只要用户使用旧数据库，候选管理页就会稳定报错。
- 任何文件内容更新入口都会把系统推向“自动挖掘”，继续制造与业务预期不一致的边数据。
- 即使后端 job 框架存在，前端因为缺少独立队列 API/页面，仍无法形成可观测的异步作业体验。

## 建议修复项（实现阶段）

1. 先补数据库迁移，确保旧库可升级后再继续联调候选管理。
2. 回退 `file.content_replaced` 的自动挖掘行为，改成“标记文件已变动，提示用户手动重挖”。
3. 重做图谱挖掘前端结构：
   - Tab 1：按网元看文件并批量选择挖掘
   - Tab 2：挖掘队列/文件状态动态展示
   - 其他 Tab：候选管理、图谱边
4. 补齐 jobs 队列 API 与前端绑定，覆盖 job 与 job_item 两层状态。
5. 为“批量选择启动挖掘”和“旧库升级后候选页可打开”补最小回归测试。

## 无法确认的残余风险

- 用户反馈“上传后立即出现已挖掘/有边”，当前静态代码能明确确认“文件内容更新一定会自动重挖”，但是否还有上传链路上的额外隐式调用，还需要联调现场再追一次上传后的前端请求序列。
- `MiningWorker` 的并发安全和大文件性能本轮未做压力级验证。

## 管理员介入影响

- 先前管理员放行的是“实施计划 v10 可执行”，不是“当前实现已满足原始需求”。
- 本轮问题属于实现阶段的真实偏差，尤其是需求回退和旧库迁移缺失，不能以“计划已放行”覆盖。

## 本轮结论（2026-04-04 22:20）

- 结论：**实现代码当前不通过，需 Claude 修复后再复审**
- 关键原因：
  - 现有代码与用户刚刚再次明确的 3 条原始需求存在直接冲突。
  - 用户现场复现的 `llm_assessment_json` 缺列报错已能从代码静态确认根因。
