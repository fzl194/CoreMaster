import pytest
from core.services.registry import ServiceRegistry


class FakeService:
    async def do_stuff(self) -> str:
        return "done"


@pytest.mark.asyncio
async def test_register_and_get_service():
    registry = ServiceRegistry()
    svc = FakeService()
    registry.register(FakeService, svc)
    assert registry.get(FakeService) is svc
    assert await registry.get(FakeService).do_stuff() == "done"


def test_list_services():
    registry = ServiceRegistry()
    registry.register(FakeService, FakeService())
    assert FakeService in registry.list_services()


def test_get_unregistered_raises():
    registry = ServiceRegistry()
    with pytest.raises(KeyError):
        registry.get(FakeService)
