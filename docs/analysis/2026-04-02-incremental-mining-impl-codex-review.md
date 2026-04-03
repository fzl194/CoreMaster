# 增量挖掘实现代码审查

- 状态：已审查
- 审查日期：2026-04-02
- 审查对象：`a7f3f1b..52eedf8`
- 关联交接：`docs/handoffs/2026-04-02-incremental-mining-claude-handoff.md`

## 1. 审查背景

本轮审查针对 Claude 基于增量挖掘设计 v3 的正式实现交接。管理员已明确要求本轮审查不能只看文档，需要深入核对最近多次实现提交的最终落地代码，并优先检查前端“选择网元版本后看不到文件名”的实际症状。

## 2. 审查范围

- 提交区间：`a7f3f1b..52eedf8`
- 后端：
  - `backend/plugins/mml_manager/main.py`
  - `backend/plugins/mml_manager/candidate_engine.py`
  - `backend/tests/test_dependency_mining.py`
- 前端：
  - `frontend/src/api/dependency-mining.ts`
  - `frontend/src/views/plugins/DependencyMining.vue`

## 3. 发现的问题

### 3.1 P1：`/files/mining-status` 返回字段与前端契约不一致，文件列表会显示空白文件名

- 位置：
  - `backend/plugins/mml_manager/main.py:1404`
  - `frontend/src/api/dependency-mining.ts:51`
  - `frontend/src/views/plugins/DependencyMining.vue:55`
- 问题：
  - 前端 `FileMiningStatus` 类型和页面渲染都读取 `file_name`。
  - 但后端 `GET /files/mining-status` 实际查询返回的是 `fe.name`，没有别名成 `file_name`。
  - 因此接口层字段名不匹配，页面左侧复选框标签会拿到 `undefined`，这与管理员当前看到的“选中网元版本后看不到文件名”现象一致。
- 影响：
  - 当前主流程最基础的文件选择器不可用，管理员无法可靠区分要挖掘的是哪些文件。
  - 这不是展示细节，而是直接阻断增量式“按文件选择挖掘”的核心使用路径。
- 建议：
  - 后端将 `fe.name` 明确别名为 `file_name`，或前端统一改回读取 `name`，两端必须收敛为同一契约。
  - 增加 API/前端契约测试，至少覆盖 `mining-status` 返回文件名字段。

### 3.2 P1：后端没有真正收死状态机，非法的 `graph -> non_graph`、`non_graph -> graph`、`graph -> rejected` 仍可通过 API 直接发生

- 位置：
  - `backend/plugins/mml_manager/main.py:919`
  - `backend/plugins/mml_manager/main.py:997`
  - `backend/plugins/mml_manager/main.py:1032`
  - 设计约束：`docs/plans/2026-04-02-mml-incremental-mining-design.md:488`
- 问题：
  - `accept_candidate()` 仅禁止当前已是 `graph` 的记录再次 accept，没有阻止 `non_graph -> graph`。
  - `mark_non_graph()` 仅禁止当前已是 `non_graph` 的记录再次标记，没有阻止 `graph -> non_graph`。
  - `reject_candidate()` 仅禁止当前已是 `rejected` 的记录再次 reject，没有阻止 `graph -> rejected` 或 `non_graph -> rejected`。
  - 也就是说，虽然前端按钮层面只暴露了部分合法路径，但后端 API 没有把状态机规则真正落成服务端约束，任何直接调接口的调用方都能绕开设计要求。
- 影响：
  - 管理员明确要求 `non_graph` 不能直接转 `graph`，`graph` 和 `non_graph` 只能先 `revert -> pending` 再重新审核。
  - 当前实现把这条最关键的知识治理规则放在了 UI 假设上，而不是数据层/服务层，存在知识库被非法状态迁移污染的风险。
- 建议：
  - 在 `accept/reject/mark-non-graph` 三个端点里显式校验允许的来源状态。
  - 为非法转移返回 400，并补 API 级测试覆盖。

### 3.3 P2：图谱边回退时写入了未定义的 `deleted` 状态，和当前设计与表语义不一致

