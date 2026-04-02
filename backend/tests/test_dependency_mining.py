# backend/tests/test_dependency_mining.py
"""Tests for the MML dependency mining pipeline.

Covers: candidate_engine unit tests, command extraction API,
candidate generation API, review queue API (list/accept/reject),
and end-to-end pipeline.
"""
import pytest
import pytest_asyncio
import json
from pathlib import Path
from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from core.config import DB_PATH
from core.services.registry import ServiceRegistry
from core.services.database import DatabaseService
from core.services.parser import ParserService
from core.plugin.loader import PluginLoader
from core.plugin.context import PluginContext

_TEST_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "test_depmmining.db"


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    registry = ServiceRegistry()
    db = DatabaseService(db_path=str(_TEST_DB_PATH))
    await db.start()
    registry.register(DatabaseService, db)

    parser = ParserService()
    registry.register(ParserService, parser)

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


@pytest_asyncio.fixture(scope="module")
async def client():
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()
    _TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with _test_app.router.lifespan_context(_test_app):
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()


BASE = "/api/plugins/mml_manager"


async def _create_ne_version(client, vendor="huawei", ne_type="5GC", version="V100R001"):
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": vendor,
        "ne_type": ne_type,
        "version": version,
    })
    return resp.json()["id"], resp


async def _upload_file(client, filename, content, ne_version_id, parent_id=None):
    metadata = json.dumps({
        "parent_id": parent_id,
        "items": {filename: {"ne_version_id": ne_version_id}}
    })
    resp = await client.post(
        f"{BASE}/upload",
        data={"metadata": metadata},
        files={"files": (filename, content, "text/plain")},
    )
    data = resp.json()
    return data.get("uploaded", []), resp


# ── Unit Tests: candidate_engine ──────────────────────────────────────────


def test_generate_candidates_basic():
    """Two scripts with known VPN→APN dependency via VRFNAME/VPN value match."""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_candidates

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
    assert c["evidence"]["hit_count"] == 1


def test_generate_candidates_multiple_scripts():
    """Same dependency from 2 scripts → hit_count=2."""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_candidates

    scripts = [
        {
            "file_entry_id": 1,
            "ne_version_id": 1,
            "commands": [
                {"operation": "ADD", "name": "VPN", "params": [{"name": "VPN", "value": "vpn1"}], "line_number": 1},
                {"operation": "ADD", "name": "APN", "params": [{"name": "VRFNAME", "value": "vpn1"}], "line_number": 2},
            ]
        },
        {
            "file_entry_id": 2,
            "ne_version_id": 1,
            "commands": [
                {"operation": "ADD", "name": "VPN", "params": [{"name": "VPN", "value": "vpn2"}], "line_number": 1},
                {"operation": "ADD", "name": "APN", "params": [{"name": "VRFNAME", "value": "vpn2"}], "line_number": 2},
            ]
        },
    ]
    candidates = generate_candidates(scripts)
    assert len(candidates) == 1
    assert candidates[0]["evidence"]["hit_count"] == 2
    assert candidates[0]["confidence"] > 0.5


def test_generate_candidates_null_values_filtered():
    """params with None or empty string values are excluded."""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_candidates

    scripts = [
        {
            "file_entry_id": 1,
            "ne_version_id": 1,
            "commands": [
                {"operation": "ADD", "name": "VPN", "params": [{"name": "VPN", "value": None}, {"name": "DESC", "value": ""}], "line_number": 1},
                {"operation": "ADD", "name": "APN", "params": [{"name": "VRFNAME", "value": None}], "line_number": 2},
            ]
        },
    ]
    candidates = generate_candidates(scripts)
    # No candidates because no non-null, non-empty value matches
    assert len(candidates) == 0


def test_generate_single_file_candidates():
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
    assert result["distinctiveness"] == 1.0  # 2 unique / 2 total


