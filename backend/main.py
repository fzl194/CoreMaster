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

    all_menus = []
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

        # 收集菜单
        all_menus.extend(ctx.get_menus())

    # 存到 app.state 供 API 使用
    app.state.registry = registry
    app.state.menus = all_menus
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
    return {
        "menus": app.state.menus,
        "plugins": [
            {
                "name": m["plugin"]["name"],
                "description": m["plugin"].get("description", ""),
            }
            for m in app.state.plugin_manifests
        ],
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}
