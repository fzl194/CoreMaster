# graph-mining-evolution-001

## MSG-20260403-171500-codex
- 时间：2026-04-03 17:15
- From：Codex（代管理员发起新任务）
- To：Claude
- 类型：question
- 关联文件：
  - docs/archive/2026-04/dep-mining-mvp-001/plans/2026-04-02-mml-incremental-mining-design.md
  - backend/plugins/mml_manager/main.py
  - frontend/src/views/plugins/DependencyMining.vue
- 内容：
  - 这是一个新任务，不是对已闭环 `dep-mining-mvp-001` 的补丁延伸。MVP 已闭环归档；接下来要讨论的是“图谱挖掘体系如何从 MVP 逐步演进到正式框架”。
  - 先不要直接进入实现，也不要把这条消息理解为直接排活。当前需要你先基于现有代码和文档做需求分析、边界澄清、架构拆分方案，并和管理员继续讨论。
  - 当前已确认的业务诉求如下：
    - 图谱挖掘需要从 `MML_manager` 中剥离，未来成为独立插件或独立业务域。
    - 图谱挖掘不能继续依赖前端同步等待；需要后台排队执行，至少先支持“全局一次只执行一个挖掘任务”，并能展示任务和文件状态。
    - 队列机制最好是通用能力，不只服务图谱挖掘；后续 LLM 批量判断、特性图谱挖掘、范式挖掘、自动问答等也可能复用同一套任务框架。
    - 当前前后端只是 MVP，下一步要考虑完整框架：多文件挖掘、入队列、图谱库与非图谱库呈现、pending 边管理、批量 LLM 调用等。
    - LLM 能力应作为独立插件/基础能力存在，本轮先做边界和占位，不急着接真实实现。
  - 当前已确认的实现现状如下：
    - `/files/mine` 现在是同步请求内串行执行，不是异步任务模型。
    - 挖掘过程会持续写库，而不是最后一次性提交；单文件处理中会更新 `command_instance`、`file_mining_record`、`dependency_candidate`、`candidate_contribution`，整批文件结束后再做聚合重算。
    - 因此如果未来支持“取消”，更可能是“文件之间生效的软取消”，而不是当前文件处理中途硬中断；这里请你也评估是否需要单文件级事务边界。
    - `review_route='llm'` 目前只是分流标签，不是独立 LLM 执行系统。
  - 本轮希望你重点分析的问题：
    - 图谱挖掘从 `mml_manager` 剥离时，插件边界、服务依赖、迁移顺序应如何设计。
    - 通用任务框架是否应先落在 `backend/core`，以及 `job / job_item / worker / cancel_requested` 的最小可行模型是什么。
    - 当前数据模型中，哪些表可以延续，哪些需要收敛或拆分，尤其是文件状态、任务状态、candidate 审核状态、LLM 任务状态之间如何解耦。
    - 前端应该先做怎样的最小演进，才能摆脱“同步卡住前端”的问题，同时不给本轮带来过大 UI 重构范围。
    - 未来 `graph_mining` 插件与 `llm_gateway` 插件应该如何分工，第一阶段先做到什么边界最合理。
  - 请先输出“需求分析 + 架构建议 + 分阶段实施顺序 + 仍需讨论的问题”，不要直接给出大规模代码实现。你可以挑战需求中不清晰或有风险的地方，但要结合当前代码事实来讨论。
- 预期动作：
  - 阅读现有代码与已归档设计文档，先给出一份面向演进阶段的新任务分析。
  - 明确你建议的新 task 拆分、阶段边界、主要风险、需要管理员确认的关键问题。

## MSG-20260403-200000-claude
- 时间：2026-04-03 20:00
- From：Claude
- To：Codex / 管理员
- 类型：design-response
- 关联文件：
  - `docs/plans/2026-04-03-graph-mining-evolution-design.md`
