# MML 命令依赖关系挖掘系统 — 增量挖掘设计

> 状态：v3（修订版）
> 修订说明：v2 修复 3 个设计级 P1；v3 修复重挖误删正式知识层问题
> 日期：2026-04-02
> 前序文档：`docs/plans/2026-04-01-mml-dependency-mining-design.md`
> 变更原因：管理员明确新目标为"按文件选择的增量式挖掘系统"，原"按版本全量"模型不再适用
> 修订说明：收敛主状态为四种、统一文件事实层、落地算法版本方案 A

## 1. 需求变化摘要

原设计：选择一个网元版本 → 全量提取所有脚本命令 → 全量生成候选
新需求：管理员手动选择若干文件 → 增量挖掘 → 候选池长期累积

| 维度 | 原设计 | 新需求 |
|------|--------|--------|
| 挖掘粒度 | 按版本全量 | 按文件增量 |
| 结果可替换 | 不支持 | 同文件重挖替换旧贡献 |
| 候选池 | 每次全量重算 | 长期汇总池，增量追加 |
| 主状态 | pending / accepted / rejected | pending / graph / non_graph / rejected |
| 审核路由 | 混入 status | 独立 `review_route` 字段 |
| 文件事实层 | 无 | 统一记录所有挖掘结果，不限候选状态 |
| 算法版本 | 无 | 激活版本隔离，历史可保留 |
| 图谱证据累积 | 无 | 新文件匹配时证据追加到图谱边 |
| 非图谱库 | 无 | 知识级否定，与 reject 语义不同 |

## 2. 核心概念

### 2.1 两层分离：事实层 + 决策层

```
事实层（统一文件挖掘结果）:
  candidate_contribution — 每个文件对每个关系键的贡献
  无论当前关系键处于什么状态（pending/graph/non_graph/rejected），
  文件挖掘结果都必须先沉淀到这一层。

决策层（关系状态流转）:
  dependency_candidate.status — pending / graph / non_graph / rejected
  决定"这条关系当前在哪"，但不影响事实层的记录。
```

### 2.2 四层实体

```
文件 (file_entry)           — 管理员选择的操作对象
  ↓ 提取
命令实例 (command_instance) — 文件内的解析结果
  ↓ 生成
文件事实 (candidate_contribution) — 文件对关系键的统一贡献（事实层）
  ↓ 汇总
关系 (dependency_candidate) — 长期汇总项，status 标识当前决策（决策层）
  ↓ 审核
图谱边 (graph_edge)         — 已确认的依赖关系
```

### 2.3 主状态机（4 种状态）

```
                          ┌────────────┐
                          │  pending   │  ← 候选池中待审核
                          └──┬───┬──┬──┘
                             │   │  │
                  accept     │   │  │ reject
                 (→ graph)   │   │  │ (可回退)
                             │   │  │
                   mark      │   │  │
                 non_graph   │   │  │
                             ▼   ▼  ▼
                       ┌──────┐ ┌──────────┐  ┌───────┐
                       │graph │ │non_graph │  │reject │
                       │(图谱)│ │(非图谱)  │  │       │
                       └──┬───┘ └────┬─────┘  └───────┘
                          │          │            ↑
                     revert│    revert│            │
                          ▼          ▼            │
                       回到 pending ──────────────┘
                         (新证据激活)

非法转换: non_graph → graph（必须先 revert 到 pending 再 accept）
```

**状态定义**（仅 4 种）：

| 状态 | 含义 | 审核路由 |
|------|------|---------|
| `pending` | 候选池中待审核 | 由 `review_route` 字段决定审核路径 |
| `graph` | 已确认入图谱 | — |
| `non_graph` | 专家确认绝不可能是图谱边 | — |
| `rejected` | 本次不通过，新证据可再进池 | — |

### 2.4 审核路由（独立字段，不混入 status）

`review_route` 是 `dependency_candidate` 上的独立字段，表达"这条 pending 候选应该走哪条审核路径"：

| review_route 值 | 含义 | 何时设置 |
|----------------|------|---------|
| `auto` | 高置信度，自动通过初筛 | 候选生成时按置信度自动设置 |
| `llm` | 等 LLM 审核（第二期） | 候选生成时按置信度自动设置 |
| `manual` | 等人工审核 | 候选生成时按置信度自动设置 |
| NULL | 无路由 | status 非 pending 时清空 |

**关键规则**：
- `review_route` 仅在 `status='pending'` 时有意义
- `status` 变为 `graph` / `non_graph` / `rejected` 时，`review_route` 清空
- `rejected` 被新证据激活回 `pending` 时，按新置信度重设 `review_route`

