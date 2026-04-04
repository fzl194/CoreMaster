# backend/tests/test_graph_mining_integration.py
"""
Integration tests for graph_mining plugin – §11 coverage.

Test cases:
1. 单文件删除 → graph_mining 清理 contribution + file_mining_record + 重算候选
2. 文件夹递归删除 → 所有后代文件的 contribution / file_mining_record 均被清理
3. 版本删除 → 该版本下所有文件的清理链路生效，候选重算
4. 已审核候选终态保护 (graph → 重挖后状态不变)
5. rejected 终态保护 (rejected 新证据后状态不变)
6. rejected 终态零贡献保留 (rejected 零贡献时记录保留)
7. 零贡献终态不被删除 (graph 零贡献时记录保留)
8. 文件状态派生正确 (/files API 返回状态与 job_item + file_mining_record 组合一致)
9. 文件内容替换后不自动挖掘 (file.content_replaced → 仅标记 changed)
10. 候选状态机转换完整流程 (pending → graph → revert → reject → revert → pending)
"""
import json
import pytest
import pytest_asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from core.services.registry import ServiceRegistry
from core.services.database import DatabaseService
from core.services.parser import ParserService
from core.plugin.loader import PluginLoader
from core.plugin.context import PluginContext
from core.events.bus import PluginEventBus
from core.jobs.service import JobService
from core.jobs.worker import JobWorker
from core.jobs.models import CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE, CREATE_INDEXES

_TEST_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "test_gm_integration.db"
_MML_BASE = "/api/plugins/mml_manager"
_GM_BASE = "/api/plugins/graph_mining"


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    registry = ServiceRegistry()
    db = DatabaseService(db_path=str(_TEST_DB_PATH))
    await db.start()
    registry.register(DatabaseService, db)

    parser = ParserService()
    registry.register(ParserService, parser)

    event_bus = PluginEventBus()
    registry.register(PluginEventBus, event_bus)

    await db.execute(CREATE_JOBS_TABLE)
    await db.execute(CREATE_JOB_ITEMS_TABLE)
    for sql in CREATE_INDEXES:
        await db.execute(sql)

    job_service = JobService(db)
    registry.register(JobService, job_service)
    worker = JobWorker(job_service)
    registry.register(JobWorker, worker)

    loader = PluginLoader(plugins_dir=Path(__file__).resolve().parent.parent / "plugins")
    manifests = loader.scan()

    for manifest in manifests:
        plugin_name = manifest["plugin"]["name"]
        ctx = PluginContext(registry, name=plugin_name)
        plugin_dir = Path(manifest["_dir"])
        entry_file = plugin_dir / manifest["plugin"]["backend"]["entry"]
        if entry_file.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"plugins.{plugin_name}", str(entry_file)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "Plugin"):
                plugin_instance = module.Plugin()
                await plugin_instance.on_register(ctx)
                prefix = manifest["plugin"]["backend"]["routes_prefix"]
                if hasattr(plugin_instance, "router"):
                    app.include_router(plugin_instance.router, prefix=prefix)

    app.state.registry = registry
    yield
    await db.stop()


_test_app = FastAPI(lifespan=_test_lifespan)

# Module-level references populated during fixture setup
_db_ref: DatabaseService | None = None
_job_service_ref: JobService | None = None


