# MML 文件管理器实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 MML 文件管理从"按网元版本组织"改为"Web 文件管理器"模式，支持自由创建文件夹、多级目录导航和批量上传。

**Architecture:** 用 `file_entry` 统一表替代 `mml_file` 表，通过 `parent_id` 递归构建目录树。后端提供目录浏览、文件夹创建、递归删除、带网元版本关联的文件上传 API。前端重写为面包屑导航 + 表格的文件管理器视图。

**Tech Stack:** FastAPI + aiosqlite (后端)，Vue 3 + Naive UI + Monaco Editor (前端)

---

### Task 1: 后端 — 替换数据库表和 stats 接口

**Files:**
- Modify: `backend/plugins/mml_manager/main.py` (全文重写)

**Step 1: 重写 `main.py` 中的数据库建表部分**

将 `mml_file` 表替换为 `file_entry` 表。保留 `ne_version` 表不变。

在 `on_register` 方法中，将第 34-45 行的 `CREATE TABLE mml_file` 替换为：

```python
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS file_entry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER REFERENCES file_entry(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                ne_version_id INTEGER REFERENCES ne_version(id),
                file_size INTEGER DEFAULT 0,
                file_path TEXT,
                description TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(parent_id, name, type)
            )
        """)
```

**Step 2: 更新 stats 接口**

将 stats 接口中的 `mml_file` 引用改为 `file_entry`，并只统计 `type='file'` 的记录：

```python
        @self.router.get("/stats")
        async def get_stats():
            fc = await self.db.query("SELECT COUNT(*) AS cnt FROM file_entry WHERE type='file'")
            nc = await self.db.query("SELECT COUNT(*) AS cnt FROM ne_version")
            return {
                "file_count": fc[0]["cnt"] if fc else 0,
                "ne_version_count": nc[0]["cnt"] if nc else 0,
            }
```

**Step 3: 更新 delete_ne_version 接口中的引用**

将检查关联文件的查询从 `mml_file` 改为 `file_entry`：

```python
            files = await self.db.query(
                "SELECT id FROM file_entry WHERE ne_version_id=?", (ne_id,)
            )
```

**Step 4: 删除所有旧的文件管理路由**

删除以下路由（将在后续 Task 中替换）：
- `POST /upload`（旧版）
- `GET /files`
- `GET /files/{file_id}`
- `GET /files/{file_id}/content`
- `PUT /files/{file_id}/content`
- `GET /files/{file_id}/download`
- `DELETE /files/{file_id}`

只保留 parse、ne-versions CRUD、stats 接口。

**Step 5: 提交**

```bash
git add backend/plugins/mml_manager/main.py
git commit -m "refactor(mml_manager): replace mml_file table with file_entry table"
```

---

### Task 2: 后端 — 实现目录浏览 API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

**Step 1: 实现 `GET /entries` 接口**

在 `on_register` 中添加路由：

```python
        @self.router.get("/entries")
        async def list_entries(parent_id: int | None = Query(None)):
            if parent_id is not None:
                # Verify parent exists and is a folder
                parent_rows = await self.db.query(
                    "SELECT id, type FROM file_entry WHERE id=?", (parent_id,)
                )
                if not parent_rows:
                    return JSONResponse(status_code=404, content={"detail": "目录不存在"})
                if parent_rows[0]["type"] != "folder":
                    return JSONResponse(status_code=400, content={"detail": "目标不是文件夹"})
                sql = (
                    "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                    "e.file_size, e.description, e.created_at, e.updated_at, "
                    "n.vendor, n.ne_type, n.version "
                    "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                    "WHERE e.parent_id=? ORDER BY e.type DESC, e.name ASC"
                )
                rows = await self.db.query(sql, (parent_id,))
            else:
                sql = (
                    "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                    "e.file_size, e.description, e.created_at, e.updated_at, "
                    "n.vendor, n.ne_type, n.version "
                    "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                    "WHERE e.parent_id IS NULL ORDER BY e.type DESC, e.name ASC"
                )
                rows = await self.db.query(sql)
            return rows
```

