# MML Dependency Mining MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the MVP of the MML command dependency mining system — enhanced parser, candidate generation, review queue API, and minimal frontend — all within the existing `mml_manager` plugin.

**Architecture:** Enhance the existing `ParserService` to support multi-line/quote-aware parsing. Add 4 database tables (`command_instance`, `dependency_candidate`, `graph_edge`, `graph_changelog`) to the `mml_manager` plugin. Implement candidate generation engine as a service module within `mml_manager`. Add review queue API endpoints. Build a minimal Vue frontend view.

**Tech Stack:** Python 3 / FastAPI / aiosqlite (backend), Vue 3 / Naive UI / TypeScript (frontend), pytest / pytest-asyncio / httpx (testing)

**Design Reference:** `docs/plans/2026-04-01-mml-dependency-mining-design.md`

---

## Task 1: Enhance Parser — Multi-line, Quotes, Escape, Parse Report

**Files:**
- Modify: `backend/core/services/parser.py`
- Modify: `backend/core/services/protocols.py`

**Step 1: Update ParserServiceProtocol in protocols.py**

Add `parse_text_with_report` to the protocol so plugins can opt into the report.

```python
# In protocols.py, update ParserServiceProtocol:
@runtime_checkable
class ParserServiceProtocol(Protocol):
    def parse_text(self, text: str) -> list[dict]: ...
    def parse_file(self, path: str) -> list[dict]: ...
    def parse_text_with_report(self, text: str) -> dict: ...
```

**Step 2: Rewrite ParserService to support multi-line, quotes, escapes, and classification**

The new parser must:
1. Join continuation lines (lines that don't end with `;`)
2. Handle `/* ... */` block comments
3. Split parameters quote-aware (commas inside quotes are not separators)
4. Handle `\"` and `\\` escape sequences in quoted values
5. Classify each line as `parsed`, `skipped`, or `unrecognized`
6. Return a parse report via `parse_text_with_report()`
7. Maintain backward compatibility: `parse_text()` returns same `list[dict]` format

Key algorithm for multi-line:
- Iterate lines, accumulating into a buffer
- When a line ends with `;`, the buffer is complete → parse it
- When a line ends with `\`, strip the backslash and continue accumulating
- Block comments `/* ... */` are stripped before line processing

Key algorithm for quote-aware param splitting:
- Walk the params string character by character
- Track whether we're inside double or single quotes
- Only split on commas when not inside quotes
- Handle `\"` and `\\` inside double-quoted strings
- Strip outer quotes from values

**Step 3: Commit**

```bash
git add backend/core/services/parser.py backend/core/services/protocols.py
git commit -m "feat: enhance MML parser — multi-line, quote-aware, escape, parse report"
```

---

## Task 2: Parser Tests — Regression + New Scenarios

**Files:**
- Create: `backend/tests/test_parser_enhanced.py`

**Step 1: Write comprehensive parser tests**

Create `test_parser_enhanced.py` with these tests:

1. **Existing behavior preserved** (run same assertions as original test_parser.py)
   - `test_single_command` — ADD APN with params
   - `test_multiple_commands` — ADD + MOD
   - `test_skip_comments` — `//` line comments
   - `test_skip_empty_lines`
   - `test_param_without_value` — `APN;` → value=None
   - `test_command_with_spaces`

2. **Multi-line support**
   - `test_multiline_command_no_semicolon` — command split across lines joined by lack of `;`
   - `test_multiline_command_backslash` — line ending with `\` continues
   - `test_multiple_multiline_commands` — several multi-line commands in sequence

3. **Quote-aware splitting**
   - `test_value_with_comma_in_quotes` — `DESC="a,b,c"` → single param value `"a,b,c"`
   - `test_value_with_single_quotes` — `NAME='has space'` → value `"has space"`
   - `test_mixed_quotes` — mix of double and single quoted values

4. **Escape characters**
   - `test_escaped_quote_in_value` — `DESC="say \"hello\""` → value `say "hello"`
   - `test_escaped_backslash` — `PATH="C:\\Users"` → value `C:\Users`

5. **Block comments**
   - `test_block_comment` — `/* comment */` is skipped
   - `test_multiline_block_comment` — `/* line1\nline2 */` is skipped

6. **Parse report**
   - `test_parse_report_counts` — verify total_lines, parsed, skipped, unrecognized counts
   - `test_parse_report_unrecognized_samples` — unrecognized lines appear in sample list
   - `test_parse_text_backward_compat` — `parse_text()` still returns `list[dict]`

**Step 2: Run ALL parser tests (old + new) to verify no regression**

Run: `cd backend && python -m pytest tests/test_parser.py tests/test_parser_enhanced.py -v`
Expected: All 6 original + all new tests PASS

**Step 3: Commit**

```bash
git add backend/tests/test_parser_enhanced.py
git commit -m "test: add comprehensive parser tests — multi-line, quotes, escape, report"
```

---

## Task 3: Database Tables — 4 Core Tables

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

**Step 1: Add 4 tables to `on_register()`**

Add these `CREATE TABLE IF NOT EXISTS` statements after the existing tables:

```sql
-- Command instances extracted from parsed scripts
CREATE TABLE IF NOT EXISTS command_instance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_entry_id INTEGER NOT NULL REFERENCES file_entry(id) ON DELETE CASCADE,
    ne_version_id INTEGER NOT NULL REFERENCES ne_version(id),
    command_index INTEGER NOT NULL,
    operation TEXT NOT NULL,
    name TEXT NOT NULL,
    params_json TEXT NOT NULL,
    line_number INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Dependency candidates generated by the mining engine
CREATE TABLE IF NOT EXISTS dependency_candidate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ne_version_id INTEGER NOT NULL REFERENCES ne_version(id),
    ref_command TEXT NOT NULL,
    ref_param TEXT NOT NULL,
    def_command TEXT NOT NULL,
    def_param TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    confidence REAL NOT NULL,
    scores_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    source_batch TEXT,
    review_history_json TEXT DEFAULT '[]',
    graph_edge_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ne_version_id, ref_command, ref_param, def_command, def_param)
);

