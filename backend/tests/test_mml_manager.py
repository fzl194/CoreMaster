# backend/tests/test_mml_manager.py
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

# Use a separate temp DB so we don't pollute the real one
_TEST_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "test_mml.db"


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
    # Ensure clean database for this test module
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()

    # Ensure the data directory exists
    _TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with _test_app.router.lifespan_context(_test_app):
        transport = ASGITransport(app=_test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    # Cleanup test DB after all tests in this module
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink()


BASE = "/api/plugins/mml_manager"


# ── Helper ──────────────────────────────────────────────────────────────────

async def _create_ne_version(client, vendor="huawei", ne_type="5GC", version="V100R001"):
    """Helper: create an NE version and return (ne_id, resp)."""
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": vendor,
        "ne_type": ne_type,
        "version": version,
    })
    return resp.json()["id"], resp


async def _upload_file(client, filename, content, ne_version_id, parent_id=None):
    """Helper: upload a single file via the new upload endpoint, return (entries, resp)."""
    metadata = json.dumps({
        "parent_id": parent_id,
        "items": {
            filename: {"ne_version_id": ne_version_id}
        }
    })
    resp = await client.post(
        f"{BASE}/upload",
        data={"metadata": metadata},
        files={"files": (filename, content, "text/plain")},
    )
    return resp.json(), resp


# ── 1. NE Version CRUD ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_01_create_ne_version(client):
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC",
        "version": "V100R001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["vendor"] == "huawei"
    assert data["ne_type"] == "5GC"
    assert data["version"] == "V100R001"
    assert "id" in data


