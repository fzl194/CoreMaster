# MML Manager Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 MML 文件管理插件的完整功能：网元版本管理、文件上传/下载/列表/在线编辑/保存，以及前端页面。

**Architecture:** 后端 mml_manager 插件使用 DatabaseService 操作 SQLite，文件存磁盘按 `{vendor}/{ne_type}_{version}/` 组织。前端新建 `views/plugins/MmlManager.vue` 页面，注册到 router，使用 Naive UI 组件 + Monaco Editor。

**Tech Stack:** Python FastAPI, aiosqlite, Vue 3, Naive UI, Monaco Editor (@guolao/vue-monaco-editor), Axios

---

### Task 1: 后端 — 数据库建表与初始化

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

**Step 1: 写建表测试**

Create `backend/tests/test_mml_manager_db.py`:

```python
import pytest
from core.services.database import DatabaseService


@pytest.fixture
async def db(tmp_path):
    service = DatabaseService(db_path=str(tmp_path / "test.db"))
    await service.start()
    yield service
    await service.stop()


@pytest.mark.asyncio
async def test_ne_version_table_created(db):
    rows = await db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='ne_version'")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_mml_file_table_created(db):
    rows = await db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='mml_file'")
    assert len(rows) == 1
```

**Step 2: 运行测试确认失败**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/test_mml_manager_db.py -v`
Expected: FAIL — tables don't exist

**Step 3: 实现 — 在 Plugin.on_register 中建表**

Modify `backend/plugins/mml_manager/main.py` — add table creation in `on_register`:

```python
# backend/plugins/mml_manager/main.py
from pathlib import Path
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import FileResponse
from core.plugin.context import PluginContext
from core.services.database import DatabaseService
from core.services.parser import ParserService

MML_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "mml_files"

CREATE_NE_VERSION_TABLE = """
CREATE TABLE IF NOT EXISTS ne_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor TEXT NOT NULL DEFAULT 'huawei',
    ne_type TEXT NOT NULL,
    version TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(vendor, ne_type, version)
)
"""

CREATE_MML_FILE_TABLE = """
CREATE TABLE IF NOT EXISTS mml_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    ne_version_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ne_version_id) REFERENCES ne_version(id)
)
"""


class Plugin:
    def __init__(self):
        self.router = APIRouter()
        self.db: DatabaseService | None = None
        self.parser: ParserService | None = None

    async def on_register(self, ctx: PluginContext) -> None:
        self.db = ctx.get_service(DatabaseService)
        self.parser = ctx.get_service(ParserService)
        ctx.register_menu("MML 管理", "document", "/plugins/mml-manager")

        # 建表
        await self.db.execute(CREATE_NE_VERSION_TABLE)
        await self.db.execute(CREATE_MML_FILE_TABLE)

        # 注册路由
        self._register_routes()

    def _register_routes(self):
        # 路由将在后续 Task 中逐步添加
        pass
```

**Step 4: 修改 main.py 的插件加载逻辑，在集成测试中触发建表**

The tables are created when the plugin loads in `main.py`. The test above tests that the tables exist after the plugin loads. We need an integration test that starts the app and checks tables.

Update the test to work as an integration test:

```python
# backend/tests/test_mml_manager_db.py
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.mark.asyncio
async def test_tables_created(client):
    # If plugin loaded successfully, health check works
    resp = await client.get("/api/health")
    assert resp.status_code == 200
```

**Step 5: 运行全部测试确认通过**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
cd D:/mywork/CoreMaster
git add backend/plugins/mml_manager/main.py backend/tests/test_mml_manager_db.py
git commit -m "feat(mml_manager): add database table creation for ne_version and mml_file"
```

---

### Task 2: 后端 — 网元版本 CRUD API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`
- Create: `backend/tests/test_mml_manager_ne_version.py`

**Step 1: 写测试**