### 2.5 文件级贡献模型（统一事实层）

**核心原则：所有文件挖掘结果都必须进入事实层，不论当前关系处于什么状态。**

```
文件 A 挖出关系键 (ADD APN.VRFNAME → ADD VPN.VPN):
  → 写入 contribution(file_A, key, evidence, scores)
  → 无论 key 当前是 pending / graph / non_graph / rejected

文件 B 也挖出同一关系键:
  → 写入 contribution(file_B, key, evidence, scores)
  → 汇总分 = aggregate(contribution_A + contribution_B)

状态对贡献的影响:
  pending:  贡献影响汇总分，参与排序
  graph:    贡献仍然记录，但汇总分仅供查看，不影响图谱边
  non_graph: 贡献仍然记录，作为"有新证据但专家仍否决"的追溯依据
  rejected: 新贡献触发激活 → 回到 pending
```

重挖文件 A 时：
1. 删除 contribution_A
2. 插入 contribution_A'
3. 重算汇总分数

**正式知识保护规则**：
- graph / non_graph 关系记录永不因零贡献被删除
- 零贡献清理仅适用于候选池中的临时关系（pending / rejected）
- 正式知识零贡献时：汇总分数置零，标记"当前版本无支持"，记录保留

### 2.6 算法版本方案

**核心规则：当前汇总只认一个激活算法版本的贡献，不混算。**

```
candidate_contribution.algorithm_version — 每条贡献记录的算法版本
dependency_candidate.active_algorithm_version — 当前汇总使用的版本

汇总时只取 algorithm_version = active_algorithm_version 的贡献。
历史版本贡献保留在数据库中，可追溯，但不参与当前汇总。
```

**版本升级流程**：
1. 部署新算法 → 更新全局默认算法版本为 v2
2. 新挖掘的文件贡献标记 algorithm_version='v2'
3. 管理员可选择将候选池的 active_algorithm_version 切换到 v2
4. 切换后：汇总仅基于 v2 贡献重算，v1 贡献保留但不计入
5. 管理员可选择对 v1 文件批量重挖（生成 v2 贡献）

## 3. 数据模型

### 3.1 新增表

**file_mining_record** — 文件挖掘状态

```sql
CREATE TABLE IF NOT EXISTS file_mining_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_entry_id INTEGER NOT NULL UNIQUE,
    ne_version_id INTEGER NOT NULL,
    mined INTEGER NOT NULL DEFAULT 0,
    algorithm_version TEXT NOT NULL DEFAULT 'v1',
    command_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_entry_id) REFERENCES file_entry(id)
);
```

**candidate_contribution** — 文件挖掘事实层（统一记录所有挖掘结果）

```sql
CREATE TABLE IF NOT EXISTS candidate_contribution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    file_entry_id INTEGER NOT NULL,
    algorithm_version TEXT NOT NULL DEFAULT 'v1',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    scores_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES dependency_candidate(id),
    FOREIGN KEY (file_entry_id) REFERENCES file_entry(id),
    UNIQUE(candidate_id, file_entry_id, algorithm_version)
);
```

### 3.2 修改表

**dependency_candidate** — 主状态收敛 + 新增独立字段

```sql
-- 新增列
ALTER TABLE dependency_candidate ADD COLUMN review_route TEXT;
  -- 值: 'auto' | 'llm' | 'manual' | NULL
  -- 仅 status='pending' 时有值
ALTER TABLE dependency_candidate ADD COLUMN non_graph_reason TEXT;
ALTER TABLE dependency_candidate ADD COLUMN non_graph_reviewer TEXT;
ALTER TABLE dependency_candidate ADD COLUMN active_algorithm_version TEXT NOT NULL DEFAULT 'v1';
  -- 当前汇总使用的算法版本

-- status 枚举收敛为 4 种:
--   pending | graph | non_graph | rejected
-- （删除 auto_passed / llm_review / man_review）
```

### 3.3 保留表（不变）

- `command_instance` — 命令实例
- `graph_edge` — 图谱边
- `graph_changelog` — 变更日志

## 4. 核心操作

### 4.1 挖掘选中文件

