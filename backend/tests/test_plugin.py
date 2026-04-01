# backend/tests/test_plugin.py
import pytest
from pathlib import Path
from core.services.registry import ServiceRegistry
from core.plugin.context import PluginContext
from core.plugin.loader import PluginLoader


class FakeService:
    pass


def test_context_get_service():
    registry = ServiceRegistry()
    registry.register(FakeService, FakeService())
    ctx = PluginContext(registry, name="test")
    assert isinstance(ctx.get_service(FakeService), FakeService)


def test_loader_scan_plugins(tmp_path):
    # 创建一个模拟插件目录
    plugin_dir = tmp_path / "test_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.toml").write_text(
        '[plugin]\nname = "test_plugin"\nversion = "0.1.0"\n'
        'description = "test"\n\n'
        '[plugin.backend]\nentry = "main.py"\n'
        'routes_prefix = "/api/plugins/test"\n\n'
        '[plugin.frontend]\nentry = "src/index.vue"\n'
        'menu_title = "Test"\nicon = "test"\n'
    )
    loader = PluginLoader(plugins_dir=tmp_path)
    manifests = loader.scan()
    assert len(manifests) == 1
    assert manifests[0]["plugin"]["name"] == "test_plugin"