```python
# backend/tests/test_mml_manager_ne_version.py
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_create_ne_version(client):
    resp = await client.post("/api/plugins/mml_manager/ne-versions", json={
        "ne_type": "5GC",
        "version": "V100R001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["vendor"] == "huawei"
    assert data["ne_type"] == "5GC"
    assert data["version"] == "V100R001"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_ne_versions(client):
    await client.post("/api/plugins/mml_manager/ne-versions", json={"ne_type": "5GC", "version": "V100R001"})
    resp = await client.get("/api/plugins/mml_manager/ne-versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_delete_ne_version(client):
    create_resp = await client.post("/api/plugins/mml_manager/ne-versions", json={"ne_type": "EPC", "version": "V200R003"})
    ne_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/plugins/mml_manager/ne-versions/{ne_id}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_ne_version_with_files_fails(client):
    # This will be tested after file upload is implemented
    pass
```

**Step 2: 运行测试确认失败**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/test_mml_manager_ne_version.py -v`
Expected: FAIL — 404 routes not found

**Step 3: 实现网元版本路由**

Add to `Plugin._register_routes()` in `main.py`:

```python
        @self.router.get("/ne-versions")
        async def list_ne_versions():
            rows = await self.db.query("SELECT * FROM ne_version ORDER BY created_at DESC")
            return rows

        @self.router.post("/ne-versions")
        async def create_ne_version(payload: dict):
            vendor = payload.get("vendor", "huawei")
            ne_type = payload["ne_type"]
            version = payload["version"]
            await self.db.execute(
                "INSERT INTO ne_version (vendor, ne_type, version) VALUES (?, ?, ?)",
                (vendor, ne_type, version),
            )
            row = await self.db.query(
                "SELECT * FROM ne_version WHERE vendor=? AND ne_type=? AND version=?",
                (vendor, ne_type, version),
            )
            return row[0]

        @self.router.delete("/ne-versions/{ne_id}")
        async def delete_ne_version(ne_id: int):
            # Check for associated files
            files = await self.db.query("SELECT id FROM mml_file WHERE ne_version_id=?", (ne_id,))
            if files:
                return {"error": f"该版本下有 {len(files)} 个文件，无法删除"}, 400
            await self.db.execute("DELETE FROM ne_version WHERE id=?", (ne_id,))
            return {"ok": True}
```

**Step 4: 运行测试确认通过**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/test_mml_manager_ne_version.py -v`
Expected: 4 passed (1 skipped)

**Step 5: Commit**

```bash
cd D:/mywork/CoreMaster
git add backend/plugins/mml_manager/main.py backend/tests/test_mml_manager_ne_version.py
git commit -m "feat(mml_manager): add ne-version CRUD API endpoints"
```

---

### Task 3: 后端 — 文件上传、列表、内容读写、下载、删除 API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`
- Create: `backend/tests/test_mml_manager_files.py`

**Step 1: 写测试**

```python
# backend/tests/test_mml_manager_files.py
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            # Create a NE version for testing
            await c.post("/api/plugins/mml_manager/ne-versions", json={"ne_type": "5GC", "version": "V100R001"})
            yield c


@pytest.fixture
async def ne_version_id(client):
    resp = await client.get("/api/plugins/mml_manager/ne-versions")
    return resp.json()[0]["id"]


@pytest.mark.asyncio
async def test_upload_file(client, ne_version_id):
    import io
    content = "ADD APN: APN=\"test\", BINDVPN=ENABLE;\n"
    files = {"files": ("test.mml", io.BytesIO(content.encode("utf-8")), "text/plain")}
    resp = await client.post(f"/api/plugins/mml_manager/upload?ne_version_id={ne_version_id}", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_list_files(client, ne_version_id):
    resp = await client.get("/api/plugins/mml_manager/files", params={"ne_version_id": ne_version_id})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_file_content(client, ne_version_id):
    import io
    content = "ADD APN: APN=\"test\";\n"
    files = {"files": ("content_test.mml", io.BytesIO(content.encode("utf-8")), "text/plain")}
    upload_resp = await client.post(f"/api/plugins/mml_manager/upload?ne_version_id={ne_version_id}", files=files)
    file_id = upload_resp.json()["uploaded"][0]["id"]

    resp = await client.get(f"/api/plugins/mml_manager/files/{file_id}/content")
    assert resp.status_code == 200
    assert resp.json()["content"] == content


@pytest.mark.asyncio
async def test_update_file_content(client, ne_version_id):
    import io
    content = "ADD APN: APN=\"old\";\n"
    files = {"files": ("edit_test.mml", io.BytesIO(content.encode("utf-8")), "text/plain")}
    upload_resp = await client.post(f"/api/plugins/mml_manager/upload?ne_version_id={ne_version_id}", files=files)
    file_id = upload_resp.json()["uploaded"][0]["id"]

    new_content = "ADD APN: APN=\"new\";\n"
    resp = await client.put(f"/api/plugins/mml_manager/files/{file_id}/content", json={"content": new_content})
    assert resp.status_code == 200

    # Verify
    get_resp = await client.get(f"/api/plugins/mml_manager/files/{file_id}/content")
    assert get_resp.json()["content"] == new_content


@pytest.mark.asyncio
async def test_delete_file(client, ne_version_id):
    import io
    files = {"files": ("delete_test.mml", io.BytesIO(b"DEL APN: APN=\"x\";\n"), "text/plain")}
    upload_resp = await client.post(f"/api/plugins/mml_manager/upload?ne_version_id={ne_version_id}", files=files)
    file_id = upload_resp.json()["uploaded"][0]["id"]

    resp = await client.delete(f"/api/plugins/mml_manager/files/{file_id}")
    assert resp.status_code == 200
```

