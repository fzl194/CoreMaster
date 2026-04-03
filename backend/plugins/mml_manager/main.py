# backend/plugins/mml_manager/main.py
import json
import shutil
import sys
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Query, Form
from fastapi.responses import FileResponse, JSONResponse
from core.plugin.context import PluginContext
from core.services.parser import ParserService, read_text_auto, decode_bytes_auto
from core.services.database import DatabaseService

# Ensure candidate_engine can be imported
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

MML_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "mml_files"


def _json_serialize_evidence(evidence: dict) -> str:
    """Serialize evidence dict to JSON, converting sets to sorted lists."""
    clean = {}
    for k, v in evidence.items():
        if isinstance(v, set):
            clean[k] = sorted(v)
        elif isinstance(v, list):
            clean[k] = [
                {sk: (sorted(sv) if isinstance(sv, set) else sv) for sk, sv in item.items()}
                if isinstance(item, dict) else item
                for item in v
            ]
        else:
            clean[k] = v
    return json.dumps(clean, ensure_ascii=False)


def _safe_file_path(file_path: str | None) -> Path | None:
    """校验 file_path 是否位于 MML_STORAGE_ROOT 下，防止路径穿越。

    使用 is_relative_to() 而非字符串前缀比较，避免同前缀兄弟目录绕过
    （如 /data/mml_files_backup 通过 /data/mml_files 的 startswith 检查）。
    """
    if not file_path:
        return None
    try:
        resolved = Path(file_path).resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(MML_STORAGE_ROOT):
        return None
    return resolved


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.parser: ParserService | None = None
        self.db: DatabaseService | None = None

    async def on_register(self, ctx: PluginContext) -> None:
        self.parser = ctx.get_service(ParserService)
        self.db = ctx.get_service(DatabaseService)

        # Create database tables
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS ne_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor TEXT NOT NULL DEFAULT 'huawei',
                ne_type TEXT NOT NULL,
                version TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(vendor, ne_type, version)
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS file_entry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER REFERENCES file_entry(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                ne_version_id INTEGER REFERENCES ne_version(id),
                file_size INTEGER DEFAULT 0,
                file_path TEXT,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(parent_id, name, type)
            )
        """)

        # ── Dependency Mining Tables ──────────────────────────────────

        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS command_instance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_entry_id INTEGER NOT NULL REFERENCES file_entry(id) ON DELETE CASCADE,
                ne_version_id INTEGER NOT NULL REFERENCES ne_version(id),
                command_index INTEGER NOT NULL,
                operation TEXT NOT NULL,
                name TEXT NOT NULL,
                params_json TEXT NOT NULL,
                line_number INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS dependency_candidate (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ne_version_id INTEGER NOT NULL REFERENCES ne_version(id),
                ref_command TEXT NOT NULL,
                ref_param TEXT NOT NULL,
                def_command TEXT NOT NULL,
                def_param TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                confidence REAL NOT NULL,
                scores_json TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                source_batch TEXT,
                review_history_json TEXT DEFAULT '[]',
                graph_edge_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ne_version_id, ref_command, ref_param, def_command, def_param)
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS graph_edge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ne_version_id INTEGER NOT NULL REFERENCES ne_version(id),
                ref_command TEXT NOT NULL,
                ref_param TEXT NOT NULL,
                def_command TEXT NOT NULL,
                def_param TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'mined',
                confidence REAL NOT NULL,
                evidence_json TEXT NOT NULL,
                confirmed_by TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(ne_version_id, ref_command, ref_param, def_command, def_param)
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS graph_changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dependency_id INTEGER REFERENCES graph_edge(id),
                candidate_id INTEGER REFERENCES dependency_candidate(id),
                change_type TEXT NOT NULL,
                snapshot_before TEXT,
                snapshot_after TEXT,
                trigger_type TEXT NOT NULL DEFAULT 'human',
                trigger_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS file_mining_record (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_entry_id INTEGER NOT NULL UNIQUE,
                ne_version_id INTEGER NOT NULL,
                mined INTEGER NOT NULL DEFAULT 0,
                algorithm_version TEXT NOT NULL DEFAULT 'v1',
                command_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_entry_id) REFERENCES file_entry(id)
            )
        """)
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
                FOREIGN KEY (candidate_id) REFERENCES dependency_candidate(id),
                FOREIGN KEY (file_entry_id) REFERENCES file_entry(id),
                UNIQUE(candidate_id, file_entry_id, algorithm_version)
            )
        """)

        # Add new columns to dependency_candidate (idempotent for existing DBs)
        for _col_sql in [
            "ALTER TABLE dependency_candidate ADD COLUMN review_route TEXT",
            "ALTER TABLE dependency_candidate ADD COLUMN non_graph_reason TEXT",
            "ALTER TABLE dependency_candidate ADD COLUMN non_graph_reviewer TEXT",
            "ALTER TABLE dependency_candidate ADD COLUMN active_algorithm_version TEXT NOT NULL DEFAULT 'v1'",
        ]:
            try:
                await self.db.execute(_col_sql)
            except Exception:
                pass  # Column already exists

        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cmd_inst_file ON command_instance(file_entry_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cmd_inst_ne ON command_instance(ne_version_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cand_status ON dependency_candidate(status)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cand_ne ON dependency_candidate(ne_version_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_edge_status ON graph_edge(status)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_edge_ne ON graph_edge(ne_version_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_cl_dep ON graph_changelog(dependency_id)"
        )

        # Ensure storage root exists
        MML_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

        # ── Parse endpoints (existing) ──────────────────────────────────

        @self.router.post("/parse")
        async def parse_mml(file: UploadFile = File(...)):
            content = decode_bytes_auto(await file.read())
            commands = self.parser.parse_text(content)
            return {"commands": commands, "count": len(commands)}

        @self.router.post("/parse-text")
        async def parse_mml_text(payload: dict):
            commands = self.parser.parse_text(payload["text"])
            return {"commands": commands, "count": len(commands)}

        # ── NE Version CRUD ─────────────────────────────────────────────

        @self.router.get("/ne-versions")
        async def list_ne_versions():
            rows = await self.db.query(
                "SELECT id, vendor, ne_type, version, created_at FROM ne_version ORDER BY id"
            )
            return rows

        @self.router.post("/ne-versions")
        async def create_ne_version(payload: dict):
            vendor = payload.get("vendor", "huawei")
            ne_type = payload["ne_type"]
            version = payload["version"]
            try:
                await self.db.execute(
                    "INSERT INTO ne_version (vendor, ne_type, version) VALUES (?, ?, ?)",
                    (vendor, ne_type, version),
                )
            except Exception:
                return JSONResponse(
                    status_code=409,
                    content={"detail": "该网元版本已存在"},
                )
            rows = await self.db.query(
                "SELECT id, vendor, ne_type, version, created_at FROM ne_version "
                "WHERE vendor=? AND ne_type=? AND version=?",
                (vendor, ne_type, version),
            )
            return rows[0]

        @self.router.delete("/ne-versions/{ne_id}")
        async def delete_ne_version(ne_id: int):
            # Check for associated files in file_entry table
            files = await self.db.query(
                "SELECT id FROM file_entry WHERE ne_version_id=? AND type='file'", (ne_id,)
            )
            if files:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "该网元版本下存在关联文件，无法删除"},
                )
            await self.db.execute("DELETE FROM ne_version WHERE id=?", (ne_id,))
            return {"ok": True}

        # ── File Entry Management ───────────────────────────────────────

        @self.router.get("/entries")
        async def list_entries(parent_id: int | None = Query(None)):
            if parent_id is not None:
                # Verify parent entry exists and is a folder
                parent_rows = await self.db.query(
                    "SELECT id, type FROM file_entry WHERE id=?", (parent_id,)
                )
                if not parent_rows:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "指定目录不存在"},
                    )
                if parent_rows[0]["type"] != "folder":
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "指定条目不是文件夹"},
                    )
                rows = await self.db.query(
                    "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                    "e.file_size, e.description, e.created_at, e.updated_at, "
                    "n.vendor, n.ne_type, n.version "
                    "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                    "WHERE e.parent_id=? "
                    "ORDER BY e.type DESC, e.name ASC",
                    (parent_id,),
                )
            else:
                rows = await self.db.query(
                    "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                    "e.file_size, e.description, e.created_at, e.updated_at, "
                    "n.vendor, n.ne_type, n.version "
                    "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                    "WHERE e.parent_id IS NULL "
                    "ORDER BY e.type DESC, e.name ASC"
                )
            return rows

        @self.router.get("/entries/{entry_id}/path")
        async def get_entry_path(entry_id: int):
            path_chain = []
            current_id = entry_id

            while current_id is not None:
                rows = await self.db.query(
                    "SELECT id, parent_id, name FROM file_entry WHERE id=?",
                    (current_id,),
                )
                if not rows:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "条目不存在"},
                    )
                entry = rows[0]
                path_chain.append({"id": entry["id"], "name": entry["name"]})
                current_id = entry["parent_id"]

            # Reverse to get root-first order
            path_chain.reverse()
            return path_chain

        @self.router.post("/entries")
        async def create_entry(payload: dict):
            parent_id = payload.get("parent_id")
            name = payload.get("name", "").strip()

            if not name:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "文件夹名称不能为空"},
                )

            if parent_id is not None:
                # Verify parent exists and is a folder
                parent_rows = await self.db.query(
                    "SELECT id, type FROM file_entry WHERE id=?", (parent_id,)
                )
                if not parent_rows:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "父目录不存在"},
                    )
                if parent_rows[0]["type"] != "folder":
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "父条目不是文件夹"},
                    )

            try:
                await self.db.execute(
                    "INSERT INTO file_entry (parent_id, name, type) VALUES (?, ?, 'folder')",
                    (parent_id, name),
                )
            except Exception:
                return JSONResponse(
                    status_code=409,
                    content={"detail": "同名文件夹已存在"},
                )

            rows = await self.db.query(
                "SELECT id, parent_id, name, type, ne_version_id, file_size, "
                "description, created_at, updated_at "
                "FROM file_entry WHERE parent_id IS ? AND name=? AND type='folder' "
                "ORDER BY id DESC LIMIT 1",
                (parent_id, name),
            )
            entry = rows[0]

            # Create physical directory using entry_id as name
            folder_path = MML_STORAGE_ROOT / str(entry["id"])
            folder_path.mkdir(parents=True, exist_ok=True)

            return entry

        @self.router.delete("/entries/{entry_id}")
        async def delete_entry(entry_id: int):
            rows = await self.db.query(
                "SELECT id, parent_id, name, type FROM file_entry WHERE id=?",
                (entry_id,),
            )
            if not rows:
                return JSONResponse(
                    status_code=404,
                    content={"detail": "条目不存在"},
                )
            entry = rows[0]

            if entry["type"] == "file":
                # Delete single file: DB record + disk file
                file_rows = await self.db.query(
                    "SELECT file_path FROM file_entry WHERE id=?", (entry_id,)
                )
                if file_rows:
                    p = _safe_file_path(file_rows[0]["file_path"])
                    if p and p.exists():
                        p.unlink()
                await self.db.execute("DELETE FROM file_entry WHERE id=?", (entry_id,))
            else:
                # Folder: recursively collect all descendant entry IDs
                all_ids = []

                async def collect_ids(eid: int):
                    children = await self.db.query(
                        "SELECT id, type FROM file_entry WHERE parent_id=?", (eid,)
                    )
                    for child in children:
                        all_ids.append((child["id"], child["type"]))
                        if child["type"] == "folder":
                            await collect_ids(child["id"])

                all_ids.append((entry_id, "folder"))
                await collect_ids(entry_id)

                # Delete disk files for all file-type entries
                for eid, etype in all_ids:
                    if etype == "file":
                        file_rows = await self.db.query(
                            "SELECT file_path FROM file_entry WHERE id=?", (eid,)
                        )
                        if file_rows:
                            p = _safe_file_path(file_rows[0]["file_path"])
                            if p and p.exists():
                                p.unlink()

                # Delete disk directories for all folder-type entries (children first)
                folder_ids = [eid for eid, etype in all_ids if etype == "folder"]
                for fid in reversed(folder_ids):
                    folder_path = MML_STORAGE_ROOT / str(fid)
                    if folder_path.exists():
                        shutil.rmtree(str(folder_path))

                # Delete all database records
                for eid, _ in all_ids:
                    await self.db.execute("DELETE FROM file_entry WHERE id=?", (eid,))

            return {"ok": True}

        # ── File Upload ─────────────────────────────────────────────────

        @self.router.post("/upload")
        async def upload_files(
            metadata: str = Form(...),
            files: list[UploadFile] = File(...),
        ):
            try:
                meta = json.loads(metadata)
            except json.JSONDecodeError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "metadata 不是有效的 JSON"},
                )

            parent_id = meta.get("parent_id")
            items = meta.get("items", {})

            # Validate parent_id if provided
            if parent_id is not None:
                parent_rows = await self.db.query(
                    "SELECT id, type FROM file_entry WHERE id=?", (parent_id,)
                )
                if not parent_rows:
                    return JSONResponse(
                        status_code=404,
                        content={"detail": "父目录不存在"},
                    )
                if parent_rows[0]["type"] != "folder":
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "父条目不是文件夹"},
                    )

            # Determine storage directory
            if parent_id is not None:
                storage_dir = MML_STORAGE_ROOT / str(parent_id)
            else:
                storage_dir = MML_STORAGE_ROOT
            storage_dir.mkdir(parents=True, exist_ok=True)

            uploaded = []
            failed = []
            for f in files:
                filename = f.filename
                suffix = Path(filename).suffix.lower()

                # Validate extension
                if suffix not in (".mml", ".txt"):
                    failed.append({"filename": filename, "reason": "不支持的文件类型"})
                    continue

                # Validate file has corresponding item in metadata
                if filename not in items:
                    failed.append({"filename": filename, "reason": "元数据中缺少该文件"})
                    continue

                item_meta = items[filename]
                ne_version_id = item_meta.get("ne_version_id")

                # Validate ne_version_id exists
                if ne_version_id is not None:
                    ne_rows = await self.db.query(
                        "SELECT id FROM ne_version WHERE id=?", (ne_version_id,)
                    )
                    if not ne_rows:
                        failed.append({"filename": filename, "reason": "网元版本不存在"})
                        continue

                content_bytes = await f.read()

                # Insert into database first to get entry_id
                await self.db.execute(
                    "INSERT INTO file_entry (parent_id, name, type, ne_version_id, file_size) "
                    "VALUES (?, ?, 'file', ?, ?)",
                    (parent_id, filename, ne_version_id, len(content_bytes)),
                )

                rows = await self.db.query(
                    "SELECT id FROM file_entry "
                    "WHERE parent_id IS ? AND name=? AND type='file' "
                    "ORDER BY id DESC LIMIT 1",
                    (parent_id, filename),
                )
                if not rows:
                    failed.append({"filename": filename, "reason": "数据库写入失败"})
                    continue
                entry_id = rows[0]["id"]

                # Store on disk using entry_id as filename
                disk_filename = f"{entry_id}{suffix}"
                disk_path = storage_dir / disk_filename

                try:
                    disk_path.write_bytes(content_bytes)
                except OSError:
                    # 磁盘写入失败，回滚数据库记录
                    await self.db.execute("DELETE FROM file_entry WHERE id=?", (entry_id,))
                    failed.append({"filename": filename, "reason": "磁盘写入失败"})
                    continue

                # Update file_path in database
                await self.db.execute(
                    "UPDATE file_entry SET file_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(disk_path), entry_id),
                )

                # Fetch the complete entry to return
                result_rows = await self.db.query(
                    "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                    "e.file_size, e.file_path, e.description, e.created_at, e.updated_at, "
                    "n.vendor, n.ne_type, n.version "
                    "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                    "WHERE e.id=?",
                    (entry_id,),
                )
                if result_rows:
                    uploaded.append(result_rows[0])

            return {"uploaded": uploaded, "failed": failed}

        # ── File Content Operations ─────────────────────────────────────

        @self.router.get("/files/{file_id}/content")
        async def get_file_content(file_id: int):
            rows = await self.db.query(
                "SELECT id, name, file_path FROM file_entry WHERE id=? AND type='file'",
                (file_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = _safe_file_path(rows[0]["file_path"])
            if p is None or not p.exists():
                return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
            content = p.read_text(encoding="utf-8")
            return {"content": content}

        @self.router.put("/files/{file_id}/content")
        async def update_file_content(file_id: int, payload: dict):
            rows = await self.db.query(
                "SELECT id, file_path FROM file_entry WHERE id=? AND type='file'",
                (file_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = _safe_file_path(rows[0]["file_path"])
            if p is None:
                return JSONResponse(status_code=400, content={"detail": "文件路径无效"})
            p.parent.mkdir(parents=True, exist_ok=True)
            new_content = payload["content"]
            p.write_text(new_content, encoding="utf-8")
            await self.db.execute(
                "UPDATE file_entry SET file_size=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (len(new_content.encode("utf-8")), file_id),
            )
            return {"ok": True}

        @self.router.get("/files/{file_id}/download")
        async def download_file(file_id: int):
            rows = await self.db.query(
                "SELECT id, name, file_path FROM file_entry WHERE id=? AND type='file'",
                (file_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = _safe_file_path(rows[0]["file_path"])
            if p is None or not p.exists():
                return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
            return FileResponse(str(p), filename=rows[0]["name"])

        @self.router.put("/files/{file_id}")
        async def update_file_meta(file_id: int, payload: dict):
            rows = await self.db.query(
                "SELECT id FROM file_entry WHERE id=? AND type='file'",
                (file_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})

            updates = []
            params: list = []

            if "ne_version_id" in payload:
                updates.append("ne_version_id=?")
                params.append(payload["ne_version_id"])
            if "name" in payload:
                updates.append("name=?")
                params.append(payload["name"])

            if not updates:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "没有需要更新的字段"},
                )

            updates.append("updated_at=CURRENT_TIMESTAMP")
            params.append(file_id)

            await self.db.execute(
                f"UPDATE file_entry SET {', '.join(updates)} WHERE id=?",
                tuple(params),
            )

            result_rows = await self.db.query(
                "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                "e.file_size, e.file_path, e.description, e.created_at, e.updated_at, "
                "n.vendor, n.ne_type, n.version "
                "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                "WHERE e.id=?",
                (file_id,),
            )
            return result_rows[0]

        # ── Stats ───────────────────────────────────────────────────────

        @self.router.get("/stats")
        async def get_stats():
            fc = await self.db.query("SELECT COUNT(*) AS cnt FROM file_entry WHERE type='file'")
            nc = await self.db.query("SELECT COUNT(*) AS cnt FROM ne_version")
            return {
                "file_count": fc[0]["cnt"] if fc else 0,
                "ne_version_count": nc[0]["cnt"] if nc else 0,
            }

        # ── Dependency Mining: Command Instance Extraction ─────────────

        @self.router.post("/scripts/{file_id}/extract-commands")
        async def extract_commands(file_id: int):
            """Parse a script file and persist command instances."""
            rows = await self.db.query(
                "SELECT id, name, file_path, ne_version_id FROM file_entry WHERE id=? AND type='file'",
                (file_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            entry = rows[0]
            ne_version_id = entry["ne_version_id"]
            if not ne_version_id:
                return JSONResponse(status_code=400, content={"detail": "文件未绑定网元版本"})

            p = _safe_file_path(entry["file_path"])
            if p is None or not p.exists():
                return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
            content = read_text_auto(p)

            result = self.parser.parse_text_with_report(content)
            commands = result["commands"]
            report = result["report"]

            # Delete old instances for re-extraction
            await self.db.execute(
                "DELETE FROM command_instance WHERE file_entry_id=?", (file_id,)
            )

            instances = []
            for idx, cmd in enumerate(commands):
                params_json = json.dumps(cmd["params"], ensure_ascii=False)
                await self.db.execute(
                    "INSERT INTO command_instance "
                    "(file_entry_id, ne_version_id, command_index, operation, name, params_json, line_number) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (file_id, ne_version_id, idx, cmd["operation"], cmd["name"],
                     params_json, cmd["line_number"]),
                )
                inst_rows = await self.db.query(
                    "SELECT id, file_entry_id, ne_version_id, command_index, "
                    "operation, name, params_json, line_number "
                    "FROM command_instance WHERE file_entry_id=? AND command_index=? "
                    "ORDER BY id DESC LIMIT 1",
                    (file_id, idx),
                )
                if inst_rows:
                    row = inst_rows[0]
                    row["params"] = json.loads(row["params_json"])
                    instances.append(row)

            return {"instances": instances, "total": len(instances), "report": report}

        @self.router.post("/versions/{ne_version_id}/batch-extract")
        async def batch_extract_commands(ne_version_id: int):
            """[DEPRECATED] Extract command instances from all files of a given NE version.

            Superseded by POST /files/mine which handles extraction + generation in one step.
            Kept for backward compatibility with existing tests.
            """
            file_rows = await self.db.query(
                "SELECT id, name, file_path FROM file_entry "
                "WHERE ne_version_id=? AND type='file'",
                (ne_version_id,),
            )
            if not file_rows:
                return {"extracted": [], "total_files": 0, "total_instances": 0}

            extracted = []
            total_instances = 0
            for entry in file_rows:
                p = _safe_file_path(entry["file_path"])
                if p is None or not p.exists():
                    continue
                content = p.read_text(encoding="utf-8")
                result = self.parser.parse_text_with_report(content)
                commands = result["commands"]

                await self.db.execute(
                    "DELETE FROM command_instance WHERE file_entry_id=?", (entry["id"],)
                )

                for idx, cmd in enumerate(commands):
                    params_json = json.dumps(cmd["params"], ensure_ascii=False)
                    await self.db.execute(
                        "INSERT INTO command_instance "
                        "(file_entry_id, ne_version_id, command_index, operation, name, params_json, line_number) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (entry["id"], ne_version_id, idx, cmd["operation"], cmd["name"],
                         params_json, cmd["line_number"]),
                    )

                extracted.append({
                    "file_id": entry["id"],
                    "file_name": entry["name"],
                    "instance_count": len(commands),
                })
                total_instances += len(commands)

            return {
                "extracted": extracted,
                "total_files": len(extracted),
                "total_instances": total_instances,
            }

        # ── Dependency Mining: Candidate Generation ────────────────────
        # [DEPRECATED] Superseded by POST /files/mine (incremental file-level mining).
        # Kept for backward compatibility with existing tests.

        @self.router.post("/candidates/generate")
        async def generate_candidates_endpoint(payload: dict):
            """[DEPRECATED] Generate dependency candidates for a given NE version scope.

            Superseded by POST /files/mine. Kept for backward compatibility.
            """
            ne_version_id = payload["ne_version_id"]

            # Query all command instances for this ne_version, grouped by file
            rows = await self.db.query(
                "SELECT id, file_entry_id, command_index, operation, name, "
                "params_json, line_number "
                "FROM command_instance WHERE ne_version_id=? "
                "ORDER BY file_entry_id, command_index",
                (ne_version_id,),
            )

            scripts: dict[int, dict] = {}
            for row in rows:
                fid = row["file_entry_id"]
                if fid not in scripts:
                    scripts[fid] = {
                        "file_entry_id": fid,
                        "ne_version_id": ne_version_id,
                        "commands": [],
                    }
                scripts[fid]["commands"].append({
                    "operation": row["operation"],
                    "name": row["name"],
                    "params": json.loads(row["params_json"]),
                    "line_number": row["line_number"],
                })

            if not scripts:
                return {"candidates": [], "total": 0}

            from candidate_engine import generate_candidates as _gen_candidates
            candidates = _gen_candidates(list(scripts.values()))

            # Persist candidates (upsert by unique key)
            persisted = []
            for c in candidates:
                scores_json = json.dumps(c["scores"], ensure_ascii=False)
                evidence_json = json.dumps(c["evidence"], ensure_ascii=False)
                try:
                    await self.db.execute(
                        "INSERT INTO dependency_candidate "
                        "(ne_version_id, ref_command, ref_param, def_command, def_param, "
                        "status, confidence, scores_json, evidence_json, review_route) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (ne_version_id, c["ref_command"], c["ref_param"],
                         c["def_command"], c["def_param"], c["status"],
                         c["confidence"], scores_json, evidence_json,
                         c.get("review_route", "manual")),
                    )
                except Exception:
                    # Unique-key conflict: update scores/evidence but preserve
                    # human terminal states (graph / non_graph / rejected).
                    await self.db.execute(
                        "UPDATE dependency_candidate SET "
                        "status = CASE "
                        "  WHEN status IN ('graph', 'non_graph', 'rejected') THEN status "
                        "  ELSE ? "
                        "END, "
                        "confidence=?, scores_json=?, evidence_json=?, "
                        "review_route = CASE "
                        "  WHEN status IN ('graph', 'non_graph', 'rejected') THEN review_route "
                        "  ELSE ? "
                        "END, "
                        "updated_at=CURRENT_TIMESTAMP "
                        "WHERE ne_version_id=? AND ref_command=? AND ref_param=? "
                        "AND def_command=? AND def_param=?",
                        (c["status"], c["confidence"], scores_json, evidence_json,
                         c.get("review_route", "manual"),
                         ne_version_id, c["ref_command"], c["ref_param"],
                         c["def_command"], c["def_param"]),
                    )

                cand_rows = await self.db.query(
                    "SELECT id, ne_version_id, ref_command, ref_param, def_command, "
                    "def_param, status, confidence, scores_json, evidence_json, "
                    "review_route, created_at, updated_at "
                    "FROM dependency_candidate WHERE ne_version_id=? "
                    "AND ref_command=? AND ref_param=? AND def_command=? AND def_param=?",
                    (ne_version_id, c["ref_command"], c["ref_param"],
                     c["def_command"], c["def_param"]),
                )
                if cand_rows:
                    row = cand_rows[0]
                    row["scores"] = json.loads(row["scores_json"])
                    row["evidence"] = json.loads(row["evidence_json"])
                    persisted.append(row)

            return {"candidates": persisted, "total": len(persisted)}

        # ── Dependency Mining: Review Queue ─────────────────────────────

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
                f"active_algorithm_version, created_at, updated_at "
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
            # Only pending-like states can accept (rejected must be re-activated to pending via new evidence)
            pending_like = ("pending", "auto_passed", "llm_review", "man_review")
            if current not in pending_like:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"只能从 pending 状态接受，当前: {current}"},
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
            pending_like = ("pending", "auto_passed", "llm_review", "man_review")
            if current not in pending_like:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"只能从 pending 状态拒绝，当前: {current}"},
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

        # ── Dependency Mining: Mark Non-Graph ────────────────────────────

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
            pending_like = ("pending", "auto_passed", "llm_review", "man_review")
            if current not in pending_like:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"只能从 pending 状态标记非图谱，当前: {current}"},
                )

            # Update status to non_graph, clear review_route
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

        # ── Dependency Mining: Revert ────────────────────────────────────

        @self.router.post("/candidates/{candidate_id}/revert")
        async def revert_candidate(candidate_id: int, payload: dict):
            """Revert a candidate: graph→pending (delete edge), non_graph→pending."""
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

            # Determine review_route based on confidence
            review_route = self._determine_review_route(cand["confidence"])

            if current_status == "graph":
                # Revoke the associated graph_edge (set status='revoked')
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

                # Changelog
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

                # Changelog
                await self.db.execute(
                    "INSERT INTO graph_changelog "
                    "(candidate_id, change_type, snapshot_after, trigger_type, trigger_id) "
                    "VALUES (?, 'revert', ?, 'human', ?)",
                    (candidate_id,
                     json.dumps({"status": "pending", "from": "non_graph"}, ensure_ascii=False),
                     reviewer),
                )

            return {"ok": True, "candidate_id": candidate_id}

        # ── Dependency Mining: File-Level Mining ─────────────────────────

        @self.router.post("/files/mine")
        async def mine_selected_files(payload: dict):
            """Mine selected files: parse, generate candidates, merge into pool."""
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

            # Get algorithm version
            alg_ver = "v1"

            all_candidates = []

            for file_id in file_ids:
                # a. Parse file → command instances (delete old first, then re-insert)
                entry_rows = await self.db.query(
                    "SELECT id, name, file_path, ne_version_id FROM file_entry "
                    "WHERE id=? AND type='file'",
                    (file_id,),
                )
                if not entry_rows:
                    continue
                entry = entry_rows[0]
                p = _safe_file_path(entry["file_path"])
                if p is None or not p.exists():
                    continue
                content = read_text_auto(p)

                result = self.parser.parse_text_with_report(content)
                commands = result["commands"]

                # Delete old command instances and re-insert
                await self.db.execute(
                    "DELETE FROM command_instance WHERE file_entry_id=?", (file_id,)
                )
                for idx, cmd in enumerate(commands):
                    params_json = json.dumps(cmd["params"], ensure_ascii=False)
                    await self.db.execute(
                        "INSERT INTO command_instance "
                        "(file_entry_id, ne_version_id, command_index, operation, name, params_json, line_number) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (file_id, ne_version_id, idx, cmd["operation"], cmd["name"],
                         params_json, cmd["line_number"]),
                    )

                # b. Generate single-file candidates
                script = {
                    "file_entry_id": file_id,
                    "ne_version_id": ne_version_id,
                    "commands": commands,
                }
                from candidate_engine import generate_single_file_candidates
                local_candidates = generate_single_file_candidates(script)

                # c. Update file_mining_record
                await self.db.execute(
                    "INSERT INTO file_mining_record (file_entry_id, ne_version_id, mined, algorithm_version, command_count) "
                    "VALUES (?, ?, 1, ?, ?) "
                    "ON CONFLICT(file_entry_id) DO UPDATE SET "
                    "mined=1, algorithm_version=?, command_count=?, updated_at=CURRENT_TIMESTAMP",
                    (file_id, ne_version_id, alg_ver, len(commands), alg_ver, len(commands)),
                )

                # d. Merge each local candidate into pool
                for lc in local_candidates:
                    cand_key = (
                        lc["ref_command"], lc["ref_param"],
                        lc["def_command"], lc["def_param"],
                    )
                    confidence = lc["scores"]["confidence"]

                    # Find existing candidate
                    existing = await self.db.query(
                        "SELECT id, status, confidence, active_algorithm_version FROM dependency_candidate "
                        "WHERE ne_version_id=? AND ref_command=? AND ref_param=? "
                        "AND def_command=? AND def_param=?",
                        (ne_version_id, *cand_key),
                    )

                    if not existing:
                        # Create new candidate
                        review_route = self._determine_review_route(confidence)
                        scores_json = json.dumps(lc["scores"], ensure_ascii=False)
                        evidence_json = _json_serialize_evidence(lc["evidence"])

                        await self.db.execute(
                            "INSERT INTO dependency_candidate "
                            "(ne_version_id, ref_command, ref_param, def_command, def_param, "
                            "status, confidence, scores_json, evidence_json, "
                            "review_route, active_algorithm_version) "
                            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)",
                            (ne_version_id, *cand_key, confidence,
                             scores_json, evidence_json, review_route, alg_ver),
                        )
                        existing = await self.db.query(
                            "SELECT id, status, active_algorithm_version FROM dependency_candidate "
                            "WHERE ne_version_id=? AND ref_command=? AND ref_param=? "
                            "AND def_command=? AND def_param=?",
                            (ne_version_id, *cand_key),
                        )

                    cand_row = existing[0]
                    cand_id = cand_row["id"]
                    cand_status = cand_row["status"]

                    # UPSERT contribution
                    contrib_evidence = _json_serialize_evidence(lc["evidence"])
                    contrib_scores = json.dumps(lc["scores"], ensure_ascii=False)
                    await self.db.execute(
                        "INSERT INTO candidate_contribution "
                        "(candidate_id, file_entry_id, algorithm_version, evidence_json, scores_json) "
                        "VALUES (?, ?, ?, ?, ?) "
                        "ON CONFLICT(candidate_id, file_entry_id, algorithm_version) DO UPDATE SET "
                        "evidence_json=?, scores_json=?, updated_at=CURRENT_TIMESTAMP",
                        (cand_id, file_id, alg_ver, contrib_evidence, contrib_scores,
                         contrib_evidence, contrib_scores),
                    )

                    # Defer score recalculation until all files are processed
                    all_candidates.append((cand_id, cand_status))

            # After all files processed: query actual distinct mined file count
            total_mined_rows = await self.db.query(
                "SELECT COUNT(DISTINCT file_entry_id) as cnt FROM file_mining_record "
                "WHERE ne_version_id=? AND mined=1",
                (ne_version_id,),
            )
            total_mined_files = total_mined_rows[0]["cnt"] if total_mined_rows else 0

            # Recalculate scores for all affected candidates with correct denominator
            seen_cand_ids = set()
            for cand_id, cand_status in all_candidates:
                if cand_id in seen_cand_ids:
                    continue
                seen_cand_ids.add(cand_id)

                await self._recalculate_candidate_scores(cand_id, alg_ver, total_mined_files)

                # If status was 'rejected': reactivate
                if cand_status == "rejected":
                    updated_cand = await self.db.query(
                        "SELECT confidence FROM dependency_candidate WHERE id=?",
                        (cand_id,),
                    )
                    new_confidence = updated_cand[0]["confidence"] if updated_cand else 0.0
                    new_review_route = self._determine_review_route(new_confidence)
                    await self.db.execute(
                        "UPDATE dependency_candidate SET status='pending', review_route=?, "
                        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (new_review_route, cand_id),
                    )

            return {
                "mined_files": len(file_ids),
                "total_files": len(file_ids),
                "total_candidates": len(seen_cand_ids),
                "candidates": list(seen_cand_ids),
            }

        @self.router.post("/files/{file_id}/re-mine")
        async def re_mine_file(file_id: int):
            """Re-mine a single file: remove old contributions, recalculate, then re-mine."""
            # Verify file exists
            rows = await self.db.query(
                "SELECT id, ne_version_id FROM file_entry WHERE id=? AND type='file'",
                (file_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            ne_version_id = rows[0]["ne_version_id"]
            if not ne_version_id:
                return JSONResponse(status_code=400, content={"detail": "文件未绑定网元版本"})

            # Get current algorithm version from file_mining_record, default 'v1'
            fmr_rows = await self.db.query(
                "SELECT algorithm_version FROM file_mining_record WHERE file_entry_id=?",
                (file_id,),
            )
            alg_ver = fmr_rows[0]["algorithm_version"] if fmr_rows else "v1"

            # Step 1: Find candidates affected by this file's contributions
            affected_contribs = await self.db.query(
                "SELECT candidate_id FROM candidate_contribution "
                "WHERE file_entry_id=? AND algorithm_version=?",
                (file_id, alg_ver),
            )
            affected_cand_ids = list(set(c["candidate_id"] for c in affected_contribs))

            # Step 2: Delete this file's contributions for current algorithm version
            await self.db.execute(
                "DELETE FROM candidate_contribution "
                "WHERE file_entry_id=? AND algorithm_version=?",
                (file_id, alg_ver),
            )

            # Step 3: Recalculate affected candidates' scores and handle zero-contribution
            for cand_id in affected_cand_ids:
                cand_rows = await self.db.query(
                    "SELECT id, status, graph_edge_id FROM dependency_candidate WHERE id=?",
                    (cand_id,),
                )
                if not cand_rows:
                    continue
                cand_status = cand_rows[0]["status"]
                cand_graph_edge_id = cand_rows[0]["graph_edge_id"]

                # Count remaining contributions for active_algorithm_version
                remaining = await self.db.query(
                    "SELECT COUNT(*) as cnt FROM candidate_contribution "
                    "WHERE candidate_id=? AND algorithm_version=?",
                    (cand_id, alg_ver),
                )
                contrib_count = remaining[0]["cnt"] if remaining else 0

                if contrib_count == 0:
                    # graph/non_graph with zero contributions: KEEP, set scores to zero
                    if cand_status in ("graph", "non_graph"):
                        zero_scores = json.dumps({
                            "support": 0.0, "distinctiveness": 0.0,
                            "order_consistency": 0.0, "name_relevance": 0.0,
                        }, ensure_ascii=False)
                        empty_evidence = json.dumps({}, ensure_ascii=False)
                        await self.db.execute(
                            "UPDATE dependency_candidate SET confidence=0.0, scores_json=?, "
                            "evidence_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (zero_scores, empty_evidence, cand_id),
                        )
                        # Sync evidence clear to graph_edge if candidate is in graph
                        if cand_status == "graph" and cand_graph_edge_id:
                            await self.db.execute(
                                "UPDATE graph_edge SET evidence_json=?, confidence=0.0, "
                                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (empty_evidence, cand_graph_edge_id),
                            )
                    elif cand_status in ("pending", "rejected"):
                        # Delete zero-contribution candidates only if pending/rejected
                        await self.db.execute(
                            "DELETE FROM dependency_candidate WHERE id=?", (cand_id,)
                        )
                        continue
                else:
                    # Recalculate scores
                    await self._recalculate_candidate_scores(cand_id, alg_ver)  # total_mined_files will be auto-detected

            # Step 4: Re-execute mine logic for this single file
            resp = await mine_selected_files({"file_ids": [file_id]})
            if isinstance(resp, JSONResponse):
                return resp
            return resp

        @self.router.get("/files/mining-status")
        async def get_mining_status(ne_version_id: int = Query(...)):
            """Query file mining status for an NE version."""
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
            return rows

    # ── Helper Methods ────────────────────────────────────────────────

    @staticmethod
    def _determine_review_route(confidence: float) -> str:
        """Determine review route based on confidence score."""
        if confidence >= 0.85:
            return "auto"
        elif confidence >= 0.50:
            return "llm"
        else:
            return "manual"

    async def _recalculate_candidate_scores(self, cand_id: int, alg_ver: str, total_mined_files: int = 0):
        """Recalculate aggregated scores for a candidate from its contributions.

        Args:
            cand_id: candidate id
            alg_ver: algorithm version to filter contributions
            total_mined_files: total number of mined files for the ne_version (for support calc)
        """
        from candidate_engine import aggregate_contributions

        contribs = await self.db.query(
            "SELECT file_entry_id, scores_json, evidence_json FROM candidate_contribution "
            "WHERE candidate_id=? AND algorithm_version=?",
            (cand_id, alg_ver),
        )

        if not contribs:
            return

        # Get total mined files if not provided
        if total_mined_files <= 0:
            cand_rows = await self.db.query(
                "SELECT ne_version_id FROM dependency_candidate WHERE id=?",
                (cand_id,),
            )
            if cand_rows:
                mined_rows = await self.db.query(
                    "SELECT COUNT(DISTINCT file_entry_id) as cnt FROM file_mining_record "
                    "WHERE ne_version_id=? AND mined=1",
                    (cand_rows[0]["ne_version_id"],),
                )
                total_mined_files = mined_rows[0]["cnt"] if mined_rows else len(contribs)

        # Build contribution list for aggregation
        # Include ALL mined files: ones with hits as has_hit=True, and calculate
        # how many files had no hit for this candidate (for support denominator)
        hit_file_count = len(contribs)
        total_hit_count = 0
        contrib_list = []
        all_evidence = []
        per_file_data = []
        for c in contribs:
            file_entry_id = c["file_entry_id"]
            scores = json.loads(c["scores_json"])
            evidence = json.loads(c["evidence_json"])
            hit_count = evidence.get("hit_count", 1)
            total_hit_count += hit_count
            contrib_list.append({
                "has_hit": True,
                "hit_values": evidence.get("hit_values", []),
                "order_consistency": scores.get("order_consistency", 0.0),
                "name_relevance": scores.get("name_relevance", 0.0),
                "hit_count": hit_count,
                "confidence": scores.get("confidence", 0.0),
                "sample_scripts": evidence.get("sample_scripts", []),
            })
            all_evidence.append(evidence)
            per_file_data.append({
                "file_entry_id": file_entry_id,
                "hit_count": hit_count,
                "hit_values": evidence.get("hit_values", []),
                "sample_scripts": evidence.get("sample_scripts", []),
            })

        # Add placeholder contributions for files without hits (for correct support)
        no_hit_count = max(0, total_mined_files - hit_file_count)
        for _ in range(no_hit_count):
            contrib_list.append({
                "has_hit": False,
                "hit_values": [],
                "order_consistency": 0.0,
                "name_relevance": 0.0,
                "hit_count": 0,
                "confidence": 0.0,
                "sample_scripts": [],
            })

        aggregated = aggregate_contributions(contrib_list)

        # Collect all hit values across contributions for evidence
        all_values = set()
        for ev in all_evidence:
            vals = ev.get("hit_values", [])
            if isinstance(vals, (list, set)):
                all_values.update(vals)
            elif isinstance(vals, str):
                all_values.add(vals)

        all_scripts = []
        for pf in per_file_data:
            for s in pf["sample_scripts"]:
                all_scripts.append({
                    "file_entry_id": pf["file_entry_id"],
                    **s,
                })

        new_evidence = {
            "hit_count": total_hit_count,
            "hit_file_count": hit_file_count,
            "total_mined_files": total_mined_files,
            "hit_values": sorted(all_values),
            "sample_scripts": all_scripts[:10],
            "per_file": per_file_data,
        }

        new_scores = {
            "support": aggregated["support"],
            "distinctiveness": aggregated["distinctiveness"],
            "order_consistency": aggregated["order_consistency"],
            "name_relevance": aggregated["name_relevance"],
        }

        await self.db.execute(
            "UPDATE dependency_candidate SET confidence=?, scores_json=?, evidence_json=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (aggregated["confidence"],
             json.dumps(new_scores, ensure_ascii=False),
             json.dumps(new_evidence, ensure_ascii=False),
             cand_id),
        )

        # Sync evidence to graph_edge if candidate is in graph status
        cand_status_row = await self.db.query(
            "SELECT status, graph_edge_id FROM dependency_candidate WHERE id=?",
            (cand_id,),
        )
        if cand_status_row:
            cs = cand_status_row[0]
            if cs["status"] == "graph" and cs["graph_edge_id"]:
                await self.db.execute(
                    "UPDATE graph_edge SET evidence_json=?, confidence=?, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (json.dumps(new_evidence, ensure_ascii=False),
                     aggregated["confidence"],
                     cs["graph_edge_id"]),
                )