文件夹排在前面（`type DESC`，因为 'folder' > 'file'），同类型按名称排序。

**Step 2: 实现 `GET /entries/{id}/path` 面包屑接口**

```python
        @self.router.get("/entries/{entry_id}/path")
        async def get_entry_path(entry_id: int):
            path = []
            current_id = entry_id
            while current_id is not None:
                rows = await self.db.query(
                    "SELECT id, parent_id, name FROM file_entry WHERE id=?", (current_id,)
                )
                if not rows:
                    break
                row = rows[0]
                path.append({"id": row["id"], "name": row["name"]})
                current_id = row["parent_id"]
            path.reverse()
            return path
```

**Step 3: 提交**

```bash
git add backend/plugins/mml_manager/main.py
git commit -m "feat(mml_manager): add directory browsing API (entries, path)"
```

---

### Task 3: 后端 — 实现文件夹创建和递归删除 API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

**Step 1: 添加 `import shutil` 到文件顶部**

```python
import shutil
```

**Step 2: 实现 `POST /entries` 创建文件夹**

```python
        @self.router.post("/entries")
        async def create_entry(payload: dict):
            name = payload.get("name", "").strip()
            entry_type = payload.get("type", "folder")
            parent_id = payload.get("parent_id")

            if not name:
                return JSONResponse(status_code=400, content={"detail": "名称不能为空"})

            # Validate parent if specified
            if parent_id is not None:
                parent_rows = await self.db.query(
                    "SELECT id, type FROM file_entry WHERE id=?", (parent_id,)
                )
                if not parent_rows:
                    return JSONResponse(status_code=404, content={"detail": "父目录不存在"})
                if parent_rows[0]["type"] != "folder":
                    return JSONResponse(status_code=400, content={"detail": "父目标不是文件夹"})

            # Create real directory on disk for folders
            if entry_type == "folder":
                await self.db.execute(
                    "INSERT INTO file_entry (parent_id, name, type) VALUES (?, ?, ?)",
                    (parent_id, name, "folder"),
                )
                rows = await self.db.query(
                    "SELECT id, parent_id, name, type, created_at, updated_at FROM file_entry "
                    "WHERE parent_id IS ? AND name=? AND type='folder' ORDER BY id DESC LIMIT 1",
                    (parent_id, name),
                )
                entry = rows[0]
                # Create real directory
                dir_path = MML_STORAGE_ROOT / str(entry["id"])
                dir_path.mkdir(parents=True, exist_ok=True)
                return entry

            return JSONResponse(status_code=400, content={"detail": "不支持的类型"})
```

**Step 3: 实现 `DELETE /entries/{id}` 递归删除**

```python
        @self.router.delete("/entries/{entry_id}")
        async def delete_entry(entry_id: int):
            rows = await self.db.query(
                "SELECT id, type, file_path FROM file_entry WHERE id=?", (entry_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "条目不存在"})

            entry = rows[0]

            if entry["type"] == "folder":
                # Recursively collect all descendant IDs
                async def collect_ids(parent_id: int) -> list[int]:
                    result = [parent_id]
                    children = await self.db.query(
                        "SELECT id FROM file_entry WHERE parent_id=?", (parent_id,)
                    )
                    for child in children:
                        result.extend(await collect_ids(child["id"]))
                    return result

                all_ids = await collect_ids(entry_id)

                # Delete disk files for all file-type entries
                file_entries = await self.db.query(
                    f"SELECT file_path FROM file_entry WHERE id IN ({','.join('?' * len(all_ids))}) AND type='file'",
                    tuple(all_ids),
                )
                for fe in file_entries:
                    if fe["file_path"] and Path(fe["file_path"]).exists():
                        Path(fe["file_path"]).unlink()

                # Delete the folder directory on disk
                folder_path = MML_STORAGE_ROOT / str(entry_id)
                if folder_path.exists():
                    shutil.rmtree(folder_path)

                # Delete all DB records (parent first triggers CASCADE but we do it explicitly)
                placeholders = ",".join("?" * len(all_ids))
                await self.db.execute(
                    f"DELETE FROM file_entry WHERE id IN ({placeholders})",
                    tuple(all_ids),
                )
            else:
                # Delete single file
                if entry["file_path"] and Path(entry["file_path"]).exists():
                    Path(entry["file_path"]).unlink()
                await self.db.execute("DELETE FROM file_entry WHERE id=?", (entry_id,))

            return {"ok": True}
```

