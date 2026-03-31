from typing import Any
from core.services.registry import ServiceRegistry


class PluginContext:
    """插件运行上下文，提供访问公共能力的接口"""

    def __init__(self, registry: ServiceRegistry, name: str) -> None:
        self._registry = registry
        self._name = name
        self._menus: list[dict] = []

    def get_service(self, service_type: type) -> Any:
        return self._registry.get(service_type)

    def register_service(self, service_type: type, instance: Any) -> None:
        self._registry.register(service_type, instance)

    def register_menu(self, title: str, icon: str, path: str) -> None:
        self._menus.append({"title": title, "icon": icon, "path": path})

    def get_menus(self) -> list[dict]:
        return list(self._menus)
