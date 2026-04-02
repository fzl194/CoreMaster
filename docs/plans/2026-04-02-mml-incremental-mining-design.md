# MML 命令依赖关系挖掘系统 — 增量挖掘设计

> 状态：草案
> 日期：2026-04-02
> 前序文档：`docs/plans/2026-04-01-mml-dependency-mining-design.md`
> 变更原因：管理员明确新目标为"按文件选择的增量式挖掘系统"，原"按版本全量"模型不再适用

## 1. 需求变化摘要

原设计：选择一个网元版本 → 全量提取所有脚本命令 → 全量生成候选
新需求：管理员手动选择若干文件 → 增量挖掘 → 候选池长期累积

| 维度 | 原设计 | 新需求 |
|------|--------|--------|
| 挖掘粒度 | 按版本全量 | 按文件增量 |
| 结果可替换 | 不支持 | 同文件重挖替换旧贡献 |
| 候选池 | 每次全量重算 | 长期汇总池，增量追加 |
| 状态模型 | pending / accepted / rejected | pending / graph / non_graph / rejected |
| 图谱证据累积 | 无 | 新文件匹配时证据追加到图谱边 |
| 非图谱库 | 无 | 知识级否定，与 reject 语义不同 |

## 2. 核心概念

### 2.1 四层实体

```
文件 (file_entry)           — 管理员选择的操作对象
  ↓ 提取
命令实例 (command_instance) — 文件内的解析结果
  ↓ 生成
候选贡献 (candidate_contribution) — 文件对候选池的贡献
  ↓ 汇总
候选 (dependency_candidate) — 长期汇总池中的待审核项
  ↓ 审核
图谱边 (graph_edge)         — 已确认的依赖关系
非图谱记录                   — 已确认的非依赖关系
```

### 2.2 候选池状态机

```
                          ┌─────────────────────────────────┐
                          │        候选池 (pending)           │
                          │  pending / auto_passed /         │
                          │  llm_review / man_review         │
                          └──────┬──────────┬───────────────┘
                                 │          │
                     accept      │   mark   │  reject
                    (→ graph)    │ non_graph │  (可回退)
                                 │          │
                                 ▼          ▼
                          ┌─────────┐  ┌──────────┐
                          │  graph  │  │non_graph │
                          │(图谱库) │  │(非图谱库) │
                          └────┬────┘  └────┬─────┘
                               │            │
                          revert│       revert│
                               ▼            ▼
                          回到候选池    回到候选池

非法转换: non_graph → graph（必须先 revert 到 pending 再 accept）
```

**状态定义**：

| 状态 | 含义 | 层级 |
|------|------|------|
| `pending` | 刚生成，未分配审核路径 | 候选池 |
| `auto_passed` | 高置信度，自动通过初筛 | 候选池 |
| `llm_review` | 等待 LLM 审核（第二期） | 候选池 |
| `man_review` | 等待人工审核 | 候选池 |
| `graph` | 已确认入图谱 | 图谱库 |
| `non_graph` | 专家确认绝不可能是图谱边 | 非图谱库 |
| `rejected` | 本次不通过，新证据可再进池 | — |

**关键规则**：
- `rejected` 不是终态：新文件挖掘产生新证据时，rejected 候选可回到 pending
- `non_graph` 是知识级否定：比 reject 语义更强，表示专家判断
- `non_graph → graph` 必须先 revert 到 pending，不能直接转换
- `graph → pending`（revert）时删除关联 graph_edge

### 2.3 文件级贡献模型

每个文件对候选池的贡献独立可追踪：

```
文件 A 贡献 → 候选 X (evidence_A, scores_A)
文件 B 贡献 → 候选 X (evidence_B, scores_B)
                         ↓ 汇总
                候选 X 的最终分数 = aggregate(evidence_A + evidence_B)
```