-- Confirmed dependency edges in the graph
CREATE TABLE IF NOT EXISTS graph_edge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ne_version_id INTEGER NOT NULL REFERENCES ne_version(id),
    ref_command TEXT NOT NULL,
    ref_param TEXT NOT NULL,
    def_command TEXT NOT NULL,
    def_param TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL DEFAULT 'mined',
    confidence REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    confirmed_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ne_version_id, ref_command, ref_param, def_command, def_param)
);

-- Changelog for graph edge mutations
CREATE TABLE IF NOT EXISTS graph_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dependency_id INTEGER REFERENCES graph_edge(id),
    candidate_id INTEGER REFERENCES dependency_candidate(id),
    change_type TEXT NOT NULL,
    snapshot_before TEXT,
    snapshot_after TEXT,
    trigger_type TEXT NOT NULL DEFAULT 'human',
    trigger_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Also create indexes:
```sql
CREATE INDEX IF NOT EXISTS idx_command_instance_file ON command_instance(file_entry_id);
CREATE INDEX IF NOT EXISTS idx_command_instance_ne_version ON command_instance(ne_version_id);
CREATE INDEX IF NOT EXISTS idx_candidate_status ON dependency_candidate(status);
CREATE INDEX IF NOT EXISTS idx_candidate_ne_version ON dependency_candidate(ne_version_id);
CREATE INDEX IF NOT EXISTS idx_graph_edge_status ON graph_edge(status);
CREATE INDEX IF NOT EXISTS idx_graph_edge_ne_version ON graph_edge(ne_version_id);
CREATE INDEX IF NOT EXISTS idx_changelog_dependency ON graph_changelog(dependency_id);
```

**Step 2: Run existing mml_manager tests to verify no regression**

Run: `cd backend && python -m pytest tests/test_mml_manager.py -v`
Expected: All 26 tests PASS

**Step 3: Commit**

```bash
git add backend/plugins/mml_manager/main.py
git commit -m "feat: add 4 core database tables for dependency mining"
```

---

## Task 4: Command Instance Extraction API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`
- Create: `backend/tests/test_dependency_mining.py`

**Step 1: Write the failing test for command instance extraction**