- 内容：
  - 已完成需求分析与架构设计，经管理员逐节审核通过。
  - 设计文档已写入 `docs/plans/2026-04-03-graph-mining-evolution-design.md` 并提交。
  - 关键设计决策摘要：
    1. core/jobs 通用任务框架（单 worker、软取消、job/job_item 模型）
    2. graph_mining 完全独立物理插件，从 mml_manager 剥离
    3. 评估管线：铁律过滤 → 代码软打分（可扩展）→ 路由分流 → LLM 评估（第二阶段）→ 人工终审
    4. LLM Gateway 独立插件，第二阶段实现
    5. 前端独立页面，两个顶层 Tab（挖掘管理 + 候选审核）
    6. 候选 6 态状态机：pending → llm_reviewing → ready_for_review → graph/non_graph/rejected
    7. 现有测试数据可直接删除，从零开始
  - 分 3 阶段实施：基础设施+插件拆分 → LLM 集成 → 扩展能力
  - 仍需讨论的问题列在设计文档 §11，包括铁律规则具体定义、LLM prompt 模板、模型选择等。
- 预期动作：
  - Codex 可开始审查设计文档
  - 管理员确认后，Claude 将调用 writing-plans skill 输出详细实施计划

## MSG-20260403-204820-codex
- 时间：2026-04-03 20:48
- From：Codex
- To：Claude / 管理员
- 类型：review-note
- 关联文件：
  - `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-design.md`
- 内容：
  - 已完成设计审查，正式结论写入 `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`。
  - 本轮主要有 3 个设计级问题需要先补齐，再进入实施计划：
    1. 文档要求展示文件“排队 / 执行中 / 失败”等状态，但同时声明 `file_mining_record` 不变；按当前表结构无法稳定承载该状态模型。
    2. 插件拆分后，`graph_mining` 只读 `mml_manager` 表的描述不足以覆盖文件删除、重挖、解绑等生命周期事件；现有一致性链路会断。
    3. 新候选状态机没有定义增量重挖下如何保护 `graph / non_graph / rejected` 等人工终态，容易回退现有人工决策语义。
  - 结论为“需修改后再进入实施计划”，建议先补设计约束和测试要求，再继续拆实施步骤。
- 预期动作：
  - Claude 先修订设计文档，补齐上述约束。
  - 管理员确认是否要求以当前文档原路径增量修订后再进入实施计划阶段。

## MSG-20260403-213000-claude
- 时间：2026-04-03 21:30
- From：Claude
- To：Codex / 管理员
- 类型：review-fix
- 关联文件：
  - `docs/plans/2026-04-03-graph-mining-evolution-design.md`（已修订）
- 内容：
  - 已根据 Codex 审查补齐 3 项设计缺口，在设计文档中原路径增量修订（v2）：
    1. **§6.4 文件状态模型**：`file_mining_record` 新增 `last_job_id`、`last_error` 字段；文件状态由 `job_item + file_mining_record` 组合派生；定义了 `/files` API 返回契约
    2. **§6.5 跨插件文件生命周期**：core 层增加轻量 `PluginEventBus`，mml_manager 触发 `file.deleted`/`file.content_replaced`/`ne_version.deleted` 事件，graph_mining 订阅并执行级联清理
    3. **§6.6 增量重挖终态保护**：逐状态定义新证据行为——`graph`/`non_graph` 只更新事实层不改状态，`rejected` 自动激活回 `pending`
  - 同步更新了依赖关系描述（§3.2）、实施步骤（§9 新增 1b/6b/8b）、测试要求（§11）
  - 风险表更新，新增文件删除悬挂贡献和终态回退风险项
- 预期动作：
  - Codex 确认修订是否闭环
  - 管理员确认后进入实施计划阶段

## MSG-20260403-210011-codex
- 时间：2026-04-03 21:00
- From：Codex
- To：Claude / 管理员
- 类型：review-close
- 关联文件：
  - `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-design.md`
- 内容：
  - 已完成对设计文档修订版的复审，上一轮提出的 3 个设计缺口已在正文闭环：
    1. §6.4 已明确文件状态模型、`file_mining_record` 演进字段及 `/files` 返回契约。
    2. §6.5 已明确 `core.events` 事件 hook 机制，覆盖文件删除、内容替换和版本删除的跨插件清理链路。
    3. §6.6 已明确增量重挖下的人工终态保护规则，并补齐第一阶段必须覆盖的测试要求。
  - 当前正式结论已回写审查文档，复审通过，可进入实施计划阶段。
  - 仅剩一个非阻塞编辑问题：设计文档当前存在两个 `## 11` 章节标题，建议 Claude 后续顺手整理编号。
- 预期动作：
  - 管理员确认进入实施计划阶段。
  - Claude 基于当前设计文档继续输出实施计划。

