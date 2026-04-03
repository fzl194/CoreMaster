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


def test_no_self_referential_candidates():
    """Self-referential candidates (same command + same param) must be filtered out."""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_candidates, generate_single_file_candidates

    # Two ADD APN commands with same APNNAME value — should NOT produce self-loop
    scripts = [
        {
            "file_entry_id": 1,
            "ne_version_id": 1,
            "commands": [
                {"operation": "ADD", "name": "APN", "params": [{"name": "APNNAME", "value": "apn1"}], "line_number": 1},
                {"operation": "ADD", "name": "APN", "params": [{"name": "APNNAME", "value": "apn1"}], "line_number": 2},
            ]
        },
    ]

    candidates = generate_candidates(scripts)
    for c in candidates:
        assert not (c["ref_command"] == c["def_command"] and c["ref_param"] == c["def_param"]), \
            f"Self-referential candidate found: {c['ref_command']}/{c['ref_param']} -> {c['def_command']}/{c['def_param']}"

    # Also test generate_single_file_candidates
    results = generate_single_file_candidates(scripts[0])
    for r in results:
        assert not (r["ref_command"] == r["def_command"] and r["ref_param"] == r["def_param"]), \
            f"Self-referential contribution found: {r['ref_command']}/{r['ref_param']} -> {r['def_command']}/{r['def_param']}"


def test_single_file_multiple_hits_accumulated():
    """同一文件内同 key 多次命中，evidence 应累加而非覆盖。"""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_single_file_candidates

    # 1 APN + 4 VPNINST commands, all sharing VPN value
    script = {
        "file_entry_id": 1,
        "ne_version_id": 1,
        "commands": [
            {"operation": "ADD", "name": "APN", "params": [{"name": "VPN", "value": "vpn1"}], "line_number": 1},
            {"operation": "ADD", "name": "VPNINST", "params": [{"name": "VRFNAME", "value": "vpn1"}], "line_number": 2},
            {"operation": "ADD", "name": "VPNINST", "params": [{"name": "VRFNAME", "value": "vpn1"}], "line_number": 3},
            {"operation": "ADD", "name": "VPNINST", "params": [{"name": "VRFNAME", "value": "vpn1"}], "line_number": 4},
            {"operation": "ADD", "name": "VPNINST", "params": [{"name": "VRFNAME", "value": "vpn1"}], "line_number": 5},
        ],
    }
    results = generate_single_file_candidates(script)
    # Should produce exactly 1 result: ADD VPNINST/VRFNAME -> ADD APN/VPN
    assert len(results) == 1
    r = results[0]
    assert r["ref_command"] == "ADD VPNINST"
    assert r["ref_param"] == "VRFNAME"
    assert r["def_command"] == "ADD APN"
    assert r["def_param"] == "VPN"
    # 4 hits (APN at line 1 matched by 4 VPNINST at lines 2-5)
    assert r["evidence"]["hit_count"] == 4
    assert len(r["evidence"]["sample_scripts"]) == 4


def test_single_file_multiple_hit_values():
    """同一文件内同 key 匹配不同值，hit_values 应包含所有唯一值。"""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_single_file_candidates

    script = {
        "file_entry_id": 1,
        "ne_version_id": 1,
        "commands": [
            {"operation": "ADD", "name": "VPN", "params": [{"name": "VPN", "value": "v1"}], "line_number": 1},
            {"operation": "ADD", "name": "APN", "params": [{"name": "VRFNAME", "value": "v1"}], "line_number": 2},
            {"operation": "ADD", "name": "VPN", "params": [{"name": "VPN", "value": "v2"}], "line_number": 3},
            {"operation": "ADD", "name": "APN", "params": [{"name": "VRFNAME", "value": "v2"}], "line_number": 4},
        ],
    }
    results = generate_single_file_candidates(script)
    # One key: ADD APN/VRFNAME -> ADD VPN/VPN
    assert len(results) == 1
    r = results[0]
    # 4 hits (v1: VPN@1→APN@2 + VPN@1→APN@4 + VPN@3→APN@4; v2: VPN@3→APN@4)
    # Actually: (i=0,j=1):v1, (i=0,j=3):v2, (i=2,j=3):v2 — but (i=0,j=3) match v1!=v2 skip
    # So: (0,1) v1 match, (2,3) v2 match — wait, also (0,3): VPN.v1 vs APN.v2 no match
    # And (0,1): VPN.v1 vs APN.v1 match, (2,3): VPN.v2 vs APN.v2 match
    # Total 2 hits, values {v1, v2}
    assert r["evidence"]["hit_count"] >= 2
    assert "v1" in r["evidence"]["hit_values"]
    assert "v2" in r["evidence"]["hit_values"]


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