重挖文件 A 时：
1. 删除 contribution_A
2. 插入 contribution_A'
3. 重算候选 X 分数 = aggregate(contribution_A' + evidence_B)

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

**candidate_contribution** — 文件对候选的贡献

```sql
CREATE TABLE IF NOT EXISTS candidate_contribution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    file_entry_id INTEGER NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    scores_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES dependency_candidate(id),
    FOREIGN KEY (file_entry_id) REFERENCES file_entry(id),
    UNIQUE(candidate_id, file_entry_id)
);
```

### 3.2 修改表

**dependency_candidate** — 新增字段和状态

```sql
-- 新增列
ALTER TABLE dependency_candidate ADD COLUMN non_graph_reason TEXT;
ALTER TABLE dependency_candidate ADD COLUMN non_graph_reviewer TEXT;

-- status 枚举扩展为:
--   pending | auto_passed | llm_review | man_review
--   | graph | non_graph | rejected
```

### 3.3 保留表（不变）

- `command_instance` — 命令实例
- `graph_edge` — 图谱边
- `graph_changelog` — 变更日志

### 3.4 删除/不再使用

- `batch-extract` 端点 — 被"文件级挖掘"取代
- 版本级全量 generate — 被增量贡献模型取代

## 4. 核心操作

### 4.1 挖掘选中文件

```
输入: file_ids[] (同一 ne_version 下的文件列表)

FOR EACH file_id IN file_ids:
    1. 解析文件 → command_instance[]
    2. 生成该文件的本地候选:
       - 基于该文件的 command_instance 运行 candidate_engine
       - 得到 local_candidates[] (每个含 key + evidence + scores)
    3. 更新 file_mining_record (mined=1, command_count=N)
    4. FOR EACH local_candidate:
        a. 查找 ne_version 下同 key 的 graph_edge → 若存在:
           - 追加证据到 graph_edge.evidence_json
           - 不创建候选
           - CONTINUE
        b. 查找 ne_version 下同 key 的 dependency_candidate:
           - 若 status='non_graph' → 跳过（不挑战专家结论）
           - 若 status='graph' → 已被 4a 处理
           - 若 status='pending'|'auto_passed'|'llm_review'|'man_review'|'rejected':
             * 若已有该文件的 contribution → 替换
             * 若无 → 新增 contribution
             * 重算候选汇总分数
             * 若 status='rejected' → 回到 pending（新证据激活）
        c. 若不存在 → 创建新候选 (status='pending' 或按置信度分层)
           + 创建 contribution
```

### 4.2 重挖单文件

```
输入: file_entry_id

1. 删除该文件所有 candidate_contribution
2. 找到受影响的候选，重算分数
3. 删除零贡献候选（无任何文件支撑的候选）
4. 按 4.1 流程重新挖掘该文件
```

### 4.3 Accept 候选 → graph

```
1. 创建 graph_edge 记录
2. 更新 candidate: status='graph', graph_edge_id=新边ID
3. 写 changelog
```

### 4.4 标记 non_graph

```
1. 更新 candidate: status='non_graph', non_graph_reason=?, non_graph_reviewer=?
2. 写 changelog
```

### 4.5 Reject 候选

```
1. 更新 candidate: status='rejected'
2. 写 changelog
注: rejected 不是终态，新文件挖掘可将其激活回 pending
```

### 4.6 Revert graph → pending

```
1. 删除关联的 graph_edge
2. 更新 candidate: status='pending', graph_edge_id=NULL
3. 写 changelog
```

### 4.7 Revert non_graph → pending

```
1. 更新 candidate: status='pending', non_graph_reason=NULL, non_graph_reviewer=NULL
2. 写 changelog
```

## 5. 分数重算

当文件贡献发生变化时，需要重算候选的汇总分数。

### 5.1 汇总策略

```python
def recalculate_scores(contributions: list[dict]) -> dict:
    """从文件级贡献重算候选汇总分数。"""
    total_files = len(contributions)

    # 支持度：有匹配的文件数 / 总文件数
    support = sum(1 for c in contributions if c["has_hit"]) / max(total_files, 1)

    # 区分度：唯一值数 / 总命中数
    all_values = [v for c in contributions for v in c["hit_values"]]
    distinctiveness = len(set(all_values)) / max(len(all_values), 1)

    # 顺序一致性：定义方在前的比例
    order_scores = [c["order_consistency"] for c in contributions]
    order_consistency = sum(order_scores) / max(len(order_scores), 1)

    # 名称相关度：取均值
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

### 5.2 证据合并

```python
def merge_evidence(contributions: list[dict]) -> dict:
    """合并所有文件的证据。"""
    hit_count = sum(c["hit_count"] for c in contributions)
    hit_values = list(set(v for c in contributions for v in c["hit_values"]))
    sample_scripts = []
    for c in sorted(contributions, key=lambda x: x["confidence"], reverse=True):
        sample_scripts.extend(c["sample_scripts"][:3])
        if len(sample_scripts) >= 5:
            break

    return {
        "hit_count": hit_count,
        "total_scripts": len(contributions),
        "hit_values": hit_values,
        "sample_scripts": sample_scripts[:5],
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
| GET | `/candidates` | 列表（支持 status, ne_version_id 过滤） |
| POST | `/candidates/{id}/accept` | 确认 → graph |
| POST | `/candidates/{id}/reject` | 拒绝 |
| POST | `/candidates/{id}/mark-non-graph` | 标记非图谱 `{ reason, reviewer }` |
| POST | `/candidates/{id}/revert` | 回退到 pending（graph/non_graph 适用） |

### 6.3 图谱

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/graph-edges` | 列表 `?ne_version_id=` |

### 6.4 删除/弃用

- ~~POST `/candidates/generate`~~ — 被文件级挖掘替代
- ~~POST `/versions/{id}/batch-extract`~~ — 被文件级挖掘替代
- ~~POST `/scripts/{id}/extract-commands`~~ — 被整合进挖掘流程（仍可保留作为调试接口）

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
│                        │ │         | 操作: 通过/拒绝/.. │    │
│                        │ └──────────────────────────────┘    │
└────────────────────────┴─────────────────────────────────────┘
```

### 7.2 文件列表功能

- 显示选中版本下的所有脚本文件
- 复选框选择要挖掘的文件
- 显示挖掘状态：已挖掘 / 未挖掘
- 命令数量（已挖掘时显示）
- "挖掘选中" 按钮 — 触发增量挖掘
- "重新挖掘" 按钮 — 对已挖掘文件重挖

### 7.3 候选池 tab

- 与现有表格类似，增加状态筛选
- 操作按钮根据状态动态显示：
  - pending: 通过 / 拒绝 / 标记非图谱
  - graph: 回退
  - non_graph: 回退
  - rejected: 无操作（等待新证据激活）

### 7.4 图谱库 tab

- 显示所有 status='graph' 的候选及其 graph_edge
- 可查看证据详情
- 可回退到 pending

### 7.5 非图谱库 tab

- 显示所有 status='non_graph' 的记录
- 显示标记原因和操作人
- 可回退到 pending

## 8. 与原设计的关系

| 原设计章节 | 本文档处理 |
|-----------|-----------|
| §2 整体架构 | 保留三层漏斗，候选池改为增量汇总 |
| §3 算法流程 | 保留值匹配和评分算法，改为文件级执行 + 汇总 |
| §3.0 解析器 | 已完成，不变 |
| §4.1 候选状态机 | 用本文 §2.2 替代 |
| §4.2 图谱边状态机 | 保留 active/revoked |
| §5 LLM 集成 | 不变，延后到第二期 |
| §6 开发路线 | 用本文重新定义 MVP |

## 9. MVP 范围

### 包含

- 文件选择 + 增量挖掘 + 重挖
- candidate_contribution 贡献层
- 候选池 + 图谱库 + 非图谱库 三层状态
- 图谱边证据累积
- 回退操作
- 前端文件选择 + 候选审核界面

### 不包含（延后）

- LLM 集成（第二期）
- 图谱变更时间线 UI（第二期）
- 版本冷启动（第三期）
- 已知边周期复核（第三期）
- 算法版本自动重挖（预留字段，不实现逻辑）
