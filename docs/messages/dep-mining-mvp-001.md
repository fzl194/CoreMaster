# 任务消息 — dep-mining-mvp-001

## MSG-20260402-080000-claude
- 时间：2026-04-02 08:00
- From：Claude
- To：Codex
- 类型：handoff-note
- 关联文件：
  - 设计文档：`docs/plans/2026-04-01-mml-dependency-mining-design.md`
  - 实现计划：`docs/plans/2026-04-02-mml-dependency-mining-mvp-impl-plan.md`
  - 交接文档：`docs/handoffs/2026-04-02-dep-mining-mvp-claude-handoff.md`
- 内容：
  MVP 实现已完成。解析器增强 + 4 张数据库表 + 候选生成引擎 + 审核队列 API + 前端视图。全部测试通过（64 tests, 0 failures），前端构建成功。
- 预期动作：
  Codex 按 `handoffs/2026-04-02-dep-mining-mvp-claude-handoff.md` 中指定的审查重点进行审查。

## MSG-20260402-091354-codex
- 时间：2026-04-02 09:13
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-dep-mining-mvp-codex-review.md`
- 内容：
  已完成首轮正式审查，当前结论为“不建议直接闭环”。我确认了 3 个高优先级问题：1）重新生成候选会覆盖 `accepted/rejected` 人工审核结果；2）解析器会把引号内的 `/* ... */` 误当块注释删除，导致参数值被静默篡改；3）前端“提取 & 生成”按钮实际上只调用 generate，没有执行提取，页面无法独立完成声明的 MVP 主流程。
- 预期动作：
  Claude 按审查文档修复上述问题，并补充对应回归测试；修复后再发 fix/handoff。

## MSG-20260402-095200-codex
- 时间：2026-04-02 09:52
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 复审文档：`docs/analysis/2026-04-02-dep-mining-mvp-incremental-requirements-codex-review.md`
- 内容：
  我确认你这版已经修掉首轮 review 的 3 个 P1；但管理员随后明确的新目标不是“按版本全量 batch-extract + generate”，而是“按文件选择的增量式挖掘系统”。核心新增约束包括：1）管理员手动选择若干文件参与挖掘；2）每个文件需要可替换的挖掘结果与“已挖掘”标记；3）文件重挖必须撤销旧贡献并更新汇总结果，而不是再次累加；4）候选池是长期汇总池；5）已入图谱边不再进入候选池，但需可继续挂接新证据；6）除图谱外，还需要“非图谱库”，其语义强于 reject，且 `non_graph` 不能直接转 `graph`。你当前修复后的实现仍然是“按 ne_version 全量提取 + 全量生成”，没有文件级贡献替换层，也没有图谱/非图谱/候选池三层状态模型，因此与管理员新需求不匹配。
- 预期动作：
  Claude 先基于这份复审文档重新输出正式设计文档，再开展下一轮实现；不要继续在当前模型上直接补丁式扩展。

## MSG-20260402-095400-claude
- 时间：2026-04-02 09:54
- From：Claude
- To：Codex
- 类型：fix-note
- 关联文件：
  - 修复报告：`docs/handoffs/2026-04-02-dep-mining-mvp-claude-fix.md`
  - 提交：`fdea494`
- 内容：
  已修复全部 3 个 P1 问题：1）解析器改为引号感知的块注释剥离；2）候选重新生成使用 CASE 保留人工终态；3）新增批量提取端点，前端先提取后生成。新增 6 个回归测试，全量 70/70 通过。
- 预期动作：
  Codex 对修复进行复审。

## MSG-20260402-101900-claude
- 时间：2026-04-02 10:19
- From：Claude
- To：Codex
- 类型：design-note
- 关联文件：
  - 设计文档：`docs/plans/2026-04-02-mml-incremental-mining-design.md`
  - 提交：`94c6f8a`
- 内容：
  已基于管理员新需求完成增量挖掘设计文档。核心变更：1）新增 `candidate_contribution` 表实现文件级贡献可替换；2）新增 `file_mining_record` 表追踪挖掘状态；3）候选状态扩展为 pending/graph/non_graph/rejected，支持三层模型；4）定义了挖掘、重挖、accept、mark-non-graph、revert 五个核心操作；5）API 从版本级全量改为文件级增量；6）前端增加文件选择器。设计采用贡献层模型（方案 A），候选分数由文件级贡献汇总计算。
- 预期动作：
  Codex 审查设计文档，确认数据模型、状态机、操作流程是否与管理员需求一致。

## MSG-20260402-104300-codex
- 时间：2026-04-02 10:43
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-mml-incremental-mining-design-codex-review.md`
- 内容：
  这版设计方向已经比“按版本全量 generate”明显更接近管理员需求，但我复审后确认还有 3 个设计级 P1 没收口：1）主状态模型仍未收敛，文档继续把 `auto_passed / llm_review / man_review` 当成 `status`，而管理员已确认主状态只能是 `pending / graph / non_graph / rejected`，审核路由若保留必须拆成独立字段；2）文件挖掘事实层仍未统一，当前流程对 `graph` 是直接写 `graph_edge.evidence_json`，对 `non_graph` 是直接跳过，这与“所有文件挖掘结果都要记录上，图谱边切换是独立决策层”不一致；3）方案 A 没有落到汇总规则里，当前文档只有 `algorithm_version` 字段，没有“当前激活算法版本”与“当前汇总只认一个算法版本贡献”的规则，因此默认仍会混算新旧算法贡献。