In `test_dependency_mining.py`, test the flow:
1. Create an NE version
2. Upload a script file
3. Call `POST /api/plugins/mml_manager/scripts/{file_id}/extract-commands`
4. Verify command instances are stored and returned

```python
@pytest.mark.asyncio
async def test_extract_commands_from_script(client):
    # Create NE version
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF", "V100R005")
    # Upload a script with known commands
    script_content = b'ADD VPN: VPN="vpn5g_01", DESC="5G VPN";\nADD APN: APN="test_apn", VRFNAME="vpn5g_01";\n'
    entries, _ = await _upload_file(client, "test_extract.mml", script_content, ne_id)
    file_id = entries[0]["id"]

    # Extract commands
    resp = await client.post(f"{BASE}/scripts/{file_id}/extract-commands")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["report"]["parsed"] == 2
    instances = data["instances"]
    assert instances[0]["operation"] == "ADD"
    assert instances[0]["name"] == "VPN"
    assert instances[1]["operation"] == "ADD"
    assert instances[1]["name"] == "APN"
```

**Step 2: Implement the extract-commands endpoint**

Add to `on_register()` in `main.py`:

```python
@self.router.post("/scripts/{file_id}/extract-commands")
async def extract_commands(file_id: int):
    # 1. Get file content
    rows = await self.db.query(
        "SELECT id, name, file_path, ne_version_id FROM file_entry WHERE id=? AND type='file'",
        (file_id,),
    )
    if not rows:
        return JSONResponse(status_code=404, content={"detail": "文件不存在"})
    entry = rows[0]
    ne_version_id = entry["ne_version_id"]
    if not ne_version_id:
        return JSONResponse(status_code=400, content={"detail": "文件未绑定网元版本"})

    # 2. Read file content
    p = _safe_file_path(entry["file_path"])
    if p is None or not p.exists():
        return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
    content = p.read_text(encoding="utf-8")

    # 3. Parse with report
    result = self.parser.parse_text_with_report(content)
    commands = result["commands"]
    report = result["report"]

    # 4. Delete old instances for this file (re-extraction)
    await self.db.execute("DELETE FROM command_instance WHERE file_entry_id=?", (file_id,))

    # 5. Store command instances
    instances = []
    for idx, cmd in enumerate(commands):
        import json as _json
        params_json = _json.dumps(cmd["params"], ensure_ascii=False)
        await self.db.execute(
            "INSERT INTO command_instance (file_entry_id, ne_version_id, command_index, operation, name, params_json, line_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, ne_version_id, idx, cmd["operation"], cmd["name"], params_json, cmd["line_number"]),
        )
        rows = await self.db.query(
            "SELECT id, file_entry_id, ne_version_id, command_index, operation, name, params_json, line_number "
            "FROM command_instance WHERE file_entry_id=? AND command_index=? ORDER BY id DESC LIMIT 1",
            (file_id, idx),
        )
        if rows:
            row = rows[0]
            row["params"] = _json.loads(row["params_json"])
            instances.append(row)

    return {
        "instances": instances,
        "total": len(instances),
        "report": report,
    }
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_extract_commands_from_script -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/plugins/mml_manager/main.py backend/tests/test_dependency_mining.py
git commit -m "feat: add command instance extraction API endpoint"
```

---

## Task 5: Candidate Generation Engine

**Files:**
- Create: `backend/plugins/mml_manager/candidate_engine.py`
- Modify: `backend/plugins/mml_manager/main.py`
- Modify: `backend/tests/test_dependency_mining.py`

**Step 1: Write the candidate generation engine module**

Create `candidate_engine.py` as a standalone module with pure functions that can be tested independently:

