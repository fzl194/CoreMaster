# 图谱挖掘体系演进设计

> 状态：已批准（含审查修订）
> 日期：2026-04-03
> 前序任务：`dep-mining-mvp-001`（已闭环归档）
> 任务 ID：`graph-mining-evolution-001`
> 修订说明：
> - v1：初始版本，经管理员逐节审核通过
> - v2：根据 Codex 审查补齐 3 项设计缺口（文件状态模型、跨插件生命周期、增量重挖终态保护）

## 1. 背景与目标

`dep-mining-mvp-001` 闭环后，图谱挖掘功能已有基本的文件级增量挖掘、候选池管理、图谱/非图谱库功能。但 MVP 存在以下限制：

- 挖掘逻辑耦合在 `mml_manager` 插件中，无法独立演进
- `POST /files/mine` 同步阻塞，前端卡住等待
- 无通用任务框架，无法复用队列能力
- LLM 仅为标签占位，无实际调用能力
- 评估逻辑不可扩展，无法新增评分维度或铁律规则

本设计的目标是将图谱挖掘体系从 MVP 演进为正式框架，重点解决：

1. **插件独立化**：graph_mining 从 mml_manager 完全剥离
2. **异步任务队列**：core 层通用任务框架，支持文件级异步挖掘
3. **可扩展评估管线**：铁律过滤 + 代码软打分 + LLM 评估的分层管线
4. **LLM 网关**：独立插件，作为通用 LLM 调用基础设施
5. **前端独立页面**：挖掘管理和候选审核两个主 Tab

## 2. 已确认的设计决策

| 决策项 | 结论 |
|--------|------|
| 任务框架 | core 层通用框架，graph_mining 作为第一个消费者 |
| 插件边界 | graph_mining 完全独立物理插件 |
| 数据迁移 | 删除现有测试数据，从零开始 |
| LLM Gateway | 独立插件，第一阶段只做基础调用能力 |
| 审核原则 | 物理打分保留，人工始终终审，LLM 为建议角色 |
| 评估管线 | 铁律过滤 → 代码软打分 → 路由分流 → LLM 评估（可选）→ 人工终审 |
| 前端通信 | 轮询模式（2s 间隔查询 job 状态） |
| 网元版本选择 | 放在挖掘管理 tab 内部 |

## 3. 整体架构

### 3.1 插件布局

```
backend/
├── core/
│   ├── services/          # 现有：database, parser, registry
│   ├── plugin/            # 现有：loader, context
│   └── jobs/              # 新增：通用任务框架
│       ├── models.py      # job / job_item 数据模型 + 状态枚举
│       ├── service.py     # JobService：创建/查询/取消 job
│       └── worker.py      # JobWorker：单 worker 循环，从队列取 job 执行
├── plugins/
│   ├── mml_manager/       # 瘦身：只保留文件管理 + 命令提取
│   ├── graph_mining/      # 新增：图谱挖掘独立插件
│   │   ├── plugin.toml
│   │   ├── main.py        # 路由注册 + 初始化
│   │   ├── routers/       # 按功能拆分的路由模块
│   │   │   ├── mining.py      # 挖掘相关 API
│   │   │   ├── candidates.py  # 候选管理 API
│   │   │   └── graph.py       # 图谱操作 API
│   │   ├── engine/        # 评估管线
│   │   │   ├── pipeline.py     # 管线编排
│   │   │   ├── hard_rules.py   # 铁律过滤器（可扩展）
│   │   │   ├── scorers.py      # 代码软打分器（可扩展）
│   │   │   └── scorer_base.py  # 评分器基类/协议
│   │   ├── workers/       # Job 消费者
│   │   │   └── mining_worker.py
│   │   └── models.py      # 挖掘相关的数据库表管理
│   ├── llm_gateway/       # 新增（第二阶段）：LLM 网关独立插件
│   │   ├── plugin.toml
│   │   ├── main.py
│   │   ├── service.py     # LLM 调用封装
│   │   └── models.py      # 调用记录表
│   └── db_manager/        # 不变
```