- 位置：
  - `backend/plugins/mml_manager/main.py:1106`
  - 设计约束：`docs/plans/2026-04-02-mml-incremental-mining-design.md:488`
- 问题：
  - `graph_edge` 表初始化语义仍是设计里的 `active/revoked`，但 `revert_candidate()` 在 graph 回退时写的是 `status='deleted'`。
  - 当前表结构、文档和其他逻辑都没有把 `deleted` 定义成正式状态。
- 影响：
  - 这会让图谱边状态语义分叉：文档和审查口径认为是 `active/revoked`，代码实际落成 `active/deleted`。
  - 后续如果有依赖 `revoked` 语义的查询、统计、导出或清理逻辑，会出现状态兼容问题。
- 建议：
  - 收敛到单一边状态语义；若回退本意是“撤销”，应统一使用设计中定义的状态，并补相应测试。

## 4. 测试缺口

- `backend/tests/test_dependency_mining.py` 通过了 26 个增量挖掘测试，但没有覆盖：
  - `GET /files/mining-status` 的文件名字段契约
  - `non_graph -> graph` 非法直转被拒绝
  - `graph -> non_graph` 非法直转被拒绝
  - `graph -> rejected` / `non_graph -> rejected` 被拒绝
  - `graph_edge` 回退后的状态值是否符合设计语义

## 5. 回归风险

- 文件选择器字段名错误说明当前前后端接口变更没有形成稳定契约；后续再改接口时，类似“测试能过但页面直接坏掉”的风险较高。
- 当前状态机主要靠前端按钮约束，后端未收死；后续一旦增加脚本调用、批量操作或新前端入口，非法流转会再次出现。

## 6. 建议修复项

- 统一 `mining-status` 的文件名字段，并补契约测试。
- 在 `accept/reject/mark-non-graph` 三个端点中显式收紧允许的来源状态。
- 统一 `graph_edge.status` 的回退语义，避免引入未定义状态值。

## 7. 无法确认的残余风险

- 当前实现仍保留 `active_algorithm_version` 相关字段，但本轮实现未包含“切换激活算法版本”操作；因此相关版本隔离逻辑只做了静态代码核对，没有通过真实切换流程验证。

## 8. 管理员介入影响

- 管理员提供了前端真实现象“选择网元版本后看不到文件名”，本轮审查据此优先追查接口契约，确认了一个可复现的 P1。
- 管理员还要求本轮审查必须覆盖 Claude 最近多次提交链和最终代码，而不是只读最新文档；本轮已按 `a7f3f1b..52eedf8` 整段实现区间审查。

## 9. 最终评估

- 结论：当前实现不能直接闭环，需要先修上述问题后再复审。
- 其中 `3.1` 和 `3.2` 都会直接影响管理员实际使用与状态治理正确性，属于应先处理的阻塞项。

## 10. 第二轮复审结论（基于 `602e7b0`）

- 复审对象：`52eedf8..602e7b0`
- 复审时间：2026-04-02 17:35
- 已确认修复：
  - `GET /files/mining-status` 已改为返回 `file_name`，前后端契约对齐。
  - `graph -> non_graph`、`non_graph -> graph`、`graph -> rejected`、`non_graph -> rejected` 已在后端显式拦截。
  - `graph_edge` 回退状态已从 `deleted` 改为 `revoked`。
  - `python -m pytest backend/tests/test_dependency_mining.py -q` 复跑通过，32 passed。
- 剩余问题：
  - P1：`accept_candidate()` 仍允许 `rejected -> graph` 直接发生。代码把 `rejected` 列入 accept 的允许来源状态，并返回“只能从 pending 或 rejected 状态接受”。这和通过复审的设计文档不一致。设计明确要求 `rejected` 只能在新证据进入后被系统激活回 `pending`，前端 rejected tab 也定义为“无操作，等待新证据激活”。
- 影响：
  - 审核员可以绕过“新证据激活 -> pending”中间态，直接把已拒绝候选入图，破坏状态机闭环与审核轨迹语义。
