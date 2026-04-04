import pytest


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