**Step 4: 提交**

```bash
git add backend/plugins/mml_manager/main.py
git commit -m "feat(mml_manager): add folder create and recursive delete API"
```

---

### Task 4: 后端 — 实现文件上传 API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

**Step 1: 添加 `import json` 到文件顶部**

```python
import json
```

**Step 2: 更新 FastAPI imports**

```python
from fastapi import APIRouter, UploadFile, File, Query, Form
```

**Step 3: 实现 `POST /upload` 新版上传接口**

```python
        @self.router.post("/upload")
        async def upload_files(
            metadata: str = Form(...),
            files: list[UploadFile] = File(...),
        ):
            # Parse metadata JSON
            try:
                meta = json.loads(metadata)
            except json.JSONDecodeError:
                return JSONResponse(status_code=400, content={"detail": "metadata JSON 格式错误"})

            parent_id = meta.get("parent_id")
            items = meta.get("items", {})

            if not items:
                return JSONResponse(status_code=400, content={"detail": "未指定文件的网元版本"})

            # Validate parent directory
            if parent_id is not None:
                parent_rows = await self.db.query(
                    "SELECT id, type FROM file_entry WHERE id=?", (parent_id,)
                )
                if not parent_rows:
                    return JSONResponse(status_code=404, content={"detail": "目标目录不存在"})
                if parent_rows[0]["type"] != "folder":
                    return JSONResponse(status_code=400, content={"detail": "目标不是文件夹"})

            uploaded = []
            for f in files:
                # Validate extension
                suffix = Path(f.filename).suffix.lower()
                if suffix not in (".mml", ".txt"):
                    continue

                # Each file must have ne_version_id in metadata
                file_meta = items.get(f.filename)
                if not file_meta or "ne_version_id" not in file_meta:
                    continue

                ne_version_id = file_meta["ne_version_id"]

                # Verify NE version exists
                ne_rows = await self.db.query(
                    "SELECT id FROM ne_version WHERE id=?", (ne_version_id,)
                )
                if not ne_rows:
                    continue

                content_bytes = await f.read()

                # Determine disk path
                if parent_id is not None:
                    disk_dir = MML_STORAGE_ROOT / str(parent_id)
                else:
                    disk_dir = MML_STORAGE_ROOT
                disk_dir.mkdir(parents=True, exist_ok=True)

                # Insert DB record first to get ID
                await self.db.execute(
                    "INSERT INTO file_entry (parent_id, name, type, ne_version_id, file_size) "
                    "VALUES (?, ?, 'file', ?, ?)",
                    (parent_id, f.filename, ne_version_id, len(content_bytes)),
                )
                rows = await self.db.query(
                    "SELECT id FROM file_entry WHERE parent_id IS ? AND name=? ORDER BY id DESC LIMIT 1",
                    (parent_id, f.filename),
                )
                entry_id = rows[0]["id"]

                # Write to disk using entry_id
                disk_path = disk_dir / f"{entry_id}{suffix}"
                disk_path.write_bytes(content_bytes)

                # Update file_path in DB
                await self.db.execute(
                    "UPDATE file_entry SET file_path=? WHERE id=?",
                    (str(disk_path), entry_id),
                )

                # Fetch complete entry for response
                result_rows = await self.db.query(
                    "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                    "e.file_size, e.description, e.created_at, e.updated_at, "
                    "n.vendor, n.ne_type, n.version "
                    "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                    "WHERE e.id=?",
                    (entry_id,),
                )
                if result_rows:
                    uploaded.append(result_rows[0])

            return uploaded
```