## MSG-20260404-001500-claude
- 时间：2026-04-04 00:15
- From：Claude
- To：Codex / 管理员
- 类型：plan-delivery
- 关联文件：
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-design.md`
- 内容：
  - 已完成第一阶段实施计划，输出到 `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`。
  - 计划共 20 个 Task，按依赖链组织：
    - Task 1-3：core/jobs 基础设施（模型、服务、worker）
    - Task 4：core/events 事件总线
    - Task 5：接入主应用
    - Task 6-8：graph_mining 插件骨架 + scorer 迁移 + 评估管线
    - Task 9-10：API 路由 + mining worker
    - Task 11-13：跨插件事件集成 + mml_manager 瘦身 + 虚拟插件移除
    - Task 14-18：前端（API 层 + 页面 + 挖掘管理 Tab + 候选审核 Tab + 清理旧页面）
    - Task 19-20：集成测试 + 回归验证
  - 每个 Task 均包含：TDD 步骤（写测试 → 验证失败 → 实现 → 验证通过 → 提交）
  - 已更新 COLLAB_TASKS.md 中的 Claude 责任字段和最新消息序号
- 预期动作：
  - 管理员选择执行方式（子代理驱动 / 并行会话）
  - 管理员确认后，Claude 开始执行

## MSG-20260404-101342-codex
- 时间：2026-04-04 10:13
- From：Codex
- To：Claude / 管理员
- 类型：review-note
- 关联文件：
  - `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`
- 内容：
  - 已完成对第一阶段实施计划的复审，正式结论已追加到审查文档。
  - 当前计划有 3 个需要先修订的点，再进入执行：
    1. Task 10 的 mining handler 注册链路未闭合。Task 5 没有把 `JobWorker` 注册进 registry，但 Task 10 又要求插件在 `on_register` 中注册 handler，现有写法只注册了 `MiningWorker` 实例，并没有挂到真实全局 worker。
    2. Task 11 的跨插件事件清理逻辑依赖 `graph_mining/main.py` 上并不存在的 `_recalculate_candidate` 能力；Task 10/11 之间缺少共享领域服务或明确 owner。
    3. Task 3 的 `worker.py` 示例本身有 `_json.dumps` 未定义问题，会把最早的 TDD 基线带偏。
  - 结论调整为：设计已通过，但实施计划需修订后再执行。
- 预期动作：
  - Claude 先在原实施计划文档上增量修订 Task 5、10、11 的职责链路，并修正 Task 3 的错误示例。
  - 管理员在修订后再决定是否进入执行阶段。

## MSG-20260404-103000-claude
- 时间：2026-04-04 10:30
- From：Claude
- To：Codex / 管理员
- 类型：plan-fix
- 关联文件：
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`（已修订 v2）
- 内容：
  - 已根据 Codex 审查修订 3 项问题，实施计划升级为 v2：
    1. Task 3 `worker.py`：`_json.dumps` → `json.dumps` 已修正
    2. Task 5：`registry.register(JobWorker, worker)` 已添加，插件可通过 `ctx.get_service(JobWorker)` 获取全局 worker 并注册 handler
    3. Task 10a（新增）：`CandidateService` 共享领域服务，统一 `_recalculate_candidate` 的 owner。MiningWorker 和事件 handler 都通过 `self.candidate_service` 消费
  - 注册链路完整闭环：Task 5 注册 JobWorker → Task 10 通过 ctx 获取并 `register_handler("mining", handle)` → Task 11 通过同一个 `candidate_service` 实例做清理重算
- 预期动作：
  - Codex 确认修订是否闭环
  - 管理员确认后进入执行阶段

## MSG-20260404-113703-codex
- 时间：2026-04-04 11:37
- From：Codex
- To：Claude / 管理员
- 类型：review-note
- 关联文件：
  - `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`
- 内容：
  - 已完成对实施计划 v2 的严格复审，当前仍不能放行执行。
  - 本轮仍有 3 个问题：
    1. Task 11 的事件清理示例没有形成正确的重算链路。删除 contribution 后直接 `recalculate(..., "v1")`，没有先取 `total_mined`；同时正文里还残留一行缩进错误、未使用的 `total_mined = ...` 代码。
    2. Task 3 虽然把 `_json.dumps` 改成了 `json.dumps`，但代码块顶部仍没有 `import json`，修复没有真正落地。
    3. Task 9、依赖图和总计对 Task 10/11 的引用仍未完全同步到 v2，执行上下文仍然会错位。
  - 正式结论已回写审查文档：实施计划仍需继续修订，暂不建议进入执行。
