from typing import Any


class ServiceRegistry:
    """全局服务注册表，所有公共能力的容器"""

    def __init__(self) -> None:
        self._services: dict[type, Any] = {}

    def register(self, service_type: type, instance: Any) -> None:
        self._services[service_type] = instance

    def get(self, service_type: type) -> Any:
        if service_type not in self._services:
            raise KeyError(f"Service {service_type.__name__} not registered")
        return self._services[service_type]

    def list_services(self) -> list[type]:
        return list(self._services.keys())