### 3.2 依赖关系

```
graph_mining → core.services (database, parser)
graph_mining → core.jobs (任务框架)
graph_mining → core.events (订阅文件生命周期事件，见 §6.5)
graph_mining → llm_gateway (通过 ServiceRegistry 获取 LLM 服务)

llm_gateway → core.services (database)
llm_gateway 不依赖 graph_mining

mml_manager → core.services (database, parser)
mml_manager → core.events (触发文件生命周期事件)
mml_manager 不依赖 graph_mining
```

graph_mining 通过共享数据库只读访问 mml_manager 的 `file_entry`、`command_instance`、`ne_version` 表，不走 HTTP API。文件删除/替换等生命周期事件通过 core.events 通知 graph_mining 执行级联清理（见 §6.5）。

## 4. 通用任务框架（core/jobs）

### 4.1 约束（第一阶段）

- 单 worker 进程，全局一次只执行一个 job
- job_item 之间串行执行
- 软取消：cancel 标记在 job 和 job_item 上，worker 在 item 间隙检查
- 不做优先级、不做分布式、不做重试

### 4.2 数据模型

```sql
CREATE TABLE job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,           -- 'mining' | 'llm_review' | 未来其他
    status TEXT NOT NULL DEFAULT 'queued',
    params_json TEXT NOT NULL DEFAULT '{}',
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE job_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,       -- 业务标识（如 file_entry_id）
    status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT,
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job(id)
);
```

### 4.3 状态枚举

```python
class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class JobItemStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
```

### 4.4 服务接口

```python
class JobService:
    async def create_job(self, type: str, params: dict, item_keys: list[str]) -> int: ...
    async def get_job(self, job_id: int) -> dict | None: ...
    async def list_jobs(self, type: str | None = None, limit: int = 20) -> list[dict]: ...
    async def cancel_job(self, job_id: int) -> bool: ...
    async def update_job_status(self, job_id: int, status: str, **kwargs) -> None: ...
    async def update_item_status(self, item_id: int, status: str, **kwargs) -> None: ...
    async def get_pending_jobs(self) -> list[dict]: ...

class JobWorker:
    """后台 worker 循环。从队列取 job，逐 item 执行。"""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def register_handler(self, job_type: str, handler: Callable) -> None: ...
```

## 5. 评估管线

### 5.1 候选完整生命周期

```
文件挖掘 Job (mining_job)
    ↓ 逐文件处理
    ↓ 解析命令 → 生成原始候选对（ref_cmd, ref_param, def_cmd, def_param）
    ↓
铁律过滤 (HardRulePipeline)
    ├─ 不满足 → 直接丢弃（不进库）
    └─ 通过 ↓
代码软打分 (ScorerPipeline)
    ↓ 输出：多维分数 + 综合分数
    ↓ 写入 candidate_contribution（事实层）
    ↓ 汇总到 dependency_candidate
    ↓ 按 review_route 分流
    ├─ auto:     直接标记 ready_for_review
    ├─ llm:      创建 llm_review_job → 触发 LLM 评估（第二阶段）
    └─ manual:   直接标记 ready_for_review
    ↓
LLM 评估 (llm_review_job) ← 仅 llm 路由（第二阶段）
    ↓ LLM 返回建议 + 置信度
    ↓ 更新候选的 llm_assessment_json
    ↓ 标记 ready_for_review
    ↓
人工审核
    ├─ → graph（入图谱）
    ├─ → non_graph（明确非图谱）
    └─ → rejected（拒绝，新证据可激活）
```

### 5.2 铁律过滤器（可扩展）

```python
class HardRule(Protocol):
    """铁律基类。返回 False 表示候选被直接淘汰。"""
    def check(self, candidate: RawCandidate, context: MiningContext) -> bool: ...

# 第一阶段内置规则
class SameParameterRule(HardRule):
    """ref_param 和 def_param 不能是同一个参数"""

class SelfReferenceRule(HardRule):
    """ref_command 和 def_command + 参数不能完全相同"""

class MinimumCommandDistanceRule(HardRule):
    """两条命令在文件中的行距不能太远"""
```