**Step 4: 提交**

```bash
git add backend/plugins/mml_manager/main.py
git commit -m "feat(mml_manager): add file upload API with per-file NE version"
```

---

### Task 5: 后端 — 实现文件内容读写和下载 API

**Files:**
- Modify: `backend/plugins/mml_manager/main.py`

**Step 1: 实现文件内容读写、下载、元数据更新接口**

这些接口从 `file_entry` 表查询，使用 `name` 作为下载文件名：

```python
        @self.router.get("/files/{file_id}/content")
        async def get_file_content(file_id: int):
            rows = await self.db.query(
                "SELECT file_path FROM file_entry WHERE id=? AND type='file'", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = Path(rows[0]["file_path"])
            if not p.exists():
                return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
            content = p.read_text(encoding="utf-8")
            return {"content": content}

        @self.router.put("/files/{file_id}/content")
        async def update_file_content(file_id: int, payload: dict):
            rows = await self.db.query(
                "SELECT file_path FROM file_entry WHERE id=? AND type='file'", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = Path(rows[0]["file_path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            new_content = payload["content"]
            p.write_text(new_content, encoding="utf-8")
            await self.db.execute(
                "UPDATE file_entry SET file_size=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (len(new_content.encode("utf-8")), file_id),
            )
            return {"ok": True}

        @self.router.get("/files/{file_id}/download")
        async def download_file(file_id: int):
            rows = await self.db.query(
                "SELECT file_path, name FROM file_entry WHERE id=? AND type='file'", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            p = Path(rows[0]["file_path"])
            if not p.exists():
                return JSONResponse(status_code=404, content={"detail": "磁盘文件不存在"})
            return FileResponse(str(p), filename=rows[0]["name"])

        @self.router.put("/files/{file_id}")
        async def update_file_meta(file_id: int, payload: dict):
            rows = await self.db.query(
                "SELECT id FROM file_entry WHERE id=? AND type='file'", (file_id,)
            )
            if not rows:
                return JSONResponse(status_code=404, content={"detail": "文件不存在"})
            updates = []
            params = []
            if "ne_version_id" in payload:
                updates.append("ne_version_id=?")
                params.append(payload["ne_version_id"])
            if "name" in payload:
                updates.append("name=?")
                params.append(payload["name"])
            if not updates:
                return JSONResponse(status_code=400, content={"detail": "无更新字段"})
            updates.append("updated_at=CURRENT_TIMESTAMP")
            params.append(file_id)
            await self.db.execute(
                f"UPDATE file_entry SET {', '.join(updates)} WHERE id=?",
                tuple(params),
            )
            result = await self.db.query(
                "SELECT e.id, e.parent_id, e.name, e.type, e.ne_version_id, "
                "e.file_size, e.description, e.created_at, e.updated_at, "
                "n.vendor, n.ne_type, n.version "
                "FROM file_entry e LEFT JOIN ne_version n ON e.ne_version_id = n.id "
                "WHERE e.id=?",
                (file_id,),
            )
            return result[0]
```

**Step 2: 提交**

```bash
git add backend/plugins/mml_manager/main.py
git commit -m "feat(mml_manager): add file content/dowload/metadata API using file_entry"
```

---

### Task 6: 后端测试 — 更新集成测试

**Files:**
- Rewrite: `backend/tests/test_mml_manager.py`

**Step 1: 重写测试文件**

完整替换为适配新接口的测试。测试基础设施（`_test_lifespan`、`client` fixture）保持不变，只更新测试用例。

