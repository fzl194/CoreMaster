import aiosqlite
from pathlib import Path


class DatabaseService:
    """SQLite 数据库服务"""

    def __init__(self, db_path: str = "coremaster.db") -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def start(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")

    async def stop(self) -> None:
        if self._conn:
            await self._conn.close()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