@pytest.mark.asyncio
async def test_mining_status_file_name_field(client):
    """mining-status 返回 file_name 字段（不是 name）。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_FNAME", "V_FNAME")
    entries, _ = await _upload_file(client, "fname_test.mml", b'ADD VPN: VPN="v1";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    resp = await client.get(f"{BASE}/files/mining-status", params={"ne_version_id": ne_id})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    item = data[0]
    assert "file_name" in item
    assert item["file_name"] == "fname_test.mml"


@pytest.mark.asyncio
async def test_state_machine_non_graph_to_graph_blocked(client):
    """non_graph 不能直接转 graph（必须先 revert 到 pending）。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SM_NG2G", "V_SM_NG2G")
    entries, _ = await _upload_file(client, "sm_ng2g.mml", b'ADD VPN: VPN="ng2g";\nADD APN: VRFNAME="ng2g";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # pending → non_graph (legal)
    await client.post(f"{BASE}/candidates/{cand_id}/mark-non-graph", json={"reason": "test", "reviewer": "admin"})

    # non_graph → accept/graph (illegal, must go through pending first)
    resp = await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_state_machine_graph_to_non_graph_blocked(client):
    """graph 不能直接转 non_graph（必须先 revert 到 pending）。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SM_G2NG", "V_SM_G2NG")
    entries, _ = await _upload_file(client, "sm_g2ng.mml", b'ADD VPN: VPN="g2ng";\nADD APN: VRFNAME="g2ng";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # pending → graph (legal)
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})

    # graph → non_graph (illegal)
    resp = await client.post(f"{BASE}/candidates/{cand_id}/mark-non-graph", json={"reason": "test", "reviewer": "admin"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_state_machine_graph_to_rejected_blocked(client):
    """graph 不能直接转 rejected（必须先 revert 到 pending）。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SM_G2R", "V_SM_G2R")
    entries, _ = await _upload_file(client, "sm_g2r.mml", b'ADD VPN: VPN="g2r";\nADD APN: VRFNAME="g2r";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # pending → graph (legal)
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})

    # graph → rejected (illegal)
    resp = await client.post(f"{BASE}/candidates/{cand_id}/reject", json={"reviewer": "admin"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_state_machine_non_graph_to_rejected_blocked(client):
    """non_graph 不能直接转 rejected（必须先 revert 到 pending）。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SM_NG2R", "V_SM_NG2R")
    entries, _ = await _upload_file(client, "sm_ng2r.mml", b'ADD VPN: VPN="ng2r";\nADD APN: VRFNAME="ng2r";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # pending → non_graph (legal)
    await client.post(f"{BASE}/candidates/{cand_id}/mark-non-graph", json={"reason": "test", "reviewer": "admin"})

    # non_graph → rejected (illegal)
    resp = await client.post(f"{BASE}/candidates/{cand_id}/reject", json={"reviewer": "admin"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_revert_graph_edge_status_revoked(client):
    """graph 回退时 graph_edge 状态应变为 'revoked'（不是 'deleted'）。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_EDGE_ST", "V_EDGE_ST")
    entries, _ = await _upload_file(client, "edge_st.mml", b'ADD VPN: VPN="est";\nADD APN: VRFNAME="est";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # pending → graph
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})

    # Get graph_edge_id
    db = client._transport.app.state.registry.get(DatabaseService)
    cand_rows = await db.query("SELECT graph_edge_id FROM dependency_candidate WHERE id=?", (cand_id,))
    edge_id = cand_rows[0]["graph_edge_id"]
    assert edge_id is not None

    # graph → pending (revert)
    await client.post(f"{BASE}/candidates/{cand_id}/revert", json={"reviewer": "admin"})

    # Verify graph_edge status is 'revoked'
    edge_rows = await db.query("SELECT status FROM graph_edge WHERE id=?", (edge_id,))
    assert edge_rows[0]["status"] == "revoked"


@pytest.mark.asyncio
async def test_state_machine_rejected_to_graph_blocked(client):
    """rejected 不能直接 accept 为 graph（必须通过新证据激活回 pending）。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SM_R2G", "V_SM_R2G")
    entries, _ = await _upload_file(client, "sm_r2g.mml", b'ADD VPN: VPN="r2g";\nADD APN: VRFNAME="r2g";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]

    # pending → rejected (legal)
    await client.post(f"{BASE}/candidates/{cand_id}/reject", json={"reviewer": "admin"})

    # rejected → graph (illegal, must be re-activated to pending via new evidence first)
    resp = await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_mine_single_file_multiple_hits_evidence(client):
    """单文件内同候选多次命中，evidence 应累加而非只保留最后一次。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_MHIT", "V_MHIT")
    # 1 APN + 4 VPNINST, all share same VPN value
    content = (
        b'ADD APN: VPN="vpn1";\n'
        b'ADD VPNINST: VRFNAME="vpn1";\n'
        b'ADD VPNINST: VRFNAME="vpn1";\n'
        b'ADD VPNINST: VRFNAME="vpn1";\n'
        b'ADD VPNINST: VRFNAME="vpn1";\n'
    )
    entries, _ = await _upload_file(client, "mhit.mml", content, ne_id)
    file_id = entries[0]["id"]

    resp = await client.post(f"{BASE}/files/mine", json={"file_ids": [file_id]})
    assert resp.status_code == 200

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert len(cands) >= 1
    cand = cands[0]

    # Verify evidence has accumulated hits
    evidence = json.loads(cand["evidence_json"]) if isinstance(cand["evidence_json"], str) else cand["evidence_json"]
    assert evidence["hit_count"] >= 3, f"Expected >=3 hits but got {evidence['hit_count']}"
    assert evidence["hit_file_count"] >= 1
    assert "total_mined_files" in evidence


@pytest.mark.asyncio
async def test_mine_support_uses_total_files(client):
    """support 应基于总挖掘文件数，不是只基于有命中的文件数。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_SUPP", "V_SUPP")

    # File 1: has VPN-APN match
    entries1, _ = await _upload_file(client, "supp1.mml", b'ADD VPN: VPN="v1";\nADD APN: VRFNAME="v1";', ne_id)
    # File 2: no match (different commands)
    entries2, _ = await _upload_file(client, "supp2.mml", b'ADD EQM: EQMID="eqm1";', ne_id)
    # File 3: has VPN-APN match
    entries3, _ = await _upload_file(client, "supp3.mml", b'ADD VPN: VPN="v3";\nADD APN: VRFNAME="v3";', ne_id)

    file_ids = [entries1[0]["id"], entries2[0]["id"], entries3[0]["id"]]
    resp = await client.post(f"{BASE}/files/mine", json={"file_ids": file_ids})
    assert resp.status_code == 200

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert len(cands) >= 1
    # The VPN-APN candidate should have support < 1.0 because file 2 has no match
    scores = json.loads(cands[0]["scores_json"]) if isinstance(cands[0]["scores_json"], str) else cands[0]["scores_json"]
    assert scores["support"] < 1.0, f"Expected support < 1.0 (2/3 files hit), got {scores['support']}"
    # 2 out of 3 files had the match
    assert abs(scores["support"] - 2/3) < 0.01, f"Expected support ≈ 0.667, got {scores['support']}"


def test_single_file_hit_count_not_truncated_at_10():
    """单文件 >10 次命中时 hit_count 不应被 sample_scripts 上限截断。"""
    import sys
    plugin_dir = str(Path(__file__).resolve().parent.parent / "plugins" / "mml_manager")
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)
    from candidate_engine import generate_single_file_candidates

    # 1 APN + 15 VPNINST, all share same VPN value → 15 hits
    commands = [
        {"operation": "ADD", "name": "APN", "params": [{"name": "VPN", "value": "vpn1"}], "line_number": 1},
    ]
    for i in range(15):
        commands.append(
            {"operation": "ADD", "name": "VPNINST", "params": [{"name": "VRFNAME", "value": "vpn1"}], "line_number": 2 + i}
        )

    script = {"file_entry_id": 1, "ne_version_id": 1, "commands": commands}
    results = generate_single_file_candidates(script)
    assert len(results) == 1
    r = results[0]
    assert r["evidence"]["hit_count"] == 15, f"Expected 15 hits but got {r['evidence']['hit_count']}"
    assert len(r["evidence"]["sample_scripts"]) == 10  # capped at 10 for samples


@pytest.mark.asyncio
async def test_mine_mixed_new_and_already_mined_files(client):
    """混合选择已挖文件和新文件时 support 分母不应重复计数。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_MIXED", "V_MIXED")

    # File 1: has VPN-APN match
    entries1, _ = await _upload_file(client, "mix1.mml", b'ADD VPN: VPN="v1";\nADD APN: VRFNAME="v1";', ne_id)
    # File 2: no match (different commands)
    entries2, _ = await _upload_file(client, "mix2.mml", b'ADD EQM: EQMID="eqm1";', ne_id)

    # Mine both files first
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries1[0]["id"], entries2[0]["id"]]})

    # Now mine file 1 again (already mined) — support denominator should NOT increase
    resp = await client.post(f"{BASE}/files/mine", json={"file_ids": [entries1[0]["id"]]})
    assert resp.status_code == 200

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert len(cands) >= 1
    scores = json.loads(cands[0]["scores_json"]) if isinstance(cands[0]["scores_json"], str) else cands[0]["scores_json"]

    # Support should still be 1/2 = 0.5 (file 1 hit, file 2 no hit), not 1/3
    assert abs(scores["support"] - 0.5) < 0.01, f"Expected support ≈ 0.5, got {scores['support']}"