def test_name_similarity():
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import _name_similarity

    assert _name_similarity("VRFNAME", "VPN") == 0.0 or _name_similarity("VRFNAME", "VPN") > 0.0
    assert _name_similarity("VPN", "VPN") == 1.0
    assert _name_similarity("VPN_NAME", "VPN_ID") >= 0.7


# ── API Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_commands_from_script(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_EXT", "V100R010")
    script_content = b'ADD VPN: VPN="vpn5g_01", DESC="5G VPN";\nADD APN: APN="test_apn", VRFNAME="vpn5g_01";\n'
    entries, _ = await _upload_file(client, "test_extract.mml", script_content, ne_id)
    file_id = entries[0]["id"]

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


@pytest.mark.asyncio
async def test_generate_candidates_endpoint(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_GEN", "V100R100")
    scripts = [
        b'ADD VPN: VPN="vpn1";\nADD APN: VRFNAME="vpn1";\n',
        b'ADD VPN: VPN="vpn2";\nADD APN: VRFNAME="vpn2";\n',
    ]
    for i, content in enumerate(scripts):
        entries, _ = await _upload_file(client, f"gen_{i}.mml", content, ne_id)
        resp = await client.post(f"{BASE}/scripts/{entries[0]['id']}/extract-commands")
        assert resp.status_code == 200

    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    candidates = data["candidates"]
    match = [c for c in candidates if c["ref_param"] == "VRFNAME" and c["def_param"] == "VPN"]
    assert len(match) == 1
    assert match[0]["evidence"]["hit_count"] == 2
    assert match[0]["confidence"] > 0.5


@pytest.mark.asyncio
async def test_list_candidates(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_LIST", "V100R200")
    resp = await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_accept_candidate(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_ACCEPT", "V100R300")
    scripts = [
        b'ADD VPN: VPN="vpn_acc1";\nADD APN: VRFNAME="vpn_acc1";\n',
    ]
    for i, content in enumerate(scripts):
        entries, _ = await _upload_file(client, f"accept_{i}.mml", content, ne_id)
        await client.post(f"{BASE}/scripts/{entries[0]['id']}/extract-commands")

    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    candidates = resp.json()["candidates"]
    assert len(candidates) >= 1
    candidate_id = candidates[0]["id"]

    # Accept
    resp = await client.post(
        f"{BASE}/candidates/{candidate_id}/accept",
        json={"reviewer": "test_admin"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["graph_edge_id"] is not None
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_reject_candidate(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REJECT", "V100R400")
    scripts = [
        b'ADD VPN: VPN="vpn_rej1";\nADD APN: VRFNAME="vpn_rej1";\n',
    ]
    for i, content in enumerate(scripts):
        entries, _ = await _upload_file(client, f"reject_{i}.mml", content, ne_id)
        await client.post(f"{BASE}/scripts/{entries[0]['id']}/extract-commands")

    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    candidates = resp.json()["candidates"]
    assert len(candidates) >= 1
    candidate_id = candidates[0]["id"]

    # Reject
    resp = await client.post(
        f"{BASE}/candidates/{candidate_id}/reject",
        json={"reviewer": "test_admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_full_pipeline(client):
    """E2E: create version → upload scripts → extract → generate → accept → verify graph."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_E2E", "V100R999")

    scripts_data = [
        b'ADD VPN: VPN="vpn_e2e_1";\nADD APN: VRFNAME="vpn_e2e_1";\n',
        b'ADD VPN: VPN="vpn_e2e_2";\nADD APN: VRFNAME="vpn_e2e_2";\n',
        b'ADD VPN: VPN="vpn_e2e_3";\nADD APN: VRFNAME="vpn_e2e_3";\n',
    ]
    for i, content in enumerate(scripts_data):
        entries, _ = await _upload_file(client, f"e2e_{i}.mml", content, ne_id)
        resp = await client.post(f"{BASE}/scripts/{entries[0]['id']}/extract-commands")
        assert resp.status_code == 200

    # Generate candidates
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    assert len(candidates) >= 1

    target = [c for c in candidates if c["ref_param"] == "VRFNAME"]
    assert len(target) == 1
    candidate_id = target[0]["id"]
    assert target[0]["confidence"] > 0.5

    # Accept
    resp = await client.post(
        f"{BASE}/candidates/{candidate_id}/accept",
        json={"reviewer": "e2e_tester"},
    )
    assert resp.status_code == 200
    edge_id = resp.json()["graph_edge_id"]
    assert edge_id is not None

    # Verify candidate is now graph
    resp = await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id, "status": "graph"})
    graph_cands = resp.json()
    assert any(c["id"] == candidate_id for c in graph_cands)


@pytest.mark.asyncio
async def test_regenerate_preserves_graph_status(client):
    """Generate → Accept → Regenerate: graph status must NOT be overwritten."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REGEN", "V100R500")
    scripts = [
        b'ADD VPN: VPN="vpn_regen1";\nADD APN: VRFNAME="vpn_regen1";\n',
    ]
    for i, content in enumerate(scripts):
        entries, _ = await _upload_file(client, f"regen_{i}.mml", content, ne_id)
        await client.post(f"{BASE}/scripts/{entries[0]['id']}/extract-commands")

    # First generate
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    candidates = resp.json()["candidates"]
    assert len(candidates) >= 1
    candidate_id = candidates[0]["id"]

    # Accept
    resp = await client.post(
        f"{BASE}/candidates/{candidate_id}/accept",
        json={"reviewer": "test_admin"},
    )
    assert resp.status_code == 200

    # Regenerate — graph status must be preserved
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    regenerated = resp.json()["candidates"]
    match = [c for c in regenerated if c["id"] == candidate_id]
    assert len(match) == 1
    assert match[0]["status"] == "graph"


@pytest.mark.asyncio
async def test_regenerate_preserves_rejected_status(client):
    """Generate → Reject → Regenerate: rejected status must NOT be overwritten."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REGEN2", "V100R600")
    scripts = [
        b'ADD VPN: VPN="vpn_rej2";\nADD APN: VRFNAME="vpn_rej2";\n',
    ]
    for i, content in enumerate(scripts):
        entries, _ = await _upload_file(client, f"regenrej_{i}.mml", content, ne_id)
        await client.post(f"{BASE}/scripts/{entries[0]['id']}/extract-commands")

    # First generate
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    candidates = resp.json()["candidates"]
    assert len(candidates) >= 1
    candidate_id = candidates[0]["id"]

    # Reject
    resp = await client.post(
        f"{BASE}/candidates/{candidate_id}/reject",
        json={"reviewer": "test_admin"},
    )
    assert resp.status_code == 200

    # Regenerate — rejected status must be preserved
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    regenerated = resp.json()["candidates"]
    match = [c for c in regenerated if c["id"] == candidate_id]
    assert len(match) == 1
    assert match[0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_batch_extract_commands(client):
    """Batch extract all files for an NE version, then generate candidates."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_BATCH", "V100R700")
    scripts = [
        b'ADD VPN: VPN="vpn_batch1";\nADD APN: VRFNAME="vpn_batch1";\n',
        b'ADD VPN: VPN="vpn_batch2";\nADD APN: VRFNAME="vpn_batch2";\n',
    ]
    for i, content in enumerate(scripts):
        await _upload_file(client, f"batch_{i}.mml", content, ne_id)

    # Batch extract — no per-file extract-commands call needed
    resp = await client.post(f"{BASE}/versions/{ne_id}/batch-extract")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_files"] == 2
    assert data["total_instances"] == 4  # 2 commands per script

    # Generate should now work without prior per-file extraction
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    candidates = resp.json()["candidates"]
    assert len(candidates) >= 1


# ── Schema Tests: Incremental Mining Tables ─────────────────────────────


@pytest.mark.asyncio
async def test_schema_file_mining_record(client):
    """file_mining_record table exists with correct structure."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SCHEMA", "V_SCHEMA")
    entries, _ = await _upload_file(client, "schema_test.mml", b'ADD VPN: VPN="v1";', ne_id)
    file_id = entries[0]["id"]
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
    """candidate_contribution table exists with correct structure."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_CONTRIB", "V_CONTRIB")
    entries, _ = await _upload_file(client, "contrib_test.mml", b'ADD VPN: VPN="v1";', ne_id)
    file_id = entries[0]["id"]
    db = client._transport.app.state.registry.get(DatabaseService)

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
    """dependency_candidate has new columns: review_route, non_graph_reason, non_graph_reviewer, active_algorithm_version."""
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


# ── Incremental Mining API Tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_mine_selected_files(client):
    """Mine selected files, producing candidates with contributions."""
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
    # Verify file_mining_record
    db = client._transport.app.state.registry.get(DatabaseService)
    for fid in file_ids:
        rows = await db.query("SELECT mined, command_count FROM file_mining_record WHERE file_entry_id=?", (fid,))
        assert len(rows) == 1
        assert rows[0]["mined"] == 1
    # Verify candidate pool
    resp = await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})
    candidates = resp.json()
    assert len(candidates) >= 1
    match = [c for c in candidates if c["ref_param"] == "VRFNAME"]
    assert len(match) == 1
    assert match[0]["status"] == "pending"
    # Verify contributions
    cand_id = match[0]["id"]
    contribs = await db.query("SELECT * FROM candidate_contribution WHERE candidate_id=?", (cand_id,))
    assert len(contribs) == 2


@pytest.mark.asyncio
async def test_remine_file(client):
    """Re-mine file: old contribution replaced, not duplicated."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REMINE", "V_REMINE")
    entries, _ = await _upload_file(client, "remine.mml", b'ADD VPN: VPN="old";\nADD APN: VRFNAME="old";', ne_id)
    file_id = entries[0]["id"]
    await client.post(f"{BASE}/files/mine", json={"file_ids": [file_id]})
    resp = await client.post(f"{BASE}/files/{file_id}/re-mine")
    assert resp.status_code == 200
    db = client._transport.app.state.registry.get(DatabaseService)
    cands = await db.query("SELECT id FROM dependency_candidate WHERE ne_version_id=?", (ne_id,))
    assert len(cands) == 1
    contribs = await db.query("SELECT * FROM candidate_contribution WHERE candidate_id=?", (cands[0]["id"],))
    assert len(contribs) == 1  # Not 2


@pytest.mark.asyncio
async def test_remine_preserves_graph(client):
    """Re-mine doesn't delete graph status even with zero contributions."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REMINE_G", "V_REMINE_G")
    entries1, _ = await _upload_file(client, "remg_1.mml", b'ADD VPN: VPN="vg";\nADD APN: VRFNAME="vg";', ne_id)
    fid1 = entries1[0]["id"]
    await client.post(f"{BASE}/files/mine", json={"file_ids": [fid1]})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id, "status": "pending"})).json()
    cand_id = cands[0]["id"]
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    resp = await client.post(f"{BASE}/files/{fid1}/re-mine")
    assert resp.status_code == 200
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    graph_cands = [c for c in cands if c["status"] == "graph"]
    assert len(graph_cands) == 1


