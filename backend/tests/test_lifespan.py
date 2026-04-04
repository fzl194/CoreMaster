import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def services(tmp_path):
    """搭建完整的服务栈（与 main.py lifespan 一致）"""
    from core.services.database import DatabaseService
    from core.services.registry import ServiceRegistry
    from core.jobs.service import JobService
    from core.jobs.worker import JobWorker
    from core.jobs.models import CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE, CREATE_INDEXES
    from core.events.bus import PluginEventBus

    db = DatabaseService(db_path=str(tmp_path / "test.db"))
    await db.start()

    # 初始化 job 表（与 main.py 一致）
    for sql in [CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE] + CREATE_INDEXES:
        await db.execute(sql)

    registry = ServiceRegistry()
    registry.register(DatabaseService, db)

    job_service = JobService(db)
    registry.register(JobService, job_service)

    event_bus = PluginEventBus()
    registry.register(PluginEventBus, event_bus)

    worker = JobWorker(job_service)
    registry.register(JobWorker, worker)

    yield {"db": db, "registry": registry, "worker": worker, "event_bus": event_bus}
    await db.stop()


@pytest.mark.asyncio
async def test_lifespan_registers_all_services(services):
    """验证所有核心服务正确注册"""
    from core.jobs.service import JobService
    from core.jobs.worker import JobWorker
    from core.events.bus import PluginEventBus

    reg = services["registry"]
    assert reg.get(JobService) is not None, "JobService not registered"
    assert reg.get(JobWorker) is not None, "JobWorker not registered"
    assert reg.get(PluginEventBus) is not None, "PluginEventBus not registered"


@pytest.mark.asyncio
async def test_worker_handler_registration_via_registry(services):
    """验证插件可以通过 registry 获取 JobWorker 并注册 handler"""
    from core.jobs.worker import JobWorker

    worker = services["registry"].get(JobWorker)
    called = []

    async def handler(job, items):
        called.append(True)

    worker.register_handler("test_type", handler)
    assert "test_type" in worker._handlers


@pytest.mark.asyncio
async def test_event_bus_subscription_via_registry(services):
    """验证插件可以通过 registry 获取 PluginEventBus 并订阅事件"""
    bus = services["event_bus"]
    received = []
    bus.on("file.deleted", lambda p: received.append(p))
    await bus.emit("file.deleted", {"file_entry_id": 1})
    assert len(received) == 1
    assert received[0]["file_entry_id"] == 1
