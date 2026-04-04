# 图谱挖掘体系演进 — 第一阶段实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将图谱挖掘从 mml_manager 剥离为独立 graph_mining 插件，接入 core/jobs 通用任务框架实现异步挖掘，重构评估管线，前端独立页面。

**Architecture:** core 层新增 jobs（通用任务框架）和 events（跨插件事件通知）两个模块。graph_mining 作为独立物理插件从 mml_manager 迁移全部挖掘代码，接入任务框架。前端从单一 DependencyMining.vue 拆为独立 GraphMining 页面。mml_manager 瘦身后只保留文件管理 + 命令提取，通过事件通知 graph_mining 清理。

**Tech Stack:** Python 3 / FastAPI / aiosqlite / pytest-asyncio (后端) | Vue 3 / Naive UI / TypeScript (前端)

**设计文档:** `docs/plans/2026-04-03-graph-mining-evolution-design.md` (v2, 已审查通过)

> **修订说明:**
> - v1：初始版本（2026-04-04）
> - v2：根据 Codex 审查修订 3 项问题（Task 3 `_json.dumps` 修正、Task 5 `JobWorker` 注册到 registry、Task 10a 新增 `CandidateService` 统一 owner）
> - v3：根据 Codex 第二轮审查修订 3 项问题（Task 11 重算链路补 total_mined + 清理残留代码、Task 3 补 `import json`、依赖图+总计同步 v2 结构）

---

## Task 1: core/jobs 数据模型与枚举

**Files:**
- Create: `backend/core/jobs/__init__.py`
- Create: `backend/core/jobs/models.py`
- Test: `backend/tests/test_core_jobs.py`

**Step 1: 写测试 — 模型导入与枚举值**

```python
# backend/tests/test_core_jobs.py
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
```

**Step 2: 运行测试验证失败**

```
Run: cd backend && python -m pytest tests/test_core_jobs.py -v
Expected: FAIL — ModuleNotFoundError: No module named 'core.jobs'
```

**Step 3: 实现 models.py**

```python
# backend/core/jobs/__init__.py
# 空包标记
```

```python
# backend/core/jobs/models.py
from enum import Enum

class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class JobItemStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"

CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS job (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    params_json TEXT NOT NULL DEFAULT '{}',
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);
"""

CREATE_JOB_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS job_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT,
    error_message TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES job(id)
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_job_type ON job(type);",
    "CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);",
    "CREATE INDEX IF NOT EXISTS idx_job_item_job_id ON job_item(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_job_item_status ON job_item(status);",
]
```

**Step 4: 运行测试验证通过**

```
Run: cd backend && python -m pytest tests/test_core_jobs.py -v
Expected: 3 passed
```

**Step 5: 提交**

```
git add backend/core/jobs/__init__.py backend/core/jobs/models.py backend/tests/test_core_jobs.py
git commit -m "[claude]: add core/jobs data models with enums and SQL schema"
```

---

## Task 2: core/jobs JobService

**Files:**
- Create: `backend/core/jobs/service.py`
- Modify: `backend/tests/test_core_jobs.py` — 追加 service 测试

**Step 1: 写测试 — JobService CRUD**

追加到 `test_core_jobs.py`:

```python
import pytest

@pytest.fixture
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
    job_id = await svc.create_job("mining", {"file_ids": [1, 2]}, ["file:1", "file:2"])
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
    job_id = await svc.create_job("mining", {}, ["file:1"])
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
```

**Step 2: 运行测试验证失败**

```
Run: cd backend && python -m pytest tests/test_core_jobs.py -v -k "job_db"
Expected: FAIL — ModuleNotFoundError: No module named 'core.jobs.service'
```

**Step 3: 实现 service.py**

```python
# backend/core/jobs/service.py
import json
from core.jobs.models import JobStatus, JobItemStatus


class JobService:
    """通用任务服务：job / job_item 的 CRUD 操作"""

    def __init__(self, db) -> None:
        self.db = db

    async def create_job(self, job_type: str, params: dict, item_keys: list[str]) -> int:
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
```

**Step 4: 运行测试验证通过**

```
Run: cd backend && python -m pytest tests/test_core_jobs.py -v
Expected: 8 passed
```

**Step 5: 提交**

```
git add backend/core/jobs/service.py backend/tests/test_core_jobs.py
git commit -m "[claude]: add core/jobs JobService with CRUD operations"
```

---

## Task 3: core/jobs JobWorker

**Files:**
- Create: `backend/core/jobs/worker.py`
- Modify: `backend/tests/test_core_jobs.py` — 追加 worker 测试

**Step 1: 写测试 — Worker 消费任务**

追加到 `test_core_jobs.py`:

```python
@pytest.mark.asyncio
async def test_worker_processes_job(job_db):
    from core.jobs.service import JobService
    from core.jobs.worker import JobWorker
    import asyncio

    svc = JobService(job_db)
    worker = JobWorker(svc)

    processed = []

    async def mock_handler(job, items):
        processed.append(job["id"])
        return {"done": True}

    worker.register_handler("test_type", mock_handler)

    job_id = await svc.create_job("test_type", {}, ["item1"])

    # 启动 worker 并让它处理一个任务后停止
    task = asyncio.create_task(worker.start())
    await asyncio.sleep(0.3)
    await worker.stop()
    await task

    assert len(processed) == 1
    job = await svc.get_job(job_id)
    assert job["status"] == "completed"
```

**Step 2: 运行测试验证失败**

```
Run: cd backend && python -m pytest tests/test_core_jobs.py::test_worker_processes_job -v
Expected: FAIL
```

**Step 3: 实现 worker.py**

```python
# backend/core/jobs/worker.py
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
```

> 注意：`result_json` 需要传 json 字符串。上面 handler 调用中 `import json` 已在顶部。如 `result` 为 None，传 None。

**Step 4: 运行测试验证通过**

```
Run: cd backend && python -m pytest tests/test_core_jobs.py -v
Expected: 9 passed
```

**Step 5: 提交**

```
git add backend/core/jobs/worker.py backend/tests/test_core_jobs.py
git commit -m "[claude]: add core/jobs JobWorker with handler registration"
```

---

## Task 4: core/events 插件事件总线

**Files:**
- Create: `backend/core/events/__init__.py`
- Create: `backend/core/events/bus.py`
- Test: `backend/tests/test_core_events.py`

