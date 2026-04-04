import asyncio
import json
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class JobWorker:
    """后台 worker 循环：从队列取 job，逐 item 执行"""

    def __init__(self, job_service, poll_interval: float = 0.5) -> None:
        self._svc = job_service
        self._handlers: dict[str, Callable] = {}
        self._running = False
        self._poll_interval = poll_interval

    def register_handler(self, job_type: str, handler: Callable) -> None:
        self._handlers[job_type] = handler

    async def start(self) -> None:
        self._running = True
        while self._running:
            pending = await self._svc.get_pending_jobs()
            for job in pending:
                # 重新检查状态（可能已被取消）
                fresh = await self._svc.get_job(job["id"])
                if not fresh or fresh["status"] != "queued":
                    continue
                await self._process_job(fresh)
            await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        self._running = False

    async def _process_job(self, job: dict) -> None:
        job_id = job["id"]
        job_type = job["type"]
        handler = self._handlers.get(job_type)
        if not handler:
            logger.warning("No handler for job type: %s", job_type)
            return

        await self._svc.update_job_status(job_id, "running")
        items = await self._svc.get_job_items(job_id)

        try:
            result = await handler(job, items)
            await self._svc.update_job_status(
                job_id, "completed", result_json=json.dumps(result, ensure_ascii=False) if result else None
            )
        except Exception as e:
            logger.exception("Job %d failed", job_id)
            await self._svc.update_job_status(
                job_id, "failed", error_message=str(e)
            )