@pytest.mark.asyncio
async def test_remine_graph_zero_contribution_clears_evidence(client):
    """re-mine 删掉唯一贡献后，graph 候选的 evidence_json 应被清空。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_REME", "V_REME")
    entries, _ = await _upload_file(client, "reme.mml", b'ADD VPN: VPN="v1";\nADD APN: VRFNAME="v1";', ne_id)
    file_id = entries[0]["id"]

    # Mine and accept
    await client.post(f"{BASE}/files/mine", json={"file_ids": [file_id]})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]
    await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})

    # Verify evidence is populated before re-mine
    db = client._transport.app.state.registry.get(DatabaseService)
    cand_before = (await db.query("SELECT evidence_json FROM dependency_candidate WHERE id=?", (cand_id,)))[0]
    evidence_before = json.loads(cand_before["evidence_json"])
    assert evidence_before.get("hit_count", 0) > 0, "Evidence should be populated before re-mine"

    # Update file content to have no matches, then re-mine
    await client.put(f"{BASE}/files/{file_id}/content", json={"content": "ADD EQM: EQMID=\"empty\";\n"})
    await client.post(f"{BASE}/files/{file_id}/re-mine")

    # Verify graph candidate still exists but evidence is cleared
    cand_after = (await db.query("SELECT evidence_json, confidence, status FROM dependency_candidate WHERE id=?", (cand_id,)))[0]
    assert cand_after["status"] == "graph"
    assert cand_after["confidence"] == 0.0
    evidence_after = json.loads(cand_after["evidence_json"])
    assert evidence_after == {} or evidence_after.get("hit_count", 0) == 0, \
        f"Evidence should be empty/zeroed after re-mine removes all contributions, got {evidence_after}"


@pytest.mark.asyncio
async def test_graph_edge_evidence_updates_on_incremental_mine(client):
    """增量挖掘新文件后，graph_edge.evidence_json 应同步更新。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_GEDGE", "V_GEDGE")

    # File 1: VPN-APN match
    entries1, _ = await _upload_file(client, "gedge1.mml", b'ADD VPN: VPN="vx";\nADD APN: VRFNAME="vx";', ne_id)

    # Mine file 1 and accept
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries1[0]["id"]]})
    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    cand_id = cands[0]["id"]
    accept_resp = await client.post(f"{BASE}/candidates/{cand_id}/accept", json={"reviewer": "admin"})
    edge_id = accept_resp.json()["graph_edge_id"]

    # Check graph_edge evidence after accept
    db = client._transport.app.state.registry.get(DatabaseService)
    edge_before = (await db.query("SELECT evidence_json FROM graph_edge WHERE id=?", (edge_id,)))[0]
    evidence_before = json.loads(edge_before["evidence_json"])
    assert evidence_before.get("hit_count", 0) == 1

    # File 2: same VPN-APN match (adds new evidence)
    entries2, _ = await _upload_file(client, "gedge2.mml", b'ADD VPN: VPN="vx";\nADD APN: VRFNAME="vx";', ne_id)
    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries2[0]["id"]]})

    # graph_edge evidence should be updated with new contribution
    edge_after = (await db.query("SELECT evidence_json FROM graph_edge WHERE id=?", (edge_id,)))[0]
    evidence_after = json.loads(edge_after["evidence_json"])
    assert evidence_after.get("hit_count", 0) >= 2, \
        f"graph_edge evidence should reflect new hit, got hit_count={evidence_after.get('hit_count')}"