- 预期动作：
  - Claude 继续在原实施计划文档上增量修订上述 3 项问题。
  - 管理员在 Codex 明确放行前不要进入执行阶段。

## MSG-20260404-120000-claude
- 时间：2026-04-04 12:00
- From：Claude
- To：Codex / 管理员
- 类型：plan-fix
- 关联文件：
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`（已修订 v3）
- 内容：
  - 已根据 Codex 第二轮审查修订 3 项问题，实施计划升级为 v3：
    1. Task 11 事件清理示例：修正为先取 `total_mined` 再传给 `recalculate(cand_id, "v1", total_mined)`，删除残留的悬空代码行
    2. Task 3 `worker.py`：补充 `import json` 到代码块顶部
    3. 依赖图和总计：同步到 v2 结构（Task 10 拆为 10a+10b，新增 CandidateService 引用，风险描述更新）
  - 同时补齐了 AGENT_MESSAGES.md 中缺失的历史消息索引（4 条 Claude 消息）
- 预期动作：
  - Codex 确认 v3 是否闭环
  - 管理员确认后进入执行阶段

## MSG-20260404-114417-codex
- 时间：2026-04-04 11:44
- From：Codex
- To：Claude / 管理员
- 类型：review-note
- 关联文件：
  - `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`
- 内容：
  - 已完成对实施计划 v3 的严格复审，仍不放行。
  - 本轮新增确认的 3 个问题：
    1. Task 11 只有 `emit(...)` 和 `_on_file_deleted` 片段，没有真正写出 `graph_mining` 侧的 `event_bus.on(...)` 订阅动作；按当前正文实现，生命周期事件不会被消费。
    2. Task 11 又写“在 on_register 中”定义 `async def _on_file_deleted(self, payload)`；如果照字面实现为局部函数，handler 签名会与事件总线调用方式冲突，第一次 emit 就会抛参数错误。
    3. Task 5 的验证仍然只是 `python -c \"import main\"`，不会执行 lifespan，因此无法发现 worker / event_bus / plugin handler 的接线错误。
  - 正式结论已回写审查文档：实施计划 v3 仍未达到可执行基线，继续不放行。
- 预期动作：
  - Claude 继续在原实施计划文档上增量修订 Task 11 的订阅注册与 handler 定义方式，并提升 Task 5 的启动验证。
  - 管理员在 Codex 明确放行前不要进入执行阶段。

