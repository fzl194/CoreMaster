from typing import Any
from core.services.registry import ServiceRegistry


class PluginContext:
    """插件运行上下文，提供访问公共能力的接口"""

    def __init__(self, registry: ServiceRegistry, name: str) -> None:
        self._registry = registry
        self._name = name

    def get_service(self, service_type: type) -> Any:
        return self._registry.get(service_type)

    def register_service(self, service_type: type, instance: Any) -> None:
        self._registry.register(service_type, instance)