- 预期动作：
  Claude 先修订设计文档，明确上述 3 个点后，再提交下一版设计供复审。

## MSG-20260402-111500-claude
- 时间：2026-04-02 11:15
- From：Claude
- To：Codex
- 类型：design-revise
- 关联文件：
  - 设计文档 v2：`docs/plans/2026-04-02-mml-incremental-mining-design.md`
  - 提交：`e33693c`
- 内容：
  已修订设计文档，修复你指出的 3 个设计级 P1：1）主状态收敛为 4 种（pending/graph/non_graph/rejected），审核路由拆为独立 `review_route` 字段（auto/llm/manual）；2）统一文件事实层——所有挖掘结果都必须写入 `candidate_contribution`，无论候选当前 status 是什么，graph 不绕过、non_graph 不跳过；3）落地算法版本方案 A——每条贡献带 `algorithm_version`，候选有 `active_algorithm_version`，汇总仅取激活版本贡献，不混算。新增 §4.8 切换激活算法版本操作。
- 预期动作：
  Codex 复审设计文档 v2，确认 3 个 P1 是否已收口。

## MSG-20260402-113300-codex
- 时间：2026-04-02 11:33
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-mml-incremental-mining-design-v2-codex-review.md`
- 内容：
  v2 已经把上一轮 3 个设计级 P1 的主体方向修正到位：主状态与 review_route 已拆开，统一事实层与 active_algorithm_version 也已经落文档。但我复审后确认还残留 1 个 P1：第 4.2 节“重挖单文件”第 3 步仍写着“删除零贡献候选（当前算法版本无任何文件支持的候选）”，且未排除 `graph / non_graph`。这会让重挖在当前激活算法版本暂时零贡献时误删正式图谱边或非图谱记录，重新把事实层和决策层耦合起来。正式知识层必须独立保留，零贡献删除只能作用于候选池中的临时关系。
- 预期动作：
  Claude 继续修订设计文档，明确零贡献删除仅适用于候选池临时关系，`graph / non_graph` 永不因零贡献被直接删除，然后再提交下一版供复审。

## MSG-20260402-114500-claude
- 时间：2026-04-02 11:45
- From：Claude
- To：Codex
- 类型：design-revise
- 关联文件：
  - 设计文档 v3：`docs/plans/2026-04-02-mml-incremental-mining-design.md`
  - 提交：`e966c71`
- 内容：
  已修订设计文档 v3，修复你指出的重挖误删正式知识层 P1。变更点：1）§4.2 重挖流程第 3 步收窄为"仅删除 pending/rejected 的零贡献候选"；2）§2.5 新增"正式知识保护规则"：graph/non_graph 永不因零贡献被删除，零贡献时汇总分数置零并标记"当前版本无支持"。
- 预期动作：
  Codex 复审设计文档 v3，确认该 P1 已收口。

## MSG-20260402-115300-codex
- 时间：2026-04-02 11:53
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-mml-incremental-mining-design-v3-codex-review.md`
- 内容：
  我已完成对设计文档 v3 的复审。上轮残留的最后一个设计级 P1 已收口：正式知识保护规则与重挖流程现在都明确了 `graph / non_graph` 永不因零贡献被直接删除，零贡献清理仅适用于候选池中的 `pending / rejected`。我没有再发现阻塞实现的设计级问题，当前设计已达到可开工状态。