- 建议修复：
  - 收紧 `accept_candidate()`，只允许 `pending -> graph`。
  - 补一条 `rejected -> accept` 返回 400 的回归测试。
- 复审结论：
  - 当前实现仍不能闭环，需先修复该剩余 P1。

## 11. 第三轮复审结论（基于 `f257add`）

- 复审对象：`602e7b0..f257add`
- 复审时间：2026-04-02 18:10
- 已确认修复：
  - `accept_candidate()` 已移除 `rejected` 作为允许来源状态，当前只允许 `pending` 及兼容旧数据的 pending-like 遗留状态进入 `graph`。
  - 返回报错文案已收紧为“只能从 pending 状态接受”。
  - 已新增 `test_state_machine_rejected_to_graph_blocked`，覆盖 `rejected -> accept` 返回 400 的场景。
- 验证：
  - 复查了 `backend/plugins/mml_manager/main.py` 中 `accept_candidate()` 的最终生效代码。
  - 复查了 `backend/tests/test_dependency_mining.py` 新增的状态机回归测试。
  - 复跑 `python -m pytest backend/tests/test_dependency_mining.py -q`，结果 `33 passed`。
- 复审结论：
  - 上一轮残留的最后一个状态机级 P1 已收口。
  - 当前实现层面未再发现阻塞闭环的代码级问题。

## 12. 第四轮复审结论（基于 `3a2adcc`）

- 复审对象：`f257add..3a2adcc`
- 复审时间：2026-04-03 09:30
- 已确认修复：
  - 同命令同参数的自环候选已过滤。
  - 单文件内多次命中不再因 `candidate_contribution` upsert 被最后一次覆盖。
  - `evidence_json` 已新增 `hit_file_count` 和 `total_mined_files`。
  - 我复跑 `python -m pytest backend/tests/test_dependency_mining.py -q`，结果 `38 passed`。
- 剩余问题：
  - P1：单文件 `hit_count` 仍然被 `sample_scripts` 上限 10 截断。`generate_single_file_candidates()` 先把样例列表限制为最多 10 条，再用 `len(sample_scripts)` 回填 `hit_count`，这意味着真实命中次数一旦超过 10，`evidence.hit_count` 和后续聚合的总命中次数都会被低估。位置：`backend/plugins/mml_manager/candidate_engine.py:257`、`backend/plugins/mml_manager/candidate_engine.py:266`。
  - P1：`/files/mine` 在“选中的文件里包含已挖过文件”时会把 `support` 分母算大。当前实现把 `total_mined_files_before + len(file_ids)` 直接传入重算逻辑；如果本次选择的文件中有一部分本来就已经在 `file_mining_record` 里，分母会重复计数，导致 `support`、`confidence` 和 `evidence.total_mined_files` 都偏小。位置：`backend/plugins/mml_manager/main.py:1207`、`backend/plugins/mml_manager/main.py:1317`。
- 测试缺口：
  - 当前新增测试覆盖了“4 次命中”和“2/3 support”，但没有覆盖“同一文件 >10 次命中”。
  - 当前新增测试也没有覆盖“`/files/mine` 混合选择已挖文件 + 新文件”的重复计数场景。
- 残余风险 / 开放点：
  - 当前 `aggregate_contributions()` 会把无命中文件的占位 contribution 一起纳入 `order_consistency`、`name_relevance` 均值，导致这两个维度也会随着未命中文件数增加而下降。我可以证明当前实现会出现这种附加惩罚，但这条是否符合业务定义，仍需要 Claude 在 fix 说明里明确口径。
- 复审结论：
  - 当前实现仍不能闭环，需要先修掉上述 2 个 P1 再复审。