**Step 1: 写测试**

```python
# backend/tests/test_core_events.py
import pytest

@pytest.mark.asyncio
async def test_event_bus_on_and_emit():
    from core.events.bus import PluginEventBus
    bus = PluginEventBus()
    received = []
    bus.on("file.deleted", lambda payload: received.append(payload))
    await bus.emit("file.deleted", {"file_entry_id": 42})
    assert len(received) == 1
    assert received[0]["file_entry_id"] == 42

@pytest.mark.asyncio
async def test_event_bus_multiple_handlers():
    from core.events.bus import PluginEventBus
    bus = PluginEventBus()
    results = []
    bus.on("test", lambda p: results.append("a"))
    bus.on("test", lambda p: results.append("b"))
    await bus.emit("test", {})
    assert results == ["a", "b"]

@pytest.mark.asyncio
async def test_event_bus_handler_error_not_blocked():
    """handler 失败不应阻塞后续 handler 或调用方"""
    from core.events.bus import PluginEventBus
    bus = PluginEventBus()
    results = []

    async def bad_handler(p):
        raise RuntimeError("boom")

    bus.on("test", bad_handler)
    bus.on("test", lambda p: results.append("ok"))

    # emit 不应抛异常
    await bus.emit("test", {})
    assert "ok" in results

@pytest.mark.asyncio
async def test_event_bus_no_handlers():
    from core.events.bus import PluginEventBus
    bus = PluginEventBus()
    # emit 没有 handler 的类型不应报错
    await bus.emit("unknown.event", {"x": 1})
```

**Step 2: 运行测试验证失败**

```
Run: cd backend && python -m pytest tests/test_core_events.py -v
Expected: FAIL
```

**Step 3: 实现 bus.py**

```python
# backend/core/events/__init__.py
# 空包标记
```

```python
# backend/core/events/bus.py
import asyncio
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)


class PluginEventBus:
    """轻量级插件间事件通知。同步调用，不跨进程。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def emit(self, event_type: str, payload: dict) -> None:
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Event handler failed for %s", event_type)
```

**Step 4: 运行测试验证通过**

```
Run: cd backend && python -m pytest tests/test_core_events.py -v
Expected: 4 passed
```

**Step 5: 提交**

```
git add backend/core/events/__init__.py backend/core/events/bus.py backend/tests/test_core_events.py
git commit -m "[claude]: add core/events PluginEventBus for cross-plugin lifecycle notifications"
```

---

## Task 5: core/jobs 和 core/events 接入主应用

**Files:**
- Modify: `backend/main.py` — 初始化 JobService、JobWorker、PluginEventBus

**Step 1: 在 lifespan 中初始化新服务**

在 `backend/main.py` 的 lifespan 函数中，在 parser 注册后添加：

```python
# 新增导入
from core.jobs.service import JobService
from core.jobs.worker import JobWorker
from core.jobs.models import CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE, CREATE_INDEXES
from core.events.bus import PluginEventBus

# 在 registry.register(ParserService, parser) 之后：

# 初始化 job 表
for sql in [CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE] + CREATE_INDEXES:
    await db.execute(sql)

# 注册通用服务
job_service = JobService(db)
registry.register(JobService, job_service)

event_bus = PluginEventBus()
registry.register(PluginEventBus, event_bus)

# 创建 worker 并注册到 registry，插件可通过 ctx.get_service(JobWorker) 获取并注册 handler
worker = JobWorker(job_service)
registry.register(JobWorker, worker)

app.state.job_worker = worker
app.state.event_bus = event_bus

# 在所有插件加载完成后（yield 之前）启动 worker
# 注意：放在插件加载循环之后，确保 handler 已全部注册
import asyncio
asyncio.create_task(worker.start())
```

在清理阶段（yield 之后）添加：

```python
await worker.stop()
```

**Step 2: 验证 lifespan 启动与服务注册**

新增 `backend/tests/test_lifespan.py`：

```python
import pytest
from main import app


@pytest.mark.asyncio
async def test_lifespan_registers_services():
    """验证应用 lifespan 正确注册 JobService、JobWorker、PluginEventBus"""
    async with app.router.lifespan_context(app):
        # 从 app.state.registry 取得全局注册表（与 main.py startup 一致）
        from core.services.registry import ServiceRegistry
        from core.jobs.service import JobService
        from core.jobs.worker import JobWorker
        from core.events.bus import PluginEventBus

        reg = app.state.registry
        assert reg.get(JobService) is not None, "JobService not registered"
        assert reg.get(JobWorker) is not None, "JobWorker not registered"
        assert reg.get(PluginEventBus) is not None, "PluginEventBus not registered"
```

```
Run: cd backend && python -m pytest tests/test_lifespan.py -v
Expected: 1 passed
```
**Step 3: 更新 PluginContext**

在 `backend/core/plugin/context.py` 中，`get_service` 和 `register_service` 已通过 registry 代理，无需改动。插件可以通过 `ctx.get_service(JobService)` 和 `ctx.get_service(PluginEventBus)` 获取服务。

**Step 4: 提交**

```
git add backend/main.py
git commit -m "[claude]: integrate core/jobs and core/events into application lifespan"
```

---

## Task 6: graph_mining 插件骨架

**Files:**
- Create: `backend/plugins/graph_mining/plugin.toml`
- Create: `backend/plugins/graph_mining/__init__.py`
- Create: `backend/plugins/graph_mining/main.py` — 插件类 + 表建删
- Modify: `backend/plugins/order.toml` — 新增 graph_mining

**Step 1: 创建 plugin.toml**

```toml
# backend/plugins/graph_mining/plugin.toml
[plugin]
name = "graph_mining"
version = "0.1.0"
description = "MML 命令参数依赖关系挖掘与图谱管理"

[plugin.backend]
entry = "main.py"
routes_prefix = "/api/plugins/graph_mining"

[plugin.frontend]
entry = "src/index.vue"
menu_title = "图谱挖掘"
icon = "git-branch"
```

**Step 2: 更新 order.toml**

```toml
# backend/plugins/order.toml
order = ["mml_manager", "graph_mining", "db_manager"]
```

**Step 3: 创建 main.py 骨架**