扩展方式：graph_mining 插件启动时从配置或注册表加载 HardRule 列表，新增规则只需实现 HardRule 协议。

### 5.3 代码软打分器（可扩展）

```python
class Scorer(Protocol):
    """评分器基类。每个评分器返回 0-1 的分数。"""
    def score(self, candidate: RawCandidate, context: MiningContext) -> float: ...
    @property
    def name(self) -> str: ...
    @property
    def weight(self) -> float: ...

# 第一阶段内置评分器（从现有 candidate_engine 迁移）
class ValueMatchScorer(Scorer):      # 参数值匹配（原 support 维度）
class DistinctivenessScorer(Scorer): # 值的唯一性（原 distinctiveness 维度）
class OrderConsistencyScorer(Scorer): # 命令顺序一致性
class NameSimilarityScorer(Scorer):   # 参数名相似度
```

扩展方式：Scorer 列表可配置，权重可调。新增评分维度只需实现 Scorer 协议。

### 5.4 LLM 核查规则（可扩展，第二阶段）

```python
class LLMReviewRule(Protocol):
    """LLM 评估规则。生成 prompt + 解析结果。"""
    def build_prompt(self, candidate: DependencyCandidate, contributions: list) -> str: ...
    def parse_response(self, llm_response: str) -> LLMAssessment: ...

# 第二阶段内置规则
class DependencyVerificationRule(LLMReviewRule):
    """给定候选及其证据，判断是否为真实依赖关系"""
```

扩展方式：llm_gateway 提供 prompt 模板注册表，graph_mining 注册自己的核查规则。

## 6. 数据模型

### 6.1 候选状态机（6 态）

```
                     ┌───────────┐
                     │  pending  │ ← 挖掘产出，等分流
                     └───┬───┬───┘
                         │   │
        auto/manual      │   │ llm route
                         │   │
                         │   ▼
                         │ ┌──────────────┐
                         │ │llm_reviewing │ ← LLM job 执行中
                         │ └──────┬───────┘
                         │        │ LLM 完成
                         ▼        ▼
                    ┌─────────────────┐
                    │ ready_for_review│ ← 人工可审
                    └──┬───┬──┬───────┘
                       │   │  │
            accept     │   │  │ reject
            (→ graph)  │   │  │
            mark       │   │  │
          non_graph    │   │  │
                       ▼   ▼  ▼
                 ┌──────┐┌──────────┐┌──────────┐
                 │graph ││non_graph ││ rejected │
                 └──┬───┘└────┬─────┘└──────────┘
                    │         │         ↑
               revert    revert       │
                    ▼         ▼       │
                 回到 pending ────────┘
                   (新证据激活)
```

非法转换：non_graph → graph（必须先 revert 到 pending 再 accept）

### 6.2 表归属

**core/jobs 管理（通用）：**
- `job` — 任务实例
- `job_item` — 任务子项

**graph_mining 管理（从 mml_manager 迁移 + 演进）：**
- `dependency_candidate` — 候选记录（status 扩展为 6 种，新增 `llm_assessment_json`）
- `candidate_contribution` — 文件级贡献（不变）
- `file_mining_record` — 文件挖掘状态（演进，见 §6.4）
- `graph_edge` — 图谱边（不变）
- `graph_changelog` — 变更日志（不变）

**mml_manager 管理（保留）：**
- `ne_version` — 网元版本
- `file_entry` — 文件条目
- `command_instance` — 命令实例

**llm_gateway 管理（新增，第二阶段）：**
- `llm_call_log` — LLM 调用记录

### 6.3 dependency_candidate 字段变更