## 13. 第五轮复审结论（基于 `adb4d87`）
- 审查提交区间：`3a2adcc..adb4d87`
- 审查时间：2026-04-03 10:45
- 已确认修复项
  - `generate_single_file_candidates()` 已将单文件真实命中次数单独累加，`hit_count` 不再受 `sample_scripts` 上限 10 截断。
  - `/files/mine` 已改为在全部文件处理完成后重新查询 `file_mining_record` 的去重文件数，再统一重算候选分数；混合“已挖文件 + 新文件”时不会再把 `support` 分母重复计数。
  - 新增回归测试已覆盖“单文件 >10 次命中”和“混合已挖/新文件时 support 分母正确”两个场景。
  - 复跑 `python -m pytest backend/tests/test_dependency_mining.py -q`，结果 `40 passed`。
- 发现的问题
  - 本轮未发现新的实现级问题。
- 测试缺口
  - 当前测试已覆盖本轮修复场景；未额外发现新的阻塞级缺口。
- 回归风险
  - 当前 `aggregate_contributions()` 仍会把无命中文件占位项一起计入 `order_consistency`、`name_relevance` 的均值。这与现有设计文档口径一致，因此本轮不作为缺陷拦截，但后续若管理员调整评分语义，需要同步修订设计和测试。
- 建议修复项
  - 无阻塞项。
- 无法确认的残余风险
  - 若未来希望 `order_consistency`、`name_relevance` 只反映命中文件质量，而不受未命中文件数量影响，需要单独调整评分模型。
- 管理员介入影响
  - 管理员前序强调了 evidence 汇总与评分语义的可解释性；本轮修复已收掉对应实现偏差中的阻塞部分。
- 最终评估
  - 当前实现已收口，可以进入下一阶段验证或使用。
## 14. 第六轮复审结论（基于当前实现一致性复查）
- 审查时间：2026-04-03 11:30
- 审查背景
  - 本轮不再只核对 `hit_count / support` 修复，而是沿“单文件生成 -> 文件级 contribution -> 候选聚合 -> graph_edge 落库 -> 前端读取”链路重新核查 evidence 与文件维度的一致性。
- 发现的问题
  - P1：`re-mine` 在 `graph` / `non_graph` 候选当前算法版本下零 contribution 时，只把 `confidence` 和 `scores_json` 清零，没有同步清空或重算 `evidence_json`。这样会出现“分数为 0，但 evidence 仍保留旧 `hit_count / hit_values / sample_scripts`”的脏状态。位置：`backend/plugins/mml_manager/main.py` `re-mine` 零贡献分支。
  - P1：已入图谱边 `graph_edge` 的 `evidence_json` 不会随着后续增量挖掘同步更新。当前只在 `accept_candidate()` 时把当时的候选 evidence 写入 `graph_edge`；后续新文件再命中同 key，只会更新 `dependency_candidate` / `candidate_contribution`，不会更新 `graph_edge`。这与“图谱动态构建、证据持续关联”目标不一致。位置：`backend/plugins/mml_manager/main.py` `accept_candidate()` 与 `mine_selected_files()`。
  - P2：候选级 `dependency_candidate.evidence_json` 已经把文件维度压平。真正区分文件的是 `candidate_contribution(candidate_id, file_entry_id, algorithm_version)`；聚合后 evidence 仅保留总 `hit_count`、`hit_file_count`、`hit_values` 和不带 `file_entry_id` 的 `sample_scripts`，审核页无法知道每条样例来自哪个文件。位置：`backend/plugins/mml_manager/main.py` 聚合重算逻辑。
  - P2：前端 evidence 契约仍停留在旧模型，类型和展示都未跟上后端。前端还定义 `total_scripts` / `counter_examples`，页面展示仍读取 `selectedCandidate.evidence.total_scripts`，而后端当前实际返回的是 `hit_file_count` / `total_mined_files`。这会导致候选详情语义错误。位置：`frontend/src/api/dependency-mining.ts`、`frontend/src/views/plugins/DependencyMining.vue`。
- 测试缺口
  - 现有测试覆盖了 `hit_count` 累加、`support` 分母和部分状态机，但没有覆盖：1）`graph/non_graph` 零 contribution 后 evidence 是否同步清零；2）graph edge 是否随新增 contribution 更新 evidence；3）前端 evidence 契约是否与后端一致。
