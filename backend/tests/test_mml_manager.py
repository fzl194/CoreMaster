# backend/tests/test_mml_manager.py
import pytest
import pytest_asyncio
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


@pytest.mark.asyncio
async def test_create_ne_version(client):
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
async def test_list_ne_versions(client):
    resp = await client.get(f"{BASE}/ne-versions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_delete_ne_version_no_files(client):
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
async def test_delete_ne_version_with_files_rejected(client):
    # Create version
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DEL",
        "version": "V300R001",
    })
    assert resp.status_code == 200
    ne_id = resp.json()["id"]

    # Upload a file
    mml_content = "ADD APN: APN=\"test\", BINDVPN=ENABLE;"
    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("sample.mml", mml_content.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200

    # Delete version should be rejected (400)
    resp = await client.delete(f"{BASE}/ne-versions/{ne_id}")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_file(client):
    # Create NE version first
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_UPLOAD",
        "version": "V100R002",
    })
    assert resp.status_code == 200
    ne_id = resp.json()["id"]

    # Upload
    mml_content = "ADD APN: APN=\"upload_test\", BINDVPN=ENABLE;"
    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("test.mml", mml_content.encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["filename"] == "test.mml"
    assert data[0]["ne_version_id"] == ne_id


@pytest.mark.asyncio
async def test_list_files(client):
    resp = await client.get(f"{BASE}/files")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_list_files_by_ne_version(client):
    # Create version
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_LIST",
        "version": "V100R003",
    })
    ne_id = resp.json()["id"]

    # Upload a file
    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("list_test.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 200

    # Filter by ne_version_id
    resp = await client.get(f"{BASE}/files", params={"ne_version_id": ne_id})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert all(f["ne_version_id"] == ne_id for f in data)


@pytest.mark.asyncio
async def test_get_file_detail(client):
    # Create version and upload
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DETAIL",
        "version": "V100R004",
    })
    ne_id = resp.json()["id"]

    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("detail.mml", b"detail content", "text/plain")},
    )
    file_id = resp.json()[0]["id"]

    # Get detail
    resp = await client.get(f"{BASE}/files/{file_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == file_id
    assert data["filename"] == "detail.mml"
    assert "vendor" in data  # JOINed from ne_version


@pytest.mark.asyncio
async def test_get_file_content(client):
    # Create version and upload
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_CONTENT",
        "version": "V100R005",
    })
    ne_id = resp.json()["id"]

    content = "ADD APN: APN=\"content_test\";"
    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("content.mml", content.encode("utf-8"), "text/plain")},
    )
    file_id = resp.json()[0]["id"]

    resp = await client.get(f"{BASE}/files/{file_id}/content")
    assert resp.status_code == 200
    assert resp.json()["content"] == content


@pytest.mark.asyncio
async def test_update_file_content(client):
    # Create version and upload
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_UPDATE",
        "version": "V100R006",
    })
    ne_id = resp.json()["id"]

    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("update.mml", b"old content", "text/plain")},
    )
    file_id = resp.json()[0]["id"]

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
async def test_download_file(client):
    # Create version and upload
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DOWNLOAD",
        "version": "V100R007",
    })
    ne_id = resp.json()["id"]

    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("download.txt", b"download me", "text/plain")},
    )
    file_id = resp.json()[0]["id"]

    resp = await client.get(f"{BASE}/files/{file_id}/download")
    assert resp.status_code == 200
    assert resp.text == "download me"


@pytest.mark.asyncio
async def test_delete_file(client):
    # Create version and upload
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DELFILE",
        "version": "V100R008",
    })
    ne_id = resp.json()["id"]

    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("deleteme.mml", b"to be deleted", "text/plain")},
    )
    file_id = resp.json()[0]["id"]

    # Delete
    resp = await client.delete(f"{BASE}/files/{file_id}")
    assert resp.status_code == 200

    # Verify it's gone
    resp = await client.get(f"{BASE}/files/{file_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stats(client):
    resp = await client.get(f"{BASE}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "file_count" in data
    assert "ne_version_count" in data
    assert isinstance(data["file_count"], int)
    assert isinstance(data["ne_version_count"], int)


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension(client):
    # Create version
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_BAD",
        "version": "V100R009",
    })
    ne_id = resp.json()["id"]

    # Upload a .py file — should be skipped
    resp = await client.post(
        f"{BASE}/upload?ne_version_id={ne_id}",
        files={"files": ("bad.py", b"print('hi')", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_duplicate_ne_version_rejected(client):
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DUP",
        "version": "V100R010",
    })
    assert resp.status_code == 200
    resp = await client.post(f"{BASE}/ne-versions", json={
        "vendor": "huawei",
        "ne_type": "5GC_DUP",
        "version": "V100R010",
    })
    assert resp.status_code == 409