```sql
-- 新增列
ALTER TABLE dependency_candidate ADD COLUMN llm_assessment_json TEXT;
-- 存储 LLM 评估结果：{"recommendation": "accept"/"reject", "confidence": 0.91, "reasoning": "..."}

-- status 枚举扩展为 6 种：
--   pending | llm_reviewing | ready_for_review | graph | non_graph | rejected
```

### 6.4 文件状态模型（审查修订）

`file_mining_record` 需要演进以承载异步任务场景下的文件级状态。新增 `last_job_id` 和 `last_error` 字段：

```sql
-- file_mining_record 演进
ALTER TABLE file_mining_record ADD COLUMN last_job_id INTEGER;
ALTER TABLE file_mining_record ADD COLUMN last_error TEXT;
-- last_job_id: 关联最近一次处理该文件的 job（FK job.id）
-- last_error: 最近一次失败的错误信息
```

**文件状态派生规则**（API 层组合查询，不存冗余状态）：

| 文件状态 | 派生条件 |
|----------|----------|
| 未挖掘 | `file_mining_record` 不存在 |
| 排队中 | 存在 `job_item` 且 `status='pending'`，通过 `item_key=file_entry_id` 关联 |
| 挖掘中 | 存在 `job_item` 且 `status='running'` |
| 已完成 | `file_mining_record.mined=1` 且无活跃 `job_item` |
| 失败 | 最近 `job_item` 的 `status='failed'`，且 `file_mining_record.mined=0` |

**`/files` API 返回契约**：

```json
{
  "file_id": 42,
  "name": "cfg_apn_03.mml",
  "mining_status": "completed",  // unmined | queued | running | completed | failed
  "last_job_id": 3,
  "last_error": null,
  "mined_at": "2026-04-03T20:30:00",
  "command_count": 15
}
```

### 6.5 跨插件文件生命周期事件（审查修订）

**问题**：文件删除、内容替换、版本解绑等操作发生在 `mml_manager`，但关联的 `candidate_contribution`、`dependency_candidate`、`graph_edge` 数据归 `graph_mining` 管理。"只读依赖"不足以保证一致性。

**方案：core 层轻量事件 hook 机制**

```python
# core/plugin/events.py
class PluginEventBus:
    """轻量级插件间事件通知。同步调用，不跨进程。"""

    def on(self, event_type: str, handler: Callable) -> None:
        """注册事件处理器。"""
        ...

    async def emit(self, event_type: str, payload: dict) -> None:
        """触发事件，按注册顺序调用所有处理器。"""
        ...
```

**事件类型与数据流**：

| 事件 | 触发方 | payload | 订阅方处理 |
|------|--------|---------|-----------|
| `file.deleted` | mml_manager | `{file_entry_id, ne_version_id}` | graph_mining 删除该文件的 contribution、重算候选、清理零贡献候选 |
| `file.content_replaced` | mml_manager | `{file_entry_id, ne_version_id}` | graph_mining 删除旧 contribution、触发该文件在 graph_mining 层面的重算 |
| `ne_version.deleted` | mml_manager | `{ne_version_id}` | graph_mining 级联删除该版本所有挖掘数据 |

**依赖方向**：mml_manager 依赖 core.events（无方向变化）。graph_mining 依赖 core.events（注册 handler）。mml_manager 不依赖 graph_mining。

**第一阶段实现约束**：
- 事件 handler 同步执行（在 mml_manager 的请求处理上下文中）
- 如果 handler 失败，记录错误但不阻塞 mml_manager 的主操作
- 不做事件持久化、不做异步队列、不做重试

### 6.6 增量重挖与人工终态保护规则（审查修订）

**核心原则：新证据只更新事实层，不自动覆盖人工决策。**

当增量挖掘产出的候选与已有 `dependency_candidate` 匹配时，按当前状态分支处理：