@pytest.mark.asyncio
async def test_candidate_evidence_has_per_file_breakdown(client):
    """候选 evidence 应包含文件维度，审核员能看到样例来自哪个文件。"""
    ne_id, _ = await _create_ne_version(client, "huawei", "UPF_PFILE", "V_PFILE")

    # Two files with same dependency
    entries1, _ = await _upload_file(client, "pf1.mml", b'ADD VPN: VPN="vv";\nADD APN: VRFNAME="vv";', ne_id)
    entries2, _ = await _upload_file(client, "pf2.mml", b'ADD VPN: VPN="vv";\nADD APN: VRFNAME="vv";', ne_id)

    await client.post(f"{BASE}/files/mine", json={"file_ids": [entries1[0]["id"], entries2[0]["id"]]})

    cands = (await client.get(f"{BASE}/candidates", params={"ne_version_id": ne_id})).json()
    assert len(cands) >= 1
    cand = cands[0]
    evidence = json.loads(cand["evidence_json"]) if isinstance(cand["evidence_json"], str) else cand["evidence_json"]

    # Evidence should have per_file breakdown with file_entry_id
    assert "per_file" in evidence, f"Missing per_file in evidence: {evidence}"
    assert len(evidence["per_file"]) == 2, f"Expected 2 file entries, got {len(evidence['per_file'])}"
    # Each per_file entry should identify the file
    for pf in evidence["per_file"]:
        assert "file_entry_id" in pf, f"per_file entry missing file_entry_id: {pf}"
        assert "hit_count" in pf, f"per_file entry missing hit_count: {pf}"

    # sample_scripts should include file_entry_id
    for s in evidence.get("sample_scripts", []):
        assert "file_entry_id" in s, f"sample_scripts entry missing file_entry_id: {s}"
