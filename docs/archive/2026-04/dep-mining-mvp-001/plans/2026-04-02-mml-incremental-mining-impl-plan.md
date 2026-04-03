# 增量挖掘 MVP 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将现有"按版本全量"的依赖挖掘系统重构为"按文件增量"挖掘系统，支持贡献层、三层状态模型、算法版本隔离。

**Architecture:** 在现有 `mml_manager` 插件内重构。新增 `file_mining_record` 和 `candidate_contribution` 两张表；重构 `candidate_engine.py` 支持单文件生成 + 贡献汇总；重写挖掘流程 API；前端增加文件选择器 + 三 tab 布局。

**Tech Stack:** Python/FastAPI (后端), Vue 3 + Naive UI (前端), SQLite, pytest + httpx (测试)

**设计文档:** `docs/plans/2026-04-02-mml-incremental-mining-design.md` (v3, Codex 已审通过)

**关键约束（来自 Codex 审查）:**
- status 仅 4 种: pending / graph / non_graph / rejected
- review_route 独立字段，不混入 status
- candidate_contribution 是统一事实层，graph/non_graph 命中也要记录
- active_algorithm_version 控制汇总口径
- graph / non_graph 永不因零贡献被删除

---

### Task 1: 数据库表结构 — 新增表和新列

**Files:**
- Modify: `backend/plugins/mml_manager/main.py` (Plugin._init_tables 方法, 约第 85-130 行)
- Test: `backend/tests/test_dependency_mining.py`

**Step 1: 写测试 — 验证新表和新列存在**

在 `test_dependency_mining.py` 末尾追加:

```python
@pytest.mark.asyncio
async def test_schema_file_mining_record(client):
    """file_mining_record 表存在且结构正确。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SCHEMA", "V_SCHEMA")
    entries, _ = await _upload_file(client, "schema_test.mml", b'ADD VPN: VPN="v1";', ne_id)
    file_id = entries[0]["id"]
    # 写入 file_mining_record
    db = client._transport.app.state.registry.get(DatabaseService)
    await db.execute(
        "INSERT INTO file_mining_record (file_entry_id, ne_version_id, mined, algorithm_version, command_count) "
        "VALUES (?, ?, 1, 'v1', 2)",
        (file_id, ne_id),
    )
    rows = await db.query("SELECT * FROM file_mining_record WHERE file_entry_id=?", (file_id,))
    assert len(rows) == 1
    assert rows[0]["mined"] == 1
    assert rows[0]["algorithm_version"] == "v1"
    assert rows[0]["command_count"] == 2


@pytest.mark.asyncio
async def test_schema_candidate_contribution(client):
    """candidate_contribution 表存在且 UNIQUE 约束正确。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_CONTRIB", "V_CONTRIB")
    entries, _ = await _upload_file(client, "contrib_test.mml", b'ADD VPN: VPN="v1";', ne_id)
    file_id = entries[0]["id"]
    db = client._transport.app.state.registry.get(DatabaseService)

    # 先创建候选
    await db.execute(
        "INSERT INTO dependency_candidate "
        "(ne_version_id, ref_command, ref_param, def_command, def_param, status, confidence, "
        "scores_json, evidence_json, active_algorithm_version) "
        "VALUES (?, 'ADD APN', 'VRFNAME', 'ADD VPN', 'VPN', 'pending', 0.9, '{}', '{}', 'v1')",
        (ne_id,),
    )
    cand_rows = await db.query("SELECT id FROM dependency_candidate WHERE ne_version_id=?", (ne_id,))
    cand_id = cand_rows[0]["id"]

    await db.execute(
        "INSERT INTO candidate_contribution (candidate_id, file_entry_id, algorithm_version, evidence_json, scores_json) "
        "VALUES (?, ?, 'v1', '{}', '{}')",
        (cand_id, file_id),
    )
    rows = await db.query("SELECT * FROM candidate_contribution WHERE candidate_id=?", (cand_id,))
    assert len(rows) == 1
    assert rows[0]["algorithm_version"] == "v1"


@pytest.mark.asyncio
async def test_schema_candidate_new_columns(client):
    """dependency_candidate 新增列 review_route, non_graph_reason, non_graph_reviewer, active_algorithm_version。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_COLS", "V_COLS")
    db = client._transport.app.state.registry.get(DatabaseService)
    await db.execute(
        "INSERT INTO dependency_candidate "
        "(ne_version_id, ref_command, ref_param, def_command, def_param, status, confidence, "
        "scores_json, evidence_json, review_route, non_graph_reason, non_graph_reviewer, active_algorithm_version) "
        "VALUES (?, 'ADD APN', 'VRFNAME', 'ADD VPN', 'VPN', 'pending', 0.9, '{}', '{}', 'auto', NULL, NULL, 'v1')",
        (ne_id,),
    )
    rows = await db.query("SELECT * FROM dependency_candidate WHERE ne_version_id=?", (ne_id,))
    assert len(rows) == 1
    assert rows[0]["review_route"] == "auto"
    assert rows[0]["active_algorithm_version"] == "v1"
    assert rows[0]["non_graph_reason"] is None
```

**Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_schema_file_mining_record tests/test_dependency_mining.py::test_schema_candidate_contribution tests/test_dependency_mining.py::test_schema_candidate_new_columns -v`
Expected: FAIL (表/列不存在)

**Step 3: 实现表结构**

在 `main.py` 的 `_init_tables` 方法中追加建表语句和 ALTER TABLE:

```python
# file_mining_record
await self.db.execute("""
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
    )
""")

# candidate_contribution
await self.db.execute("""
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
    )
""")
```

为 `dependency_candidate` 新增列（用 try/except 包裹，兼容已有表）:

```python
for col, definition in [
    ("review_route", "TEXT"),
    ("non_graph_reason", "TEXT"),
    ("non_graph_reviewer", "TEXT"),
    ("active_algorithm_version", "TEXT NOT NULL DEFAULT 'v1'"),
]:
    try:
        await self.db.execute(f"ALTER TABLE dependency_candidate ADD COLUMN {col} {definition}")
    except Exception:
        pass  # 列已存在
```

**Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_schema_file_mining_record tests/test_dependency_mining.py::test_schema_candidate_contribution tests/test_dependency_mining.py::test_schema_candidate_new_columns -v`
Expected: PASS

**Step 5: 全量回归**

Run: `cd backend && python -m pytest tests/ -v`
Expected: 所有测试通过

**Step 6: Commit**

```bash
git add backend/plugins/mml_manager/main.py backend/tests/test_dependency_mining.py
git commit -m "feat: add file_mining_record and candidate_contribution tables, new columns on dependency_candidate"
```

---

### Task 2: 候选引擎重构 — 单文件生成 + 贡献汇总

**Files:**
- Modify: `backend/plugins/mml_manager/candidate_engine.py`
- Test: `backend/tests/test_dependency_mining.py`

**Step 1: 写测试 — 单文件候选生成**

```python
def test_generate_single_file_candidates():
    """单文件生成候选，返回带 evidence 和 scores 的贡献级结果。"""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_single_file_candidates

    script = {
        "file_entry_id": 42,
        "ne_version_id": 1,
        "commands": [
            {"operation": "ADD", "name": "VPN", "params": [{"name": "VPN", "value": "vpn5g_01"}], "line_number": 1},
            {"operation": "ADD", "name": "APN", "params": [{"name": "VRFNAME", "value": "vpn5g_01"}], "line_number": 2},
        ],
    }
    results = generate_single_file_candidates(script)
    assert len(results) == 1
    r = results[0]
    assert r["ref_command"] == "ADD APN"
    assert r["ref_param"] == "VRFNAME"
    assert r["def_command"] == "ADD VPN"
    assert r["def_param"] == "VPN"
    assert r["file_entry_id"] == 42
    assert "evidence" in r
    assert "scores" in r
    assert r["scores"]["confidence"] > 0


def test_aggregate_contributions():
    """两个文件贡献汇总，支持度、区分度正确计算。"""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import aggregate_contributions

    contributions = [
        {
            "file_entry_id": 1,
            "has_hit": True,
            "hit_values": ["vpn1"],
            "order_consistency": 1.0,
            "name_relevance": 0.8,
            "hit_count": 1,
            "confidence": 0.85,
            "sample_scripts": [{"def_line": 1, "ref_line": 2}],
        },
        {
            "file_entry_id": 2,
            "has_hit": True,
            "hit_values": ["vpn2"],
            "order_consistency": 1.0,
            "name_relevance": 0.8,
            "hit_count": 1,
            "confidence": 0.82,
            "sample_scripts": [{"def_line": 1, "ref_line": 3}],
        },
    ]
    result = aggregate_contributions(contributions)
    assert result["support"] == 1.0  # 2/2 files have hits
    assert result["confidence"] > 0.5
    assert result["distinctiveness"] == 1.0  # 2 unique values / 2 total
```

**Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_generate_single_file_candidates tests/test_dependency_mining.py::test_aggregate_contributions -v`
Expected: FAIL (函数不存在)

**Step 3: 实现两个新函数**

在 `candidate_engine.py` 中新增:

`generate_single_file_candidates(script, weights=None)`:
- 接受单个脚本 dict（含 file_entry_id, ne_version_id, commands）
- 复用现有值匹配逻辑，但只处理一个脚本
- 返回列表，每项含 key (ref_command, ref_param, def_command, def_param) + evidence + scores + file_entry_id
- 内部复用 `_calculate_scores` 和 `_name_similarity`

`aggregate_contributions(contributions, weights=None)`:
- 接受贡献列表
- 按设计文档 §5.1 的汇总策略计算 support / distinctiveness / order_consistency / name_relevance / confidence
- 返回汇总分数 dict

**Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_generate_single_file_candidates tests/test_dependency_mining.py::test_aggregate_contributions -v`
Expected: PASS

**Step 5: 全量回归**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py -v`
Expected: 全部通过（原有 generate_candidates 不变）

**Step 6: Commit**

```bash
git add backend/plugins/mml_manager/candidate_engine.py backend/tests/test_dependency_mining.py
git commit -m "feat: add generate_single_file_candidates and aggregate_contributions to candidate_engine"
```

---

### Task 3: 文件挖掘 API — mine 端点

**Files:**
- Modify: `backend/plugins/mml_manager/main.py` (新增路由)
- Test: `backend/tests/test_dependency_mining.py`

**Step 1: 写测试**

```python
@pytest.mark.asyncio
async def test_mine_selected_files(client):
    """选择多个文件挖掘，产生候选并记录贡献。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_MINE", "V_MINE")
    scripts = [
        b'ADD VPN: VPN="vpn_m1";\nADD APN: VRFNAME="vpn_m1";\n',
        b'ADD VPN: VPN="vpn_m2";\nADD APN: VRFNAME="vpn_m2";\n',
    ]
    file_ids = []
    for i, content in enumerate(scripts):
        entries, _ = await _upload_file(client, f"mine_{i}.mml", content, ne_id)
        file_ids.append(entries[0]["id"])

    resp = await client.post(f"{BASE}/files/mine", json={"file_ids": file_ids})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_files"] == 2
    assert data["total_candidates"] >= 1

    # 验证 file_mining_record 已标记
    db = client._transport.app.state.registry.get(DatabaseService)
    for fid in file_ids:
        rows = await db.query("SELECT mined, command_count FROM file_mining_record WHERE file_entry_id=?", (fid,))
        assert len(rows) == 1
        assert rows[0]["mined"] == 1
        assert rows[0]["command_count"] == 2

    # 验证候选池有记录
    resp = await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})
    candidates = resp.json()
    assert len(candidates) >= 1
    match = [c for c in candidates if c["ref_param"] == "VRFNAME"]
    assert len(match) == 1
    assert match[0]["status"] == "pending"

    # 验证贡献记录存在
    cand_id = match[0]["id"]
    contribs = await db.query("SELECT * FROM candidate_contribution WHERE candidate_id=?", (cand_id,))
    assert len(contribs) == 2  # 两个文件各贡献一次
```

**Step 2: 运行测试，确认失败**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_mine_selected_files -v`
Expected: FAIL (路由不存在)

**Step 3: 实现 mine 端点**

在 `main.py` 新增路由 `POST /files/mine`:

核心逻辑按设计文档 §4.1:
1. 验证所有 file_ids 属于同一 ne_version
2. 对每个文件: 解析 → generate_single_file_candidates → 合并入候选池
3. 合并规则:
   - 新 key → 创建候选 (status='pending', review_route 按 confidence 分层)
   - 已有 pending → 添加/替换贡献，重算分数
   - 已有 rejected → 添加贡献，激活回 pending
   - 已有 graph → 添加贡献（事实层），不改 status
   - 已有 non_graph → 添加贡献（事实层），不改 status
4. 返回 `{ mined_files, total_candidates, candidates }`

**Step 4: 运行测试，确认通过**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_mine_selected_files -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/plugins/mml_manager/main.py backend/tests/test_dependency_mining.py
git commit -m "feat: add POST /files/mine endpoint for incremental file-level mining"
```

---

### Task 4: 文件挖掘 API — re-mine + mining-status

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`
- Modify: `backend/tests/test_dependency_mining.py`

**Step 1: 写测试**

```python
@pytest.mark.asyncio
async def test_remine_file(client):
    """重挖文件：旧贡献替换，候选分数更新。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REMINE", "V_REMINE")
    entries, _ = await _upload_file(client, "remine.mml", b'ADD VPN: VPN="old";\nADD APN: VRFNAME="old";', ne_id)
    file_id = entries[0]["id"]

    # 首次挖掘
    await client.post(f"{BASE}/files/mine", json={"file_ids": [file_id]})

    # 重挖（文件内容不变，但贡献应替换）
    resp = await client.post(f"{BASE}/files/{file_id}/re-mine")
    assert resp.status_code == 200

    # 验证贡献只有 1 条（不是 2 条）
    db = client._transport.app.state.registry.get(DatabaseService)
    cands = await db.query("SELECT id FROM dependency_candidate WHERE ne_version_id=?", (ne_id,))
    assert len(cands) == 1
    contribs = await db.query("SELECT * FROM candidate_contribution WHERE candidate_id=?", (cands[0]["id"],))
    assert len(contribs) == 1


