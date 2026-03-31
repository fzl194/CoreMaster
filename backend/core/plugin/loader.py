from pathlib import Path
import toml


class PluginLoader:
    """扫描并加载插件"""

    def __init__(self, plugins_dir: Path) -> None:
        self._plugins_dir = plugins_dir

    def scan(self) -> list[dict]:
        """扫描插件目录，返回所有 plugin.toml 的内容"""
        manifests = []
        if not self._plugins_dir.exists():
            return manifests
        for plugin_path in sorted(self._plugins_dir.iterdir()):
            if not plugin_path.is_dir():
                continue
            toml_path = plugin_path / "plugin.toml"
            if not toml_path.exists():
                continue
            manifest = toml.load(toml_path)
            manifest["_dir"] = str(plugin_path)
            manifests.append(manifest)
        return manifests