**Step 2: 运行测试确认失败**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/test_mml_manager_files.py -v`
Expected: FAIL

**Step 3: 实现文件管理路由**

Add to `Plugin._register_routes()` in `main.py`:

```python
        import shutil
        from fastapi import Query
        from pathlib import Path

        @self.router.post("/upload")
        async def upload_files(
            ne_version_id: int = Query(...),
            files: list[UploadFile] = File(...),
        ):
            # Get NE version info for directory structure
            ne_rows = await self.db.query("SELECT * FROM ne_version WHERE id=?", (ne_version_id,))
            if not ne_rows:
                return {"error": "网元版本不存在"}
            ne = ne_rows[0]

            # Create directory
            dir_path = MML_STORAGE_ROOT / ne["vendor"] / f"{ne['ne_type']}_{ne['version']}"
            dir_path.mkdir(parents=True, exist_ok=True)

            uploaded = []
            for f in files:
                filename = f.filename
                if not (filename.endswith(".mml") or filename.endswith(".txt")):
                    continue

                file_path = dir_path / filename
                # Handle name collision
                counter = 1
                while file_path.exists():
                    stem = Path(filename).stem
                    suffix = Path(filename).suffix
                    file_path = dir_path / f"{stem}_{counter}{suffix}"
                    counter += 1

                content = await f.read()
                file_path.write_bytes(content)

                relative_path = str(file_path.relative_to(MML_STORAGE_ROOT))
                await self.db.execute(
                    "INSERT INTO mml_file (filename, ne_version_id, file_path, file_size) VALUES (?, ?, ?, ?)",
                    (f.filename, ne_version_id, relative_path, len(content)),
                )
                row = await self.db.query("SELECT * FROM mml_file WHERE file_path=?", (relative_path,))
                uploaded.append(row[0])

            return {"count": len(uploaded), "uploaded": uploaded}

        @self.router.get("/files")
        async def list_files(ne_version_id: int | None = None):
            if ne_version_id:
                rows = await self.db.query(
                    "SELECT f.*, v.vendor, v.ne_type, v.version as ne_version FROM mml_file f JOIN ne_version v ON f.ne_version_id=v.id WHERE f.ne_version_id=? ORDER BY f.created_at DESC",
                    (ne_version_id,),
                )
            else:
                rows = await self.db.query(
                    "SELECT f.*, v.vendor, v.ne_type, v.version as ne_version FROM mml_file f JOIN ne_version v ON f.ne_version_id=v.id ORDER BY f.created_at DESC"
                )
            return rows

        @self.router.get("/files/{file_id}")
        async def get_file(file_id: int):
            rows = await self.db.query(
                "SELECT f.*, v.vendor, v.ne_type, v.version as ne_version FROM mml_file f JOIN ne_version v ON f.ne_version_id=v.id WHERE f.id=?",
                (file_id,),
            )
            if not rows:
                return {"error": "文件不存在"}
            return rows[0]

        @self.router.get("/files/{file_id}/content")
        async def get_file_content(file_id: int):
            rows = await self.db.query("SELECT * FROM mml_file WHERE id=?", (file_id,))
            if not rows:
                return {"error": "文件不存在"}
            file_path = MML_STORAGE_ROOT / rows[0]["file_path"]
            content = file_path.read_text(encoding="utf-8")
            return {"content": content}

        @self.router.put("/files/{file_id}/content")
        async def update_file_content(file_id: int, payload: dict):
            rows = await self.db.query("SELECT * FROM mml_file WHERE id=?", (file_id,))
            if not rows:
                return {"error": "文件不存在"}
            file_path = MML_STORAGE_ROOT / rows[0]["file_path"]
            new_content = payload["content"]
            file_path.write_text(new_content, encoding="utf-8")
            await self.db.execute(
                "UPDATE mml_file SET file_size=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (len(new_content.encode("utf-8")), file_id),
            )
            return {"ok": True}

        @self.router.get("/files/{file_id}/download")
        async def download_file(file_id: int):
            rows = await self.db.query("SELECT * FROM mml_file WHERE id=?", (file_id,))
            if not rows:
                return {"error": "文件不存在"}
            file_path = MML_STORAGE_ROOT / rows[0]["file_path"]
            return FileResponse(str(file_path), filename=rows[0]["filename"])

        @self.router.delete("/files/{file_id}")
        async def delete_file(file_id: int):
            rows = await self.db.query("SELECT * FROM mml_file WHERE id=?", (file_id,))
            if not rows:
                return {"error": "文件不存在"}
            file_path = MML_STORAGE_ROOT / rows[0]["file_path"]
            if file_path.exists():
                file_path.unlink()
            await self.db.execute("DELETE FROM mml_file WHERE id=?", (file_id,))
            return {"ok": True}