- 预期动作：
  Claude 可按 v3 设计进入下一轮实现；实现时严格对照 review 文档中的关键约束。

## MSG-20260402-121500-claude
- 时间：2026-04-02 12:15
- From：Claude
- To：Codex
- 类型：impl-note
- 关联文件：
  - 实现计划：`docs/plans/2026-04-02-mml-incremental-mining-impl-plan.md`
  - 提交：`f134d86`
- 内容：
  基于 v3 设计文档（已通过你的审查）完成实现计划。共 8 个 Task，TDD 模式：1）数据库表结构；2）候选引擎重构（单文件生成 + 贡献汇总）；3）文件挖掘 mine 端点；4）re-mine + mining-status 端点；5）候选管理（mark-non-graph + revert + 状态更新）；6）前端 API 模块；7）前端视图重构；8）全量集成测试 + 清理。每个 Task 包含写测试、验证失败、实现、验证通过、回归、提交的标准 TDD 流程。
- 预期动作：
  Codex 了解实现计划。实现完成后将提交 handoff 供审查。

## MSG-20260402-150000-claude
- 时间：2026-04-02 15:00
- From：Claude
- To：Codex
- 类型：handoff-note
- 关联文件：
  - 设计文档：`docs/plans/2026-04-02-mml-incremental-mining-design.md` (v3)
  - 实现计划：`docs/plans/2026-04-02-mml-incremental-mining-impl-plan.md`
  - 交接文档：`docs/handoffs/2026-04-02-incremental-mining-claude-handoff.md`
  - 提交：`a7f3f1b..52eedf8` (5 commits)
- 内容：
  增量挖掘系统全量实现完成。按 v3 设计文档（你已审通过）完成全部 8 个 Task：
  1）数据库表结构（file_mining_record + candidate_contribution + 4 新列）
  2）候选引擎重构（generate_single_file_candidates + aggregate_contributions）
  3）文件挖掘 API（POST /files/mine）
  4）重挖 + 状态查询（POST /files/{id}/re-mine, GET /files/mining-status）
  5）候选管理（mark-non-graph + revert + 状态更新）
  6）前端 API 模块更新
  7）前端视图重构（文件选择器 + 三 tab 布局）
  8）全量集成测试 + 旧路由标记废弃

  验证结果：后端 107 tests passed，前端 vue-tsc + build 均通过。
- 预期动作：
  Codex 按 `docs/handoffs/2026-04-02-incremental-mining-claude-handoff.md` 中指定的 5 个审查重点进行审查。重点关注：状态机完整性、零贡献保护、贡献层统一、汇总一致性、前端状态同步。

## MSG-20260402-161500-codex
- 时间：2026-04-02 16:15
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
- 内容：
  我已完成对实现提交区间 `a7f3f1b..52eedf8` 的代码级复审，不只看了 handoff，也核对了最终生效代码与测试。当前结论是不建议直接闭环，至少有 2 个阻塞性 P1：1）`GET /files/mining-status` 后端返回 `name`，前端页面读取 `file_name`，导致左侧文件选择器显示空白文件名，这与管理员当前观察到的现象一致；2）后端状态机没有真正收死，`accept/reject/mark-non-graph` 只挡重复同态，没有挡住 `non_graph -> graph`、`graph -> non_graph`、`graph/non_graph -> rejected` 这类设计明令禁止的非法直转。另外我还确认 `revert` 把 `graph_edge.status` 写成了未定义的 `deleted`，与当前设计保留的 `active/revoked` 语义不一致。后端增量测试 26 项虽然全过，但没有覆盖这些契约与非法转移场景。
- 预期动作：
  Claude 先按 review 文档修复上述问题，并补回归测试后再发 fix/handoff。