```
输入: file_ids[] (同一 ne_version 下的文件列表)
当前算法版本: ALG_VER (全局配置)

FOR EACH file_id IN file_ids:
    1. 解析文件 → command_instance[]
    2. 生成该文件的本地候选:
       - 基于该文件的 command_instance 运行 candidate_engine
       - 得到 local_candidates[] (每个含 key + evidence + scores)
    3. 更新 file_mining_record (mined=1, command_count=N, algorithm_version=ALG_VER)
    4. FOR EACH local_candidate:
        a. 查找 ne_version 下同 key 的 dependency_candidate:

           若不存在 → 创建候选:
             - status = 'pending'
             - review_route = 按 confidence 分层 (auto/llm/manual)
             - active_algorithm_version = ALG_VER
             + 创建 contribution (algorithm_version=ALG_VER)
             + 重算汇总分数（仅 ALG_VER 贡献）

           若存在:
             - 写入/替换 contribution (algorithm_version=ALG_VER)
               【无论当前 status 是什么，贡献都必须记录到事实层】

             - 按 status 分支处理:
               status='pending':
                 重算汇总分数（仅 active_algorithm_version 贡献）
               status='rejected':
                 重算汇总分数
                 → status 改为 'pending'（新证据激活）
                 → review_route 按新 confidence 重设
               status='graph':
                 贡献已记录，汇总分更新（供查看）
                 不改变 status，不额外操作 graph_edge
               status='non_graph':
                 贡献已记录，作为追溯依据
                 不改变 status（专家结论不变）
```

### 4.2 重挖单文件

```
输入: file_entry_id
当前算法版本: ALG_VER

1. 删除该文件在 ALG_VER 下的所有 candidate_contribution
   （其他算法版本的贡献不受影响）
2. 找到受影响的候选，重算汇总分数（仅 active_algorithm_version 贡献）
3. 清理零贡献候选:
   - 仅删除 status 为 pending 或 rejected 且当前激活算法版本下零贡献的候选
   - graph / non_graph 即使零贡献也永不删除（正式知识层独立保留）
   - graph / non_graph 零贡献时: 汇总分数置零，标记 "当前版本无支持"，关系记录保留
4. 按 4.1 流程重新挖掘该文件
```

### 4.3 Accept 候选 → graph

```
1. 创建 graph_edge 记录
2. 更新 candidate:
   - status = 'graph'
   - review_route = NULL
   - graph_edge_id = 新边ID
3. 写 changelog
```

### 4.4 标记 non_graph

```
1. 更新 candidate:
   - status = 'non_graph'
   - review_route = NULL
   - non_graph_reason = ?
   - non_graph_reviewer = ?
2. 写 changelog
注: 已有的 contribution 不删除，作为追溯依据保留
```

### 4.5 Reject 候选

```
1. 更新 candidate:
   - status = 'rejected'
   - review_route = NULL
2. 写 changelog
注: rejected 不是终态，新文件挖掘可将其激活回 pending
    已有的 contribution 不删除
```

### 4.6 Revert graph → pending

```
1. 删除关联的 graph_edge
2. 更新 candidate:
   - status = 'pending'
   - graph_edge_id = NULL
   - review_route = 按 confidence 重设
3. 写 changelog
```

### 4.7 Revert non_graph → pending

```
1. 更新 candidate:
   - status = 'pending'
   - non_graph_reason = NULL
   - non_graph_reviewer = NULL
   - review_route = 按 confidence 重设
2. 写 changelog
```

### 4.8 切换激活算法版本

```
输入: ne_version_id, new_algorithm_version

1. 更新该版本下所有候选的 active_algorithm_version = new_ver
2. 对每个候选重算汇总分数（仅 new_ver 贡献）
3. 无 new_ver 贡献的候选 → 汇总分清零，但仍保留候选记录
```

## 5. 分数重算

当文件贡献发生变化时，需要重算候选的汇总分数。

### 5.1 算法版本过滤

```python
def recalculate_scores(candidate, all_contributions):
    """从文件级贡献重算候选汇总分数，仅使用激活算法版本。"""
    active_ver = candidate["active_algorithm_version"]

    # 仅取激活算法版本的贡献
    active_contribs = [
        c for c in all_contributions
        if c["algorithm_version"] == active_ver
    ]

    if not active_contribs:
        return {"confidence": 0.0, "support": 0.0, ...}

    return _aggregate(active_contribs)
```

### 5.2 汇总策略

```python
def _aggregate(contributions: list[dict]) -> dict:
    """汇总同一算法版本的贡献。"""
    total_files = len(contributions)

    support = sum(1 for c in contributions if c["has_hit"]) / max(total_files, 1)

    all_values = [v for c in contributions for v in c["hit_values"]]
    distinctiveness = len(set(all_values)) / max(len(all_values), 1)

    order_scores = [c["order_consistency"] for c in contributions]
    order_consistency = sum(order_scores) / max(len(order_scores), 1)

    name_scores = [c["name_relevance"] for c in contributions]
    name_relevance = sum(name_scores) / max(len(name_scores), 1)

    confidence = (0.35 * support + 0.35 * distinctiveness
                  + 0.20 * order_consistency + 0.10 * name_relevance)

    return {
        "support": support,
        "distinctiveness": distinctiveness,
        "order_consistency": order_consistency,
        "name_relevance": name_relevance,
        "confidence": confidence,
    }
```