```python
# backend/plugins/graph_mining/main.py
import json
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.db = None
        self.parser = None
        self.job_service = None
        self.event_bus = None

    async def on_register(self, ctx):
        self.db = ctx.get_service(
            __import__("core.services.database", fromlist=["DatabaseService"]).DatabaseService
        )
        # 简化获取方式
        from core.services.database import DatabaseService
        from core.services.parser import ParserService
        from core.jobs.service import JobService
        from core.events.bus import PluginEventBus

        self.db = ctx.get_service(DatabaseService)
        self.parser = ctx.get_service(ParserService)
        self.job_service = ctx.get_service(JobService)
        self.event_bus = ctx.get_service(PluginEventBus)

        await self._create_tables()
        self._register_routes()

    async def _create_tables(self):
        # dependency_candidate (迁移自 mml_manager，新增 llm_assessment_json)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS dependency_candidate (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ne_version_id INTEGER NOT NULL,
                ref_command TEXT NOT NULL,
                ref_param TEXT NOT NULL,
                def_command TEXT NOT NULL,
                def_param TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                confidence REAL NOT NULL DEFAULT 0.0,
                scores_json TEXT NOT NULL DEFAULT '{}',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                source_batch TEXT,
                review_history_json TEXT DEFAULT '[]',
                graph_edge_id INTEGER,
                review_route TEXT,
                non_graph_reason TEXT,
                non_graph_reviewer TEXT,
                active_algorithm_version TEXT DEFAULT 'v1',
                llm_assessment_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ne_version_id, ref_command, ref_param, def_command, def_param)
            );
        """)

        # candidate_contribution
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS candidate_contribution (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                file_entry_id INTEGER NOT NULL,
                algorithm_version TEXT NOT NULL DEFAULT 'v1',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                scores_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(candidate_id, file_entry_id, algorithm_version)
            );
        """)

        # file_mining_record (演进：新增 last_job_id, last_error)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS file_mining_record (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_entry_id INTEGER NOT NULL UNIQUE,
                ne_version_id INTEGER NOT NULL,
                mined INTEGER NOT NULL DEFAULT 0,
                algorithm_version TEXT NOT NULL DEFAULT 'v1',
                command_count INTEGER NOT NULL DEFAULT 0,
                last_job_id INTEGER,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # graph_edge
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS graph_edge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ne_version_id INTEGER NOT NULL,
                ref_command TEXT NOT NULL,
                ref_param TEXT NOT NULL,
                def_command TEXT NOT NULL,
                def_param TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'mined',
                confidence REAL NOT NULL DEFAULT 0.0,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                confirmed_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ne_version_id, ref_command, ref_param, def_command, def_param)
            );
        """)

        # graph_changelog
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS graph_changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dependency_id INTEGER,
                candidate_id INTEGER,
                change_type TEXT NOT NULL,
                snapshot_after TEXT,
                trigger_type TEXT,
                trigger_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 索引
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_dc_status ON dependency_candidate(status);")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_dc_ne_version ON dependency_candidate(ne_version_id);")
        await self.db.execute("CREATE INDEX IF NOT EXISTS idx_cc_candidate ON candidate_contribution(candidate_id);")

    def _register_routes(self):
        # 路由将在后续 Task 中逐步添加
        pass
```

**Step 4: 验证插件可加载**

```
Run: cd backend && python -c "from plugins.graph_mining.main import Plugin; p = Plugin(); print('OK')"
Expected: OK
```

**Step 5: 提交**

```
git add backend/plugins/graph_mining/ backend/plugins/order.toml
git commit -m "[claude]: add graph_mining plugin skeleton with schema creation"
```

---

## Task 7: 迁移 candidate_engine → graph_mining/engine

**Files:**
- Create: `backend/plugins/graph_mining/engine/__init__.py`
- Create: `backend/plugins/graph_mining/engine/scorers.py` — 从 candidate_engine.py 迁移

**Step 1: 迁移**

将 `backend/plugins/mml_manager/candidate_engine.py` 的全部内容复制到 `backend/plugins/graph_mining/engine/scorers.py`。

不需要改动函数签名和逻辑，仅移动文件位置。这个文件包含纯函数（无 DB 依赖），迁移零风险。

```python
# backend/plugins/graph_mining/engine/__init__.py
from .scorers import (
    generate_candidates,
    generate_single_file_candidates,
    aggregate_contributions,
    DEFAULT_WEIGHTS,
    THETA_HIGH,
    THETA_LOW,
)
```

**Step 2: 验证导入路径**

```
Run: cd backend && python -c "
import sys; sys.path.insert(0, 'plugins/graph_mining')
from engine.scorers import generate_single_file_candidates, DEFAULT_WEIGHTS
print('weights:', DEFAULT_WEIGHTS)
print('OK')
"
Expected: weights: {'support': 0.35, ...} OK
```

**Step 3: 提交**

```
git add backend/plugins/graph_mining/engine/
git commit -m "[claude]: migrate candidate_engine to graph_mining/engine/scorers"
```

---

## Task 8: 评估管线 — HardRule + Pipeline

**Files:**
- Create: `backend/plugins/graph_mining/engine/hard_rules.py`
- Create: `backend/plugins/graph_mining/engine/pipeline.py`
- Test: `backend/tests/test_mining_pipeline.py`

**Step 1: 写测试 — HardRule 过滤**

```python
# backend/tests/test_mining_pipeline.py
import pytest

def test_same_parameter_rule_filters():
    from plugins.graph_mining.engine.hard_rules import SameParameterRule
    rule = SameParameterRule()
    # ref_param == def_param → 淘汰
    candidate = {"ref_cmd": "ADD APN", "ref_param": "APNNAME", "def_cmd": "ADD VPN", "def_param": "APNNAME"}
    assert rule.check(candidate) is False
    # 不同参数 → 通过
    candidate["def_param"] = "VPNNAME"
    assert rule.check(candidate) is True

def test_self_reference_rule_filters():
    from plugins.graph_mining.engine.hard_rules import SelfReferenceRule
    rule = SelfReferenceRule()
    # 完全相同命令+参数 → 淘汰
    candidate = {"ref_cmd": "ADD APN", "ref_param": "APNNAME", "def_cmd": "ADD APN", "def_param": "APNNAME"}
    assert rule.check(candidate) is False
    # 相同命令不同参数 → 通过
    candidate["def_param"] = "APNID"
    assert rule.check(candidate) is True

def test_pipeline_runs_rules_then_scorers():
    from plugins.graph_mining.engine.pipeline import MiningPipeline
    from plugins.graph_mining.engine.hard_rules import SameParameterRule

    pipeline = MiningPipeline(hard_rules=[SameParameterRule()])
    candidates = [
        {"ref_cmd": "A", "ref_param": "X", "def_cmd": "B", "def_param": "X"},  # 淘汰
        {"ref_cmd": "A", "ref_param": "X", "def_cmd": "B", "def_param": "Y"},  # 通过
    ]
    passed = pipeline.filter(candidates)
    assert len(passed) == 1
    assert passed[0]["def_param"] == "Y"
```