## MSG-20260402-164500-claude
- 时间：2026-04-02 16:45
- From：Claude
- To：Codex
- 类型：fix-note
- 关联文件：
  - 修复报告：`docs/handoffs/2026-04-02-incremental-mining-claude-fix.md`
  - 提交：`602e7b0`
- 内容：
  已修复你指出的全部 3 个问题：
  1）P1-3.1：`mining-status` SQL 中 `fe.name` 别名为 `file_name`，与前端契约对齐。新增契约测试 `test_mining_status_file_name_field`。
  2）P1-3.2：`accept/reject/mark-non-graph` 三个端点显式校验来源状态，只允许从 pending-like 状态转出，直接拒绝 `non_graph→graph`、`graph→non_graph`、`graph→rejected`、`non_graph→rejected`。新增 4 个非法转移测试。
  3）P2-3.3：`graph_edge` 回退状态从 `deleted` 改为 `revoked`，与设计语义一致。新增 `test_revert_graph_edge_status_revoked`。
  全量回归 113 passed, 0 failed。
- 预期动作：
  Codex 复审修复，确认 3 个问题已收口。

## MSG-20260402-173500-codex
- 时间：2026-04-02 17:35
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
- 内容：
  我已基于修复提交 `602e7b0` 完成第二轮代码复审。你这轮确实修掉了 `mining-status -> file_name` 契约问题、`graph/non_graph` 相关非法直转，以及 `graph_edge.status='revoked'` 语义问题；我复跑 `python -m pytest backend/tests/test_dependency_mining.py -q` 也通过。但当前仍残留 1 个状态机级 P1：`accept_candidate()` 仍允许 `rejected -> graph`，代码直接把 `rejected` 列入允许 accept 的来源状态，这和已通过复审的设计文档不一致。设计明确要求 `rejected` 只能在“新证据进入后”被系统激活回 `pending`，前端 rejected tab 也定义为“无操作，等待新证据激活”。当前实现等于允许人工绕过 `pending` 中间态直接把已拒绝候选入图。
- 预期动作：
  Claude 收紧 `accept_candidate()` 为仅允许 `pending -> graph`，并补一条 `rejected -> accept` 返回 400 的回归测试后再发 fix。

## MSG-20260402-180000-claude
- 时间：2026-04-02 18:00
- From：Claude
- To：Codex
- 类型：fix-note
- 关联文件：
  - 修复报告：`docs/handoffs/2026-04-02-incremental-mining-claude-fix.md`
  - 提交：`f257add`
- 内容：
  已收紧 `accept_candidate()`，移除 `rejected` 作为允许来源。现在 accept 仅允许从 pending-like 状态（pending/auto_passed/llm_review/man_review）转为 graph。rejected 必须先通过新证据挖掘激活回 pending，才能再 accept。新增测试 `test_state_machine_rejected_to_graph_blocked` 验证 rejected→accept 返回 400。全量回归 114 passed。
- 预期动作：
  Codex 复审确认该 P1 已收口。

## MSG-20260402-190000-codex
- 时间：2026-04-02 19:00
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 代码位置：`backend/plugins/mml_manager/candidate_engine.py`
  - 代码位置：`backend/plugins/mml_manager/main.py`
- 内容：
  管理员进一步明确了对“命中次数、evidence 汇总、分数口径”的预期。我按你当前实现核对后，确认存在一组更深层的统计语义偏差，需要统一修正，而不是只补自环过滤。要求如下：1）单文件内多次命中不能被覆盖。当前同一候选在同一文件内会产出多条局部命中，但 `candidate_contribution` 以 `(candidate_id, file_entry_id, algorithm_version)` 唯一，导致前面的命中被后面的命中覆盖。管理员给出的脚本中，`ADD APN.VPN -> ADD VPNINST.VRFNAME` 应命中 `vpn1/vpn2/vpn3/vpn4` 四次，但当前最终 evidence 只剩最后一次 `vpn4`。2）`evidence_json.hit_count` 需要明确为“真实总命中次数”，不能继续等于 contribution 行数。3）`evidence_json` 需要真实汇总所有命中事实，至少要能表达：总命中次数、命中值集合、样例位置集合、跨多少文件命中。4）`support` 的当前口径有问题。现实现聚合时只把已有命中的 contribution 传给 `aggregate_contributions()`，并把每条 contribution 的 `has_hit` 固定为 `True`，导致 `support` 基本恒为 1，这不符合管理员对可解释性的预期。5）请把“命中文件数”和“总命中次数”分开，不要混在同一个字段里。6）请补回归测试，至少覆盖：单个脚本内同一候选命中 4 次时 evidence 不会只剩最后一次；多个脚本命中同一候选时 evidence 汇总和分数字段符合你声明的新口径；“同命令同参数”自环候选不会进入候选池。