```python
"""Candidate generation engine for MML dependency mining.

Implements:
- Value match aggregation with script-level dedup
- Multi-dimensional scoring (support, distinctiveness, order_consistency, name_relevance)
- Known knowledge exclusion
- Confidence calculation with configurable weights
"""
import json
from collections import defaultdict

# Default scoring weights
DEFAULT_WEIGHTS = {
    "support": 0.35,
    "distinctiveness": 0.35,
    "order_consistency": 0.20,
    "name_relevance": 0.10,
}


def generate_candidates(command_instances_by_script: list[dict]) -> list[dict]:
    """Generate candidates from command instances grouped by script.

    Args:
        command_instances_by_script: list of {
            "file_entry_id": int,
            "ne_version_id": int,
            "commands": [{"operation", "name", "params": [{"name", "value"}], "line_number"}]
        }

    Returns:
        list of candidate dicts ready for database insertion.
    """
    # ... implementation per design doc section 3 phase 2-3
    pass


def calculate_scores(candidate_data: dict, total_cooccurrence: int) -> dict:
    """Calculate multi-dimensional scores for a candidate.

    Returns: {"support", "distinctiveness", "order_consistency", "name_relevance", "confidence"}
    """
    pass


def _name_similarity(name_a: str, name_b: str) -> float:
    """Calculate parameter name similarity (0.0-1.0).

    Uses normalized edit distance + substring detection + suffix stripping.
    """
    pass
```

Key algorithm for `generate_candidates`:
1. Iterate all scripts in the same ne_version scope
2. For each script, find all (cmd_i, cmd_j) pairs where i < j
3. For each pair, find all param pairs with matching non-null, non-empty values
4. Aggregate by candidate key (ref_cmd, ref_param, def_cmd, def_param)
5. Deduplicate at script level: same script only counts once per candidate key
6. Calculate scores for each candidate

**Step 2: Write unit tests for candidate_engine**

In `test_dependency_mining.py`, add tests:

```python
from plugins.mml_manager.candidate_engine import generate_candidates, calculate_scores

def test_generate_candidates_basic():
    """Two scripts with known VPN→APN dependency via VRFNAME/VPN value match."""
    scripts = [
        {
            "file_entry_id": 1,
            "ne_version_id": 1,
            "commands": [
                {"operation": "ADD", "name": "VPN", "params": [{"name": "VPN", "value": "vpn5g_01"}], "line_number": 1},
                {"operation": "ADD", "name": "APN", "params": [{"name": "VRFNAME", "value": "vpn5g_01"}], "line_number": 2},
            ]
        }
    ]
    candidates = generate_candidates(scripts)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["ref_command"] == "ADD APN"
    assert c["ref_param"] == "VRFNAME"
    assert c["def_command"] == "ADD VPN"
    assert c["def_param"] == "VPN"
    assert c["hit_count"] == 1

def test_generate_candidates_dedup():
    """Same candidate from 2 scripts should have hit_count=2, not double-count."""
    pass

def test_generate_candidates_null_values_filtered():
    """params with None or empty string values are excluded."""
    pass

def test_scores_calculation():
    """Verify support, distinctiveness, order_consistency, confidence."""
    pass
```

**Step 3: Implement the candidate generation functions**

Fill in `generate_candidates`, `calculate_scores`, `_name_similarity`.

**Step 4: Run candidate engine tests**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py -k candidate -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/plugins/mml_manager/candidate_engine.py backend/tests/test_dependency_mining.py
git commit -m "feat: implement candidate generation engine with scoring"
```

---

## Task 6: Candidate Generation API Endpoint

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`
- Modify: `backend/tests/test_dependency_mining.py`

**Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_generate_candidates_endpoint(client):
    # Setup: create NE version + upload 2 scripts with known dependency
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_GEN", "V100R100")
    # Script 1
    s1 = b'ADD VPN: VPN="vpn5g_01";\nADD APN: VRFNAME="vpn5g_01";\n'
    entries1, _ = await _upload_file(client, "gen1.mml", s1, ne_id)
    await client.post(f"{BASE}/scripts/{entries1[0]['id']}/extract-commands")
    # Script 2
    s2 = b'ADD VPN: VPN="vpn5g_02";\nADD APN: VRFNAME="vpn5g_02";\n'
    entries2, _ = await _upload_file(client, "gen2.mml", s2, ne_id)
    await client.post(f"{BASE}/scripts/{entries2[0]['id']}/extract-commands")

    # Generate candidates
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    # Should find ADD APN.VRFNAME → ADD VPN.VPN
    candidates = data["candidates"]
    match = [c for c in candidates if c["ref_param"] == "VRFNAME" and c["def_param"] == "VPN"]
    assert len(match) == 1
    assert match[0]["hit_count"] == 2
    assert match[0]["confidence"] > 0.5