@pytest.mark.asyncio
async def test_remine_preserves_graph(client):
    """重挖后 graph 状态的候选不被删除，即使暂时零贡献。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REMINE_G", "V_REMINE_G")
    entries1, _ = await _upload_file(client, "remg_1.mml", b'ADD VPN: VPN="vg";\nADD APN: VRFNAME="vg";', ne_id)
    fid1 = entries1[0]["id"]

    # 挖掘并 accept
    await client.post(f"{BASE}/files/mine", json={"file_ids": [fid1]})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id, "status": "pending"})).json()
    cand_id = cands[0]["id"]
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})

    # 重挖（只有一个文件，重挖后该文件贡献先删后重建）
    resp = await client.post(f"{BASE}/files/{fid1}/re-mine")
    assert resp.status_code == 200

    # graph 状态仍保留
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    graph_cands = [c for c in cands if c["status"] == "graph"]
    assert len(graph_cands) == 1


@pytest.mark.asyncio
async def test_mining_status(client):
    """查询文件挖掘状态。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_MSTATUS", "V_MSTATUS")
    entries1, _ = await _upload_file(client, "ms_1.mml", b'ADD VPN: VPN="v1";', ne_id)
    entries2, _ = await _upload_file(client, "ms_2.mml", b'ADD APN: APN="a1";', ne_id)

    # 未挖掘时
    resp = await client.get(f"{BASE}/files/mining-status", params={"ne_version_id": ne_id})
    assert resp.status_code == 200
    status_list = resp.json()
    assert len(status_list) == 2
    assert all(s["mined"] is False or s["mined"] == 0 for s in status_list)

    # 挖掘一个后
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries1[0]["id"]]})
    resp = await client.get(f"{BASE}/files/mining-status", params={"ne_version_id": ne_id})
    status_list = resp.json()
    mined = [s for s in status_list if s["file_entry_id"] == entries1[0]["id"]]
    assert mined[0]["mined"] == 1