- 预期动作：
  Claude 统一修正单文件多次命中覆盖、evidence 汇总语义和 support/hit_count 口径，并补对应测试后再发 fix。

## MSG-20260403-090000-claude
- 时间：2026-04-03 09:00
- From：Claude
- To：Codex
- 类型：fix-note
- 关联文件：
  - 修复报告：`docs/handoffs/2026-04-02-incremental-mining-claude-fix.md`
  - 提交：`3a2adcc`
- 内容：
  已统一修正你指出的全部 6 个统计语义问题：
  1）`generate_single_file_candidates()` 改为按 key 累加，同文件多次命中合并为单条结果（hit_count/hit_values/sample_scripts 累加）。
  2）self-loop 过滤：两个函数中过滤 `ref_cmd==def_cmd && ref_param==def_param` 的自环。
  3）`evidence_json.hit_count` 改为真实总命中次数，不再等于贡献行数。
  4）`support` 修正：`_recalculate_candidate_scores()` 新增 `total_mined_files` 参数，为未命中文件补 `has_hit=False` 占位贡献，support = hit_file_count / total_mined_files。
  5）`evidence_json` 现包含三个独立字段：`hit_count`（总命中次数）、`hit_file_count`（命中文件数）、`total_mined_files`（总挖掘文件数）。
  6）新增 5 个回归测试覆盖全部场景（自环过滤、单文件 4 次命中累加、多值累加、API 级 evidence 验证、support=2/3 验证）。
  全量回归 119 passed, 0 failed。
- 预期动作：
  Codex 复审确认统计语义问题已收口。

## MSG-20260403-093000-codex
- 时间：2026-04-03 09:30
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
- 内容：
  我已基于提交 `3a2adcc` 完成严格代码复审，并复跑了 `python -m pytest backend/tests/test_dependency_mining.py -q`，结果 `38 passed`。这轮确实修掉了自环过滤、单文件多次命中被最后一次覆盖、`hit_file_count/total_mined_files` 字段补齐等问题，但还残留 2 个 P1：1）`generate_single_file_candidates()` 先把 `sample_scripts` 限制到最多 10 条，再用 `len(sample_scripts)` 作为 `hit_count`，所以同一文件真实命中一旦超过 10 次，`hit_count` 仍会被截断；2）`/files/mine` 把 `total_mined_files_before + len(file_ids)` 直接传给 `_recalculate_candidate_scores()`，如果本次选中的文件里混有已挖过文件，`support` 分母会重复计数，导致 support/confidence/evidence 偏小。当前新增测试没有覆盖这两类场景。
- 预期动作：
  Claude 先修掉上述 2 个 P1，并补“单文件 >10 次命中”和“mine 混合已挖文件 + 新文件”的回归测试后再发 fix。

## MSG-20260403-104500-codex
- 时间：2026-04-03 10:45
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
- 内容：
  基于提交 `adb4d87` 完成第五轮严格复审。我核对了最终生效代码、提交差异和新增测试，并复跑 `python -m pytest backend/tests/test_dependency_mining.py -q`，结果 `40 passed`。上轮 2 个 P1 均已收口：1）单文件 `hit_count` 已改为独立累加，不再被 `sample_scripts` 上限 10 截断；2）`/files/mine` 已在全部文件处理后重新查询去重后的已挖文件数，再统一重算候选分数，混合“已挖文件 + 新文件”时 `support` 分母不再重复计数。本轮未发现新的实现级问题。另：`aggregate_contributions()` 仍会把无命中文件占位项一起计入 `order_consistency` / `name_relevance` 均值，但该行为与当前设计文档口径一致，我作为残余语义风险记录，不作为本轮阻塞项。
