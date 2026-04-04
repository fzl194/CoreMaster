import json

from core.jobs.models import JobStatus, JobItemStatus


class JobService:
    """通用任务服务：job / job_item 的 CRUD 操作"""

    def __init__(self, db) -> None:
        self.db = db

    async def create_job(self, job_type: str, params: dict, item_keys: list) -> int:
        await self.db.execute(
            "INSERT INTO job (type, status, params_json, progress_total) VALUES (?, 'queued', ?, ?)",
            (job_type, json.dumps(params, ensure_ascii=False), len(item_keys)),
        )
        row = await self.db.query("SELECT last_insert_rowid() as id")
        job_id = row[0]["id"]
        for key in item_keys:
            await self.db.execute(
                "INSERT INTO job_item (job_id, item_key, status) VALUES (?, ?, 'pending')",
                (job_id, key),
            )
        return job_id

    async def get_job(self, job_id: int) -> dict | None:
        rows = await self.db.query("SELECT * FROM job WHERE id=?", (job_id,))
        return rows[0] if rows else None

    async def list_jobs(self, job_type: str | None = None, status: str | None = None, limit: int = 20) -> list[dict]:
        conditions = []
        params: list = []
        if job_type:
            conditions.append("type=?")
            params.append(job_type)
        if status:
            conditions.append("status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await self.db.query(
            f"SELECT * FROM job {where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return rows

    async def cancel_job(self, job_id: int) -> bool:
        job = await self.get_job(job_id)
        if not job or job["status"] not in ("queued", "running"):
            return False
        await self.db.execute(
            "UPDATE job SET status='cancelled', finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
        )
        # 将未开始的 item 标记为 skipped
        await self.db.execute(
            "UPDATE job_item SET status='skipped' WHERE job_id=? AND status='pending'",
            (job_id,),
        )
        return True

    async def update_job_status(self, job_id: int, status: str, **kwargs) -> None:
        sets = ["status=?"]
        vals = [status]
        if status == "running":
            sets.append("started_at=CURRENT_TIMESTAMP")
        if status in ("completed", "failed", "cancelled"):
            sets.append("finished_at=CURRENT_TIMESTAMP")
        for k, v in kwargs.items():
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(job_id)
        await self.db.execute(
            f"UPDATE job SET {', '.join(sets)} WHERE id=?", tuple(vals)
        )

    async def update_item_status(self, item_id: int, status: str, **kwargs) -> None:
        sets = ["status=?"]
        vals = [status]
        if status == "running":
            sets.append("started_at=CURRENT_TIMESTAMP")
        if status in ("completed", "failed", "skipped"):
            sets.append("finished_at=CURRENT_TIMESTAMP")
        for k, v in kwargs.items():
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(item_id)
        await self.db.execute(
            f"UPDATE job_item SET {', '.join(sets)} WHERE id=?", tuple(vals)
        )

    async def get_pending_jobs(self) -> list[dict]:
        rows = await self.db.query(
            "SELECT * FROM job WHERE status='queued' ORDER BY created_at ASC"
        )
        return rows

    async def get_job_items(self, job_id: int) -> list[dict]:
        return await self.db.query(
            "SELECT * FROM job_item WHERE job_id=? ORDER BY id", (job_id,)
        )

    async def increment_progress(self, job_id: int) -> None:
        await self.db.execute(
            "UPDATE job SET progress_current = progress_current + 1 WHERE id=?",
            (job_id,),
        )