@pytest.mark.asyncio
async def test_02_list_ne_versions(client):
    resp = await client.get(f"{BASE}/ne-versions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_03_delete_ne_version_no_files(client):
    # Create a version with no files
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "NGC",
        "version": "V200R001",
    })
    assert resp.status_code == 200
    ne_id = resp.json()["id"]

    # Delete should succeed
    resp = await client.delete(f"{BASE}/ne-versions/{ne_id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_04_delete_ne_version_with_files_rejected(client):
    # Create version
    ne_id, resp = await _create_ne_version(
        client, "huawei", "5GC_DEL", "V300R001"
    )
    assert resp.status_code == 200

    # Upload a file to root via new upload endpoint
    entries, resp = await _upload_file(
        client, "del_test.mml", b"ADD APN: APN=\"test\";", ne_id
    )
    assert resp.status_code == 200
    assert len(entries) == 1

    # Delete version should be rejected (400)
    resp = await client.delete(f"{BASE}/ne-versions/{ne_id}")
    assert resp.status_code == 400


# ── 5-6. Folder Management ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_05_create_folder(client):
    resp = await client.post(f"{BASE}/entries", json={"name": "测试文件夹"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "测试文件夹"
    assert data["type"] == "folder"
    assert data["parent_id"] is None
    assert "id" in data


@pytest.mark.asyncio
async def test_06_create_subfolder(client):
    # Create parent folder
    resp = await client.post(f"{BASE}/entries", json={"name": "父文件夹"})
    assert resp.status_code == 200
    folder_id = resp.json()["id"]

    # Create subfolder
    resp = await client.post(f"{BASE}/entries", json={
        "parent_id": folder_id,
        "name": "子文件夹",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "子文件夹"
    assert data["type"] == "folder"
    assert data["parent_id"] == folder_id


# ── 7-9. Entry Listing & Path ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_07_list_entries_root(client):
    resp = await client.get(f"{BASE}/entries")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Should contain the folders we created above
    assert len(data) >= 2
    folder_names = [e["name"] for e in data if e["type"] == "folder"]
    assert "测试文件夹" in folder_names
    assert "父文件夹" in folder_names


@pytest.mark.asyncio
async def test_08_list_entries_folder(client):
    # Find the parent folder id
    resp = await client.get(f"{BASE}/entries")
    entries = resp.json()
    parent_folder = next(e for e in entries if e["name"] == "父文件夹")
    folder_id = parent_folder["id"]

    # List contents of that folder
    resp = await client.get(f"{BASE}/entries", params={"parent_id": folder_id})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    subfolder_names = [e["name"] for e in data]
    assert "子文件夹" in subfolder_names


@pytest.mark.asyncio
async def test_09_get_entry_path(client):
    # Find the subfolder id
    resp = await client.get(f"{BASE}/entries")
    entries = resp.json()
    parent_folder = next(e for e in entries if e["name"] == "父文件夹")
    parent_id = parent_folder["id"]

    resp = await client.get(f"{BASE}/entries", params={"parent_id": parent_id})
    subfolder = next(e for e in resp.json() if e["name"] == "子文件夹")
    subfolder_id = subfolder["id"]

    # Get path for subfolder
    resp = await client.get(f"{BASE}/entries/{subfolder_id}/path")
    assert resp.status_code == 200
    path_chain = resp.json()
    assert len(path_chain) == 2
    assert path_chain[0]["name"] == "父文件夹"
    assert path_chain[1]["name"] == "子文件夹"
    assert path_chain[0]["id"] == parent_id
    assert path_chain[1]["id"] == subfolder_id


# ── 10-14. File Upload ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_10_upload_file_to_root(client):
    ne_id, resp = await _create_ne_version(
        client, "huawei", "5GC_UPLOAD_ROOT", "V100R010"
    )
    assert resp.status_code == 200

    entries, resp = await _upload_file(
        client, "root_test.mml", b"ADD APN: APN=\"root\";", ne_id
    )
    assert resp.status_code == 200
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "root_test.mml"
    assert entry["type"] == "file"
    assert entry["ne_version_id"] == ne_id
    assert entry["parent_id"] is None


@pytest.mark.asyncio
async def test_11_upload_file_to_folder(client):
    ne_id, resp = await _create_ne_version(
        client, "huawei", "5GC_UPLOAD_FOLDER", "V100R011"
    )
    assert resp.status_code == 200

    # Find the 测试文件夹 id
    resp = await client.get(f"{BASE}/entries")
    folder = next(e for e in resp.json() if e["name"] == "测试文件夹")
    folder_id = folder["id"]

    entries, resp = await _upload_file(
        client, "folder_test.mml", b"MOD APN: APN=\"folder\";", ne_id,
        parent_id=folder_id,
    )
    assert resp.status_code == 200
    assert len(entries) == 1
    assert entries[0]["name"] == "folder_test.mml"
    assert entries[0]["parent_id"] == folder_id


@pytest.mark.asyncio
async def test_12_upload_multiple_with_different_versions(client):
    ne1_id, _ = await _create_ne_version(
        client, "huawei", "5GC_MULTI_1", "V100R012A"
    )
    ne2_id, _ = await _create_ne_version(
        client, "huawei", "5GC_MULTI_2", "V100R012B"
    )

    metadata = json.dumps({
        "parent_id": None,
        "items": {
            "multi_a.mml": {"ne_version_id": ne1_id},
            "multi_b.txt": {"ne_version_id": ne2_id},
        }
    })
    resp = await client.post(
        f"{BASE}/upload",
        data={"metadata": metadata},
        files=[
            ("files", ("multi_a.mml", b"content A", "text/plain")),
            ("files", ("multi_b.txt", b"content B", "text/plain")),
        ],
    )
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    names = {e["name"] for e in entries}
    assert "multi_a.mml" in names
    assert "multi_b.txt" in names
    for e in entries:
        if e["name"] == "multi_a.mml":
            assert e["ne_version_id"] == ne1_id
        elif e["name"] == "multi_b.txt":
            assert e["ne_version_id"] == ne2_id


@pytest.mark.asyncio
async def test_13_upload_rejects_no_ne_version(client):
    # Upload a file whose metadata item references a non-existent ne_version_id
    metadata = json.dumps({
        "parent_id": None,
        "items": {
            "no_version.mml": {"ne_version_id": 999999}  # non-existent
        }
    })
    resp = await client.post(
        f"{BASE}/upload",
        data={"metadata": metadata},
        files={"files": ("no_version.mml", b"no version", "text/plain")},
    )
    assert resp.status_code == 200
    entries = resp.json()
    # The file should be skipped since the referenced ne_version_id does not exist
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_14_upload_rejects_bad_extension(client):
    ne_id, _ = await _create_ne_version(
        client, "huawei", "5GC_BAD_EXT", "V100R014"
    )

    # Upload a .py file — should be skipped
    metadata = json.dumps({
        "parent_id": None,
        "items": {
            "bad.py": {"ne_version_id": ne_id}
        }
    })
    resp = await client.post(
        f"{BASE}/upload",
        data={"metadata": metadata},
        files={"files": ("bad.py", b"print('hi')", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ── 15-18. File Content & Meta Operations ───────────────────────────────────


@pytest.mark.asyncio
async def test_15_get_file_content(client):
    ne_id, _ = await _create_ne_version(
        client, "huawei", "5GC_CONTENT", "V100R015"
    )
    content = "ADD APN: APN=\"content_test\";"
    entries, _ = await _upload_file(
        client, "content.mml", content.encode("utf-8"), ne_id
    )
    file_id = entries[0]["id"]

    resp = await client.get(f"{BASE}/files/{file_id}/content")
    assert resp.status_code == 200
    assert resp.json()["content"] == content


@pytest.mark.asyncio
async def test_16_update_file_content(client):
    ne_id, _ = await _create_ne_version(
        client, "huawei", "5GC_UPDATE", "V100R016"
    )
    entries, _ = await _upload_file(
        client, "update.mml", b"old content", ne_id
    )
    file_id = entries[0]["id"]

    # Update content
    new_content = "ADD APN: APN=\"updated\", BINDVPN=DISABLE;"
    resp = await client.put(
        f"{BASE}/files/{file_id}/content",
        json={"content": new_content},
    )
    assert resp.status_code == 200

    # Verify
    resp = await client.get(f"{BASE}/files/{file_id}/content")
    assert resp.status_code == 200
    assert resp.json()["content"] == new_content


@pytest.mark.asyncio
async def test_17_download_file(client):
    ne_id, _ = await _create_ne_version(
        client, "huawei", "5GC_DOWNLOAD", "V100R017"
    )
    entries, _ = await _upload_file(
        client, "download.txt", b"download me", ne_id
    )
    file_id = entries[0]["id"]

    resp = await client.get(f"{BASE}/files/{file_id}/download")
    assert resp.status_code == 200
    assert resp.text == "download me"


@pytest.mark.asyncio
async def test_18_update_file_meta(client):
    ne_id_old, _ = await _create_ne_version(
        client, "huawei", "5GC_META_OLD", "V100R018A"
    )
    ne_id_new, _ = await _create_ne_version(
        client, "huawei", "5GC_META_NEW", "V100R018B"
    )
    entries, _ = await _upload_file(
        client, "meta_test.mml", b"meta content", ne_id_old
    )
    file_id = entries[0]["id"]

    # Update ne_version_id
    resp = await client.put(
        f"{BASE}/files/{file_id}",
        json={"ne_version_id": ne_id_new},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ne_version_id"] == ne_id_new


# ── 19-20. Deletion ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_19_delete_file(client):
    ne_id, _ = await _create_ne_version(
        client, "huawei", "5GC_DELFILE", "V100R019"
    )
    entries, _ = await _upload_file(
        client, "deleteme.mml", b"to be deleted", ne_id
    )
    file_id = entries[0]["id"]

    # Delete using DELETE /entries/{id}
    resp = await client.delete(f"{BASE}/entries/{file_id}")
    assert resp.status_code == 200

    # Verify it's gone - get content should 404
    resp = await client.get(f"{BASE}/files/{file_id}/content")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_20_delete_folder_recursive(client):
    ne_id, _ = await _create_ne_version(
        client, "huawei", "5GC_DELFOLDER", "V100R020"
    )

    # Create a folder for deletion test
    resp = await client.post(f"{BASE}/entries", json={"name": "删除测试文件夹"})
    assert resp.status_code == 200
    folder_id = resp.json()["id"]

    # Upload a file into the folder
    entries, resp = await _upload_file(
        client, "inside.mml", b"inside folder", ne_id,
        parent_id=folder_id,
    )
    assert resp.status_code == 200
    assert len(entries) == 1
    file_id = entries[0]["id"]

    # Create a subfolder
    resp = await client.post(f"{BASE}/entries", json={
        "parent_id": folder_id,
        "name": "子目录",
    })
    assert resp.status_code == 200
    subfolder_id = resp.json()["id"]

    # Upload a file into the subfolder
    entries2, resp = await _upload_file(
        client, "deep.mml", b"deep inside", ne_id,
        parent_id=subfolder_id,
    )
    assert resp.status_code == 200
    deep_file_id = entries2[0]["id"]

    # Delete the top-level folder
    resp = await client.delete(f"{BASE}/entries/{folder_id}")
    assert resp.status_code == 200

    # Verify the folder, subfolder, and all files are gone
    resp = await client.get(f"{BASE}/entries/{folder_id}/path")
    assert resp.status_code == 404

    resp = await client.get(f"{BASE}/files/{file_id}/content")
    assert resp.status_code == 404

    resp = await client.get(f"{BASE}/files/{deep_file_id}/content")
    assert resp.status_code == 404


# ── 21-22. Stats & Duplicate ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_21_stats(client):
    resp = await client.get(f"{BASE}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "file_count" in data
    assert "ne_version_count" in data
    assert isinstance(data["file_count"], int)
    assert isinstance(data["ne_version_count"], int)
    assert data["file_count"] >= 1
    assert data["ne_version_count"] >= 1


@pytest.mark.asyncio
async def test_22_duplicate_ne_version_rejected(client):
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DUP",
        "version": "V100R022",
    })
    assert resp.status_code == 200
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DUP",
        "version": "V100R022",
    })
    assert resp.status_code == 409