```

**Step 2: Implement the generate candidates endpoint**

Add to `on_register()`:

```python
@self.router.post("/candidates/generate")
async def generate_candidates(payload: dict):
    ne_version_id = payload["ne_version_id"]

    # 1. Query all command instances for this ne_version, grouped by file
    rows = await self.db.query(
        "SELECT id, file_entry_id, command_index, operation, name, params_json, line_number "
        "FROM command_instance WHERE ne_version_id=? ORDER BY file_entry_id, command_index",
        (ne_version_id,),
    )

    # Group by file_entry_id
    scripts = {}
    for row in rows:
        fid = row["file_entry_id"]
        if fid not in scripts:
            scripts[fid] = {"file_entry_id": fid, "ne_version_id": ne_version_id, "commands": []}
        scripts[fid]["commands"].append({
            "operation": row["operation"],
            "name": row["name"],
            "params": json.loads(row["params_json"]),
            "line_number": row["line_number"],
        })

    if not scripts:
        return {"candidates": [], "total": 0}

    # 2. Run candidate generation
    from plugins.mml_manager.candidate_engine import generate_candidates
    candidates = generate_candidates(list(scripts.values()))

    # 3. Persist candidates (upsert by unique key)
    persisted = []
    for c in candidates:
        scores_json = json.dumps(c["scores"], ensure_ascii=False)
        evidence_json = json.dumps(c["evidence"], ensure_ascii=False)
        try:
            await self.db.execute(
                "INSERT INTO dependency_candidate "
                "(ne_version_id, ref_command, ref_param, def_command, def_param, status, confidence, scores_json, evidence_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ne_version_id, c["ref_command"], c["ref_param"], c["def_command"], c["def_param"],
                 c["status"], c["confidence"], scores_json, evidence_json),
            )
        except Exception:
            # Unique constraint violation — update existing
            await self.db.execute(
                "UPDATE dependency_candidate SET status=?, confidence=?, scores_json=?, evidence_json=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE ne_version_id=? AND ref_command=? AND ref_param=? AND def_command=? AND def_param=?",
                (c["status"], c["confidence"], scores_json, evidence_json,
                 ne_version_id, c["ref_command"], c["ref_param"], c["def_command"], c["def_param"]),
            )

        # Fetch the persisted record
        rows = await self.db.query(
            "SELECT id, ne_version_id, ref_command, ref_param, def_command, def_param, "
            "status, confidence, scores_json, evidence_json, created_at, updated_at "
            "FROM dependency_candidate WHERE ne_version_id=? AND ref_command=? AND ref_param=? AND def_command=? AND def_param=?",
            (ne_version_id, c["ref_command"], c["ref_param"], c["def_command"], c["def_param"]),
        )
        if rows:
            row = rows[0]
            row["scores"] = json.loads(row["scores_json"])
            row["evidence"] = json.loads(row["evidence_json"])
            persisted.append(row)

    return {"candidates": persisted, "total": len(persisted)}
```

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py::test_generate_candidates_endpoint -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/plugins/mml_manager/main.py backend/tests/test_dependency_mining.py
git commit -m "feat: add candidate generation API endpoint"
```

---

## Task 7: Review Queue API — List, Accept, Reject

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`
- Modify: `backend/tests/test_dependency_mining.py`

**Step 1: Write failing tests for review queue API**

```python
@pytest.mark.asyncio
async def test_list_candidates(client):
    # Use candidates generated in previous test
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REVIEW", "V100R200")
    resp = await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

@pytest.mark.asyncio
async def test_accept_candidate(client):
    # Generate candidates, then accept one
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_ACCEPT", "V100R201")
    # ... upload + extract + generate ...
    # Accept
    resp = await client.post(f"{BASE}/candidates/{candidate_id}/accept", json={"reviewer": "admin"})
    assert resp.status_code == 200
    # Verify graph_edge was created
    edge_id = resp.json()["graph_edge_id"]
    assert edge_id is not None