| 当前状态 | 新证据到来时的行为 |
|----------|-------------------|
| `pending` | 更新 contribution，重算汇总分，可能更新 review_route |
| `llm_reviewing` | 更新 contribution（事实层），不中断 LLM 评估流程。汇总分在 LLM 完成后重算 |
| `ready_for_review` | 更新 contribution，重算汇总分。如果 LLM 曾评估过，标记 `llm_assessment_json` 为 stale（供人工参考） |
| `graph` | 写入 contribution（事实层保留），汇总分更新供查看。**状态不变**，`graph_edge` 不动 |
| `non_graph` | 写入 contribution（作为追溯依据保留），汇总分更新。**状态不变** |
| `rejected` | 写入 contribution，重算汇总分。**状态自动激活回 `pending`**（新证据可再进池），按新置信度重设 `review_route` |

**铁律**：
- `graph` / `non_graph` 是人工终态，新证据不自动改变状态
- `rejected` 可被新证据激活，这是唯一会被自动改变的人工终态
- `graph` / `non_graph` 即使零贡献也永不自动删除候选记录
- 若需将 `graph` 改为 `non_graph`，必须先 revert 到 `pending`，再走正常审核流程

**测试要求**（第一阶段必须覆盖）：
1. 已 `graph` 候选在重挖后状态不变、贡献更新
2. 已 `non_graph` 候选在新证据后状态不变、贡献记录
3. 已 `rejected` 候选在新证据后自动激活回 `pending`
4. 零贡献的 `graph` / `non_graph` 候选不被自动删除

## 7. API 设计

### 7.1 通用任务 API（core/jobs 服务提供）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs` | 列出 jobs（支持 type、status 过滤） |
| GET | `/api/jobs/{id}` | 查询 job 状态、进度、items |
| POST | `/api/jobs/{id}/cancel` | 取消 job |

### 7.2 图谱挖掘 API（graph_mining 插件）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/plugins/graph_mining/mining/start` | 创建挖掘 job `{ file_ids: int[] }` |
| GET | `/api/plugins/graph_mining/files` | 查询版本下文件列表及挖掘状态 `?ne_version_id=` |
| GET | `/api/plugins/graph_mining/candidates` | 候选列表（支持 status, review_route, ne_version_id 过滤） |
| POST | `/api/plugins/graph_mining/candidates/{id}/accept` | 确认 → graph |
| POST | `/api/plugins/graph_mining/candidates/{id}/reject` | 拒绝 |
| POST | `/api/plugins/graph_mining/candidates/{id}/mark-non-graph` | 标记非图谱 |
| POST | `/api/plugins/graph_mining/candidates/{id}/revert` | 回退到 pending |
| POST | `/api/plugins/graph_mining/candidates/{id}/request-llm` | 手动请求 LLM 评估 |
| POST | `/api/plugins/graph_mining/candidates/batch-request-llm` | 批量请求 LLM |
| GET | `/api/plugins/graph_mining/graph-edges` | 图谱边列表 |
| GET | `/api/plugins/graph_mining/algorithm-versions` | 算法版本信息 |
| POST | `/api/plugins/graph_mining/candidates/switch-algorithm` | 切换激活算法版本 |

### 7.3 LLM 网关 API（第二阶段）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/plugins/llm_gateway/call` | 通用 LLM 调用 |
| GET | `/api/plugins/llm_gateway/config` | LLM 配置 |
| PUT | `/api/plugins/llm_gateway/config` | 更新配置 |
| GET | `/api/plugins/llm_gateway/call-log` | 调用记录 |

## 8. 前端设计

### 8.1 页面结构

独立插件页面，两个顶层 Tab 切换：

- **挖掘管理**：关注"文件 → 挖掘 → 产出候选"的生产过程
- **候选审核**：关注"候选 → 评估 → 人工决策"的审核过程

右上角任务中心浮层显示所有活跃 job，两个 Tab 都能看到。

### 8.2 挖掘管理 Tab