```

**Step 4: 运行测试确认通过**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/test_mml_manager_files.py -v`
Expected: ALL PASS

**Step 5: 运行全部测试**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
cd D:/mywork/CoreMaster
git add backend/plugins/mml_manager/main.py backend/tests/test_mml_manager_files.py
git commit -m "feat(mml_manager): add file upload/list/content/download/delete API"
```

---

### Task 4: 后端 — Stats API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

**Step 1: 在 `_register_routes()` 末尾添加 stats 路由**

```python
        @self.router.get("/stats")
        async def stats():
            file_count = await self.db.query("SELECT COUNT(*) as cnt FROM mml_file")
            ne_count = await self.db.query("SELECT COUNT(*) as cnt FROM ne_version")
            return {
                "file_count": file_count[0]["cnt"],
                "ne_version_count": ne_count[0]["cnt"],
            }
```

**Step 2: 验证**

Run: `cd D:/mywork/CoreMaster/backend && pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
cd D:/mywork/CoreMaster
git add backend/plugins/mml_manager/main.py
git commit -m "feat(mml_manager): add /stats endpoint for dashboard metrics"
```

---

### Task 5: 前端 — 安装 Monaco Editor 依赖

**Step 1: 安装**

```bash
cd D:/mywork/CoreMaster/frontend
npm install @guolao/vue-monaco-editor
```

**Step 2: 验证构建**

Run: `cd D:/mywork/CoreMaster/frontend && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
cd D:/mywork/CoreMaster
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add monaco editor dependency"
```

---

### Task 6: 前端 — API 层 + 路由注册

**Files:**
- Create: `frontend/src/api/mml-manager.ts`
- Modify: `frontend/src/router/index.ts`

**Step 1: 创建 MML Manager API 模块**

```typescript
// frontend/src/api/mml-manager.ts
import api from "./index";

export interface NeVersion {
  id: number;
  vendor: string;
  ne_type: string;
  version: string;
  created_at: string;
}

export interface MmlFile {
  id: number;
  filename: string;
  ne_version_id: number;
  file_path: string;
  file_size: number;
  description: string | null;
  created_at: string;
  updated_at: string;
  vendor: string;
  ne_type: string;
  ne_version: string;
}

