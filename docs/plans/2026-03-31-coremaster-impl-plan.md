# CoreMaster 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 搭建 CoreMaster 的可插拔框架骨架，包括后端公共能力层、插件系统、前端 Shell，以及第一个示例插件。

**Architecture:** Python FastAPI 后端 + Vue 3 前端，通过 ServiceRegistry 提供公共能力，插件通过 plugin.toml 声明并动态加载。前后端通过 HTTP API 通信。

**Tech Stack:** Python 3.11+, FastAPI, SQLite (aiosqlite), Vue 3, Vite, Naive UI, TypeScript

---

### Task 1: 后端项目初始化

**Files:**
- Create: `backend/core/__init__.py`
- Create: `backend/core/services/__init__.py`
- Create: `backend/core/plugin/__init__.py`
- Create: `backend/core/config.py`
- Create: `backend/requirements.txt`
- Create: `backend/tests/__init__.py`

**Step 1: 创建后端目录结构**

```bash
cd D:/mywork/CoreMaster
mkdir -p backend/core/services backend/core/plugin backend/plugins backend/tests
```

**Step 2: 创建 requirements.txt**

```
# backend/requirements.txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
aiosqlite>=0.20.0
toml>=0.10.2
pydantic>=2.0.0
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

**Step 3: 创建所有 __init__.py**

```bash
touch backend/core/__init__.py backend/core/services/__init__.py backend/core/plugin/__init__.py backend/tests/__init__.py
```

**Step 4: 创建 config.py**

```python
# backend/core/config.py
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PLUGINS_DIR = BASE_DIR / "plugins"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "coremaster.db"
```

**Step 5: 安装依赖**

```bash
cd backend
pip install -r requirements.txt
```

**Step 6: 验证**

```bash
python -c "from core.config import BASE_DIR; print(BASE_DIR)"
```

Expected: 输出 backend 目录路径

**Step 7: Commit**

```bash
git add backend/
git commit -m "chore: init backend project structure with dependencies"
```

---

### Task 2: ServiceRegistry 与服务协议

**Files:**
- Create: `backend/core/services/registry.py`
- Create: `backend/core/services/protocols.py`
- Create: `backend/tests/test_registry.py`

**Step 1: 写测试**

```python
# backend/tests/test_registry.py
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
```

**Step 2: 运行测试，确认失败**

```bash
cd backend
pytest tests/test_registry.py -v
```

Expected: FAIL — ModuleNotFoundError

**Step 3: 实现 ServiceRegistry**

```python
# backend/core/services/registry.py
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
```

**Step 4: 运行测试，确认通过**

```bash
pytest tests/test_registry.py -v
```

Expected: 3 passed

**Step 5: 写服务协议定义**

```python
# backend/core/services/protocols.py
from typing import Protocol, runtime_checkable


@runtime_checkable
class DatabaseServiceProtocol(Protocol):
    async def execute(self, sql: str, params: tuple = ()) -> None: ...
    async def query(self, sql: str, params: tuple = ()) -> list[dict]: ...


@runtime_checkable
class ParserServiceProtocol(Protocol):
    def parse_text(self, text: str) -> list[dict]: ...
    def parse_file(self, path: str) -> list[dict]: ...
```

**Step 6: 运行全部测试**

```bash
pytest tests/ -v
```

Expected: 3 passed

**Step 7: Commit**

```bash
git add backend/core/services/ backend/tests/test_registry.py
git commit -m "feat: add ServiceRegistry and service protocols"
```

---

### Task 3: MML 解析器

**Files:**
- Create: `backend/core/services/parser.py`
- Create: `backend/tests/test_parser.py`

**Step 1: 写测试**

```python
# backend/tests/test_parser.py
from core.services.parser import ParserService


def test_parse_single_command():
    svc = ParserService()
    text = 'ADD APN: APN="test_apn", BINDVPN=ENABLE, VRFNAME="vpn";'
    result = svc.parse_text(text)
    assert len(result) == 1
    cmd = result[0]
    assert cmd["operation"] == "ADD"
    assert cmd["name"] == "APN"
    assert len(cmd["params"]) == 3
    assert cmd["params"][0]["name"] == "APN"
    assert cmd["params"][0]["value"] == "test_apn"
    assert cmd["params"][1]["name"] == "BINDVPN"
    assert cmd["params"][1]["value"] == "ENABLE"


