# backend/plugins/mml_manager/main.py
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse
from core.plugin.context import PluginContext
from core.services.parser import ParserService
from core.services.database import DatabaseService

MML_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "mml_files"


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.parser: ParserService | None = None
        self.db: DatabaseService | None = None

    async def on_register(self, ctx: PluginContext) -> None:
        self.parser = ctx.get_service(ParserService)
        self.db = ctx.get_service(DatabaseService)
        ctx.register_menu("MML 管理", "document", "/plugins/mml-manager")

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
            CREATE TABLE IF NOT EXISTS mml_file (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                ne_version_id INTEGER NOT NULL REFERENCES ne_version(id),
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

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
            # Check for associated files
            files = await self.db.query(
                "SELECT id FROM mml_file WHERE ne_version_id=?", (ne_id,)
            )
            if files:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "该网元版本下存在关联文件，无法删除"},
                )
            await self.db.execute("DELETE FROM ne_version WHERE id=?", (ne_id,))
            return {"ok": True}

        # ── File Management ─────────────────────────────────────────────

        @self.router.post("/upload")
        async def upload_files(
            ne_version_id: int = Query(...),
            files: list[UploadFile] = File(...),
        ):
            # Look up the NE version to get vendor/ne_type/version for path
            ne_rows = await self.db.query(
                "SELECT vendor, ne_type, version FROM ne_version WHERE id=?",
                (ne_version_id,),
            )
            if not ne_rows:
                return JSONResponse(
                    status_code=404,
                    content={"detail": "网元版本不存在"},
                )
            ne = ne_rows[0]
            dest_dir = (
                MML_STORAGE_ROOT
                / ne["vendor"]
                / f"{ne['ne_type']}_{ne['version']}"
            )
            dest_dir.mkdir(parents=True, exist_ok=True)

            uploaded = []
            for f in files:
                # Validate extension
                suffix = Path(f.filename).suffix.lower()
                if suffix not in (".mml", ".txt"):
                    continue

                content_bytes = await f.read()
                # Resolve collisions
                target = dest_dir / f.filename
                stem = target.stem
                ext = target.suffix
                counter = 0
                while target.exists():
                    counter += 1
                    target = dest_dir / f"{stem}_{counter}{ext}"

                target.write_bytes(content_bytes)

                await self.db.execute(
                    "INSERT INTO mml_file (filename, ne_version_id, file_path, file_size, description) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (f.filename, ne_version_id, str(target), len(content_bytes), None),
                )
                rows = await self.db.query(
                    "SELECT id, filename, ne_version_id, file_path, file_size, description, "
                    "created_at, updated_at FROM mml_file WHERE file_path=?",
                    (str(target),),
                )
                if rows:
                    uploaded.append(rows[0])
            return uploaded

        @self.router.get("/files")
        async def list_files(ne_version_id: int | None = Query(None)):
            sql = (
                "SELECT f.id, f.filename, f.ne_version_id, f.file_path, f.file_size, "
                "f.description, f.created_at, f.updated_at, "
                "n.vendor, n.ne_type, n.version "
                "FROM mml_file f JOIN ne_version n ON f.ne_version_id = n.id"
            )
            params: tuple = ()
            if ne_version_id is not None:
                sql += " WHERE f.ne_version_id=?"
                params = (ne_version_id,)
            sql += " ORDER BY f.id"
            return await self.db.query(sql, params)

        @self.router.get("/files/{file_id}")
        async def get_file(file_id: int):
            rows = await self.db.query(
                "SELECT f.id, f.filename, f.ne_version_id, f.file_path, f.file_size, "
                "f.description, f.created_at, f.updated_at, "
                "n.vendor, n.ne_type, n.version "
                "FROM mml_file f JOIN ne_version n ON f.ne_version_id = n.id "
                "WHERE f.id=?",
                (file_id,),
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            return rows[0]

        @self.router.get("/files/{file_id}/content")
        async def get_file_content(file_id: int):
            rows = await self.db.query(
                "SELECT file_path FROM mml_file WHERE id=?", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = Path(rows[0]["file_path"])
            if not p.exists():
                return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
            content = p.read_text(encoding="utf-8")
            return {"content": content}

        @self.router.put("/files/{file_id}/content")
        async def update_file_content(file_id: int, payload: dict):
            rows = await self.db.query(
                "SELECT file_path FROM mml_file WHERE id=?", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = Path(rows[0]["file_path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            new_content = payload["content"]
            p.write_text(new_content, encoding="utf-8")
            await self.db.execute(
                "UPDATE mml_file SET file_size=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (len(new_content.encode("utf-8")), file_id),
            )
            return {"ok": True}

        @self.router.get("/files/{file_id}/download")
        async def download_file(file_id: int):
            rows = await self.db.query(
                "SELECT file_path, filename FROM mml_file WHERE id=?", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = Path(rows[0]["file_path"])
            if not p.exists():
                return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
            return FileResponse(str(p), filename=rows[0]["filename"])

        @self.router.delete("/files/{file_id}")
        async def delete_file(file_id: int):
            rows = await self.db.query(
                "SELECT file_path FROM mml_file WHERE id=?", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = Path(rows[0]["file_path"])
            if p.exists():
                p.unlink()
            await self.db.execute("DELETE FROM mml_file WHERE id=?", (file_id,))
            return {"ok": True}

        # ── Stats ───────────────────────────────────────────────────────

        @self.router.get("/stats")
        async def get_stats():
            fc = await self.db.query("SELECT COUNT(*) AS cnt FROM mml_file")
            nc = await self.db.query("SELECT COUNT(*) AS cnt FROM ne_version")
            return {
                "file_count": fc[0]["cnt"] if fc else 0,
                "ne_version_count": nc[0]["cnt"] if nc else 0,
            }
