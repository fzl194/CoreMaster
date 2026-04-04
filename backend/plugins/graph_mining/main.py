import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.db = None
        self.parser = None
        self.job_service = None
        self.event_bus = None
        self.candidate_service = None

    async def on_register(self, ctx):
        from core.services.database import DatabaseService
        from core.services.parser import ParserService
        from core.jobs.service import JobService
        from core.events.bus import PluginEventBus
        from core.jobs.worker import JobWorker
        from plugins.graph_mining.services.candidate_service import CandidateService
        from plugins.graph_mining.workers.mining_worker import MiningWorker

        self.db = ctx.get_service(DatabaseService)
        self.parser = ctx.get_service(ParserService)
        self.job_service = ctx.get_service(JobService)
        self.event_bus = ctx.get_service(PluginEventBus)

        # Shared candidate service (MiningWorker + event handlers)
        self.candidate_service = CandidateService(self.db)

        # Register mining worker handler to global JobWorker
        mining_worker = MiningWorker(self.db, self.parser, self.job_service, self.candidate_service)
        global_worker = ctx.get_service(JobWorker)
        global_worker.register_handler("mining", mining_worker.handle)

        await self._create_tables()
        self._register_routes()

        # Subscribe to cross-plugin lifecycle events
        self.event_bus.on("file.deleted", self._on_file_deleted)
        self.event_bus.on("file.content_replaced", self._on_file_content_replaced)
        self.event_bus.on("ne_version.deleted", self._on_ne_version_deleted)

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

        # Migrate old tables: add columns introduced by graph_mining that old DB won't have
        for _col_sql in [
            "ALTER TABLE dependency_candidate ADD COLUMN llm_assessment_json TEXT",
            "ALTER TABLE file_mining_record ADD COLUMN last_job_id INTEGER",
            "ALTER TABLE file_mining_record ADD COLUMN last_error TEXT",
        ]:
            try:
                await self.db.execute(_col_sql)
            except Exception:
                pass  # Column already exists

    def _register_routes(self):
        from plugins.graph_mining.services.candidate_service import _determine_review_route

        @self.router.post("/mining/start")
        async def start_mining(payload: dict):
            """创建挖掘 job，返回 job_id（异步执行）。"""
            file_ids = payload.get("file_ids", [])
            if not file_ids:
                return JSONResponse(status_code=400, content={"detail": "file_ids 不能为空"})

            # Validate all files exist and belong to the same ne_version
            ne_version_id = None
            for fid in file_ids:
                rows = await self.db.query(
                    "SELECT id, ne_version_id FROM file_entry WHERE id=? AND type='file'",
                    (fid,),
                )
                if not rows:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": f"文件 {fid} 不存在"},
                    )
                if ne_version_id is None:
                    ne_version_id = rows[0]["ne_version_id"]
                elif rows[0]["ne_version_id"] != ne_version_id:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "所有文件必须属于同一个网元版本"},
                    )

            if ne_version_id is None:
                return JSONResponse(status_code=400, content={"detail": "文件未绑定网元版本"})

            item_keys = [str(fid) for fid in file_ids]
            job_id = await self.job_service.create_job(
                "mining",
                {"file_ids": file_ids, "ne_version_id": ne_version_id},
                item_keys,
            )
            return {"job_id": job_id}

        @self.router.get("/jobs")
        async def list_jobs(limit: int = Query(20)):
            """List recent mining jobs."""
            jobs = await self.job_service.list_jobs(job_type="mining", limit=limit)
            return jobs

        @self.router.get("/jobs/{job_id}")
        async def get_job(job_id: int):
            """Get job detail with items."""
            job = await self.job_service.get_job(job_id)
            if not job:
                return JSONResponse(status_code=404, content={"detail": "任务不存在"})
            items = await self.job_service.get_job_items(job_id)
            job["items"] = items
            return job

        @self.router.post("/jobs/{job_id}/cancel")
        async def cancel_job(job_id: int):
            """Cancel a running/queued mining job."""
            ok = await self.job_service.cancel_job(job_id)
            if not ok:
                return JSONResponse(status_code=400, content={"detail": "无法取消该任务"})
            return {"ok": True}

        @self.router.get("/files")
        async def get_files(ne_version_id: int = Query(...)):
            """文件列表 + 挖掘状态派生。"""
            rows = await self.db.query(
                "SELECT fe.id as file_entry_id, fe.name as file_name, fe.file_size, fe.ne_version_id, "
                "fmr.mined, fmr.algorithm_version, fmr.command_count, "
                "fmr.created_at as mined_at "
                "FROM file_entry fe "
                "LEFT JOIN file_mining_record fmr ON fe.id = fmr.file_entry_id "
                "WHERE fe.ne_version_id=? AND fe.type='file' "
                "ORDER BY fe.name",
                (ne_version_id,),
            )

            # Batch derive mining status from recent mining jobs
            file_ids = [r["file_entry_id"] for r in rows]
            if file_ids:
                placeholders = ",".join("?" for _ in file_ids)
                job_items = await self.db.query(
                    f"SELECT ji.item_key, ji.status FROM job_item ji "
                    f"JOIN job j ON ji.job_id = j.id "
                    f"WHERE j.type='mining' AND ji.item_key IN ({placeholders}) "
                    f"ORDER BY j.created_at DESC",
                    tuple(str(fid) for fid in file_ids),
                )
                # Build latest status map (first per item_key = most recent)
                status_map = {}
                for ji in job_items:
                    key = ji["item_key"]
                    if key not in status_map:
                        status_map[key] = ji["status"]

                for row in rows:
                    fid = str(row["file_entry_id"])
                    if row.get("mined"):
                        row["mining_status"] = "completed"
                    elif fid in status_map:
                        ji_status = status_map[fid]
                        if ji_status == "running":
                            row["mining_status"] = "running"
                        elif ji_status in ("pending", "queued"):
                            row["mining_status"] = "queued"
                        elif ji_status == "failed":
                            row["mining_status"] = "failed"
                        else:
                            row["mining_status"] = "completed"
                    elif row.get("mined") == 0 and row.get("mined_at") is not None:
                        # Has a mining record with mined=0 → content was replaced
                        row["mining_status"] = "changed"
                    else:
                        row["mining_status"] = "unmined"
            else:
                for row in rows:
                    row["mining_status"] = "unmined"

            return rows

        @self.router.get("/candidates")
        async def list_candidates(
            ne_version_id: int | None = Query(None),
            status: str | None = Query(None),
        ):
            """List candidates with optional filters."""
            conditions = []
            params: list = []
            if ne_version_id is not None:
                conditions.append("ne_version_id=?")
                params.append(ne_version_id)
            if status is not None:
                conditions.append("status=?")
                params.append(status)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            rows = await self.db.query(
                f"SELECT id, ne_version_id, ref_command, ref_param, def_command, def_param, "
                f"status, confidence, scores_json, evidence_json, "
                f"graph_edge_id, review_route, non_graph_reason, non_graph_reviewer, "
                f"active_algorithm_version, llm_assessment_json, created_at, updated_at "
                f"FROM dependency_candidate {where} ORDER BY confidence DESC",
                tuple(params),
            )
            result = []
            for row in rows:
                row["scores"] = json.loads(row["scores_json"])
                row["evidence"] = json.loads(row["evidence_json"])
                result.append(row)
            return result

        @self.router.post("/candidates/{candidate_id}/accept")
        async def accept_candidate(candidate_id: int, payload: dict):
            """Accept a candidate → create graph edge + changelog. Status → 'graph'."""
            reviewer = payload.get("reviewer", "anonymous")

            rows = await self.db.query(
                "SELECT id, ne_version_id, ref_command, ref_param, def_command, def_param, "
                "status, confidence, scores_json, evidence_json, review_history_json "
                "FROM dependency_candidate WHERE id=?",
                (candidate_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "候选记录不存在"})

            cand = rows[0]
            current = cand["status"]
            pending_like = ("pending", "ready_for_review")
            if current not in pending_like:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"只能从 pending/ready_for_review 状态接受，当前: {current}"},
                )

            ne_version_id = cand["ne_version_id"]
            ref_cmd = cand["ref_command"]
            ref_param = cand["ref_param"]
            def_cmd = cand["def_command"]
            def_param = cand["def_param"]

            # Upsert graph edge
            existing = await self.db.query(
                "SELECT id FROM graph_edge WHERE ne_version_id=? "
                "AND ref_command=? AND ref_param=? AND def_command=? AND def_param=?",
                (ne_version_id, ref_cmd, ref_param, def_cmd, def_param),
            )
            if existing:
                edge_id = existing[0]["id"]
                await self.db.execute(
                    "UPDATE graph_edge SET status='active', confidence=?, "
                    "evidence_json=?, confirmed_by=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (cand["confidence"], cand["evidence_json"], reviewer, edge_id),
                )
            else:
                await self.db.execute(
                    "INSERT INTO graph_edge "
                    "(ne_version_id, ref_command, ref_param, def_command, def_param, "
                    "status, source, confidence, evidence_json, confirmed_by) "
                    "VALUES (?, ?, ?, ?, ?, 'active', 'mined', ?, ?, ?)",
                    (ne_version_id, ref_cmd, ref_param, def_cmd, def_param,
                     cand["confidence"], cand["evidence_json"], reviewer),
                )
                edge_rows = await self.db.query(
                    "SELECT id FROM graph_edge WHERE ne_version_id=? "
                    "AND ref_command=? AND ref_param=? AND def_command=? AND def_param=?",
                    (ne_version_id, ref_cmd, ref_param, def_cmd, def_param),
                )
                edge_id = edge_rows[0]["id"] if edge_rows else None

            # Update candidate status to 'graph', clear review_route
            review_entry = {"action": "accepted", "reviewer": reviewer}
            current_history = json.loads(cand.get("review_history_json") or "[]")
            current_history.append(review_entry)

            await self.db.execute(
                "UPDATE dependency_candidate SET status='graph', graph_edge_id=?, "
                "review_route=NULL, review_history_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (edge_id, json.dumps(current_history, ensure_ascii=False), candidate_id),
            )

            # Create changelog entry
            await self.db.execute(
                "INSERT INTO graph_changelog "
                "(dependency_id, candidate_id, change_type, snapshot_after, trigger_type, trigger_id) "
                "VALUES (?, ?, 'add', ?, 'human', ?)",
                (edge_id, candidate_id,
                 json.dumps({"status": "graph", "confidence": cand["confidence"]},
                            ensure_ascii=False),
                 reviewer),
            )

            return {"ok": True, "graph_edge_id": edge_id, "candidate_id": candidate_id}

        @self.router.post("/candidates/{candidate_id}/reject")
        async def reject_candidate(candidate_id: int, payload: dict):
            """Reject a candidate — no graph edge created. Status → 'rejected'."""
            reviewer = payload.get("reviewer", "anonymous")

            rows = await self.db.query(
                "SELECT id, status FROM dependency_candidate WHERE id=?",
                (candidate_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "候选记录不存在"})

            current = rows[0]["status"]
            pending_like = ("pending", "ready_for_review")
            if current not in pending_like:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"只能从 pending/ready_for_review 状态拒绝，当前: {current}"},
                )

            await self.db.execute(
                "UPDATE dependency_candidate SET status='rejected', review_route=NULL, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (candidate_id,),
            )

            # Create changelog
            await self.db.execute(
                "INSERT INTO graph_changelog "
                "(candidate_id, change_type, snapshot_after, trigger_type, trigger_id) "
                "VALUES (?, 'reject', ?, 'human', ?)",
                (candidate_id,
                 json.dumps({"status": "rejected"}, ensure_ascii=False),
                 reviewer),
            )

            return {"ok": True, "candidate_id": candidate_id}

        @self.router.post("/candidates/{candidate_id}/mark-non-graph")
        async def mark_non_graph(candidate_id: int, payload: dict):
            """Mark a candidate as non-graph dependency."""
            reason = payload.get("reason", "")
            reviewer = payload.get("reviewer", "anonymous")

            rows = await self.db.query(
                "SELECT id, status, review_history_json FROM dependency_candidate WHERE id=?",
                (candidate_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "候选记录不存在"})

            cand = rows[0]
            current = cand["status"]
            pending_like = ("pending", "ready_for_review")
            if current not in pending_like:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"只能从 pending/ready_for_review 状态标记非图谱，当前: {current}"},
                )

            review_entry = {"action": "mark_non_graph", "reviewer": reviewer, "reason": reason}
            current_history = json.loads(cand.get("review_history_json") or "[]")
            current_history.append(review_entry)

            await self.db.execute(
                "UPDATE dependency_candidate SET status='non_graph', "
                "non_graph_reason=?, non_graph_reviewer=?, review_route=NULL, "
                "review_history_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (reason, reviewer,
                 json.dumps(current_history, ensure_ascii=False), candidate_id),
            )

            # Create changelog
            await self.db.execute(
                "INSERT INTO graph_changelog "
                "(candidate_id, change_type, snapshot_after, trigger_type, trigger_id) "
                "VALUES (?, 'mark_non_graph', ?, 'human', ?)",
                (candidate_id,
                 json.dumps({"status": "non_graph", "reason": reason}, ensure_ascii=False),
                 reviewer),
            )

            return {"ok": True, "candidate_id": candidate_id}

        @self.router.post("/candidates/{candidate_id}/revert")
        async def revert_candidate(candidate_id: int, payload: dict):
            """Revert a candidate: graph→pending (revoke edge), non_graph→pending."""
            reviewer = payload.get("reviewer", "anonymous")

            rows = await self.db.query(
                "SELECT id, ne_version_id, ref_command, ref_param, def_command, def_param, "
                "status, confidence, graph_edge_id, review_history_json "
                "FROM dependency_candidate WHERE id=?",
                (candidate_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "候选记录不存在"})

            cand = rows[0]
            current_status = cand["status"]

            if current_status not in ("graph", "non_graph"):
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"只能回退 graph 或 non_graph 状态，当前: {current_status}"},
                )

            review_entry = {"action": "reverted", "reviewer": reviewer, "from_status": current_status}
            current_history = json.loads(cand.get("review_history_json") or "[]")
            current_history.append(review_entry)

            review_route = _determine_review_route(cand["confidence"])

            if current_status == "graph":
                # Revoke the associated graph_edge
                edge_id = cand.get("graph_edge_id")
                if edge_id:
                    await self.db.execute(
                        "UPDATE graph_edge SET status='revoked', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (edge_id,),
                    )

                await self.db.execute(
                    "UPDATE dependency_candidate SET status='pending', graph_edge_id=NULL, "
                    "review_route=?, review_history_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (review_route, json.dumps(current_history, ensure_ascii=False), candidate_id),
                )

                await self.db.execute(
                    "INSERT INTO graph_changelog "
                    "(candidate_id, change_type, snapshot_after, trigger_type, trigger_id) "
                    "VALUES (?, 'revert', ?, 'human', ?)",
                    (candidate_id,
                     json.dumps({"status": "pending", "from": "graph"}, ensure_ascii=False),
                     reviewer),
                )

            elif current_status == "non_graph":
                await self.db.execute(
                    "UPDATE dependency_candidate SET status='pending', "
                    "non_graph_reason=NULL, non_graph_reviewer=NULL, review_route=?, "
                    "review_history_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (review_route, json.dumps(current_history, ensure_ascii=False), candidate_id),
                )

                await self.db.execute(
                    "INSERT INTO graph_changelog "
                    "(candidate_id, change_type, snapshot_after, trigger_type, trigger_id) "
                    "VALUES (?, 'revert', ?, 'human', ?)",
                    (candidate_id,
                     json.dumps({"status": "pending", "from": "non_graph"}, ensure_ascii=False),
                     reviewer),
                )

            return {"ok": True, "candidate_id": candidate_id}

        @self.router.get("/graph-edges")
        async def list_graph_edges(ne_version_id: int | None = Query(None)):
            """图谱边列表。"""
            conditions = []
            params: list = []
            if ne_version_id is not None:
                conditions.append("ne_version_id=?")
                params.append(ne_version_id)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            rows = await self.db.query(
                f"SELECT id, ne_version_id, ref_command, ref_param, def_command, def_param, "
                f"status, source, confidence, evidence_json, confirmed_by, "
                f"created_at, updated_at "
                f"FROM graph_edge {where} ORDER BY confidence DESC",
                tuple(params),
            )
            result = []
            for row in rows:
                row["evidence"] = json.loads(row["evidence_json"])
                result.append(row)
            return result

    # ── Cross-plugin Event Handlers ────────────────────────────────────

    async def _on_file_deleted(self, payload):
        file_id = payload["file_entry_id"]
        ne_version_id = payload.get("ne_version_id")
        # Delete contributions for this file
        affected = await self.db.query(
            "SELECT candidate_id FROM candidate_contribution WHERE file_entry_id=?",
            (file_id,),
        )
        await self.db.execute(
            "DELETE FROM candidate_contribution WHERE file_entry_id=?", (file_id,)
        )
        await self.db.execute(
            "DELETE FROM file_mining_record WHERE file_entry_id=?", (file_id,)
        )
        # Recalculate affected candidates via shared service
        total_mined = await self.candidate_service.get_total_mined(ne_version_id)
        for row in affected:
            await self.candidate_service.recalculate(row["candidate_id"], "v1", total_mined)

    async def _on_file_content_replaced(self, payload):
        # Clean old contributions, mark file as unmined (not auto-mine)
        file_id = payload["file_entry_id"]
        ne_version_id = payload.get("ne_version_id")
        # Delete contributions for this file
        affected = await self.db.query(
            "SELECT candidate_id FROM candidate_contribution WHERE file_entry_id=?",
            (file_id,),
        )
        await self.db.execute(
            "DELETE FROM candidate_contribution WHERE file_entry_id=?", (file_id,)
        )
        # Reset file_mining_record to unmined (keep record so status shows "changed")
        existing = await self.db.query(
            "SELECT id FROM file_mining_record WHERE file_entry_id=?", (file_id,)
        )
        if existing:
            await self.db.execute(
                "UPDATE file_mining_record SET mined=0, last_error=NULL WHERE file_entry_id=?",
                (file_id,),
            )
        # Recalculate affected candidates via shared service
        total_mined = await self.candidate_service.get_total_mined(ne_version_id)
        for row in affected:
            await self.candidate_service.recalculate(row["candidate_id"], "v1", total_mined)

    async def _on_ne_version_deleted(self, payload):
        ne_version_id = payload["ne_version_id"]
        # Delete all contributions for files in this version
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
        await self.db.execute(
            "DELETE FROM file_mining_record WHERE ne_version_id = ?", (ne_version_id,)
        )
        # Recalculate without total_mined (recalculate auto-detects)
        for row in affected:
            await self.candidate_service.recalculate(row["candidate_id"], "v1")
