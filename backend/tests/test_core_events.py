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
