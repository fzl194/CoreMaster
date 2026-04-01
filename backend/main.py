# backend/main.py
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import PLUGINS_DIR, DB_PATH
from core.services.registry import ServiceRegistry
from core.services.database import DatabaseService
from core.services.parser import ParserService
from core.plugin.loader import PluginLoader
from core.plugin.context import PluginContext


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化公共能力
    registry = ServiceRegistry()

    db = DatabaseService(db_path=str(DB_PATH))
    await db.start()
    registry.register(DatabaseService, db)

    parser = ParserService()
    registry.register(ParserService, parser)

    # 扫描并加载插件
    loader = PluginLoader(plugins_dir=PLUGINS_DIR)
    manifests = loader.scan()

    for manifest in manifests:
        plugin_name = manifest["plugin"]["name"]
        ctx = PluginContext(registry, name=plugin_name)

        # 动态导入插件入口
        plugin_dir = Path(manifest["_dir"])
        entry_file = plugin_dir / manifest["plugin"]["backend"]["entry"]
        if entry_file.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                f"plugins.{plugin_name}", str(entry_file)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "Plugin"):
                plugin_instance = module.Plugin()
                await plugin_instance.on_register(ctx)

                # 挂载插件路由
                prefix = manifest["plugin"]["backend"]["routes_prefix"]
                if hasattr(plugin_instance, "router"):
                    app.include_router(plugin_instance.router, prefix=prefix)

    # 存到 app.state 供 API 使用
    app.state.registry = registry
    app.state.plugin_manifests = manifests

    yield

    # 清理
    await db.stop()


app = FastAPI(title="CoreMaster", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/plugins")
async def list_plugins():
    plugins = []
    for m in app.state.plugin_manifests:
        frontend = m["plugin"].get("frontend", {})
        # 从插件名推导前端路径：foo_bar → /plugins/foo-bar
        path = "/plugins/" + m["plugin"]["name"].replace("_", "-")
        plugins.append({
            "name": m["plugin"]["name"],
            "description": m["plugin"].get("description", ""),
            "menu_title": frontend.get("menu_title", m["plugin"]["name"]),
            "icon": frontend.get("icon", ""),
            "path": path,
        })
    # MVP: dependency mining is embedded in mml_manager, register as virtual plugin
    plugins.append({
        "name": "dependency_mining",
        "description": "MML 命令参数依赖关系挖掘与审核",
        "menu_title": "依赖挖掘",
        "icon": "git-branch",
        "path": "/plugins/dependency-mining",
    })
    return {"plugins": plugins}


@app.get("/api/health")
async def health():
    return {"status": "ok"}