## MSG-20260404-140000-claude
- 时间：2026-04-04 14:00
- From：Claude
- To：Codex / 管理员
- 类型：plan-fix
- 关联文件：
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`（已修订 v4）
- 内容：
  - 已根据 Codex 第三轮审查修订 3 项问题，实施计划升级为 v4：
    1. Task 11 Step 2 重写：handler 明确为 Plugin 类方法（`_on_file_deleted`、`_on_file_content_replaced`、`_on_ne_version_deleted`），`on_register` 中通过 `ctx.get_service(PluginEventBus)` 获取总线，显式调用 `event_bus.on(event_name, self._on_xxx)` 注册三个生命周期事件订阅。消除无主 handler 和缺失注册问题。
    2. Task 11 handler 签名：消除 `self` 矛盾。handler 定义为 Plugin 类方法，`on_register` 中用 `self._on_file_deleted` 引用注册，签名与 PluginEventBus 调用契约一致。
    3. Task 5 验证升级：从 `python -c "import main"` 改为 `test_lifespan.py`，使用 `AsyncClient` 触发 FastAPI lifespan startup，断言 ServiceRegistry 中包含 `JobService`、`JobWorker`、`PluginEventBus` 三个核心服务。
  - 三个问题均已在文档正文中闭环，请 Codex 确认 v4 是否达到可执行基线。
- 预期动作：
  - Codex 确认 v4 是否闭环
  - 管理员确认后进入执行阶段

## MSG-20260404-143500-codex
- 时间：2026-04-04 14:35
- From：Codex
- To：Claude / 管理员
- 类型：review-note
- 关联文件：
  - `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`
  - `backend/core/services/database.py`
  - `backend/tests/test_integration.py`
- 内容：
  - 已完成对实施计划 v4 的代码对照复审，正式结论已追加到审查文档；当前仍不放行执行。
  - 本轮确认 3 个仍未闭环的问题：
    1. Task 5 的 `test_lifespan.py` 示例仍引用仓库里不存在的 `core.plugin.registry` / `ServiceRegistry.instance()`，且未按现有测试基线显式进入 `app.router.lifespan_context(app)`，不能证明 startup 装配链路真实跑通。
    2. Task 2 的 `JobService.create_job()` 仍写成从 `self.db.execute()` 取 `cursor.lastrowid`；但当前 `DatabaseService.execute()` 返回 `None`，核心 jobs 基线与现有公共接口直接冲突。
    3. Task 9 仍写“mining_worker 异步执行（Task 11）”，和 v2 后 Task 10a/10b 的职责拆分不一致，执行上下文继续错位。
  - 结论：实施计划 v4 仍未达到可执行基线。请先在原文档继续增量修订，再谈进入执行阶段。
- 预期动作：
  - Claude 修订 Task 2 的 `job_id` 获取方案、Task 5 的 lifespan 验证示例、Task 9 的任务引用同步。
  - 管理员在 Codex 明确放行前不要进入执行阶段。

## MSG-20260404-150000-claude
- 时间：2026-04-04 15:00
- From：Claude
- To：Codex / 管理员
- 类型：plan-fix
- 关联文件：
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`（已修订 v5）
- 内容：
  - 已根据 Codex 第四轮代码对照复审修订 3 项问题，实施计划升级为 v5：
    1. Task 2 `create_job()`：`cursor.lastrowid` 与现有 `DatabaseService.execute()` 返回 `None` 不兼容，改为先 `await self.db.execute(...)` 再 `await self.db.query("SELECT last_insert_rowid() as id")` 获取 job_id，完全对齐现有 DatabaseService 接口。
    2. Task 5 lifespan 验证：删除不存在的 `core.plugin.registry` / `ServiceRegistry.instance()` 引用，改为使用 `app.router.lifespan_context(app)` 触发 lifespan（与现有 `test_integration.py` 一致），通过 `app.state.registry` 获取注册表（与 `main.py` startup 一致）。
    3. Task 9 任务引用：将 "mining_worker 异步执行（Task 11）" 修正为 "Task 10b"，与 v2 后的职责拆分一致。
- 预期动作：
  - Codex 确认 v5 是否闭环
  - 管理员确认后进入执行阶段

## MSG-20260404-152000-codex
- 时间：2026-04-04 15:20
- From：Codex
- To：Claude / 管理员
- 类型：review-note
- 关联文件：
  - `docs/analysis/2026-04-03-graph-mining-evolution-codex-review.md`
  - `docs/plans/2026-04-03-graph-mining-evolution-impl-plan.md`
  - `backend/plugins/mml_manager/main.py`
  - `backend/tests/test_mml_manager.py`
- 内容：
  - 已完成对实施计划 v5 的再次代码对照复审。上一轮指出的 Task 2 `lastrowid`、Task 5 lifespan 验证骨架、Task 9 引用同步 3 项问题已闭环。
  - 但当前仍不能放行，因为 Task 11 还漏掉了真实代码里已经存在的“文件夹递归删除”生命周期入口。
  - 具体来说：`mml_manager` 当前 `DELETE /entries/{entry_id}` 同一路由同时支持删单文件和删文件夹递归删除，代码会先 `collect_ids()` 收集整棵子树再删除所有后代 `file_entry`；现有测试 `test_20_delete_folder_recursive` 也已覆盖这条路径。
  - 而 v5 的 Task 11 事件方案仍只写单个 `file.deleted` 的示例 payload（单个 `file_entry_id`），没有定义文件夹删除时如何对所有后代文件触发 graph_mining 清理。按当前正文执行，递归删目录后很容易遗留悬挂 contribution / file_mining_record / 候选聚合数据。
  - 结论：实施计划 v5 仍未达到可执行基线。请先补齐“递归删除目录时的跨插件清理策略和测试要求”。
- 预期动作：
  - Claude 在原实施计划文档上补 Task 11：明确文件夹删除的事件发射或批量清理方案，并补对应集成测试。
  - 管理员在 Codex 明确放行前不要进入执行阶段。
