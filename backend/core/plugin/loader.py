from pathlib import Path
import toml


class PluginLoader:
    """扫描并加载插件"""

    def __init__(self, plugins_dir: Path) -> None:
        self._plugins_dir = plugins_dir

    def _load_order(self) -> list[str]:
        """读取 order.toml 中定义的插件展示顺序"""
        order_path = self._plugins_dir / "order.toml"
        if order_path.exists():
            data = toml.load(order_path)
            return data.get("order", [])
        return []

    def scan(self) -> list[dict]:
        """扫描插件目录，按 order.toml 排序后返回所有 plugin.toml 的内容"""
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

        # 按 order.toml 排序，未在列表中的排在末尾
        order = self._load_order()
        def sort_key(m: dict) -> int:
            name = m["plugin"]["name"]
            try:
                return order.index(name)
            except ValueError:
                return len(order)
        manifests.sort(key=sort_key)

        return manifests