def test_parse_multiple_commands():
    svc = ParserService()
    text = """
ADD APN: APN="apn1";
MOD APN: APN="apn2";
"""
    result = svc.parse_text(text)
    assert len(result) == 2
    assert result[0]["operation"] == "ADD"
    assert result[1]["operation"] == "MOD"


def test_skip_comments():
    svc = ParserService()
    text = """// this is a comment
ADD APN: APN="test";"""
    result = svc.parse_text(text)
    assert len(result) == 1


def test_skip_empty_lines():
    svc = ParserService()
    text = """

ADD APN: APN="test";

"""
    result = svc.parse_text(text)
    assert len(result) == 1


def test_parse_param_without_value():
    svc = ParserService()
    text = "ADD APN: APN;"
    result = svc.parse_text(text)
    assert len(result) == 1
    assert result[0]["params"][0]["name"] == "APN"
    assert result[0]["params"][0]["value"] is None


def test_parse_command_with_spaces():
    svc = ParserService()
    text = "ADD  APN :  APN = \"test\" , BIND = ON ;"
    result = svc.parse_text(text)
    assert len(result) == 1
    assert result[0]["name"] == "APN"
    assert result[0]["params"][0]["value"] == "test"
```

**Step 2: 运行测试，确认失败**

```bash
cd backend
pytest tests/test_parser.py -v
```

Expected: FAIL — ModuleNotFoundError

**Step 3: 实现 ParserService**

```python
# backend/core/services/parser.py
import re
from pathlib import Path


class ParserService:
    """MML 通用解析器"""

    # 匹配：操作类型 命令名 : 参数列表 ;
    _COMMAND_RE = re.compile(
        r"^\s*(ADD|MOD|DEL|RMV|SET|GET|LST|DSP|ACT|DEA|BLK|UBL|REG|DEREG)"
        r"\s+(\w+)\s*:\s*(.*?)\s*;\s*$",
        re.IGNORECASE,
    )

    def parse_text(self, text: str) -> list[dict]:
        results = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            match = self._COMMAND_RE.match(stripped)
            if not match:
                continue
            operation, name, params_str = match.groups()
            params = self._parse_params(params_str)
            results.append({
                "operation": operation.upper(),
                "name": name.upper(),
                "params": params,
                "raw_text": stripped,
                "line_number": line_no,
            })
        return results

    def parse_file(self, path: str) -> list[dict]:
        text = Path(path).read_text(encoding="utf-8")
        return self.parse_text(text)

    def _parse_params(self, params_str: str) -> list[dict]:
        if not params_str.strip():
            return []
        params = []
        for token in params_str.split(","):
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                key, value = token.split("=", 1)
                value = value.strip().strip('"')
            else:
                key = token.strip().strip(";")
                value = None
            params.append({"name": key.strip(), "value": value})
        return params
```

**Step 4: 运行测试，确认通过**

```bash
pytest tests/test_parser.py -v
```

Expected: 6 passed

**Step 5: Commit**

```bash
git add backend/core/services/parser.py backend/tests/test_parser.py
git commit -m "feat: add MML parser service with tests"
```

---

### Task 4: DatabaseService (SQLite)

**Files:**
- Create: `backend/core/services/database.py`
- Create: `backend/tests/test_database.py`

**Step 1: 写测试**

```python
# backend/tests/test_database.py
import pytest
from core.services.database import DatabaseService


@pytest.fixture
async def db(tmp_path):
    service = DatabaseService(db_path=str(tmp_path / "test.db"))
    await service.start()
    yield service
    await service.stop()


@pytest.mark.asyncio
async def test_execute_and_query(db):
    await db.execute(
        "CREATE TABLE test_items (id INTEGER PRIMARY KEY, name TEXT)"
    )
    await db.execute("INSERT INTO test_items (name) VALUES (?)", ("item1",))
    rows = await db.query("SELECT * FROM test_items")
    assert len(rows) == 1
    assert rows[0]["name"] == "item1"


@pytest.mark.asyncio
async def test_query_empty(db):
    await db.execute("CREATE TABLE empty_table (id INTEGER PRIMARY KEY)")
    rows = await db.query("SELECT * FROM empty_table")
    assert rows == []
```

**Step 2: 运行测试，确认失败**

```bash
cd backend
pytest tests/test_database.py -v
```

Expected: FAIL — ModuleNotFoundError

**Step 3: 实现 DatabaseService**

```python
# backend/core/services/database.py
import aiosqlite
from pathlib import Path


