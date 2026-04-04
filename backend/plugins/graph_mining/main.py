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
        self.candidate_service = None

    async def on_register(self, ctx):
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