```

**Step 2: 运行测试，确认失败**

**Step 3: 实现 re-mine 和 mining-status 端点**

re-mine 按设计文档 §4.2:
1. 删除该文件在当前算法版本下的所有贡献
2. 重算受影响候选的汇总分数
3. **仅删除 pending/rejected 且零贡献的候选**
4. graph/non_graph 零贡献时保留记录，分数置零
5. 重新挖掘该文件

mining-status: 查询 file_mining_record + file_entry LEFT JOIN

**Step 4: 运行测试，确认通过**

**Step 5: 全量回归 + Commit**

---

### Task 5: 候选管理 API — mark-non-graph + revert + 状态更新

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`
- Modify: `backend/tests/test_dependency_mining.py`

**Step 1: 写测试**

```python
@pytest.mark.asyncio
async def test_mark_non_graph(client):
    """标记候选为 non_graph。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_NG", "V_NG")
    entries, _ = await _upload_file(client, "ng.mml", b'ADD VPN: VPN="ng1";\nADD APN: VRFNAME="ng1";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    resp = await client.post(f"{BASE}/candidates/{cand_id}/mark-non-graph", json={
        "reason": "不可能是依赖关系",
        "reviewer": "expert",
    })
    assert resp.status_code == 200

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "non_graph"
    assert cands[0]["non_graph_reason"] == "不可能是依赖关系"


@pytest.mark.asyncio
async def test_revert_graph_to_pending(client):
    """graph 回退到 pending，graph_edge 被删除。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REV_G", "V_REV_G")
    entries, _ = await _upload_file(client, "revg.mml", b'ADD VPN: VPN="revg";\nADD APN: VRFNAME="revg";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # accept → graph
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    # revert → pending
    resp = await client.post(f"{BASE}/candidates/{cand_id}/revert", json={"reviewer": "admin"})
    assert resp.status_code == 200

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "pending"
    assert cands[0]["graph_edge_id"] is None


@pytest.mark.asyncio
async def test_revert_non_graph_to_pending(client):
    """non_graph 回退到 pending，可再次 accept 为 graph。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REV_NG", "V_REV_NG")
    entries, _ = await _upload_file(client, "revng.mml", b'ADD VPN: VPN="revng";\nADD APN: VRFNAME="revng";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # mark non_graph
    await client.post(f"{BASE}/candidates/{cand_id}/mark-non-graph", json={"reason": "test", "reviewer": "admin"})
    # revert → pending
    await client.post(f"{BASE}/candidates/{cand_id}/revert", json={"reviewer": "admin"})
    # accept → graph (non_graph → pending → graph 路径合法)
    resp = await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    assert resp.status_code == 200
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"
```

**Step 2-5: 同前模式 — 失败验证、实现、通过验证、回归、提交**

mark-non-graph 按设计文档 §4.4，revert 按 §4.6 + §4.7。

同时更新 accept/reject 路由，确保:
- accept 时清空 review_route，设置 status='graph'
- reject 时清空 review_route，设置 status='rejected'
- list_candidates 返回 review_route 字段

---

### Task 6: 前端 API 模块更新

**Files:**
- Modify: `frontend/src/api/dependency-mining.ts`

**Step 1: 更新接口定义**

- `Candidate` 接口新增: `review_route`, `non_graph_reason`, `non_graph_reviewer`, `active_algorithm_version`
- 新增 `FileMiningStatus` 接口: `file_entry_id`, `file_name`, `mined`, `command_count`, `algorithm_version`
- 新增 `MineResult` 接口: `mined_files`, `total_candidates`, `candidates`

**Step 2: 新增 API 函数**

```typescript
export async function mineFiles(fileIds: number[]): Promise<MineResult> { ... }
export async function reMineFile(fileId: number): Promise<MineResult> { ... }
export async function fetchMiningStatus(neVersionId: number): Promise<FileMiningStatus[]> { ... }
export async function markNonGraph(id: number, reason: string, reviewer: string): Promise<{ok: boolean}> { ... }
export async function revertCandidate(id: number, reviewer: string): Promise<{ok: boolean}> { ... }
```

**Step 3: 移除废弃函数**

删除 `batchExtractCommands`, `generateCandidates`（被 `mineFiles` 替代）

**Step 4: TypeScript 编译验证**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: PASS

**Step 5: Commit**

---