**Step 2: 运行测试验证失败**

```
Run: cd backend && python -m pytest tests/test_mining_pipeline.py -v
Expected: FAIL
```

**Step 3: 实现 hard_rules.py**

```python
# backend/plugins/graph_mining/engine/hard_rules.py
from typing import Protocol


class HardRule(Protocol):
    def check(self, candidate: dict) -> bool: ...


class SameParameterRule:
    """ref_param 和 def_param 不能是同一个参数名"""
    def check(self, candidate: dict) -> bool:
        return candidate.get("ref_param") != candidate.get("def_param")


class SelfReferenceRule:
    """同一命令 + 同一参数 → 自引用，淘汰"""
    def check(self, candidate: dict) -> bool:
        if candidate.get("ref_cmd") != candidate.get("def_cmd"):
            return True
        return candidate.get("ref_param") != candidate.get("def_param")
```

**Step 4: 实现 pipeline.py**

```python
# backend/plugins/graph_mining/engine/pipeline.py
from typing import Protocol
from .hard_rules import HardRule


class MiningPipeline:
    """评估管线：铁律过滤 → 代码软打分 → 路由分流"""

    def __init__(self, hard_rules: list | None = None):
        self._rules = hard_rules or []

    def filter(self, candidates: list[dict]) -> list[dict]:
        """应用所有铁律规则，返回通过筛选的候选"""
        result = []
        for c in candidates:
            passed = all(rule.check(c) for rule in self._rules)
            if passed:
                result.append(c)
        return result
```

**Step 5: 运行测试验证通过**

```
Run: cd backend && python -m pytest tests/test_mining_pipeline.py -v
Expected: 3 passed
```

**Step 6: 提交**

```
git add backend/plugins/graph_mining/engine/hard_rules.py backend/plugins/graph_mining/engine/pipeline.py backend/tests/test_mining_pipeline.py
git commit -m "[claude]: add mining evaluation pipeline with hard rules"
```

---

## Task 9: graph_mining 路由 — 挖掘管理 API

**Files:**
- Modify: `backend/plugins/graph_mining/main.py` — 在 `_register_routes()` 中添加路由

核心路由：

| 方法 | 路径 | 对应设计文档 |
|------|------|-------------|
| POST | `/mining/start` | §7.2 创建挖掘 job |
| GET | `/files` | §7.2 文件列表+挖掘状态 |
| GET | `/candidates` | §7.2 候选列表 |
| POST | `/candidates/{id}/accept` | §7.2 入图谱 |
| POST | `/candidates/{id}/reject` | §7.2 拒绝 |
| POST | `/candidates/{id}/mark-non-graph` | §7.2 非图谱 |
| POST | `/candidates/{id}/revert` | §7.2 回退 |
| GET | `/graph-edges` | §7.2 图谱边列表 |

**实现要点：**

1. **`POST /mining/start`** — 从 `mml_manager/main.py:1174-1353` 迁移 `/files/mine` 的核心逻辑，改造为：
   - 调用 `self.job_service.create_job("mining", {"file_ids": file_ids, "ne_version_id": ne_version_id}, item_keys)`
   - 立即返回 `{"job_id": job_id}`
   - 实际挖掘由 mining_worker 异步执行（Task 10b）

2. **`GET /files`** — 从 `main.py:1446-1459` 迁移，增加状态派生逻辑（§6.4）：
   - LEFT JOIN file_mining_record + LEFT JOIN job_item（通过 item_key=file_entry_id）
   - 派生 mining_status: unmined / queued / running / completed / failed

3. **候选 CRUD 路由** — 从 `main.py:890-1170` 迁移，状态机更新为 6 态（§6.1）：
   - accept/reject/mark-non-graph 仅允许从 `pending` / `ready_for_review` 状态操作
   - revert 将 `graph`/`non_graph` 回退到 `pending`
   - 所有状态变更写 changelog

**Step 1: 从 mml_manager 复制并改造路由到 graph_mining/main.py 的 `_register_routes`**

> 关键改造点：
> - 状态校验从 `pending_like = ("pending", "auto_passed", ...)` 改为 `pending_like = ("pending", "ready_for_review")`
> - `/files/mine` → `/mining/start`（创建 job 并返回 job_id）
> - `/files/mining-status` → `/files`（增加状态派生）
> - 所有路径前缀由 plugin.toml 自动处理

**Step 2: 验证**

```
Run: cd backend && python -m pytest tests/test_mml_manager.py -v
Expected: 已有测试不受影响（mml_manager 尚未删除路由）
```

**Step 3: 提交**

```
git add backend/plugins/graph_mining/main.py
git commit -m "[claude]: add graph_mining API routes for mining and candidate management"
```

---

## Task 10: 共享领域服务 + Mining Worker

**Files:**
- Create: `backend/plugins/graph_mining/services/__init__.py`
- Create: `backend/plugins/graph_mining/services/candidate_service.py` — 共享候选重算服务
- Create: `backend/plugins/graph_mining/workers/__init__.py`
- Create: `backend/plugins/graph_mining/workers/mining_worker.py`
- Modify: `backend/plugins/graph_mining/main.py` — 在 on_register 中注册 handler 到全局 worker

### 10a: 共享候选服务 candidate_service.py

> **职责说明**：`CandidateService` 是 graph_mining 插件内的共享领域服务，负责候选汇总分数重算和终态保护。MiningWorker（Task 10）和事件 handler（Task 11）都通过 `self.candidate_service` 调用它，避免 owner 不明。