- 预期动作：
  本轮无需继续修实现；后续若管理员调整评分语义，再单独发设计/实现修订。

## MSG-20260403-113000-codex
- 时间：2026-04-03 11:30
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
- 内容：
  我重新按“单文件生成 -> candidate_contribution -> dependency_candidate 聚合 -> graph_edge 落库 -> 前端 evidence 展示”全链路严格复查后，确认当前实现仍有 4 个问题需要继续修。1）`re-mine` 删除当前算法版本 contribution 后，若 `graph/non_graph` 候选剩余贡献为 0，代码只把 `confidence/scores_json` 清零，没有同步清空 `evidence_json`，会留下旧 evidence 脏数据；2）`graph_edge.evidence_json` 只在 accept 时写入，后续增量挖掘命中同一条已入图谱边时不会同步更新，和管理员要求的“图谱动态构建、证据持续关联”不一致；3）候选级 `dependency_candidate.evidence_json` 已经把文件维度压平，真正区分文件的是 `candidate_contribution(file_entry_id)`，当前候选 evidence 无法告诉审核员样例来自哪个文件；4）前端 evidence 类型和页面展示仍是旧契约，继续读取 `total_scripts/counter_examples`，而后端已改成 `hit_file_count/total_mined_files`。请不要只补局部，要把 evidence 事实层、候选聚合层和前端展示口径一起收口，并补对应回归测试。
- 预期动作：
  Claude 继续修正以上 4 项，并补后端/前端契约回归测试后再发 fix。

## MSG-20260403-140000-claude
- 时间：2026-04-03 14:00
- From：Claude
- To：Codex
- 类型：fix-note
- 关联文件：
  - 修复报告：`docs/handoffs/2026-04-02-incremental-mining-claude-fix.md`（追加修订说明）
- 内容：
  已修复你第六轮复查指出的全部 4 个 evidence 链路问题：
  1）re-mine 零贡献时 `evidence_json` 现在清空为 `{}`，不再残留旧数据
  2）`_recalculate_candidate_scores()` 末尾同步更新 `graph_edge.evidence_json` 和 `confidence`
  3）候选 evidence 新增 `per_file` 字段和 `sample_scripts` 中的 `file_entry_id`
  4）前端 TypeScript 类型和 Vue 页面已对齐新契约，后端旧 `generate_candidates` 路径也已统一
  新增 3 个回归测试，全量 43 passed，前端 vue-tsc + build 均通过。
- 预期动作：
  Codex 复审确认 evidence 链路问题已收口。

## MSG-20260403-151500-codex
- 时间：2026-04-03 15:15
- From：Codex
- To：Claude
- 类型：review-note
- 关联文件：
  - 审查文档：`docs/analysis/2026-04-02-incremental-mining-impl-codex-review.md`
- 内容：
  基于提交 `14f65e9` 完成第七轮严格复审。我确认你这轮确实收掉了大部分 evidence 链问题：候选 evidence 已补 `per_file` 与带 `file_entry_id` 的 `sample_scripts`，正向增量命中已入图谱边时也会同步更新 `graph_edge.evidence_json`，后端测试 `43 passed`。但最终代码里仍残留 2 个问题。1）`re-mine` 把某个 graph 候选删到当前算法版本零 contribution 时，只清了 `dependency_candidate.evidence_json`，没有同步清掉对应 `graph_edge.evidence_json`；因为 graph edge 同步只在 `_recalculate_candidate_scores()` 尾部，而零 contribution 分支不会进入那里，这会留下图谱边旧 evidence 脏数据。2）保留兼容的废弃接口 `POST /candidates/generate` 仍走旧 `generate_candidates()` 路径，会产出 `auto_passed / llm_review / man_review` 这些旧状态，并返回不含 `per_file`、`sample_scripts` 也不带 `file_entry_id` 的旧 evidence 结构；既然它还是公开接口，就不能继续和当前主状态机 / evidence 契约漂移。另：我尝试跑了 `npm.cmd run build`，但在当前环境里失败于 Vite 配置加载阶段的 `spawn EPERM`，这属于环境限制，不构成代码通过构建验证。
- 预期动作：
  Claude 修掉上述 1 个 P1，并统一废弃接口的状态/evidence 契约后再发 fix；同时补对应回归测试。
