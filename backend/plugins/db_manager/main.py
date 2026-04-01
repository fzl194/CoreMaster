import re
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from core.plugin.context import PluginContext
from core.services.database import DatabaseService

TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.db: DatabaseService | None = None

    async def on_register(self, ctx: PluginContext) -> None:
        self.db = ctx.get_service(DatabaseService)

        @self.router.get("/tables")
        async def list_tables():
            rows = await self.db.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            result = []
            for r in rows:
                cnt_rows = await self.db.query(f'SELECT COUNT(*) AS cnt FROM "{r["name"]}"')
                result.append({"name": r["name"], "row_count": cnt_rows[0]["cnt"] if cnt_rows else 0})
            return result

        @self.router.get("/tables/{table_name}/schema")
        async def table_schema(table_name: str):
            if not TABLE_NAME_RE.match(table_name):
                return JSONResponse(status_code=400, content={"detail": "非法表名"})
            exists = await self.db.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            )
            if not exists:
                return JSONResponse(status_code=404, content={"detail": "表不存在"})
            return await self.db.query(f'PRAGMA table_info("{table_name}")')

        @self.router.get("/tables/{table_name}/rows")
        async def table_rows(table_name: str, limit: int = 50, offset: int = 0):
            if not TABLE_NAME_RE.match(table_name):
                return JSONResponse(status_code=400, content={"detail": "非法表名"})
            exists = await self.db.query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
            )
            if not exists:
                return JSONResponse(status_code=404, content={"detail": "表不存在"})
            count_rows = await self.db.query(f'SELECT COUNT(*) AS total FROM "{table_name}"')
            total = count_rows[0]["total"] if count_rows else 0
            rows = await self.db.query(
                f'SELECT rowid, * FROM "{table_name}" ORDER BY rowid LIMIT ? OFFSET ?',
                (limit, offset),
            )
            return {"rows": rows, "total": total}

        @self.router.post("/tables/{table_name}/rows")
        async def insert_row(table_name: str, payload: dict):
            if not TABLE_NAME_RE.match(table_name):
                return JSONResponse(status_code=400, content={"detail": "非法表名"})
            fields: dict = payload.get("fields", {})
            if not fields:
                return JSONResponse(status_code=400, content={"detail": "无数据"})
            cols = ", ".join(f'"{k}"' for k in fields.keys())
            placeholders = ", ".join("?" for _ in fields)
            values = tuple(fields.values())
            await self.db.execute(
                f'INSERT INTO "{table_name}" ({cols}) VALUES ({placeholders})', values
            )
            rowid_rows = await self.db.query("SELECT last_insert_rowid() AS id")
            rowid = rowid_rows[0]["id"] if rowid_rows else None
            new_rows = await self.db.query(
                f'SELECT rowid, * FROM "{table_name}" WHERE rowid=?', (rowid,)
            )
            return new_rows[0] if new_rows else {"ok": True}

        @self.router.put("/tables/{table_name}/rows/{row_id}")
        async def update_row(table_name: str, row_id: int, payload: dict):
            if not TABLE_NAME_RE.match(table_name):
                return JSONResponse(status_code=400, content={"detail": "非法表名"})
            fields: dict = payload.get("fields", {})
            if not fields:
                return JSONResponse(status_code=400, content={"detail": "无数据"})
            set_clause = ", ".join(f'"{k}"=?' for k in fields.keys())
            values = tuple(fields.values()) + (row_id,)
            await self.db.execute(
                f'UPDATE "{table_name}" SET {set_clause} WHERE rowid=?', values
            )
            new_rows = await self.db.query(
                f'SELECT rowid, * FROM "{table_name}" WHERE rowid=?', (row_id,)
            )
            return new_rows[0] if new_rows else {"ok": True}

        @self.router.delete("/tables/{table_name}/rows/{row_id}")
        async def delete_row(table_name: str, row_id: int):
            if not TABLE_NAME_RE.match(table_name):
                return JSONResponse(status_code=400, content={"detail": "非法表名"})
            await self.db.execute(f'DELETE FROM "{table_name}" WHERE rowid=?', (row_id,))
            return {"ok": True}