```python
# backend/plugins/graph_mining/services/candidate_service.py
import json
import logging
from plugins.graph_mining.engine.scorers import aggregate_contributions

logger = logging.getLogger(__name__)


class CandidateService:
    """候选领域服务：汇总分数重算 + 终态保护（§6.6）"""

    def __init__(self, db):
        self.db = db

    async def recalculate(self, cand_id: int, alg_ver: str, total_mined: int = 0) -> None:
        """重算候选汇总分数，遵守 §6.6 终态保护规则。

        从 mml_manager/main.py:1473-1609 的 _recalculate_candidate_scores 迁移。
        核心逻辑：
        1. 查询所有 contributions → 聚合分数
        2. graph/non_graph 状态：只更新分数和证据，不改变状态
        3. rejected 状态：新证据自动激活回 pending
        4. 同步 graph_edge 的 evidence（如果 candidate 在 graph 状态）
        """
        # ... 完整实现从 main.py:1473-1609 迁移
        pass

    async def get_total_mined(self, ne_version_id: int) -> int:
        rows = await self.db.query(
            "SELECT COUNT(DISTINCT file_entry_id) as cnt FROM file_mining_record "
            "WHERE ne_version_id=? AND mined=1",
            (ne_version_id,),
        )
        return rows[0]["cnt"] if rows else 0
```

### 10b: Mining Worker

**Step 1: 实现 mining_worker.py**

核心逻辑从 `mml_manager/main.py:1209-1353` 的 for 循环体迁移：

```python
# backend/plugins/graph_mining/workers/mining_worker.py
import json
import logging

logger = logging.getLogger(__name__)


class MiningWorker:
    """消费 mining 类型 job 的 worker handler"""

    def __init__(self, db, parser, job_service, candidate_service):
        self.db = db
        self.parser = parser
        self.job_service = job_service
        self.candidate_service = candidate_service  # 共享领域服务

    async def handle(self, job: dict, items: list[dict]) -> dict:
        params = json.loads(job["params_json"])
        ne_version_id = params["ne_version_id"]
        alg_ver = "v1"

        all_cand_ids = set()
        mined_count = 0

        for item in items:
            # 检查取消
            fresh_job = await self.job_service.get_job(job["id"])
            if fresh_job["status"] == "cancelled":
                break

            file_id = int(item["item_key"].replace("file:", ""))
            await self.job_service.update_item_status(item["id"], "running")

            try:
                cand_ids = await self._mine_single_file(file_id, ne_version_id, alg_ver)
                all_cand_ids.update(cand_ids)
                await self.job_service.update_item_status(item["id"], "completed")
                await self.job_service.increment_progress(job["id"])
                mined_count += 1
            except Exception as e:
                logger.exception("Failed to mine file %d", file_id)
                await self.job_service.update_item_status(
                    item["id"], "failed", error_message=str(e)
                )

        # 重算所有受影响候选的汇总分数（通过共享服务）
        total_mined = await self.candidate_service.get_total_mined(ne_version_id)
        for cand_id in all_cand_ids:
            await self.candidate_service.recalculate(cand_id, alg_ver, total_mined)

        return {"mined_files": mined_count, "candidates_affected": len(all_cand_ids)}

    async def _mine_single_file(self, file_id, ne_version_id, alg_ver) -> list[int]:
        """挖掘单个文件，返回受影响的 candidate IDs"""
        # 复用 mml_manager 中的文件解析 + 候选生成 + 贡献写入逻辑
        # ... (从 main.py:1209-1315 迁移)
        pass
```

**Step 2: 在 main.py on_register 中注册 handler 到全局 JobWorker**

```python
# 在 graph_mining/main.py 的 on_register 末尾：
from .services.candidate_service import CandidateService
from .workers.mining_worker import MiningWorker
from core.jobs.worker import JobWorker

# 创建共享候选服务（MiningWorker 和事件 handler 共用）
self.candidate_service = CandidateService(self.db)

# 创建 mining worker handler
mining_worker = MiningWorker(self.db, self.parser, self.job_service, self.candidate_service)

# 从 registry 获取全局 JobWorker，注册 mining handler
global_worker = ctx.get_service(JobWorker)
global_worker.register_handler("mining", mining_worker.handle)
```

> **链路闭合**：Task 5 将 `JobWorker` 注册到 `ServiceRegistry` → Task 10 中 `ctx.get_service(JobWorker)` 获取全局 worker → 直接注册 handler。不需要额外的中间注册机制。

**Step 3: 提交**

```
git add backend/plugins/graph_mining/services/ backend/plugins/graph_mining/workers/ backend/plugins/graph_mining/main.py
git commit -m "[claude]: add shared CandidateService and MiningWorker with proper handler registration"
```

---

## Task 11: 跨插件事件 — mml_manager 触发 + graph_mining 订阅

**Files:**
- Modify: `backend/plugins/mml_manager/main.py` — 文件删除/替换处 emit 事件
- Modify: `backend/plugins/graph_mining/main.py` — 注册事件 handler

**Step 1: mml_manager emit 事件**

在 mml_manager 的 `on_register` 中获取 event_bus：

```python
from core.events.bus import PluginEventBus
self.event_bus = ctx.get_service(PluginEventBus)
```

在文件删除路由中（`DELETE /entries/{entry_id}`）添加：

```python
# 删除文件后
await self.event_bus.emit("file.deleted", {
    "file_entry_id": entry_id,
    "ne_version_id": ne_version_id,
})
```

类似地在文件内容替换、版本删除处添加事件触发。

**文件夹递归删除场景**：当前 `DELETE /entries/{entry_id}` 同一路由承担单文件和文件夹递归删除。当被删对象是文件夹时，代码先用 `collect_ids()` 收集整棵子树，再批量删除所有后代 `file_entry`。

策略：**在 `collect_ids()` 循环中按文件逐条 emit `file.deleted`**，而不是只在最外层 emit 一次。具体改动：

```python
# 在 mml_manager 的 delete_entry 路由中，文件夹删除分支里：
# 原始代码已有: for eid, etype in all_ids: ...
# 在该循环内增加事件触发：
for eid, etype in all_ids:
    if etype == "file":
        # 取该文件的 ne_version_id
        ne_rows = await self.db.query(
            "SELECT ne_version_id FROM file_entry WHERE id=?", (eid,)
        )
        ne_version_id = ne_rows[0]["ne_version_id"] if ne_rows else None
        await self.event_bus.emit("file.deleted", {
            "file_entry_id": eid,
            "ne_version_id": ne_version_id,
        })
```