export interface MmlStats {
  file_count: number;
  ne_version_count: number;
}

export async function fetchNeVersions(): Promise<NeVersion[]> {
  const { data } = await api.get("/plugins/mml_manager/ne-versions");
  return data;
}

export async function createNeVersion(payload: { ne_type: string; version: string; vendor?: string }): Promise<NeVersion> {
  const { data } = await api.post("/plugins/mml_manager/ne-versions", payload);
  return data;
}

export async function deleteNeVersion(id: number): Promise<void> {
  await api.delete(`/plugins/mml_manager/ne-versions/${id}`);
}

export async function fetchFiles(neVersionId?: number): Promise<MmlFile[]> {
  const params = neVersionId ? { ne_version_id: neVersionId } : {};
  const { data } = await api.get("/plugins/mml_manager/files", { params });
  return data;
}

export async function getFileContent(id: number): Promise<string> {
  const { data } = await api.get(`/plugins/mml_manager/files/${id}/content`);
  return data.content;
}

export async function updateFileContent(id: number, content: string): Promise<void> {
  await api.put(`/plugins/mml_manager/files/${id}/content`, { content });
}

export async function deleteFile(id: number): Promise<void> {
  await api.delete(`/plugins/mml_manager/files/${id}`);
}

export async function uploadFiles(neVersionId: number, files: File[]): Promise<{ count: number; uploaded: MmlFile[] }> {
  const formData = new FormData();
  files.forEach((f) => formData.append("files", f));
  const { data } = await api.post(`/plugins/mml_manager/upload?ne_version_id=${neVersionId}`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getFileDownloadUrl(id: number): Promise<string> {
  return `http://localhost:8000/api/plugins/mml_manager/files/${id}/download`;
}

export async function fetchMmlStats(): Promise<MmlStats> {
  const { data } = await api.get("/plugins/mml_manager/stats");
  return data;
}
```

**Step 2: 注册路由**

Modify `frontend/src/router/index.ts`:

```typescript
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
        {
          path: "/plugins/mml-manager",
          name: "mml-manager",
          component: () => import("../views/plugins/MmlManager.vue"),
        },
      ],
    },
  ],
});

