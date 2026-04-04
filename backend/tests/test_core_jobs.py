import pytest
import pytest_asyncio


def test_job_status_enum():
    from core.jobs.models import JobStatus
    assert JobStatus.queued == "queued"
    assert JobStatus.running == "running"
    assert JobStatus.completed == "completed"
    assert JobStatus.failed == "failed"
    assert JobStatus.cancelled == "cancelled"


def test_job_item_status_enum():
    from core.jobs.models import JobItemStatus
    assert JobItemStatus.pending == "pending"
    assert JobItemStatus.running == "running"
    assert JobItemStatus.completed == "completed"
    assert JobItemStatus.failed == "failed"
    assert JobItemStatus.skipped == "skipped"


def test_create_tables_sql():
    from core.jobs.models import CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE
    assert "job" in CREATE_JOBS_TABLE.lower()
    assert "job_item" in CREATE_JOB_ITEMS_TABLE.lower()


# ── Task 2: JobService tests ──


@pytest_asyncio.fixture
async def job_db(tmp_path):
    """创建临时数据库并初始化 job 表"""
    from core.services.database import DatabaseService
    from core.jobs.models import CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE, CREATE_INDEXES

    db = DatabaseService(db_path=str(tmp_path / "test.db"))
    await db.start()
    await db.execute(CREATE_JOBS_TABLE)
    await db.execute(CREATE_JOB_ITEMS_TABLE)
    for idx_sql in CREATE_INDEXES:
        await db.execute(idx_sql)
    yield db
    await db.stop()


@pytest.mark.asyncio
async def test_create_job(job_db):
    from core.jobs.service import JobService
    svc = JobService(job_db)
    job_id = await svc.create_job("mining", {"file_ids": [1, 2]}, [1, 2])
    assert job_id > 0

    job = await svc.get_job(job_id)
    assert job["type"] == "mining"
    assert job["status"] == "queued"
    assert job["progress_total"] == 2


@pytest.mark.asyncio
async def test_list_jobs(job_db):
    from core.jobs.service import JobService
    svc = JobService(job_db)
    await svc.create_job("mining", {}, ["a"])
    await svc.create_job("mining", {}, ["b"])
    jobs = await svc.list_jobs()
    assert len(jobs) == 2


@pytest.mark.asyncio
async def test_cancel_job(job_db):
    from core.jobs.service import JobService
    svc = JobService(job_db)
    job_id = await svc.create_job("mining", {}, ["a"])
    ok = await svc.cancel_job(job_id)
    assert ok is True
    job = await svc.get_job(job_id)
    assert job["status"] == "cancelled"


@pytest.mark.asyncio
async def test_update_item_status(job_db):
    from core.jobs.service import JobService
    svc = JobService(job_db)
    job_id = await svc.create_job("mining", {}, [1])
    items = await svc.get_job_items(job_id)
    item_id = items[0]["id"]

    await svc.update_item_status(item_id, "running")
    items = await svc.get_job_items(job_id)
    assert items[0]["status"] == "running"


@pytest.mark.asyncio
async def test_get_pending_jobs(job_db):
    from core.jobs.service import JobService
    svc = JobService(job_db)
    id1 = await svc.create_job("mining", {}, ["a"])
    id2 = await svc.create_job("mining", {}, ["b"])
    await svc.update_job_status(id2, "running")

    pending = await svc.get_pending_jobs()
    assert len(pending) == 1
    assert pending[0]["id"] == id1