关键测试用例：
1. `test_create_ne_version` — 保留不变
2. `test_list_ne_versions` — 保留不变
3. `test_delete_ne_version_no_files` — 保留不变
4. `test_delete_ne_version_with_files_rejected` — 适配新上传接口
5. `test_create_folder` — 新增：在根目录创建文件夹
6. `test_create_subfolder` — 新增：在子目录创建文件夹
7. `test_list_entries_root` — 新增：列出根目录
8. `test_list_entries_folder` — 新增：列出子目录内容
9. `test_get_entry_path` — 新增：获取面包屑路径
10. `test_upload_file_to_root` — 新增：上传文件到根目录
11. `test_upload_file_to_folder` — 新增：上传文件到子目录
12. `test_upload_multiple_with_different_versions` — 新增：多文件不同版本
13. `test_upload_rejects_no_ne_version` — 新增：无 ne_version_id 被跳过
14. `test_upload_rejects_bad_extension` — 保留适配
15. `test_get_file_content` — 适配新接口
16. `test_update_file_content` — 适配新接口
17. `test_download_file` — 适配新接口
18. `test_update_file_meta` — 新增：修改网元版本关联
19. `test_delete_file` — 适配 `DELETE /entries/{id}`
20. `test_delete_folder_recursive` — 新增：递归删除
21. `test_stats` — 保留适配
22. `test_duplicate_ne_version_rejected` — 保留不变

**Step 2: 运行测试验证**

```bash
cd backend && pytest tests/test_mml_manager.py -v
```

Expected: 全部 PASS

**Step 3: 提交**

```bash
git add backend/tests/test_mml_manager.py
git commit -m "test(mml_manager): rewrite integration tests for file manager API"
```

---

### Task 7: 前端 — 更新 API 层

**Files:**
- Rewrite: `frontend/src/api/mml-manager.ts`

**Step 1: 重写 API 层**

替换所有接口类型和 API 函数。保留 `NeVersion`、`MmlStats` 不变，新增 `FileEntry` 替换 `MmlFile`：

```typescript
import api from "./index";

// ── Interfaces ──────────────────────────────────────────────────────────────

export interface NeVersion {
  id: number;
  vendor: string;
  ne_type: string;
  version: string;
  created_at: string;
}

export interface FileEntry {
  id: number;
  parent_id: number | null;
  name: string;
  type: "folder" | "file";
  ne_version_id: number | null;
  file_size: number;
  description: string | null;
  created_at: string;
  updated_at: string;
  vendor: string | null;
  ne_type: string | null;
  version: string | null;
}

export interface PathSegment {
  id: number;
  name: string;
}

export interface MmlStats {
  file_count: number;
  ne_version_count: number;
}

// ── NE Versions ─────────────────────────────────────────────────────────────

export async function fetchNeVersions(): Promise<NeVersion[]> {
  const { data } = await api.get<NeVersion[]>("/plugins/mml_manager/ne-versions");
  return data;
}

// ── Entries (Directory Browsing) ────────────────────────────────────────────

export async function fetchEntries(parentId?: number | null): Promise<FileEntry[]> {
  const params: Record<string, unknown> = {};
  if (parentId !== undefined && parentId !== null) {
    params.parent_id = parentId;
  }
  const { data } = await api.get<FileEntry[]>("/plugins/mml_manager/entries", { params });
  return data;
}

export async function fetchEntryPath(entryId: number): Promise<PathSegment[]> {
  const { data } = await api.get<PathSegment[]>(`/plugins/mml_manager/entries/${entryId}/path`);
  return data;
}

export async function createFolder(name: string, parentId?: number | null): Promise<FileEntry> {
  const payload: Record<string, unknown> = { name, type: "folder" };
  if (parentId !== undefined && parentId !== null) {
    payload.parent_id = parentId;
  }
  const { data } = await api.post<FileEntry>("/plugins/mml_manager/entries", payload);
  return data;
}

export async function deleteEntry(entryId: number): Promise<void> {
  await api.delete(`/plugins/mml_manager/entries/${entryId}`);
}

// ── Files ───────────────────────────────────────────────────────────────────

export async function getFileContent(id: number): Promise<string> {
  const { data } = await api.get<{ content: string }>(`/plugins/mml_manager/files/${id}/content`);
  return data.content;
}

export async function updateFileContent(id: number, content: string): Promise<void> {
  await api.put(`/plugins/mml_manager/files/${id}/content`, { content });
}

export async function updateFileMeta(id: number, payload: { ne_version_id?: number; name?: string }): Promise<FileEntry> {
  const { data } = await api.put<FileEntry>(`/plugins/mml_manager/files/${id}`, payload);
  return data;
}

export function getFileDownloadUrl(id: number): string {
  return `http://localhost:8000/api/plugins/mml_manager/files/${id}/download`;
}