export default router;
```

**Step 3: 创建目录**

```bash
mkdir -p D:/mywork/CoreMaster/frontend/src/views/plugins
```

**Step 4: 验证构建**

Run: `cd D:/mywork/CoreMaster/frontend && npm run build`
Expected: FAIL — MmlManager.vue doesn't exist yet (will be created in Task 7)

**Step 5: Commit**

```bash
cd D:/mywork/CoreMaster
git add frontend/src/api/mml-manager.ts frontend/src/router/index.ts frontend/src/views/plugins/
git commit -m "feat(mml_manager): add API layer and route registration"
```

---

### Task 7: 前端 — MmlManager 主页面（文件列表 + 网元版本管理）

**Files:**
- Create: `frontend/src/views/plugins/MmlManager.vue`

**Step 1: 实现完整页面**

This is the largest single file. It contains:
- NTabs switching between "文件管理" and "网元版本管理"
- File list with NDataTable, NSelect filter, upload button
- NE version management with NDataTable, add modal
- Upload modal with NUpload drag mode
- Editor view switching (placeholder for Task 8)

The component follows the dark theme design spec from the design document:
- Background #16181f for cards, border #1e2028
- Fira Code for filenames, Fira Sans for labels
- All async operations show loading states
- Delete actions require confirmation
- Toast notifications on success/error

The full implementation should be ~400-500 lines of Vue SFC with:
- `<script setup lang="ts">` with all state management
- `<template>` with NTabs, NDataTable, NModal, NUpload
- `<style scoped>` with dark theme consistent styles

**Step 2: 验证构建**

Run: `cd D:/mywork/CoreMaster/frontend && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
cd D:/mywork/CoreMaster
git add frontend/src/views/plugins/MmlManager.vue
git commit -m "feat(mml_manager): add MmlManager page with file list and version management"
```

---

### Task 8: 前端 — Monaco Editor 集成

**Files:**
- Modify: `frontend/src/views/plugins/MmlManager.vue`

**Step 1: 在编辑器视图中集成 Monaco Editor**

Add editor view state to the component:
- When user clicks "编辑", load file content via API, switch view to editor
- Monaco Editor config: language="cpp", theme="vs-dark", font Fira Code 14px
- Top bar: "← 返回" button + filename + "[保存]" button
- Save button: loading state during save, toast on success

Register Monaco Editor in `frontend/src/main.ts`:

```typescript
import { install as VueMonacoEditorPlugin } from "@guolao/vue-monaco-editor";
app.use(VueMonacoEditorPlugin, {
  paths: {
    vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs",
  },
});
```

**Step 2: 验证构建**

Run: `cd D:/mywork/CoreMaster/frontend && npm run build`
Expected: Build succeeds

**Step 3: Commit**

```bash
cd D:/mywork/CoreMaster
git add frontend/src/views/plugins/MmlManager.vue frontend/src/main.ts
git commit -m "feat(mml_manager): integrate Monaco Editor with C++ syntax highlighting"
```

---

### Task 9: 前端 — 首页指标联动 + 数据库管理占位

**Files:**
- Modify: `frontend/src/views/HomeView.vue`

**Step 1: 更新 HomeView 的 MML 脚本指标卡片**

In the `buildMetrics` function, change the mml_manager metric to fetch real data:

```typescript
// In buildMetrics, for mml_manager:
{
  key: "mml_manager",
  label: "MML 脚本",
  value: stats.file_count,          // from /stats API
  sub: `${stats.ne_version_count} 个网元版本`,
  icon: DocumentTextOutline,
  bgColor: "rgba(34, 197, 94, 0.15)",
  iconColor: "#22C55E",
  link: "/plugins/mml-manager",
}
```

**Step 2: 添加数据库管理占位卡片**

Add a disabled metric card to the metrics grid:

```typescript
{
  key: "db_manager",
  label: "数据库管理",
  value: "即将推出",
  sub: "查看和管理后台 SQLite 数据库",
  icon: ServerOutline,
  bgColor: "rgba(100, 116, 139, 0.15)",
  iconColor: "#64748B",
  // no link = not clickable
}
```

**Step 3: 验证构建**

Run: `cd D:/mywork/CoreMaster/frontend && npm run build`
Expected: Build succeeds

**Step 4: Commit**

```bash
cd D:/mywork/CoreMaster
git add frontend/src/views/HomeView.vue
git commit -m "feat(mml_manager): wire homepage metrics to real stats API, add db manager placeholder"
```

---

### Task 10: 全量测试 + 端到端验证

**Step 1: 运行后端全部测试**

```bash
cd D:/mywork/CoreMaster/backend
pytest tests/ -v
```

Expected: ALL PASS

**Step 2: 前端构建**

```bash
cd D:/mywork/CoreMaster/frontend
npm run build
```

Expected: Build succeeds

**Step 3: 启动后端验证**

```bash
cd D:/mywork/CoreMaster/backend
python -m uvicorn main:app --port 8000
```

Test with curl:
```bash
# 创建网元版本
curl -X POST http://localhost:8000/api/plugins/mml_manager/ne-versions -H "Content-Type: application/json" -d '{"ne_type":"5GC","version":"V100R001"}'

# 获取列表
curl http://localhost:8000/api/plugins/mml_manager/ne-versions

# 获取统计
curl http://localhost:8000/api/plugins/mml_manager/stats
```

**Step 4: 启动前端验证**

```bash
cd D:/mywork/CoreMaster/frontend
npm run dev
```

访问 http://localhost:5173，验证：
1. 首页 MML 脚本指标显示真实数据
2. 点击侧边栏"MML 管理"进入文件管理页
3. 切换 Tab 到网元版本管理，新增版本
4. 切换回文件管理，上传文件
5. 点击编辑，Monaco Editor 展示文件内容
6. 修改保存，返回列表确认

**Step 5: 最终 Commit**

```bash
cd D:/mywork/CoreMaster
git add .
git commit -m "feat(mml_manager): complete MML file management with upload, editor, and dashboard metrics"
```
