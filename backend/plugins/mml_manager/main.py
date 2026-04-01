# backend/plugins/mml_manager/main.py
import json
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Query, Form
from fastapi.responses import FileResponse, JSONResponse
from core.plugin.context import PluginContext
from core.services.parser import ParserService
from core.services.database import DatabaseService

MML_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "mml_files"


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

        # Ensure storage root exists
        MML_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

        # ── Parse endpoints (existing) ──────────────────────────────────

        @self.router.post("/parse")
        async def parse_mml(file: UploadFile = File(...)):
            content = (await file.read()).decode("utf-8")
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