@pytest.mark.asyncio
async def test_mining_status(client):
    """Query file mining status."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_MSTATUS", "V_MSTATUS")
    entries1, _ = await _upload_file(client, "ms_1.mml", b'ADD VPN: VPN="v1";', ne_id)
    entries2, _ = await _upload_file(client, "ms_2.mml", b'ADD APN: APN="a1";', ne_id)
    resp = await client.get(f"{BASE}/files/mining-status", params={"ne_version_id": ne_id})
    assert resp.status_code == 200
    status_list = resp.json()
    assert len(status_list) == 2
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries1[0]["id"]]})
    resp = await client.get(f"{BASE}/files/mining-status", params={"ne_version_id": ne_id})
    status_list = resp.json()
    mined = [s for s in status_list if s["file_entry_id"] == entries1[0]["id"]]
    assert mined[0]["mined"] == 1


@pytest.mark.asyncio
async def test_mark_non_graph(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_NG", "V_NG")
    entries, _ = await _upload_file(client, "ng.mml", b'ADD VPN: VPN="ng1";\nADD APN: VRFNAME="ng1";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]
    resp = await client.post(f"{BASE}/candidates/{cand_id}/mark-non-graph", json={
        "reason": "不可能", "reviewer": "expert",
    })
    assert resp.status_code == 200
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "non_graph"
    assert cands[0]["non_graph_reason"] == "不可能"


@pytest.mark.asyncio
async def test_revert_graph_to_pending(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REV_G", "V_REV_G")
    entries, _ = await _upload_file(client, "revg.mml", b'ADD VPN: VPN="revg";\nADD APN: VRFNAME="revg";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    resp = await client.post(f"{BASE}/candidates/{cand_id}/revert", json={"reviewer": "admin"})
    assert resp.status_code == 200
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_revert_non_graph_to_pending(client):
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REV_NG", "V_REV_NG")
    entries, _ = await _upload_file(client, "revng.mml", b'ADD VPN: VPN="revng";\nADD APN: VRFNAME="revng";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]
    await client.post(f"{BASE}/candidates/{cand_id}/mark-non-graph", json={"reason": "test", "reviewer": "admin"})
    await client.post(f"{BASE}/candidates/{cand_id}/revert", json={"reviewer": "admin"})
    resp = await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    assert resp.status_code == 200
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"


@pytest.mark.asyncio
async def test_full_incremental_pipeline(client):
    """Full incremental mining pipeline."""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_E2E2", "V_E2E2")
    files = []
    for i, content in enumerate([
        b'ADD VPN: VPN="e2e_v1";\nADD APN: VRFNAME="e2e_v1";',
        b'ADD VPN: VPN="e2e_v2";\nADD APN: VRFNAME="e2e_v2";',
        b'ADD VPN: VPN="e2e_v3";\nADD APN: VRFNAME="e2e_v3";',
    ]):
        entries, _ = await _upload_file(client, f"e2e2_{i}.mml", content, ne_id)
        files.append(entries[0]["id"])

    # Mine first 2 files
    resp = await client.post(f"{BASE}/files/mine", json={"file_ids": files[:2]})
    assert resp.status_code == 200
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert len(cands) == 1
    cand = cands[0]
    assert cand["status"] == "pending"
    db = client._transport.app.state.registry.get(DatabaseService)
    contribs = await db.query("SELECT COUNT(*) as cnt FROM candidate_contribution WHERE candidate_id=?", (cand["id"],))
    assert contribs[0]["cnt"] == 2

    # Accept -> graph
    await client.post(f"{BASE}/candidates/{cand['id']}/accept", json={"reviewer": "admin"})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"

    # Mine 3rd file - graph stays, contribution added
    await client.post(f"{BASE}/files/mine", json={"file_ids": [files[2]]})
    contribs = await db.query("SELECT COUNT(*) as cnt FROM candidate_contribution WHERE candidate_id=?", (cand["id"],))
    assert contribs[0]["cnt"] == 3
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"

    # Revert -> pending -> mark non_graph -> revert -> accept (full cycle)
    await client.post(f"{BASE}/candidates/{cand['id']}/revert", json={"reviewer": "admin"})
    await client.post(f"{BASE}/candidates/{cand['id']}/mark-non-graph", json={"reason": "test", "reviewer": "admin"})
    await client.post(f"{BASE}/candidates/{cand['id']}/revert", json={"reviewer": "admin"})
    await client.post(f"{BASE}/candidates/{cand['id']}/accept", json={"reviewer": "admin"})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert cands[0]["status"] == "graph"