这样每个被删的后代文件都会触发独立的 `file.deleted` 事件，`graph_mining` 的 `_on_file_deleted` handler 会对每个文件分别执行清理和候选重算，确保不留挂贡献。

**Step 2: graph_mining 注册事件订阅（使用共享 CandidateService)**

在 `graph_mining/main.py` 的 `Plugin` 类上定义 handler 方法，并在 `on_register` 中注册订阅：

```python
# === Plugin 类方法（定义在 Plugin 类体内）===

async def _on_file_deleted(self, payload):
    file_id = payload["file_entry_id"]
    ne_version_id = payload.get("ne_version_id")
    # 删除该文件的 contribution
    affected = await self.db.query(
        "SELECT candidate_id FROM candidate_contribution WHERE file_entry_id=?",
        (file_id,),
    )
    await self.db.execute("DELETE FROM candidate_contribution WHERE file_entry_id=?", (file_id,))
    await self.db.execute("DELETE FROM file_mining_record WHERE file_entry_id=?", (file_id,))
    # 通过共享服务重算受影响候选（同 MiningWorker 使用的同一个实例）
    total_mined = await self.candidate_service.get_total_mined(ne_version_id)
    for row in affected:
        await self.candidate_service.recalculate(row["candidate_id"], "v1", total_mined)

async def _on_file_content_replaced(self, payload):
    # 文件内容替换：先清理旧贡献（与 file.deleted 相同逻辑）
    await self._on_file_deleted(payload)

async def _on_ne_version_deleted(self, payload):
    ne_version_id = payload["ne_version_id"]
    # 删除该版本下所有文件的贡献，然后重算受影响候选
    affected = await self.db.query(
        "SELECT DISTINCT cc.candidate_id FROM candidate_contribution cc "
        "JOIN file_mining_record fmr ON cc.file_entry_id = fmr.file_entry_id "
        "WHERE fmr.ne_version_id = ?",
        (ne_version_id,),
    )
    await self.db.execute(
        "DELETE FROM candidate_contribution WHERE file_entry_id IN "
        "(SELECT file_entry_id FROM file_mining_record WHERE ne_version_id = ?)",
        (ne_version_id,),
    )
    await self.db.execute("DELETE FROM file_mining_record WHERE ne_version_id = ?", (ne_version_id,))
    for row in affected:
        total_mined = await self.candidate_service.get_total_mined(ne_version_id)
        await self.candidate_service.recalculate(row["candidate_id"], "v1", total_mined)

# === on_register 中注册订阅（Plugin.on_register 方法体内）===

async def on_register(self, ctx):
    # ...（已有的路由、服务注册代码）...
    # 订阅跨插件生命周期事件
    self.event_bus = ctx.get_service(PluginEventBus)
    self.event_bus.on("file.deleted", self._on_file_deleted)
    self.event_bus.on("file.content_replaced", self._on_file_content_replaced)
    self.event_bus.on("ne_version.deleted", self._on_ne_version_deleted)
```

> **职责明确**: `_on_file_deleted` 等是 `Plugin` 类方法，通过 `self` 访问 `self.candidate_service`（Task 10a 注册的共享实例）和 `self.db`。`on_register` 中通过 `ctx.get_service(PluginEventBus)` 获取事件总线，并显式调用 `.on(event_name, handler)` 完成订阅注册。三个生命周期事件（`file.deleted`、`file.content_replaced`、`ne_version.deleted`）均有完整订阅链路，不存在无主 handler 或缺失注册的问题。



**集成测试要求**：在实施时补充以下测试：

- `删除单文件 → graph_mining 清理 contribution + file_mining_record + 重算候选`
- `删除含子文件的文件夹 → 所有后代文件的 contribution / file_mining_record 均被清理，无挂贡献残留`
- `删除版本 → 该版本下所有文件的清理链路生效`

**Step 3: 提交**

```
git add backend/plugins/mml_manager/main.py backend/plugins/graph_mining/main.py
git commit -m "[claude]: add cross-plugin event emission (mml_manager) and subscription (graph_mining)"
```

---

## Task 12: 瘦身 mml_manager — 移除已迁移代码

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

移除以下已迁移到 graph_mining 的代码：

| 行范围 | 内容 | 去向 |
|--------|------|------|
| 107-169 | dependency_candidate, graph_edge, graph_changelog, file_mining_record, candidate_contribution 建表 | graph_mining |
| 186-196 | ALTER TABLE migrations (review_route, non_graph_reason 等) | graph_mining |
| 793-886 | POST /candidates/generate (DEPRECATED) | 删除 |
| 890-922 | GET /candidates | graph_mining |
| 924-1006 | POST /candidates/{id}/accept | graph_mining |
| 1008-1044 | POST /candidates/{id}/reject | graph_mining |
| 1048-1093 | POST /candidates/{id}/mark-non-graph | graph_mining |
| 1097-1170 | POST /candidates/{id}/revert | graph_mining |
| 1174-1353 | POST /files/mine | graph_mining (→ mining/start) |
| 1355-1444 | POST /files/{file_id}/re-mine | graph_mining |
| 1446-1459 | GET /files/mining-status | graph_mining (→ /files) |
| 1463-1471 | _determine_review_route | graph_mining |
| 1473-1609 | _recalculate_candidate_scores | graph_mining |

mml_manager 保留：
- NE version CRUD
- File entry management (含上传)
- File content operations
- Command extraction (`POST /scripts/{file_id}/extract-commands`)
- Stats endpoint

**验证：**

```
Run: cd backend && python -m pytest tests/test_mml_manager.py -v
Expected: 与文件/命令提取相关的测试通过，挖掘相关测试因路径变更需迁移到新测试文件
```

**提交：**

```
git add backend/plugins/mml_manager/main.py
git commit -m "[claude]: slim down mml_manager, remove migrated mining code"
```

---

## Task 13: 更新 backend/main.py — 移除虚拟 dependency_mining 插件

**Files:**
- Modify: `backend/main.py` — 删除 dependency_mining 虚拟插件注册