- 最终评估
  - 当前实现不能按“证据一致、文件可追溯、图谱动态更新”口径放行，需要 Claude 继续修正。
## 15. 第七轮复审结论（基于 `14f65e9`）
- 审查提交区间：`6d10635..14f65e9`
- 审查时间：2026-04-03 15:15
- 已确认修复项
  - `dependency_candidate.evidence_json` 已补 `per_file` 和带 `file_entry_id` 的 `sample_scripts`。
  - 正向增量挖掘命中已入图谱边时，`_recalculate_candidate_scores()` 会同步更新 `graph_edge.evidence_json`。
  - 前端 evidence 类型与候选详情展示已切到 `hit_file_count / total_mined_files / per_file` 新口径。
  - 复跑 `python -m pytest backend/tests/test_dependency_mining.py -q`，结果 `43 passed`。
- 发现的问题
  - P1：`re-mine` 把某个 `graph` 候选当前算法版本下的 contribution 删到 0 时，只会把 `dependency_candidate` 的 `evidence_json` 清空，不会同步清空对应 `graph_edge.evidence_json`。因为 graph edge 同步逻辑只在 `_recalculate_candidate_scores()` 里，而零 contribution 分支不会进入该函数。这会留下“候选 evidence 已空，但图谱边 evidence 仍是旧值”的不一致状态。位置：`backend/plugins/mml_manager/main.py` `re-mine` 零 contribution 分支与 `_recalculate_candidate_scores()` 尾部同步逻辑。
  - P2：保留兼容的废弃接口 `POST /candidates/generate` 仍然走旧的 `generate_candidates()` 逻辑，会生成 `auto_passed / llm_review / man_review` 这些旧状态，并返回不含 `per_file`、`sample_scripts` 也不带 `file_entry_id` 的旧 evidence 结构。该接口仍是公开路由，当前实现与已确认的新状态机和 evidence 契约不一致。位置：`backend/plugins/mml_manager/main.py` `/candidates/generate` 与 `backend/plugins/mml_manager/candidate_engine.py` `generate_candidates()`。
- 测试缺口
  - 新增测试覆盖了候选 evidence 清空、graph edge 正向更新、候选 per-file 明细，但没有覆盖“零 contribution re-mine 后 graph_edge evidence 也应被清空/归零”以及“废弃 `/candidates/generate` 仍符合当前状态/证据契约”。
- 回归风险
  - 前端 `npm.cmd run build` 在当前环境下失败于 Vite 配置加载阶段的 `spawn EPERM`，这是环境限制，不足以证明前端构建链完全通过。
- 最终评估
  - 当前实现仍不能放行；需先修复以上 1 个 P1，并处理废弃接口的一致性问题。
## 16. 第八轮复审结论（基于 `a712579`）
- 审查提交区间：`cdd3947..a712579`
- 审查时间：2026-04-03 16:55
- 已确认修复项
  - `re-mine` 在 `graph` 候选当前算法版本下零 contribution 时，已同步把对应 `graph_edge.evidence_json` 清空并将 `confidence` 置 0。
  - 废弃但保留兼容的 `POST /candidates/generate` 已切换到 `pending + review_route` 新状态模型，并返回包含 `hit_file_count / total_mined_files / per_file / sample_scripts.file_entry_id` 的新 evidence 契约。
  - 新增回归测试已覆盖上述两个场景。
  - 复跑 `python -m pytest backend/tests/test_dependency_mining.py -q`，结果 `44 passed`。
- 发现的问题
  - 本轮未发现新的实现级问题。
- 测试缺口
  - 后端当前覆盖已足以支撑本轮修复结论；未额外发现阻塞级缺口。
- 回归风险
  - 我尝试执行 `npm.cmd run build`，但当前环境仍在 Vite 配置加载阶段报 `spawn EPERM`。这看起来是环境限制，不像代码错误；但它也意味着我不能在本地独立确认前端构建链通过。
- 最终评估
  - 代码层面当前实现已收口，可以放行；仅保留“前端 build 未能在当前环境独立复核”的验证备注。