export async function uploadFiles(
  parentId: number | null | undefined,
  files: { file: File; neVersionId: number }[],
): Promise<FileEntry[]> {
  const formData = new FormData();
  const items: Record<string, { ne_version_id: number }> = {};
  for (const item of files) {
    formData.append("files", item.file);
    items[item.file.name] = { ne_version_id: item.neVersionId };
  }
  formData.append("metadata", JSON.stringify({ parent_id: parentId ?? null, items }));
  const { data } = await api.post<FileEntry[]>("/plugins/mml_manager/upload", formData);
  return data;
}

// ── Stats ───────────────────────────────────────────────────────────────────

export async function fetchMmlStats(): Promise<MmlStats> {
  const { data } = await api.get<MmlStats>("/plugins/mml_manager/stats");
  return data;
}
```

**Step 2: 提交**

```bash
git add frontend/src/api/mml-manager.ts
git commit -m "feat(mml_manager): rewrite frontend API layer for file manager"
```

---

### Task 8: 前端 — 重写 MmlManager.vue 文件管理器视图

**Files:**
- Rewrite: `frontend/src/views/plugins/MmlManager.vue`

**Step 1: 完整重写组件**

组件包含以下区域：
1. **编辑器视图**（`v-if="editingFile"`）— 保留现有 Monaco 编辑器，只需将 `filename` 改为 `name`
2. **主列表视图**（`v-else`）— 重写为文件管理器
   - 顶部行：左侧面包屑 + 右侧工具栏按钮（新建文件夹、上传文件）
   - NDataTable 表格：名称（文件夹图标/文件图标）、类型、网元、版本、大小、操作
   - `..` 行：非根目录时显示，双击返回上级
   - 空状态提示
3. **新建文件夹模态框**
4. **上传文件模态框**

**核心状态变量：**
```typescript
const entries = ref<FileEntry[]>([]);
const currentParentId = ref<number | null>(null);
const breadcrumbs = ref<PathSegment[]>([]);
const neVersions = ref<NeVersion[]>([]);

// Editor
const editingFile = ref<{ id: number; name: string; content: string } | null>(null);
const saving = ref(false);

// Create folder modal
const showFolderModal = ref(false);
const newFolderName = ref("");

