# Codex 审查结论：MML 命令依赖关系挖掘系统 MVP

- 状态：已审查
- 审查日期：2026-04-02
- 审查分支：`master`
- 审查版本：`e6f616a`
- 审查对象：Claude 提交的 `dep-mining-mvp-001` MVP 实现
- 交接文档：`docs/handoffs/2026-04-02-dep-mining-mvp-claude-handoff.md`

## 1. 审查背景

本轮审查针对 MML 依赖挖掘 MVP 的完整交付，重点检查解析器增强、候选生成引擎、审核队列 API、最小前端页面，以及已有测试是否覆盖关键回归风险。

## 2. 审查范围

- 后端：`backend/core/services/parser.py`
- 后端：`backend/plugins/mml_manager/main.py`
- 后端：`backend/plugins/mml_manager/candidate_engine.py`
- 测试：`backend/tests/test_parser_enhanced.py`
- 测试：`backend/tests/test_dependency_mining.py`
- 前端：`frontend/src/views/plugins/DependencyMining.vue`
- 前端：`frontend/src/api/dependency-mining.ts`

## 3. 发现的问题

### P1：重新生成候选会覆盖人工审核结果，已接受/已拒绝状态无法稳定保留

- 证据：
  - 候选生成接口在唯一键冲突时直接执行 `UPDATE dependency_candidate SET status=?, confidence=?, ...`，会把已人工处理的记录重新写回算法初始状态：`backend/plugins/mml_manager/main.py:733`
  - 人工通过/拒绝写入的 `accepted` / `rejected` 状态只保存在同一行里，没有额外保护：`backend/plugins/mml_manager/main.py:855`、`backend/plugins/mml_manager/main.py:888`
- 影响：
  - 审核员刚确认过的候选，只要再次点击“生成”就可能从 `accepted` / `rejected` 退回 `auto_passed`、`llm_review` 或 `man_review`。
  - 这会破坏审核队列的幂等性，也会让前端列表、后续图谱确认流程与人工结论失去一致性。
- 建议修复：
  - 重新生成时不要覆盖人工终态；至少应保留 `accepted` / `rejected`，仅刷新分数和证据。
  - 增加回归测试，覆盖“生成 -> accept/reject -> 再生成”流程。

### P1：解析器会把引号内的 `/* ... */` 误删，合法参数值被静默篡改

- 证据：
  - `parse_text_with_report()` 在真正做语法解析前，先对整个文本执行全局 `re.sub(r"/\*.*?\*/", "", ...)`：`backend/core/services/parser.py:44`
  - 我用最小样例 `ADD APN: DESC="keep /* not comment */ text", APN="x";` 验证后，返回值中的 `DESC` 被改写为 `keep  text`。
- 影响：
  - 只要脚本参数值中合法包含 `/* ... */`，解析结果就会被无提示修改。
  - 这会进一步污染命令实例提取和候选生成证据，属于数据正确性问题。
- 建议修复：
  - 块注释剥离必须做成引号感知，不能在原始文本上用正则整体替换。
  - 补充包含双引号/单引号内注释样式文本的解析测试。

### P1：前端“提取 & 生成”按钮并没有执行提取，页面无法独立完成声明的 MVP 流程

- 证据：
  - 页面主按钮文案明确写的是“提取 & 生成”：`frontend/src/views/plugins/DependencyMining.vue:14`
  - 但点击后仅调用 `apiGenerate(selectedNeVersionId.value)`，没有任何 `extract-commands` 调用，也没有脚本选择或批量提取逻辑：`frontend/src/views/plugins/DependencyMining.vue:251`
  - 后端生成接口只读取已有 `command_instance`，不会自动从脚本文件提取：`backend/plugins/mml_manager/main.py:687`
- 影响：
  - 对只上传了脚本、还未逐个执行提取的版本，这个页面会直接返回空候选，用户会误以为系统无结果。
  - 按当前页面交互，MVP 实际上不具备“从脚本到候选”的自洽闭环。
- 建议修复：
  - 要么把按钮文案改为“生成候选”，并明确依赖前置提取步骤。
  - 要么补齐页面内的批量提取流程，再调用生成接口。

## 4. 测试缺口

- 未覆盖“候选已 accept/reject 后再次生成”的状态保持测试。
- 未覆盖“引号内包含块注释样式文本”的解析正确性测试。
- 未覆盖前端页面自身的主流程测试，尤其是“上传后未提取直接生成”的行为。

## 5. 回归风险

- 候选重新生成与人工审核结果之间存在状态回退风险。
- 解析器对包含特殊注释样式值的脚本存在静默数据污染风险。
- 前端页面宣称的闭环流程与实际实现不一致，容易形成使用层面的假阴性结果。

## 6. 建议修复项

- 保留人工终态，避免 `generate` 覆盖 `accepted` / `rejected`。
- 将块注释处理改为引号感知扫描，而不是对全文做正则替换。
- 统一前端交互与真实后端流程：补提取，或改文案并显式说明前置步骤。
- 增加针对上述 3 个问题的回归测试。

## 7. 无法确认的残余风险

- 现有实现仍未用真实现网样本验证候选算法，名称相似度和支持度权重在噪声较大的脚本集合上可能需要重新校准。
- 当前仅检查了交接文档列出的主路径，没有额外覆盖更大规模并发与历史数据迁移场景。

## 8. 管理员介入影响

- 本轮未发现新的管理员直接改代码痕迹。
- 交接文档中记录了管理员要求“从技术设计文档开始开发”以及“完成后输出 Codex 交接件”，该要求本身不影响上述缺陷判断。

## 9. 最终评估

当前版本不能判定为可闭环交付。核心问题不是样式或文案，而是存在会影响审核结果一致性、解析正确性和页面主流程可用性的 P1 缺陷。建议 Claude 先修复后，再进行下一轮复审。
