# AGENTS.md

> 本文件是 Codex 的个人行为准则。其他 Agent 读取时请无视。

## 协作协议

遵守 [TEAM.md](./TEAM.md) 中的共享团队协议。

## 输出位置与命名约定

Codex 负责把审查结论和查漏补缺分析写入 `docs/analysis/`。

路径约定：

- 审查文档：`docs/analysis/YYYY-MM-DD-<task-slug>-codex-review.md`

`codex-review` 文档至少包含：

- 审查背景
- 审查范围
- 发现的问题
- 测试缺口
- 回归风险
- 建议修复项
- 无法确认的残余风险
- 管理员介入对审查范围或结论的影响
- 最终评估

## 分析文档规则

Codex 负责将持久化分析文档写入 `docs/analysis/`。

路径约定：

- `docs/analysis/YYYY-MM-DD-<task-slug>-codex-review.md`

文档应至少包含：

1. 背景
2. 审查范围
3. 发现的问题
4. 尚未证明安全的缺口
5. 建议的后续动作
6. 验证说明
7. 管理员介入说明
8. 最终评估

如果没有发现问题，也必须明确写出"未发现问题"，并记录剩余风险与验证边界。

## 审查标准

Codex 审查时应优先关注：

1. 功能性缺陷
2. 相对于现有行为的回归
3. 相对于计划或需求的不完整实现
4. 数据一致性与迁移风险
5. API 契约不匹配
6. 缺失的校验或错误处理
7. 缺失或薄弱的测试
8. 容易在短期内引发缺陷的可维护性风险
9. 管理员直接操作是否导致审查范围漂移、文档失配或结论失效

纯样式问题优先级较低，除非它掩盖了正确性或维护性风险。

## Git 职责

Codex 在执行审查时应至少检查：

- `git status --short`
- `git diff`
- 如有需要，查看指定提交的 `git show`

Codex 的 review 文档中应明确说明：

- 本次审查基于哪个分支
- 审查的是工作区 diff、某个提交，还是某两个提交之间的差异
- 是否存在未纳入审查范围但可能影响结论的脏工作区改动
- 是否存在管理员提交或管理员文档修改影响了本次审查基线

## 文件边界

Codex 必须遵守 [TEAM.md](./TEAM.md) 中的文件归属表。具体来说：

- `docs/handoffs/*claude-handoff.md` 的初始内容由 Claude 编写，Codex 只在回写区域操作。
- `docs/plans/*` 由 Claude 独占，Codex 不得创建或修改。
- 源代码（`backend/`、`frontend/`）由 Claude 负责实现，Codex 不得直接修改。
- `docs/analysis/*` 由 Codex 独占，Codex 负责创建和维护。
- `git add` 时必须逐文件指定路径，**禁止**使用 `git add -A` 或 `git add .`，避免误提交对方的文件。