class DatabaseService:
    """SQLite 数据库服务"""

    def __init__(self, db_path: str = "coremaster.db") -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def start(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row

    async def stop(self) -> None:
        if self._conn:
            await self._conn.close()

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
```

**Step 4: 运行测试，确认通过**

```bash
pytest tests/test_database.py -v
```

Expected: 2 passed

**Step 5: 运行全部测试**

```bash
pytest tests/ -v
```

Expected: 所有测试通过

**Step 6: Commit**

```bash
git add backend/core/services/database.py backend/tests/test_database.py
git commit -m "feat: add SQLite DatabaseService with async support"
```

---

### Task 5: 插件系统 — PluginContext 与 PluginLoader

**Files:**
- Create: `backend/core/plugin/context.py`
- Create: `backend/core/plugin/loader.py`
- Create: `backend/tests/test_plugin.py`

**Step 1: 写测试**

```python
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


def test_context_register_menu():
    registry = ServiceRegistry()
    ctx = PluginContext(registry, name="test")
    ctx.register_menu("Test Page", "test-icon", "/plugins/test")
    menus = ctx.get_menus()
    assert len(menus) == 1
    assert menus[0]["title"] == "Test Page"


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
```

**Step 2: 运行测试，确认失败**

```bash
cd backend
pytest tests/test_plugin.py -v
```

**Step 3: 实现 PluginContext**

```python
# backend/core/plugin/context.py
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
```

**Step 4: 实现 PluginLoader**

```python
# backend/core/plugin/loader.py
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
```

**Step 5: 运行测试，确认通过**

```bash
pytest tests/test_plugin.py -v
```

Expected: 3 passed

**Step 6: 运行全部测试**

```bash
pytest tests/ -v
```

Expected: 所有测试通过

**Step 7: Commit**

```bash
git add backend/core/plugin/ backend/tests/test_plugin.py
git commit -m "feat: add plugin system with PluginContext and PluginLoader"
```

---

### Task 6: FastAPI 入口 main.py

**Files:**
- Create: `backend/main.py`

**Step 1: 实现 main.py**

```python
# backend/main.py
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import PLUGINS_DIR, DB_PATH, DATA_DIR
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
```

**Step 2: 创建数据目录**

```bash
mkdir -p backend/data
```

**Step 3: 验证启动**

```bash
cd backend
python -c "from main import app; print('OK')"
```

Expected: 输出 OK

**Step 4: Commit**

```bash
git add backend/main.py backend/data/
git commit -m "feat: add FastAPI entry point with plugin loading"
```

---

### Task 7: 示例插件 mml_manager（骨架）

**Files:**
- Create: `backend/plugins/mml_manager/plugin.toml`
- Create: `backend/plugins/mml_manager/main.py`

**Step 1: 创建 plugin.toml**

```toml
# backend/plugins/mml_manager/plugin.toml
[plugin]
name = "mml_manager"
version = "0.1.0"
description = "MML 文件导入与管理"

[plugin.backend]
entry = "main.py"
routes_prefix = "/api/plugins/mml_manager"

[plugin.frontend]
entry = "src/index.vue"
menu_title = "MML 管理"
icon = "document"
```

**Step 2: 创建插件入口**

```python
# backend/plugins/mml_manager/main.py
from fastapi import APIRouter, UploadFile, File
from core.plugin.context import PluginContext
from core.services.parser import ParserService


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.parser: ParserService | None = None

    async def on_register(self, ctx: PluginContext) -> None:
        self.parser = ctx.get_service(ParserService)
        ctx.register_menu("MML 管理", "document", "/plugins/mml-manager")

        @self.router.post("/parse")
        async def parse_mml(file: UploadFile = File(...)):
            content = (await file.read()).decode("utf-8")
            commands = self.parser.parse_text(content)
            return {"commands": commands, "count": len(commands)}

        @self.router.post("/parse-text")
        async def parse_mml_text(payload: dict):
            commands = self.parser.parse_text(payload["text"])
            return {"commands": commands, "count": len(commands)}
```

**Step 3: 验证**

```bash
cd backend
python -c "
from core.plugin.loader import PluginLoader
from core.config import PLUGINS_DIR
loader = PluginLoader(PLUGINS_DIR)
manifests = loader.scan()
print(f'Found {len(manifests)} plugins')
for m in manifests:
    print(f'  - {m[\"plugin\"][\"name\"]}')
"
```

Expected: Found 1 plugins, mml_manager

**Step 4: Commit**

```bash
git add backend/plugins/mml_manager/
git commit -m "feat: add mml_manager plugin skeleton"
```

---

### Task 8: 后端集成测试

**Files:**
- Create: `backend/tests/test_integration.py`

**Step 1: 写集成测试**

```python
# backend/tests/test_integration.py
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_list_plugins():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/plugins")
        assert resp.status_code == 200
        data = resp.json()
        assert "menus" in data
        assert "plugins" in data
        # 至少有 mml_manager
        names = [p["name"] for p in data["plugins"]]
        assert "mml_manager" in names


@pytest.mark.asyncio
async def test_parse_text_via_plugin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/plugins/mml_manager/parse-text",
            json={"text": 'ADD APN: APN="test", BINDVPN=ENABLE;'},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["commands"][0]["name"] == "APN"
```

**Step 2: 运行集成测试**

```bash
cd backend
pytest tests/test_integration.py -v
```

Expected: 3 passed

**Step 3: 运行全部测试**

```bash
pytest tests/ -v
```

Expected: 所有测试通过

**Step 4: Commit**

```bash
git add backend/tests/test_integration.py
git commit -m "test: add integration tests for API and plugin system"
```

---

### Task 9: 前端项目初始化

**Files:**
- Create: `frontend/` (Vue 3 + Vite 脚手架)

**Step 1: 创建 Vue 3 项目**

```bash
cd D:/mywork/CoreMaster
npm create vite@latest frontend -- --template vue-ts
```

**Step 2: 安装依赖**

```bash
cd frontend
npm install
npm install naive-ui vue-router@4 axios
npm install -D @vicons/ionicons5
```

**Step 3: 验证**

```bash
npm run dev
```

访问 http://localhost:5173，能看到默认页面即可

**Step 4: Commit**

```bash
cd D:/mywork/CoreMaster
git add frontend/
git commit -m "chore: init Vue 3 + Vite + TypeScript frontend"
```

---

### Task 10: 前端 Shell 布局

**Files:**
- Modify: `frontend/src/App.vue`
- Create: `frontend/src/layouts/MainLayout.vue`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/api/index.ts`

**Step 1: 创建 API 层**

```typescript
// frontend/src/api/index.ts
import axios from "axios";

const api = axios.create({
  baseURL: "http://localhost:8000/api",
});

export interface PluginInfo {
  name: string;
  description: string;
}

export interface MenuItem {
  title: string;
  icon: string;
  path: string;
}

export interface PluginsResponse {
  menus: MenuItem[];
  plugins: PluginInfo[];
}

export async function fetchPlugins(): Promise<PluginsResponse> {
  const { data } = await api.get<PluginsResponse>("/plugins");
  return data;
}

export default api;
```

**Step 2: 创建路由**

```typescript
// frontend/src/router/index.ts
import { createRouter, createWebHistory } from "vue-router";
import MainLayout from "../layouts/MainLayout.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      component: MainLayout,
      children: [
        {
          path: "",
          name: "home",
          component: () => import("../views/HomeView.vue"),
        },
      ],
    },
  ],
});

export default router;
```

**Step 3: 创建 MainLayout**

```vue
<!-- frontend/src/layouts/MainLayout.vue -->
<template>
  <n-layout has-sider style="height: 100vh">
    <n-layout-sider
      bordered
      :width="220"
      :collapsed-width="64"
      collapse-mode="width"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="logo">
        <span v-if="!collapsed">CoreMaster</span>
        <span v-else>CM</span>
      </div>
      <n-menu
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        :options="menuOptions"
        :value="activeKey"
        @update:value="handleMenuClick"
      />
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered style="height: 48px; padding: 0 20px; display: flex; align-items: center; justify-content: space-between;">
        <span style="font-weight: 500">{{ currentTitle }}</span>
      </n-layout-header>
      <n-layout-content style="padding: 20px">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from "vue";
import { useRouter, useRoute } from "vue-router";
import { NLayout, NLayoutSider, NLayoutHeader, NLayoutContent, NMenu } from "naive-ui";
import type { MenuOption } from "naive-ui";
import { fetchPlugins, type MenuItem } from "../api";
import {
  DocumentTextOutline,
  GitCompareOutline,
  ScanOutline,
  CreateOutline,
  CheckmarkCircleOutline,
} from "@vicons/ionicons5";

const router = useRouter();
const route = useRoute();
const collapsed = ref(false);
const menus = ref<MenuItem[]>([]);
const activeKey = ref("home");

const iconMap: Record<string, any> = {
  document: DocumentTextOutline,
  diff: GitCompareOutline,
  graph: ScanOutline,
  generate: CreateOutline,
  validator: CheckmarkCircleOutline,
};

const titleMap = computed(() => {
  const map: Record<string, string> = { home: "首页" };
  menus.value.forEach((m) => {
    map[m.path] = m.title;
  });
  return map;
});

const currentTitle = computed(() => {
  return titleMap.value[route.path] || route.path;
});

const menuOptions = computed<MenuOption[]>(() => {
  const coreItems: MenuOption[] = [
    {
      label: "首页",
      key: "home",
      icon: () => h(DocumentTextOutline),
    },
  ];

  const pluginItems: MenuOption[] = menus.value.map((m) => ({
    label: m.title,
    key: m.path,
    icon: () => h(iconMap[m.icon] || DocumentTextOutline),
  }));

  if (pluginItems.length > 0) {
    return [
      ...coreItems,
      { type: "divider", key: "d1" },
      ...pluginItems,
    ];
  }
  return coreItems;
});

function handleMenuClick(key: string) {
  if (key === "home") {
    router.push("/");
  } else {
    router.push(key);
  }
}

onMounted(async () => {
  try {
    const res = await fetchPlugins();
    menus.value = res.menus;
  } catch (e) {
    console.error("Failed to load plugins:", e);
  }
});
</script>

<style scoped>
.logo {
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: #18a058;
  border-bottom: 1px solid var(--n-border-color);
}
</style>
```

**Step 4: 创建首页**

```vue
<!-- frontend/src/views/HomeView.vue -->
<template>
  <n-card title="CoreMaster">
    <n-space vertical>
      <n-text>核心网 MML 配置管理平台</n-text>
      <n-text depth="3">从左侧菜单选择功能模块</n-text>
      <n-divider />
      <n-h3>已加载插件</n-h3>
      <n-grid :cols="3" :x-gap="12" :y-gap="12">
        <n-gi v-for="plugin in plugins" :key="plugin.name">
          <n-card size="small" hoverable>
            <n-text>{{ plugin.name }}</n-text>
            <template #footer>
              <n-text depth="3">{{ plugin.description }}</n-text>
            </template>
          </n-card>
        </n-gi>
      </n-grid>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { NCard, NSpace, NText, NDivider, NH3, NGrid, NGi } from "naive-ui";
import { fetchPlugins, type PluginInfo } from "../api";

const plugins = ref<PluginInfo[]>([]);

onMounted(async () => {
  try {
    const res = await fetchPlugins();
    plugins.value = res.plugins;
  } catch (e) {
    console.error(e);
  }
});
</script>
```

**Step 5: 修改 App.vue**

```vue
<!-- frontend/src/App.vue -->
<template>
  <n-config-provider>
    <n-message-provider>
      <router-view />
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { NConfigProvider, NMessageProvider } from "naive-ui";
</script>
```

**Step 6: 修改 main.ts**

```typescript
// frontend/src/main.ts
import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";

const app = createApp(App);
app.use(router);
app.mount("#app");
```

**Step 7: 验证**

```bash
cd frontend
npm run dev
```

访问 http://localhost:5173，应看到侧边栏 + 首页布局

**Step 8: Commit**

```bash
cd D:/mywork/CoreMaster
git add frontend/
git commit -m "feat: add frontend Shell with Naive UI layout and plugin menu"
```

---

### Task 11: 全部启动验证

**Step 1: 启动后端**

```bash
cd D:/mywork/CoreMaster/backend
uvicorn main:app --reload --port 8000
```

**Step 2: 启动前端（新终端）**

```bash
cd D:/mywork/CoreMaster/frontend
npm run dev
```

**Step 3: 端到端验证**

1. 访问 http://localhost:5173
2. 看到侧边栏，含「首页」和「MML 管理」菜单
3. 首页显示已加载插件列表
4. 点击 MML 管理菜单，路由跳转
5. 后端 http://localhost:8000/api/health 返回 ok
6. 后端 http://localhost:8000/api/plugins 返回插件列表

**Step 4: 运行全部后端测试**

```bash
cd D:/mywork/CoreMaster/backend
pytest tests/ -v
```

Expected: 所有测试通过

**Step 5: 最终 Commit**

```bash
cd D:/mywork/CoreMaster
git add .
git commit -m "feat: complete CoreMaster skeleton with plugin system and frontend shell"
```
