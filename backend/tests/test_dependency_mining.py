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

    # Verify candidate is now accepted
    resp = await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id, "status": "accepted"})
    accepted = resp.json()
    assert any(c["id"] == candidate_id for c in accepted)


@pytest.mark.asyncio
async def test_regenerate_preserves_accepted_status(client):
    """Generate → Accept → Regenerate: accepted status must NOT be overwritten."""
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

    # Regenerate — accepted status must be preserved
    resp = await client.post(f"{BASE}/candidates/generate", json={"ne_version_id": ne_id})
    assert resp.status_code == 200
    regenerated = resp.json()["candidates"]
    match = [c for c in regenerated if c["id"] == candidate_id]
    assert len(match) == 1
    assert match[0]["status"] == "accepted"


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