```
┌────────────────────────┬─────────────────────────────────────┐
│  待挖掘文件             │  挖掘任务队列                       │
│                        │                                     │
│  网元版本: [▼ 选择]     │  ┌─ #3 进行中 ──────────────────┐  │
│                        │  │ ██████████░░░░ 3/7 文件      │  │
│  ☐ cfg_bgp_01.mml  ○  │  │ ⏳ cfg_apn_04.mml 处理中...  │  │
│  ☐ cfg_vpn_02.mml  ○  │  │ ✓ cfg_apn_03.mml 已完成      │  │
│  ☑ cfg_apn_03.mml  ○  │  │ [取消任务]                     │  │
│  ☑ cfg_apn_04.mml  ⏳ │  └────────────────────────────────┘  │
│  ☐ cfg_qos_05.mml  ✓ │                                     │
│                        │  ┌─ 历史任务 ─────────────────────┐ │
│  已选 2 个文件         │  │ #2 已完成 5/5 产出 23 条候选   │ │
│  [开始挖掘 ▶]          │  │ #1 已完成 4/4 产出 18 条候选   │ │
│                        │  └────────────────────────────────┘  │
└────────────────────────┴─────────────────────────────────────┘

文件状态: ○ 未挖掘  ⏳ 排队/挖掘中  ✓ 已完成  ✗ 失败
```

### 8.3 候选审核 Tab