移除 `list_plugins()` 中的 `dependency_mining` 虚拟插件代码块（lines 89-96），因为 graph_mining 现在是正式插件。

**提交：**

```
git add backend/main.py
git commit -m "[claude]: remove virtual dependency_mining plugin, replaced by graph_mining"
```

---

## Task 14: 前端 API 层 — graph-mining.ts

**Files:**
- Create: `frontend/src/api/graph-mining.ts`
- Modify: `frontend/src/api/index.ts` — 如需导出

**Step 1: 创建 graph-mining.ts**

```typescript
// frontend/src/api/graph-mining.ts
import api from "./index";

// ── Interfaces ──

export interface JobInfo {
  id: number;
  type: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  params_json: string;
  progress_current: number;
  progress_total: number;
  result_json: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface MiningFileInfo {
  file_id: number;
  name: string;
  mining_status: "unmined" | "queued" | "running" | "completed" | "failed";
  last_job_id: number | null;
  last_error: string | null;
  mined_at: string | null;
  command_count: number;
}

export interface Candidate {
  id: number;
  ne_version_id: number;
  ref_command: string;
  ref_param: string;
  def_command: string;
  def_param: string;
  status: string;
  confidence: number;
  scores: {
    support: number;
    distinctiveness: number;
    order_consistency: number;
    name_relevance: number;
  };
  evidence: Record<string, any>;
  graph_edge_id: number | null;
  review_route: string | null;
  non_graph_reason: string | null;
  llm_assessment_json: string | null;
}

// ── Job API ──

export async function listJobs(type?: string): Promise<JobInfo[]> {
  const { data } = await api.get("/jobs", { params: type ? { type } : {} });
  return data;
}

export async function getJob(jobId: number): Promise<JobInfo> {
  const { data } = await api.get(`/jobs/${jobId}`);
  return data;
}

export async function cancelJob(jobId: number): Promise<{ ok: boolean }> {
  const { data } = await api.post(`/jobs/${jobId}/cancel`);
  return data;
}

// ── Mining API ──

export async function startMining(fileIds: number[]): Promise<{ job_id: number }> {
  const { data } = await api.post("/plugins/graph_mining/mining/start", { file_ids: fileIds });
  return data;
}

export async function fetchMiningFiles(neVersionId: number): Promise<MiningFileInfo[]> {
  const { data } = await api.get("/plugins/graph_mining/files", { params: { ne_version_id: neVersionId } });
  return data;
}

// ── Candidate API ──

export async function fetchCandidates(params?: {
  ne_version_id?: number;
  status?: string;
}): Promise<Candidate[]> {
  const { data } = await api.get("/plugins/graph_mining/candidates", { params });
  return data;
}

export async function acceptCandidate(id: number, reviewer: string) {
  const { data } = await api.post(`/plugins/graph_mining/candidates/${id}/accept`, { reviewer });
  return data;
}

export async function rejectCandidate(id: number, reviewer: string) {
  const { data } = await api.post(`/plugins/graph_mining/candidates/${id}/reject`, { reviewer });
  return data;
}

export async function markNonGraph(id: number, reason: string, reviewer: string) {
  const { data } = await api.post(`/plugins/graph_mining/candidates/${id}/mark-non-graph`, { reason, reviewer });
  return data;
}

export async function revertCandidate(id: number, reviewer: string) {
  const { data } = await api.post(`/plugins/graph_mining/candidates/${id}/revert`, { reviewer });
  return data;
}

// ── Graph Edges ──

export async function fetchGraphEdges(neVersionId: number) {
  const { data } = await api.get("/plugins/graph_mining/graph-edges", { params: { ne_version_id: neVersionId } });
  return data;
}
```

**Step 2: 添加 core/jobs 路由到后端（main.py 或独立模块）**

在 `backend/main.py` 中添加通用 jobs API 路由（或由 core/jobs 自己提供 router）：

```python
@app.get("/api/jobs")
@app.get("/api/jobs/{job_id}")
@app.post("/api/jobs/{job_id}/cancel")
```

**Step 3: 提交**

```
git add frontend/src/api/graph-mining.ts backend/main.py
git commit -m "[claude]: add frontend graph-mining API layer and backend jobs endpoints"
```

---

## Task 15: 前端路由与页面骨架

**Files:**
- Modify: `frontend/src/router/index.ts` — 新增 graph-mining 路由
- Create: `frontend/src/views/plugins/GraphMining.vue` — 页面骨架（双 Tab）

**Step 1: 更新路由**

```typescript
// 在 router/index.ts 的 children 中添加：
{
  path: "plugins/graph-mining",
  name: "graph-mining",
  component: () => import("../views/plugins/GraphMining.vue"),
},
```

**Step 2: 创建页面骨架**

GraphMining.vue 结构：
- 顶部：`<n-page-header>` + NE 版本选择器
- 主体：`<n-tabs>` 两个 Tab（挖掘管理 + 候选审核）
- 右上角：任务中心浮层（活跃 job 列表）

> 详细 UI 实现参考设计文档 §8.2 和 §8.3 的 ASCII wireframe。

**Step 3: 提交**

```
git add frontend/src/router/index.ts frontend/src/views/plugins/GraphMining.vue
git commit -m "[claude]: add GraphMining page skeleton with dual-tab layout"
```

---

## Task 16: 前端 — 挖掘管理 Tab

**Files:**
- Modify: `frontend/src/views/plugins/GraphMining.vue`

实现 §8.2 挖掘管理 Tab：
- 左侧：文件列表 + 挖掘状态标签（未挖掘/排队/挖掘中/已完成/失败）+ 多选 + 开始挖掘按钮
- 右侧：任务队列（进行中任务 + 进度条 + 取消按钮 + 历史任务）
- 轮询逻辑：创建 job 后每 2s 轮询 `getJob(jobId)` 直到 completed/failed/cancelled

**核心交互逻辑：**

```typescript
// 点击"开始挖掘" → startMining(fileIds) → 获得 job_id → 开始轮询
async function handleStartMining() {
  const { job_id } = await startMining(selectedFileIds.value);
  activeJobId.value = job_id;
  pollTimer.value = setInterval(async () => {
    const job = await getJob(job_id);
    if (["completed", "failed", "cancelled"].includes(job.status)) {
      clearInterval(pollTimer.value);
      await loadFiles(); // 刷新文件状态
    }
  }, 2000);
}
```

