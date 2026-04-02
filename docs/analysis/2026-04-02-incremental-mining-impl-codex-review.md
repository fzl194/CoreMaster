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