// Upload modal
const showUploadModal = ref(false);
const uploadFileList = ref<{ file: File; neVersionId: number | null }[]>([]);
const globalNeVersionId = ref<number | null>(null);
const uploading = ref(false);
```

**表格列定义（关键）：**

| 列 | 渲染逻辑 |
|---|---|
| 名称 | 文件夹用 FolderOutline 图标 + 蓝色文字 + `cursor: pointer`；文件用 DocumentTextOutline + 黑色文字 |
| 类型 | 固定文字 "文件夹" 或 "文件" |
| 网元 | `entry.vendor ?? "—" ` |
| 版本 | `entry.version ?? "—"` |
| 大小 | 文件显示 formatSize，文件夹显示 "—" |
| 操作 | 文件夹：删除（Popconfirm）；文件：下载、编辑、删除 |

**行双击逻辑：**
```typescript
function handleRowDoubleClick(row: FileEntry | DotEntry) {
  if ("isDot" in row) {
    navigateUp();
  } else if (row.type === "folder") {
    navigateInto(row);
  }
}
```

**导航函数：**
```typescript
async function navigateInto(folder: FileEntry) {
  currentParentId.value = folder.id;
  breadcrumbs.value.push({ id: folder.id, name: folder.name });
  await loadEntries();
}

async function navigateUp() {
  if (breadcrumbs.value.length === 0) return;
  breadcrumbs.value.pop();
  currentParentId.value = breadcrumbs.value.length > 0
    ? breadcrumbs.value[breadcrumbs.value.length - 1].id
    : null;
  await loadEntries();
}

async function navigateToBreadcrumb(index: number) {
  breadcrumbs.value = breadcrumbs.value.slice(0, index + 1);
  currentParentId.value = breadcrumbs.value.length > 0
    ? breadcrumbs.value[index].id
    : null;
  await loadEntries();
}
```

**上传对话框核心逻辑：**
- 统一版本选择器：`globalNeVersionId`，watch 变化时联动所有文件行的 `neVersionId`
- 文件列表：每行显示文件名 + 单独版本选择器 + 移除按钮
- 提交校验：所有文件的 `neVersionId` 不为 null
- 调用 `uploadFiles(currentParentId, fileList)`

**样式：** 保留现有的 `.light-table` 全局样式、暗色编辑器主题。

**Step 2: 提交**

```bash
git add frontend/src/views/plugins/MmlManager.vue
git commit -m "feat(mml_manager): rewrite frontend as file manager with breadcrumb navigation"
```

---

### Task 9: 更新 HomeView 中的 stats 引用（如有）

**Files:**
- Check: `frontend/src/views/HomeView.vue`

**Step 1: 检查 HomeView 是否需要修改**

HomeView 使用 `fetchMmlStats()` 获取统计，该接口返回格式不变（`file_count` + `ne_version_count`），因此 HomeView 不需要修改。

验证方式：确认 `HomeView.vue` 中的 stats 引用仍然使用 `MmlStats.file_count` 和 `MmlStats.ne_version_count`。

**Step 2: 无需修改则跳过此 Task**

---

### Task 10: 端到端验证

**Step 1: 启动后端**

```bash
cd backend && python -m uvicorn main:app --reload --port 8000
```

Expected: 服务正常启动，无建表错误

**Step 2: 启动前端**

```bash
cd frontend && npm run dev
```

Expected: 编译无错误

**Step 3: 手动验证流程**

1. 打开浏览器访问 MML 管理页面
2. 创建网元版本（如已存在跳过）
3. 点击"新建文件夹" → 输入名称 → 创建成功，表格中出现文件夹行
4. 双击文件夹 → 进入目录，面包屑更新
5. 点击"上传文件" → 拖入多个文件 → 设置统一版本 → 个别文件修改版本 → 提交
6. 表格显示上传的文件，包含网元和版本列
7. 点击 `..` 或面包屑跳转回上级
8. 点击文件的编辑按钮 → Monaco 编辑器打开 → 修改内容 → 保存成功
9. 点击下载 → 文件下载正常
10. 删除文件 → 确认 → 文件消失
11. 删除文件夹 → 确认 → 文件夹及其内容全部删除
12. 检查首页仪表盘统计卡片数据正确

**Step 4: 运行后端测试**

```bash
cd backend && pytest tests/test_mml_manager.py -v
```

Expected: 全部 PASS

**Step 5: 最终提交**

```bash
git add -A
git commit -m "feat(mml_manager): complete file manager redesign with directory navigation"
```