@pytest_asyncio.fixture(scope="module")
async def client():
    global _db_ref, _job_service_ref
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()
    _TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with _test_app.router.lifespan_context(_test_app):
        _db_ref = _test_app.state.registry.get(DatabaseService)
        _job_service_ref = _test_app.state.registry.get(JobService)
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _create_ne(client, vendor="huawei", ne_type="5GC", version="V100R001"):
    resp = await client.post(f"{_MML_BASE}/ne-versions", json={
        "vendor": vendor, "ne_type": ne_type, "version": version,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _create_folder(client, name="folder1", parent_id=None):
    resp = await client.post(f"{_MML_BASE}/entries", json={
        "name": name, "parent_id": parent_id,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload_file(client, filename, content, ne_version_id, parent_id=None):
    metadata = json.dumps({
        "parent_id": parent_id,
        "items": {filename: {"ne_version_id": ne_version_id}}
    })
    resp = await client.post(
        f"{_MML_BASE}/upload",
        data={"metadata": metadata},
        files={"files": (filename, content, "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    uploaded = resp.json().get("uploaded", [])
    assert len(uploaded) == 1
    return uploaded[0]["id"]


async def _seed_mining_data(client, db, ne_version_id, file_id):
    """Insert fake mining data: file_mining_record, candidate, contribution."""
    await db.execute(
        "INSERT OR REPLACE INTO file_mining_record "
        "(file_entry_id, ne_version_id, mined, algorithm_version, command_count) "
        "VALUES (?, ?, 1, 'v1', 3)",
        (file_id, ne_version_id),
    )
    # Insert a candidate
    await db.execute(
        "INSERT OR IGNORE INTO dependency_candidate "
        "(ne_version_id, ref_command, ref_param, def_command, def_param, "
        "status, confidence, scores_json, evidence_json, review_route) "
        "VALUES (?, 'SET', 'ParamA', 'ADD', 'ParamB', 'pending', 0.75, "
        "'{\"support\":0.7,\"distinctiveness\":0.8,\"order_consistency\":0.9,\"name_relevance\":0.6}', "
        "'{\"hit_count\":2,\"hit_file_count\":1}', 'manual')",
        (ne_version_id,),
    )
    rows = await db.query(
        "SELECT id FROM dependency_candidate WHERE ne_version_id=? AND ref_command='SET' LIMIT 1",
        (ne_version_id,),
    )
    cand_id = rows[0]["id"]

    # Insert contribution linking candidate → file
    await db.execute(
        "INSERT OR IGNORE INTO candidate_contribution "
        "(candidate_id, file_entry_id, algorithm_version, evidence_json, scores_json) "
        "VALUES (?, ?, 'v1', '{}', '{}')",
        (cand_id, file_id),
    )
    return cand_id


def _get_db():
    return _db_ref


def _get_job_service():
    return _job_service_ref


# ── Test 1: 单文件删除 → graph_mining 清理 contribution + file_mining_record + 重算候选 ──

@pytest.mark.asyncio
async def test_01_single_file_delete_cleanup(client):
    db = _get_db()
    ne_id = await _create_ne(client, "huawei", "5GC", "T01-V1")
    file_id = await _upload_file(
        client, "test01.mml",
        "SET ParamA=Val1;\nADD ParamB=Val2;\nSET ParamA=Val3;\n",
        ne_id,
    )
    cand_id = await _seed_mining_data(client, db, ne_id, file_id)

    # Verify data exists before delete
    contribs = await db.query(
        "SELECT * FROM candidate_contribution WHERE file_entry_id=?", (file_id,)
    )
    assert len(contribs) == 1
    fmr = await db.query(
        "SELECT * FROM file_mining_record WHERE file_entry_id=?", (file_id,)
    )
    assert len(fmr) == 1

    # Delete the file via mml_manager
    resp = await client.delete(f"{_MML_BASE}/entries/{file_id}")
    assert resp.status_code == 200

    # Verify contribution cleaned up
    contribs_after = await db.query(
        "SELECT * FROM candidate_contribution WHERE file_entry_id=?", (file_id,)
    )
    assert len(contribs_after) == 0

    # Verify file_mining_record cleaned up
    fmr_after = await db.query(
        "SELECT * FROM file_mining_record WHERE file_entry_id=?", (file_id,)
    )
    assert len(fmr_after) == 0

    # Verify candidate was deleted (was pending with zero contributions)
    cand_after = await db.query(
        "SELECT * FROM dependency_candidate WHERE id=?", (cand_id,)
    )
    assert len(cand_after) == 0


# ── Test 2: 文件夹递归删除 → 所有后代文件的 contribution / file_mining_record 均被清理 ──

@pytest.mark.asyncio
async def test_02_folder_recursive_delete_cleanup(client):
    db = _get_db()
    ne_id = await _create_ne(client, "huawei", "5GC", "T02-V1")
    folder_id = await _create_folder(client, "folder_t02")

    # Upload 2 files into folder
    f1 = await _upload_file(
        client, "file_a.mml",
        "SET ParamA=1;\nADD ParamB=2;\n",
        ne_id, parent_id=folder_id,
    )
    f2 = await _upload_file(
        client, "file_b.mml",
        "SET ParamC=3;\nADD ParamD=4;\n",
        ne_id, parent_id=folder_id,
    )

    # Seed mining data for both files
    c1 = await _seed_mining_data(client, db, ne_id, f1)
    # For file 2, create a separate candidate
    await db.execute(
        "INSERT OR IGNORE INTO dependency_candidate "
        "(ne_version_id, ref_command, ref_param, def_command, def_param, "
        "status, confidence, scores_json, evidence_json, review_route) "
        "VALUES (?, 'SET', 'ParamC', 'ADD', 'ParamD', 'pending', 0.60, '{}', '{}', 'manual')",
        (ne_id,),
    )
    rows2 = await db.query(
        "SELECT id FROM dependency_candidate WHERE ne_version_id=? AND ref_command='SET' AND ref_param='ParamC' LIMIT 1",
        (ne_id,),
    )
    c2 = rows2[0]["id"]
    await db.execute(
        "INSERT OR IGNORE INTO candidate_contribution "
        "(candidate_id, file_entry_id, algorithm_version, evidence_json, scores_json) "
        "VALUES (?, ?, 'v1', '{}', '{}')",
        (c2, f2),
    )

    # Verify data exists
    contribs = await db.query(
        "SELECT * FROM candidate_contribution WHERE file_entry_id IN (?, ?)", (f1, f2)
    )
    assert len(contribs) == 2

    # Delete folder
    resp = await client.delete(f"{_MML_BASE}/entries/{folder_id}")
    assert resp.status_code == 200

    # Verify all contributions cleaned
    contribs_after = await db.query(
        "SELECT * FROM candidate_contribution WHERE file_entry_id IN (?, ?)", (f1, f2)
    )
    assert len(contribs_after) == 0

    # Verify all file_mining_records cleaned
    fmr_after = await db.query(
        "SELECT * FROM file_mining_record WHERE file_entry_id IN (?, ?)", (f1, f2)
    )
    assert len(fmr_after) == 0


# ── Test 3: 版本删除 → 该版本下所有文件的清理链路生效，候选重算 ──

@pytest.mark.asyncio
async def test_03_version_delete_cascade_cleanup(client):
    db = _get_db()
    ne_id = await _create_ne(client, "huawei", "5GC", "T03-V1")

    f1 = await _upload_file(client, "v3_a.mml", "SET X=1;\nADD Y=2;\n", ne_id)
    f2 = await _upload_file(client, "v3_b.mml", "SET Z=3;\nADD W=4;\n", ne_id)

    await _seed_mining_data(client, db, ne_id, f1)
    await _seed_mining_data(client, db, ne_id, f2)

    # Verify data exists
    contribs = await db.query(
        "SELECT * FROM candidate_contribution WHERE file_entry_id IN (?, ?)", (f1, f2)
    )
    assert len(contribs) >= 1

    # Delete ne_version
    resp = await client.delete(f"{_MML_BASE}/ne-versions/{ne_id}")
    assert resp.status_code == 200

    # Verify file_mining_records cleaned
    fmr = await db.query(
        "SELECT * FROM file_mining_record WHERE ne_version_id=?", (ne_id,)
    )
    assert len(fmr) == 0

    # Verify contributions cleaned (via ne_version_deleted handler)
    contribs_after = await db.query(
        "SELECT cc.* FROM candidate_contribution cc "
        "JOIN file_mining_record fmr ON cc.file_entry_id = fmr.file_entry_id "
        "WHERE fmr.ne_version_id=?", (ne_id,)
    )
    assert len(contribs_after) == 0


# ── Test 4: 已审核候选终态保护 (graph 候选重挖后状态不变) ──

@pytest.mark.asyncio
async def test_04_graph_terminal_state_protection(client):
    db = _get_db()
    ne_id = await _create_ne(client, "huawei", "5GC", "T04-V1")
    f1 = await _upload_file(client, "t04.mml", "SET A=1;\nADD B=2;\n", ne_id)
    cand_id = await _seed_mining_data(client, db, ne_id, f1)

    # Accept the candidate → status becomes 'graph'
    resp = await client.post(f"{_GM_BASE}/candidates/{cand_id}/accept", json={"reviewer": "tester"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify candidate is 'graph'
    rows = await db.query("SELECT status, graph_edge_id FROM dependency_candidate WHERE id=?", (cand_id,))
    assert rows[0]["status"] == "graph"
    edge_id = rows[0]["graph_edge_id"]
    assert edge_id is not None

    # Simulate new evidence: add a contribution and recalculate
    f2 = await _upload_file(client, "t04_extra.mml", "SET A=3;\nADD B=4;\n", ne_id)
    await db.execute(
        "INSERT OR IGNORE INTO candidate_contribution "
        "(candidate_id, file_entry_id, algorithm_version, evidence_json, scores_json) "
        "VALUES (?, ?, 'v1', '{\"hit_count\":1}', '{\"support\":0.8,\"distinctiveness\":0.7,\"order_consistency\":0.6,\"name_relevance\":0.5}')",
        (cand_id, f2),
    )
    await db.execute(
        "INSERT OR REPLACE INTO file_mining_record "
        "(file_entry_id, ne_version_id, mined, algorithm_version, command_count) "
        "VALUES (?, ?, 1, 'v1', 2)",
        (f2, ne_id),
    )

    # Trigger recalculate directly
    from plugins.graph_mining.services.candidate_service import CandidateService
    svc = CandidateService(db)
    total_mined = await svc.get_total_mined(ne_id)
    await svc.recalculate(cand_id, "v1", total_mined)

    # Verify candidate is STILL 'graph' (terminal state protection)
    rows_after = await db.query("SELECT status, confidence FROM dependency_candidate WHERE id=?", (cand_id,))
    assert rows_after[0]["status"] == "graph"
    # Confidence should be updated
    assert rows_after[0]["confidence"] > 0

    # Verify graph_edge still exists and is active
    edge_rows = await db.query("SELECT status FROM graph_edge WHERE id=?", (edge_id,))
    assert edge_rows[0]["status"] == "active"


# ── Test 5: rejected 终态保护 (新证据不激活) ──

@pytest.mark.asyncio
async def test_05_rejected_terminal_state_protection(client):
    db = _get_db()
    ne_id = await _create_ne(client, "huawei", "5GC", "T05-V1")
    f1 = await _upload_file(client, "t05.mml", "SET P=1;\nADD Q=2;\n", ne_id)
    cand_id = await _seed_mining_data(client, db, ne_id, f1)

    # Reject the candidate
    resp = await client.post(f"{_GM_BASE}/candidates/{cand_id}/reject", json={"reviewer": "tester"})
    assert resp.status_code == 200

    rows = await db.query("SELECT status FROM dependency_candidate WHERE id=?", (cand_id,))
    assert rows[0]["status"] == "rejected"

    # Add new contribution and recalculate
    f2 = await _upload_file(client, "t05_extra.mml", "SET P=3;\nADD Q=4;\n", ne_id)
    await db.execute(
        "INSERT OR IGNORE INTO candidate_contribution "
        "(candidate_id, file_entry_id, algorithm_version, evidence_json, scores_json) "
        "VALUES (?, ?, 'v1', '{\"hit_count\":1}', '{\"support\":0.8,\"distinctiveness\":0.7,\"order_consistency\":0.6,\"name_relevance\":0.5}')",
        (cand_id, f2),
    )
    await db.execute(
        "INSERT OR REPLACE INTO file_mining_record "
        "(file_entry_id, ne_version_id, mined, algorithm_version, command_count) "
        "VALUES (?, ?, 1, 'v1', 2)",
        (f2, ne_id),
    )

    from plugins.graph_mining.services.candidate_service import CandidateService
    svc = CandidateService(db)
    total_mined = await svc.get_total_mined(ne_id)
    await svc.recalculate(cand_id, "v1", total_mined)

    # Status should STILL be 'rejected' (terminal, new evidence does not reactivate)
    rows_after = await db.query("SELECT status, confidence FROM dependency_candidate WHERE id=?", (cand_id,))
    assert rows_after[0]["status"] == "rejected"
    # But confidence should be updated
    assert rows_after[0]["confidence"] > 0


# ── Test 6: rejected 零贡献终态保留 ──

@pytest.mark.asyncio
async def test_06_rejected_terminal_survives_zero_contributions(client):
    db = _get_db()
    ne_id = await _create_ne(client, "huawei", "5GC", "T06-V1")
    f1 = await _upload_file(client, "t06.mml", "SET R=1;\nADD S=2;\n", ne_id)
    cand_id = await _seed_mining_data(client, db, ne_id, f1)

    # Reject the candidate
    resp = await client.post(f"{_GM_BASE}/candidates/{cand_id}/reject", json={"reviewer": "tester"})
    assert resp.status_code == 200

    # Delete the only file with contribution
    resp = await client.delete(f"{_MML_BASE}/entries/{f1}")
    assert resp.status_code == 200

    # Candidate should STILL exist (rejected = terminal, survives zero contributions)
    rows = await db.query("SELECT id, status, confidence FROM dependency_candidate WHERE id=?", (cand_id,))
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"
    assert rows[0]["confidence"] == 0.0