@pytest.mark.asyncio
async def test_reject_candidate(client):
    # Reject a candidate — no graph_edge created
    resp = await client.post(f"{BASE}/candidates/{candidate_id}/reject", json={"reviewer": "admin"})
    assert resp.status_code == 200
    # Verify status is rejected
    # Verify no graph_edge

@pytest.mark.asyncio
async def test_accept_creates_changelog(client):
    # Accept should create a changelog entry
    pass
```

**Step 2: Implement the review queue endpoints**

Add 3 endpoints to `on_register()`:

1. `GET /candidates` — list candidates with optional filters (`ne_version_id`, `status`)
2. `POST /candidates/{id}/accept` — set status to `accepted`, create graph_edge, create changelog
3. `POST /candidates/{id}/reject` — set status to `rejected`, create changelog

**Step 3: Run tests**

Run: `cd backend && python -m pytest tests/test_dependency_mining.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add backend/plugins/mml_manager/main.py backend/tests/test_dependency_mining.py
git commit -m "feat: add review queue API — list, accept, reject candidates"
```

---

## Task 8: Frontend — API Module for Dependency Mining

**Files:**
- Create: `frontend/src/api/dependency-mining.ts`

**Step 1: Create the API module**

```typescript
import api from "./index";

export interface CommandInstance {
  id: number;
  file_entry_id: number;
  ne_version_id: number;
  command_index: number;
  operation: string;
  name: string;
  params: { name: string; value: string | null }[];
  line_number: number;
}

export interface Candidate {
  id: number;
  ne_version_id: number;
  ref_command: string;
  ref_param: string;
  def_command: string;
  def_param: string;
  status: string;
  confidence: number;
  scores: {
    support: number;
    distinctiveness: number;
    order_consistency: number;
    name_relevance: number;
  };
  evidence: {
    hit_count: number;
    total_scripts: number;
    hit_values: string[];
    sample_scripts: { file_entry_id: number; lines: [number, number]; value: string }[];
    counter_examples: { file_entry_id: number; reason: string }[];
  };
  created_at: string;
  updated_at: string;
}

export interface ExtractResult {
  instances: CommandInstance[];
  total: number;
  report: { total_lines: number; parsed: number; skipped: number; unrecognized: number };
}

export async function extractCommands(fileId: number): Promise<ExtractResult> {
  const { data } = await api.post<ExtractResult>(`/plugins/mml_manager/scripts/${fileId}/extract-commands`);
  return data;
}

export async function generateCandidates(neVersionId: number): Promise<{ candidates: Candidate[]; total: number }> {
  const { data } = await api.post<{ candidates: Candidate[]; total: number }>("/plugins/mml_manager/candidates/generate", { ne_version_id: neVersionId });
  return data;
}

export async function fetchCandidates(params?: { ne_version_id?: number; status?: string }): Promise<Candidate[]> {
  const { data } = await api.get<Candidate[]>("/plugins/mml_manager/candidates", { params });
  return data;
}

export async function acceptCandidate(id: number, reviewer: string): Promise<{ graph_edge_id: number }> {
  const { data } = await api.post<{ graph_edge_id: number }>(`/plugins/mml_manager/candidates/${id}/accept`, { reviewer });
  return data;
}

