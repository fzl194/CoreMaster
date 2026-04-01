# MML 命令依赖挖掘设计审查

- 状态：已审查
- 审查日期：2026-04-01

## 1. 审查背景

- 审查对象：`docs/plans/2026-04-01-mml-dependency-mining-design.md`
- 审查目标：评估该设计在当前仓库中的可落地性、正确性风险、回归风险与验证缺口
- 当前分支：未额外确认
- 审查基线：基于当前工作区文档与现有代码实现进行审查
- Git 状态：工作区存在未跟踪目录 `.claude/`、`docs/plans/`
- 管理员介入：未见本轮管理员专属文档或提交

## 2. 审查范围

- 设计文档中的算法流程、状态模型、数据模型、分期交付
- 现有后端落地基础：
  - `backend/plugins/mml_manager/main.py`
  - `backend/core/services/parser.py`

## 3. 发现的问题

### 3.1 高风险：候选统计口径未定义去重规则，`support` 会被重复命中放大

- 位置：`docs/plans/2026-04-01-mml-dependency-mining-design.md:176`、`docs/plans/2026-04-01-mml-dependency-mining-design.md:191`、`docs/plans/2026-04-01-mml-dependency-mining-design.md:219`
- 问题：阶段 2 先对同一脚本内所有 `cmd_i/cmd_j/param_i/param_j` 的值相等组合直接 `yield`，后面又把 `hit_count` 定义为“该参数对值共享的脚本数”，`support` 也按脚本级概率解释。但设计没有规定如何把同一脚本内的多次命中折叠为一次，也没有定义多实例命令、重复参数、多值复用时的去重键。
- 影响：实现时很容易把“命中次数”误算成“命中脚本数”，导致高频模板脚本或单脚本内重复命令把 `support`、`distinctiveness`、样本证据一起抬高，直接把错误候选送进 `auto_confirmed`。
- 建议：在设计里补充明确的统计单位和去重规则，至少定义：
  - 候选聚合主键
  - `hit_count` 是否按脚本去重
  - 同一脚本多次命中如何折叠
  - `counter_examples` 的抽样口径

### 3.2 高风险：状态模型前后不一致，候选状态、图谱边状态和审查队列状态无法形成单一状态机

- 位置：`docs/plans/2026-04-01-mml-dependency-mining-design.md:285`、`docs/plans/2026-04-01-mml-dependency-mining-design.md:305`、`docs/plans/2026-04-01-mml-dependency-mining-design.md:360`、`docs/plans/2026-04-01-mml-dependency-mining-design.md:374`
- 问题：文档里同时出现了三套状态：
  - 候选记录：`auto_confirmed | llm_review | man_review | confirmed | rejected`
  - 图谱边：`candidate | confirmed | rejected | revoked`
  - 审查流程：`auto_confirmed -> 队列 -> 人工/LLM`
  但没有说明这些状态分别属于哪个实体、如何流转、何时从候选提升为图谱边、`llm_confirmed` / `llm_rejected` 是否落边、`revoked` 是否只存在于边表。
- 影响：实现时 API、前端筛选、审计日志、回滚逻辑会各自理解一套状态，最后很难保证“当前图谱”和“候选审查队列”一致。
- 建议：拆成两层状态机并写清转换：
  - 候选状态机：`pending -> auto_passed/llm_passed/manual_passed -> accepted/rejected`
  - 图谱边生命周期：`active -> revoked`
  同时明确“accepted 是否一定生成/更新边”“revoke 针对候选还是边”。

### 3.3 中风险：设计把“实例提取”当作稳定前提，但现有解析器远达不到该精度，缺少解析正确性兜底

- 位置：`docs/plans/2026-04-01-mml-dependency-mining-design.md:133`
- 相关代码：`backend/core/services/parser.py:9`、`backend/core/services/parser.py:21`、`backend/core/services/parser.py:43`
- 问题：阶段 1 假设可以稳定提取 `{operation, name, params, line_number}`，并据此做参数级依赖挖掘。但当前仓库解析器只支持单行正则、参数按逗号直接切分，没有覆盖多行命令、值中带逗号、转义/引号、复杂注释、非标准格式等情况。
- 影响：如果直接按现有解析能力推进，后续所有评分、样本、反例都建立在不稳定输入上，误报和漏报都难以解释，甚至会让人工审查界面展示错误证据。
- 建议：把“解析正确性验证”前置为一期显式交付，至少补：
  - 解析器适用语法边界
  - 失败样本落库策略
  - 一组真实 MML 样本回归测试
  - 当解析失败或部分解析时，候选生成如何降级

### 3.4 中风险：只做精确版本作用域且先排除已知依赖，会让增量挖掘无法复核旧边，也无法处理新版本冷启动

- 位置：`docs/plans/2026-04-01-mml-dependency-mining-design.md:27`、`docs/plans/2026-04-01-mml-dependency-mining-design.md:169`、`docs/plans/2026-04-01-mml-dependency-mining-design.md:276`
- 问题：
  - 文档把作用域固定到 `vendor + ne_type + version` 最细粒度，但没有为脚本稀疏的新版本设计回退或继承策略。
  - 同时又在评分前直接排除已知依赖，导致系统只能“增量补未知”，不能利用新样本复核旧依赖是否应降权、撤销或迁移。
- 影响：
  - 新版本脚本量不足时，系统很可能长期挖不出任何候选。
  - 已有错误边会永久沉积，和文档宣称的“可撤回、可迭代”不一致。
- 建议：补充两类机制：
  - 版本冷启动策略：相邻版本继承、跨版本先验、最小样本阈值
  - 已知边复核策略：已知边也进入周期性校验，只是不走同一候选队列

## 4. 测试缺口

- 文档没有定义任何离线评估集，无法证明阈值 `θ_high=0.85`、`θ_low=0.50` 在真实数据上可用。
- 没有规定如何验证候选生成阶段的误报率、漏报率、人工复核通过率。
- 没有覆盖解析器准确率测试，而当前实现明显是该方案的前置依赖。

## 5. 回归风险

- 如果按当前设计直接落库，候选状态与图谱边状态可能分叉，后续 API 和前端会围绕错误状态语义继续扩散。
- 如果统计口径不先固定，历史候选一旦入库，后面即使修正公式也会出现“同一算法不同批次不可比”的数据污染。

## 6. 建议修复项

- 先补一版“统计定义附录”，明确候选主键、脚本去重规则、样本抽样规则、反例定义。
- 重写状态机章节，分别定义候选实体和图谱边实体，不要混用状态。
- 把解析器能力评审列入一期前置任务，并绑定真实样本测试。
- 给最细粒度作用域增加冷启动与复核机制，否则“持续增量挖掘”在数据稀疏场景下不可用。

## 7. 验证说明

- 已检查设计文档全文。
- 已对照当前实现查看现有表结构与解析器边界：
  - `backend/plugins/mml_manager/main.py`
  - `backend/core/services/parser.py`
- 未运行测试；本次为设计审查，不涉及代码修改验证。

## 8. 管理员介入说明

- 未发现本轮与该任务直接相关的管理员文档、提交或状态回写。

## 9. 最终评估

- 结论：当前设计方向可行，但还不能直接进入实现。
- 原因：核心统计定义、状态机边界、解析前提、增量复核策略这四处都还不够闭合；如果现在开工，后面大概率会在数据口径和状态语义上返工。