## 6. API 设计

### 6.1 文件挖掘

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/files/mine` | 挖掘选中文件 `{ file_ids: int[] }` |
| POST | `/files/{id}/re-mine` | 重挖单文件 |
| GET | `/files/mining-status` | 查询版本下文件挖掘状态 `?ne_version_id=` |

### 6.2 候选管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/candidates` | 列表（支持 status, review_route, ne_version_id 过滤） |
| POST | `/candidates/{id}/accept` | 确认 → graph |
| POST | `/candidates/{id}/reject` | 拒绝 |
| POST | `/candidates/{id}/mark-non-graph` | 标记非图谱 `{ reason, reviewer }` |
| POST | `/candidates/{id}/revert` | 回退到 pending（graph/non_graph 适用） |

### 6.3 算法版本

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/algorithm-versions` | 当前全局算法版本 |
| POST | `/candidates/switch-algorithm` | 切换版本下候选的激活算法版本 |

### 6.4 图谱

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/graph-edges` | 列表 `?ne_version_id=` |

### 6.5 删除/弃用

- ~~POST `/candidates/generate`~~ — 被文件级挖掘替代
- ~~POST `/versions/{id}/batch-extract`~~ — 被文件级挖掘替代

## 7. 前端设计

### 7.1 页面布局

```
┌──────────────────────────────────────────────────────────────┐
│ 依赖挖掘 | 选择网元版本 [▼ dropdown]                           │
├────────────────────────┬─────────────────────────────────────┤
│ 文件列表               │ 候选池 / 图谱库 / 非图谱库            │
│                        │                                     │
│ ☐ script1.mml  已挖掘  │ [候选池] [图谱库] [非图谱库]  tab切换  │
│ ☑ script2.mml  未挖掘  │                                     │
│ ☑ script3.mml  未挖掘  │ ┌─ stats ──────────────────────┐    │
│ ☐ script4.mml  已挖掘  │ │ 总数  pending  graph  ...   │    │
│                        │ └──────────────────────────────┘    │
│ [挖掘选中] [重挖已选]  │                                     │
│                        │ ┌─ table ──────────────────────┐    │
│                        │ │ ref_cmd | ref_param | ...    │    │
│                        │ │ review_route | 操作          │    │
│                        │ └──────────────────────────────┘    │
└────────────────────────┴─────────────────────────────────────┘
```

### 7.2 候选池 tab

- 表格显示：ref_command, ref_param, def_command, def_param, confidence, review_route, status
- review_route 显示为标签：`auto`(绿) / `llm`(黄) / `manual`(红)
- 操作按钮根据 status 动态显示：
  - pending: 通过 / 拒绝 / 标记非图谱
  - graph: 回退
  - non_graph: 回退
  - rejected: 无操作（等待新证据激活）

### 7.3 图谱库 tab

- 显示所有 status='graph' 的候选及其 graph_edge
- 可查看所有 contribution（含不同算法版本）
- 可回退到 pending

### 7.4 非图谱库 tab

- 显示所有 status='non_graph' 的记录
- 显示标记原因、操作人、以及累积的 contribution 数量
- 可回退到 pending

## 8. 与原设计的关系

| 原设计章节 | 本文档处理 |
|-----------|-----------|
| §2 整体架构 | 保留三层漏斗，候选池改为增量汇总 |
| §3 算法流程 | 保留值匹配和评分算法，改为文件级执行 + 汇总 |
| §3.0 解析器 | 已完成，不变 |
| §4.1 候选状态机 | 用本文 §2.3（4 种主状态）+ §2.4（独立审核路由）替代 |
| §4.2 图谱边状态机 | 保留 active/revoked |
| §5 LLM 集成 | 不变，延后到第二期 |
| §6 开发路线 | 用本文重新定义 MVP |

## 9. MVP 范围

### 包含

- 文件选择 + 增量挖掘 + 重挖
- candidate_contribution 统一事实层
- 4 种主状态 + 独立 review_route 字段
- 算法版本字段 + 激活版本汇总隔离
- 图谱库 / 非图谱库 / 候选池 三层
- 回退操作
- 前端文件选择 + 候选审核界面

### 不包含（延后）

- LLM 集成（第二期，review_route='llm' 预留但不实现逻辑）
- 图谱变更时间线 UI（第二期）
- 版本冷启动（第三期）
- 已知边周期复核（第三期）
- 算法版本自动批量重挖（预留字段和切换接口，不实现自动触发）