export async function rejectCandidate(id: number, reviewer: string): Promise<void> {
  await api.post(`/plugins/mml_manager/candidates/${id}/reject`, { reviewer });
}
```

**Step 2: Commit**

```bash
git add frontend/src/api/dependency-mining.ts
git commit -m "feat: add frontend API module for dependency mining"
```

---

## Task 9: Frontend — Dependency Mining View

**Files:**
- Create: `frontend/src/views/plugins/DependencyMining.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layouts/MainLayout.vue` (add icon mapping)

**Step 1: Create the DependencyMining.vue component**

Minimal functional view:
- Header with NE version selector dropdown
- "Extract & Generate" action button
- Candidate table showing: ref_command, ref_param, def_command, def_param, confidence, status
- Color-coded confidence badges
- Accept / Reject action buttons per row
- Evidence drawer/modal showing hit_values, sample_scripts, counter_examples

Use Naive UI components: NSelect, NButton, NDataTable, NTag, NDrawer, NStatistic.

**Step 2: Register route in router/index.ts**

```typescript
{
  path: "plugins/dependency-mining",
  name: "dependency-mining",
  component: () => import("../views/plugins/DependencyMining.vue"),
},
```

**Step 3: Add icon mapping in MainLayout.vue**

```typescript
// Add to iconMap:
"git-branch": GitBranchOutline,
```

Import `GitBranchOutline` from `@vicons/ionicons5`.

**Step 4: Update mml_manager plugin.toml to register the frontend entry**

This is optional since the route is hardcoded. The route can also be dynamically registered from the plugin list — but for MVP, hardcoding the route is acceptable.

**Step 5: Commit**

```bash
git add frontend/src/views/plugins/DependencyMining.vue frontend/src/router/index.ts frontend/src/layouts/MainLayout.vue
git commit -m "feat: add dependency mining frontend view with review queue"
```

---

## Task 10: Full Integration Test

**Files:**
- Modify: `backend/tests/test_dependency_mining.py`

**Step 1: Write end-to-end integration test**

```python
@pytest.mark.asyncio
async def test_full_pipeline(client):
    """E2E: create version → upload scripts → extract → generate → review → verify graph."""
    # 1. Create NE version
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_E2E", "V100R999")

    # 2. Upload 3 scripts with known dependencies
    scripts = [
        b'ADD VPN: VPN="vpn1";\nADD APN: VRFNAME="vpn1";\n',
        b'ADD VPN: VPN="vpn2";\nADD APN: VRFNAME="vpn2";\n',
        b'ADD VPN: VPN="vpn3";\nADD APN: VRFNAME="vpn3";\n',
    ]
    for i, content in enumerate(scripts):
        entries, _ = await _upload_file(client, f"e2e_{i}.mml", content, ne_id)
        resp = await client.post(f"{BASE}/scripts/{entries[0]['id']}/extract-commands")
        assert resp.status_code == 200

    # 3. Generate candidates
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    assert len(candidates) >= 1

    # Find the VPN→APN candidate
    target = [c for c in candidates if c["ref_param"] == "VRFNAME"]
    assert len(target) == 1
    candidate_id = target[0]["id"]
    assert target[0]["confidence"] > 0.5

    # 4. Accept the candidate
    resp = await client.post(f"{BASE}/candidates/{candidate_id}/accept", json={"reviewer": "test_admin"})
    assert resp.status_code == 200
    edge_id = resp.json()["graph_edge_id"]
    assert edge_id is not None

    # 5. Verify graph edge exists
    edges = await self.db.query("SELECT * FROM graph_edge WHERE id=?", (edge_id,))
    assert len(edges) == 1
    assert edges[0]["status"] == "active"
    assert edges[0]["confirmed_by"] == "test_admin"

    # 6. Verify changelog exists
    logs = await self.db.query("SELECT * FROM graph_changelog WHERE dependency_id=?", (edge_id,))
    assert len(logs) >= 1
    assert logs[0]["change_type"] == "add"
```

**Step 2: Run ALL tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All tests PASS (existing + new)

**Step 3: Commit**

```bash
git add backend/tests/test_dependency_mining.py
git commit -m "test: add full integration test for dependency mining pipeline"
```

---

## Task 11: Run Full Test Suite + Verify No Regression

**Step 1: Run entire backend test suite**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: ALL tests pass (existing ~56 + new ~15+)

**Step 2: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

**Step 3: Final commit if any fixes needed**

---

## Summary of Files Created/Modified

| Action | File Path |
|--------|-----------|
| Modify | `backend/core/services/parser.py` |
| Modify | `backend/core/services/protocols.py` |
| Create | `backend/tests/test_parser_enhanced.py` |
| Modify | `backend/plugins/mml_manager/main.py` |
| Create | `backend/plugins/mml_manager/candidate_engine.py` |
| Create | `backend/tests/test_dependency_mining.py` |
| Create | `frontend/src/api/dependency-mining.ts` |
| Create | `frontend/src/views/plugins/DependencyMining.vue` |
| Modify | `frontend/src/router/index.ts` |
| Modify | `frontend/src/layouts/MainLayout.vue` |