```
┌──────────────────────────────────────────────────────────────┐
│  ┌─ 阶段统计卡片 ─────────────────────────────────────────┐  │
│  │  LLM 评估中: 5  │  可审核: 12  │  已处理: 28  │ 图谱: 156 │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                              │
│  [可审核(12)] [LLM评估中(5)] [图谱库(156)] [非图谱库(8)]      │
│                                                              │
│  ┌─ 筛选栏 ───────────────────────────────────────────────┐  │
│  │ Route: [全部▼]  置信度: [全部▼]  来源文件: [全部▼]      │  │
│  │ [批量入图谱] [批量请求LLM]                              │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ 候选卡片列表 ─────────────────────────────────────────┐  │
│  │                                                        │  │
│  │  ADD EPGroup.APN → ADD APN.APNNAME                    │  │
│  │  ████████░░ 置信度 0.82  │  auto  │ 可审核             │  │
│  │  来源: cfg_apn_03, cfg_vpn_02                         │  │
│  │  [入图谱] [非图谱] [拒绝] [▶ 请求LLM]                  │  │
│  │                                                        │  │
│  │  ADD VPN.VPNNAME → ADD EPGroup.VPNNAME                │  │
│  │  ██████░░░░ 置信度 0.61  │  llm   │ LLM 评估中        │  │
│  │  [查看LLM进度]                                          │  │
│  │                                                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ 详情抽屉（点击卡片展开）──────────────────────────────┐  │
│  │  铁律: ✓ 非自引用 ✓ 最小距离 ✓ 参数类型匹配            │  │
│  │  代码打分: support=0.80  distinct=0.70                 │  │
│  │           order=0.90    name=0.60                      │  │
│  │  LLM: "高度可信的参数依赖" (建议通过, 0.91)            │  │
│  │  证据: [文件A 详情▼] [文件C 详情▼]                     │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 8.4 前端技术方案

- 框架：Vue 3 + Naive UI（沿用现有技术栈）
- 状态管理：组件内 `ref`/`reactive`，无需 Pinia
- 轮询策略：创建 job 后每 2 秒轮询 `GET /api/jobs/{id}`，完成后停止
- 页面路由：`/plugins/graph-mining`

## 9. 分阶段实施顺序

### 第一阶段：基础设施 + 插件拆分

| 步骤 | 内容 | 预估粒度 |
|------|------|----------|
| 1 | core/jobs 通用任务框架（模型 + 服务 + worker） | 基础设施 |
| 1b | core/events 轻量事件 hook 机制 | 基础设施 |
| 2 | graph_mining 独立插件骨架（plugin.toml + 路由注册 + 表建删 + file_mining_record 演进） | 骨架搭建 |
| 3 | 从 mml_manager 迁移挖掘相关代码到 graph_mining | 代码迁移 |
| 4 | 瘦身 mml_manager（删除已迁移的挖掘代码，加入事件触发点） | 清理 |
| 5 | 评估管线重构（hard_rules + scorers + pipeline） | 管线重构 |
| 6 | 挖掘 worker：接入 core/jobs 框架 + 增量重挖终态保护 | worker 接入 |
| 6b | graph_mining 注册文件生命周期事件 handler（清理/重算） | 跨插件集成 |
| 7 | 前端：挖掘管理 tab（含文件状态派生查询） | 前端开发 |
| 8 | 前端：候选审核 tab | 前端开发 |
| 8b | §11 测试用例全覆盖 | 测试 |

### 第二阶段：LLM 集成

| 步骤 | 内容 |
|------|------|
| 9 | llm_gateway 独立插件（基础调用 + 调用记录） |
| 10 | LLM 评估 worker（llm_review_job） |
| 11 | 候选状态增加 `llm_reviewing` → `ready_for_review` |
| 12 | 前端：LLM 评估中 tab + 详情面板 LLM 结果展示 |

### 第三阶段：扩展能力

| 内容 | 说明 |
|------|------|
| 算法版本切换 | 已有字段，完善切换逻辑和批量重挖 |
| 批量 LLM 规则演进 | 新增 LLMReviewRule 实现 |
| 新评分器 | 新增 Scorer 实现 |
| 多 worker | core/jobs 扩展支持并发 |
| 任务优先级 | core/jobs 扩展 |

## 10. 主要风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 通用任务框架过度设计 | 第一阶段耗时增加 | 严格限制：单 worker、无优先级、无重试 |
| 评估管线接口不稳定 | 已有评分器需要重写 | 第一阶段先把现有 candidate_engine 逻辑原样搬入管线，再逐步重构 |
| graph_mining 读取 mml_manager 表的耦合 | 跨插件数据依赖 | 共享数据库 + 文档化只读依赖 + 事件 hook 通知（§6.5） |
| 前端改动范围大 | 开发周期长 | 分两个 tab 独立开发，挖掘管理优先 |
| 文件删除后悬挂贡献 | 数据一致性 | 核心事件 hook 机制（§6.5），handler 失败记错误不阻塞 |
| 增量重挖覆盖人工终态 | 人工决策被自动回退 | 严格终态保护规则（§6.6），回归测试覆盖 |

## 11. 第一阶段测试要求

### 11.1 必须通过的测试

1. **job 取消后状态一致性**：cancel job → job_item 全部 skipped 或 completed/failed，文件状态正确回退
2. **文件删除触发 graph_mining 清理**：删除文件 → contribution 被清理 → 受影响候选分数重算
3. **已审核候选在增量重挖后保持终态**：
   - `graph` 候选重挖后状态不变，贡献更新
   - `non_graph` 候选新证据后状态不变
   - `rejected` 候选新证据后激活回 `pending`
4. **零贡献终态候选不被删除**：`graph`/`non_graph` 零贡献时记录保留
5. **文件状态派生正确**：前端 `/files` API 返回的状态与 job_item + file_mining_record 组合一致

### 11.2 前端联调验收标准

- 文件列表状态与任务中心进度始终一致
- 同一文件不会在文件列表显示"未挖掘"同时任务中心显示"已完成"
- 取消任务后，已处理文件保持"已完成"，未处理文件回退到"未挖掘"

## 12. 仍需讨论的问题

1. **铁律规则的具体定义**：第一阶段需要哪些铁律？当前只列了 3 个示例（非自引用、非同参数、最小行距），是否需要更多？
2. **LLM 评估的 prompt 模板**：第二阶段开始前需要设计具体的 prompt 结构和输出解析格式。
3. **LLM Gateway 的模型选择**：使用哪个 LLM 服务商/模型？是否需要支持多个模型切换？
4. **评分器权重的可配置性**：权重是硬编码还是支持管理员在前端调整？第一阶段建议硬编码。
5. **候选详情中的文件证据展示**：是否需要高亮命中的参数值？还是只显示命令行号即可？
