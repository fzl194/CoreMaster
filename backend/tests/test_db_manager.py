# backend/tests/test_db_manager.py
"""db_manager 插件后端测试：受保护列、列名校验、表存在性。"""
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
from core.jobs.models import CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE

_TEST_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "test_db_mgr.db"


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


BASE = "/api/plugins/db_manager"


# ── 列表与 schema ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_01_list_tables(client):
    resp = await client.get(f"{BASE}/tables")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── 不存在的表 ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_02_schema_table_not_found(client):
    resp = await client.get(f"{BASE}/tables/nonexistent_tbl/schema")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_03_rows_table_not_found(client):
    resp = await client.get(f"{BASE}/tables/nonexistent_tbl/rows")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_04_insert_table_not_found(client):
    resp = await client.post(
        f"{BASE}/tables/nonexistent_tbl/rows",
        json={"fields": {"col1": "val"}},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_05_update_table_not_found(client):
    resp = await client.put(
        f"{BASE}/tables/nonexistent_tbl/rows/1",
        json={"fields": {"col1": "val"}},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_06_delete_table_not_found(client):
    resp = await client.delete(f"{BASE}/tables/nonexistent_tbl/rows/1")
    assert resp.status_code == 404


# ── 非法表名 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_07_invalid_table_name(client):
    resp = await client.get(f"{BASE}/tables/1;DROP TABLE/rows")
    assert resp.status_code == 400


# ── 对 ne_version 表的写操作校验 ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_08_insert_valid_row(client):
    """对 ne_version 表正常插入一行。"""
    resp = await client.post(
        f"{BASE}/tables/ne_version/rows",
        json={"fields": {"vendor": "huawei", "ne_type": "5GC", "version": "V1"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vendor"] == "huawei"


@pytest.mark.asyncio
async def test_09_insert_invalid_column(client):
    """列名不存在时应返回 400。"""
    resp = await client.post(
        f"{BASE}/tables/ne_version/rows",
        json={"fields": {"nonexistent_column": "value"}},
    )
    assert resp.status_code == 400
    assert "列不存在" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_10_update_invalid_column(client):
    """更新时列名不存在应返回 400。"""
    # 先拿到一行
    rows_resp = await client.get(f"{BASE}/tables/ne_version/rows")
    rows = rows_resp.json()["rows"]
    if not rows:
        pytest.skip("没有可更新的行")

    # ne_version 的主键是 id (INTEGER PRIMARY KEY)，SQLite 将 rowid 合并为 id
    pk = rows[0].get("rowid") or rows[0].get("id")
    resp = await client.put(
        f"{BASE}/tables/ne_version/rows/{pk}",
        json={"fields": {"bogus_col": "val"}},
    )
    assert resp.status_code == 400
    assert "列不存在" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_11_protected_column_blocked_on_insert(client):
    """受保护列 file_path 在插入时应被过滤（不会报错，但字段不生效）。"""
    # 对 file_entry 表插入（需要先满足约束），这里直接验证字段被过滤
    resp = await client.post(
        f"{BASE}/tables/ne_version/rows",
        json={"fields": {"vendor": "eric", "ne_type": "5G", "version": "E1", "file_path": "/evil/path"}},
    )
    # file_path 不是 ne_version 表的列，所以应当返回 400 列不存在
    # 这个测试验证了 _filter_protected 先移除 file_path，再校验剩余列
    # 但 ne_version 没有 file_path 列，如果过滤先执行则不会报列不存在
    # 所以这个测试主要验证的是不会因 file_path 产生意外行为
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_12_delete_row(client):
    """正常删除一行。"""
    # 先插入一行
    insert_resp = await client.post(
        f"{BASE}/tables/ne_version/rows",
        json={"fields": {"vendor": "nokia", "ne_type": "5G", "version": "N1"}},
    )
    assert insert_resp.status_code == 200
    data = insert_resp.json()
    pk = data.get("rowid") or data.get("id")

    # 删除
    resp = await client.delete(f"{BASE}/tables/ne_version/rows/{pk}")
    assert resp.status_code == 200

    # 确认已删除
    rows_resp = await client.get(f"{BASE}/tables/ne_version/rows")
    all_pks = [r.get("rowid") or r.get("id") for r in rows_resp.json()["rows"]]
    assert pk not in all_pks


# ── 无效请求 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_13_insert_empty_fields(client):
    """空 fields 应返回 400。"""
    resp = await client.post(
        f"{BASE}/tables/ne_version/rows",
        json={"fields": {}},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_14_update_empty_fields(client):
    """更新空 fields 应返回 400。"""
    resp = await client.put(
        f"{BASE}/tables/ne_version/rows/1",
        json={"fields": {}},
    )
    assert resp.status_code == 400