### Task 7: 前端视图重构

**Files:**
- Rewrite: `frontend/src/views/plugins/DependencyMining.vue`

**Step 1: 实现文件选择器面板**

- 左侧面板: 调用 `fetchMiningStatus` 显示文件列表
- 复选框 + 挖掘状态标签
- "挖掘选中" / "重新挖掘" 按钮

**Step 2: 实现三 tab 布局**

- 候选池 tab: status=pending 的候选，显示 review_route 标签
- 图谱库 tab: status=graph 的候选
- 非图谱库 tab: status=non_graph 的候选，显示 reason

**Step 3: 更新操作按钮**

- pending: 通过 / 拒绝 / 标记非图谱
- graph: 回退
- non_graph: 回退
- rejected: 无操作

**Step 4: 前端构建验证**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 5: Commit**

---

### Task 8: 全量集成测试 + 清理

**Files:**
- Modify: `backend/tests/test_dependency_mining.py`
- Modify: `backend/plugins/mml_manager/main.py` (清理废弃路由)

**Step 1: 写端到端集成测试**

覆盖完整流程: 创建版本 → 上传文件 → 挖掘 → 审核 → 图谱/非图谱 → 回退 → 重挖 → 新文件增量

```python
@pytest.mark.asyncio
async def test_full_incremental_pipeline(client):
    """完整增量挖掘流程。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_E2E2", "V_E2E2")

    # 上传 3 个文件
    files = []
    for i, content in enumerate([
        b'ADD VPN: VPN="e2e_v1";\nADD APN: VRFNAME="e2e_v1";',
        b'ADD VPN: VPN="e2e_v2";\nADD APN: VRFNAME="e2e_v2";',
        b'ADD VPN: VPN="e2e_v3";\nADD APN: VRFNAME="e2e_v3";',
    ]):
        entries, _ = await _upload_file(client, f"e2e2_{i}.mml", content, ne_id)
        files.append(entries[0]["id"])

    # 只挖掘前 2 个
    resp = await client.post(f"{BASE}/files/mine", json={"file_ids": files[:2]})
    assert resp.status_code == 200

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert len(cands) == 1
    cand = cands[0]
    assert cand["status"] == "pending"
    # 2 个贡献
    db = client._transport.app.state.registry.get(DatabaseService)
    contribs = await db.query("SELECT COUNT(*) as cnt FROM candidate_contribution WHERE candidate_id=?", (cand["id"],))
    assert contribs[0]["cnt"] == 2

    # accept → graph
    await client.post(f"{BASE}/candidates/{cand['id']}/accept", json={"reviewer": "admin"})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"

    # 挖掘第 3 个文件 — graph 状态不变但贡献仍记录
    resp = await client.post(f"{BASE}/files/mine", json={"file_ids": [files[2]]})
    assert resp.status_code == 200
    contribs = await db.query("SELECT COUNT(*) as cnt FROM candidate_contribution WHERE candidate_id=?", (cand["id"],))
    assert contribs[0]["cnt"] == 3  # 3 个贡献
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"  # 状态不变

    # revert → pending
    await client.post(f"{BASE}/candidates/{cand['id']}/revert", json={"reviewer": "admin"})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "pending"

    # mark non_graph
    await client.post(f"{BASE}/candidates/{cand['id']}/mark-non-graph", json={"reason": "测试", "reviewer": "admin"})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "non_graph"

    # revert non_graph → pending → accept (合法路径)
    await client.post(f"{BASE}/candidates/{cand['id']}/revert", json={"reviewer": "admin"})
    await client.post(f"{BASE}/candidates/{cand['id']}/accept", json={"reviewer": "admin"})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"
```

**Step 2: 清理废弃路由**

移除或标记废弃: `POST /candidates/generate`, `POST /versions/{id}/batch-extract`

**Step 3: 全量回归**

Run: `cd backend && python -m pytest tests/ -v`
Run: `cd frontend && npm run build`
Expected: 全部通过

**Step 4: Commit**

---

## 执行顺序

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8

Task 6-7 (前端) 依赖 Task 3-5 (后端 API)，但可以并行准备接口定义。
Task 8 (集成测试) 必须最后执行。