**提交：**

```
git add frontend/src/views/plugins/GraphMining.vue
git commit -m "[claude]: implement mining management tab with async job polling"
```

---

## Task 17: 前端 — 候选审核 Tab

**Files:**
- Modify: `frontend/src/views/plugins/GraphMining.vue`

实现 §8.3 候选审核 Tab：
- 阶段统计卡片（可审核 / LLM评估中 / 已处理 / 图谱库）
- 子 Tab 切换：可审核 / LLM评估中 / 图谱库 / 非图谱库
- 候选卡片列表 + 操作按钮（入图谱/非图谱/拒绝/请求LLM/回退）
- 详情抽屉（铁律/代码打分/证据/LLM评估结果）

> 注意：LLM 评估中 tab 和相关按钮在第一阶段为占位 UI，不接真实 LLM。

**提交：**

```
git add frontend/src/views/plugins/GraphMining.vue
git commit -m "[claude]: implement candidate review tab with 6-state management"
```

---

## Task 18: 前端清理 — 移除旧 DependencyMining 页面

**Files:**
- Modify: `frontend/src/router/index.ts` — 移除 dependency-mining 路由
- Delete: `frontend/src/views/plugins/DependencyMining.vue`（或归档）
- Delete: `frontend/src/api/dependency-mining.ts`（或归档）

**提交：**

```
git add frontend/src/router/index.ts
git rm frontend/src/views/plugins/DependencyMining.vue frontend/src/api/dependency-mining.ts
git commit -m "[claude]: remove legacy DependencyMining page, replaced by GraphMining"
```

---

## Task 19: 集成测试 — §11 测试用例全覆盖

**Files:**
- Create: `backend/tests/test_graph_mining_integration.py`

覆盖设计文档 §11 要求：

| 测试 | 验证点 |
|------|--------|
| job 取消后状态一致性 | cancel → job_item skipped/completed/failed，文件状态回退 |
| 文件删除触发清理 | 删除文件 → contribution 清理 → 候选分数重算 |
| 已审核候选终态保护 | graph 候选重挖后状态不变、贡献更新 |
| non_graph 终态保护 | non_graph 新证据后状态不变 |
| rejected 自动激活 | rejected 新证据后激活回 pending |
| 零贡献终态不被删除 | graph/non_graph 零贡献时记录保留 |
| 文件状态派生正确 | /files API 返回状态与 job_item + file_mining_record 组合一致 |

**测试策略：**

每个测试搭建独立临时数据库 → 插入基础数据（ne_version, file_entry, command_instance）→ 调用 graph_mining 的 API → 断言结果。

```python
@pytest.fixture
async def setup_env(tmp_path):
    """搭建完整的测试环境：db + plugin 实例"""
    from core.services.database import DatabaseService
    from core.services.parser import ParserService
    from core.jobs.service import JobService
    from core.jobs.models import CREATE_JOBS_TABLE, CREATE_JOB_ITEMS_TABLE, CREATE_INDEXES
    from core.events.bus import PluginEventBus
    from plugins.graph_mining.main import Plugin

    db = DatabaseService(db_path=str(tmp_path / "test.db"))
    await db.start()
    # 初始化所有表...
    # 创建 Plugin 实例并注册...
    yield {"db": db, "plugin": plugin}
    await db.stop()
```

**运行并验证：**

```
Run: cd backend && python -m pytest tests/test_graph_mining_integration.py -v
Expected: 7 passed
```

**提交：**

```
git add backend/tests/test_graph_mining_integration.py
git commit -m "[claude]: add integration tests for §11 requirements"
```

---

## Task 20: 全量回归测试 + 验证

**Step 1: 后端全量测试**

```
Run: cd backend && python -m pytest tests/ -v
Expected: All tests pass (new graph_mining tests + existing mml_manager tests)
```

**Step 2: 前端 build**

```
Run: cd frontend && npm run build
Expected: Build succeeds without type errors
```

**Step 3: 手动冒烟测试**

启动后端 + 前端，验证：
1. graph_mining 插件出现在侧边栏
2. 选择 NE 版本后文件列表正确展示
3. 选择文件 → 开始挖掘 → job 创建 → 轮询 → 进度更新 → 完成
4. 候选列表正确加载，审核操作（入图谱/拒绝/标记非图谱/回退）正常
5. 删除文件后 graph_mining 数据被级联清理
6. 旧 dependency-mining 页面已不可访问

**提交（如有修复）：**

```
git add <fixed files>
git commit -m "[claude]: fix regression issues from integration testing"
```

---

## 执行依赖图

```
Task 1 ──→ Task 2 ──→ Task 3 ──→ Task 5 (接入主应用)
                                              ↓
Task 4 (events) ────────────────────────→ Task 5
                                              ↓
                                  Task 6 (插件骨架) ──→ Task 7 (迁移 scorer) ──→ Task 8 (pipeline)
                                                                              ↓
                                                                    Task 9 (API 路由) ──→ Task 10a (CandidateService) ──→ Task 10b (MiningWorker)
                                                                                                                                ↓
                                                                                                                    Task 11 (事件集成，复用 CandidateService)
                                                                                                                    Task 12 (瘦身 mml_manager)
                                                                                                                    Task 13 (移除虚拟插件)
                                                                                                                              ↓
                                                                                                                    Task 14 (前端 API)
                                                                                                                    Task 15 (前端骨架)
                                                                                                                    Task 16 (挖掘 Tab)
                                                                                                                    Task 17 (审核 Tab)
                                                                                                                    Task 18 (清理旧页面)
                                                                                                                              ↓
                                                                                                                    Task 19 (集成测试)
                                                                                                                    Task 20 (回归验证)
```

## 总计

- **后端新建文件**: ~14 个（含 services/candidate_service.py）
- **前端新建/修改文件**: ~4 个
- **测试文件**: ~4 个（新增）
- **预估 Tasks**: 20 个（Task 10 拆为 10a+10b，内部编号不变）
- **风险点**: Task 10a/10b (CandidateService 终态保护逻辑最复杂)、Task 11 (跨插件事件时序，依赖 CandidateService 单实例)、Task 12 (删除代码时不能误删非挖掘代码)
