# backend/tests/test_integration.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app


@pytest_asyncio.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_plugins(client):
    resp = await client.get("/api/plugins")
    assert resp.status_code == 200
    data = resp.json()
    assert "menus" in data
    assert "plugins" in data
    # 至少有 mml_manager
    names = [p["name"] for p in data["plugins"]]
    assert "mml_manager" in names


@pytest.mark.asyncio
async def test_parse_text_via_plugin(client):
    resp = await client.post(
        "/api/plugins/mml_manager/parse-text",
        json={"text": 'ADD APN: APN="test", BINDVPN=ENABLE;'},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["commands"][0]["name"] == "APN"
