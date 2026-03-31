import pytest
import pytest_asyncio
from core.services.database import DatabaseService


@pytest_asyncio.fixture
async def db(tmp_path):
    service = DatabaseService(db_path=str(tmp_path / "test.db"))
    await service.start()
    yield service
    await service.stop()


@pytest.mark.asyncio
async def test_execute_and_query(db):
    await db.execute(
        "CREATE TABLE test_items (id INTEGER PRIMARY KEY, name TEXT)"
    )
    await db.execute("INSERT INTO test_items (name) VALUES (?)", ("item1",))
    rows = await db.query("SELECT * FROM test_items")
    assert len(rows) == 1
    assert rows[0]["name"] == "item1"


@pytest.mark.asyncio
async def test_query_empty(db):
    await db.execute("CREATE TABLE empty_table (id INTEGER PRIMARY KEY)")
    rows = await db.query("SELECT * FROM empty_table")
    assert rows == []
