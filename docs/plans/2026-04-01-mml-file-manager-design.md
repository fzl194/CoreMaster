# MML 文件管理器重设计

日期：2026-04-01

## 背景

当前 MML 文件管理按"网元版本"（vendor + ne_type + version）组织文件夹存储，用户无法自由管理目录结构。需要改为 Web 文件管理器模式：用户可自由创建文件夹/文件，支持多级目录导航和批量上传。

## 核心需求

1. 文件夹和文件以真实文件系统存储，用户自由创建和命名
2. 每个文件必须关联一个网元版本（ne_version），文件夹不关联
3. 前端以文件管理器形式展示，支持面包屑导航和目录浏览
4. 上传时支持统一设置网元版本 + 单文件覆盖
5. 网元版本管理（CRUD）保留现有实现，不做修改

## 数据库设计

新建 `file_entry` 表替代原有 `mml_file` 表，`ne_version` 表不变。

```sql
CREATE TABLE file_entry (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id     INTEGER REFERENCES file_entry(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    type          TEXT NOT NULL,               -- 'folder' | 'file'
    ne_version_id INTEGER REFERENCES ne_version(id),
    file_size     INTEGER DEFAULT 0,
    file_path     TEXT,
    description   TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_id, name, type)
);
```

- `parent_id = NULL` 表示根目录条目
- `ON DELETE CASCADE` 删除文件夹时自动级联删除子项
- `ne_version_id` 仅文件有值，文件夹为 NULL
- 前端展示使用 `name` 字段（用户可见的文件名/文件夹名）

## 磁盘存储

- 根目录：`data/mml_files/`
- 文件夹：`data/mml_files/{entry_id}/`
- 文件：`data/mml_files/{parent_entry_id}/{entry_id}.{ext}`
- 根目录下的文件：`data/mml_files/{entry_id}.{ext}`
- 磁盘用 entry_id 命名避免冲突，用户只看到 `name` 字段

## 后端 API

### 新增/替换接口

**目录浏览：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/entries?parent_id=` | 列出指定目录内容（空/不传=根目录），文件夹在前文件在后 |
| GET | `/entries/{id}/path` | 返回从根到当前条目的路径链 `[{id, name}, ...]` |
| POST | `/entries` | 创建文件夹 `{ parent_id, name }` |
| DELETE | `/entries/{id}` | 删除文件或文件夹（文件夹递归删子内容+磁盘目录） |

**文件上传：**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/upload` | FormData: `files` + `metadata`（JSON） |

`metadata` 格式：
```json
{
  "parent_id": 5,
  "items": {
    "file_a.mml": { "ne_version_id": 1 },
    "file_b.mml": { "ne_version_id": 3 }
  }
}
```

后端校验：每个文件必须在 items 中有 ne_version_id，否则拒绝。

**文件元数据更新：**

| 方法 | 路径 | 说明 |
|------|------|------|
| PUT | `/files/{id}` | 更新文件元数据（修改关联网元版本、重命名） |

### 保留不变的接口

- 网元版本 CRUD：`/ne-versions`
- 解析接口：`/parse`、`/parse-text`
- 统计接口：`/stats`
- 文件内容读写：`/files/{id}/content`
- 文件下载：`/files/{id}/download`

### 删除的接口

- `GET /files`（平铺列表）→ 替换为 `GET /entries`
- `GET /files/{id}` → 合并到 entries 返回中

## 前端 UI

### 文件管理器主视图

```
┌──────────────────────────────────────────────────────────┐
│ 根目录 > 文件夹A > 子文件夹B  ..          [新建文件夹] [上传文件] │
├──────────────────────────────────────────────────────────┤
│  名称          │ 类型   │ 网元     │ 版本   │ 大小  │ 操作          │
│  📁 ..         │ 文件夹 │ --      │ --    │ --   │ --            │
│  📁 子文件夹C  │ 文件夹 │ --      │ --    │ --   │ 删除          │
│  📁 子文件夹D  │ 文件夹 │ --      │ --    │ --   │ 删除          │
│  📄 config.mml │ 文件   │ huawei  │ V100R1│ 2KB  │ 下载/编辑/删除 │
│  📄 data.txt   │ 文件   │ zhongxing│ V200 │ 5KB  │ 下载/编辑/删除 │
└──────────────────────────────────────────────────────────┘
```

- 面包屑在左，工具栏按钮在右，同一行
- `..` 行仅在非根目录时显示，双击进入父目录
- 面包屑每一段可点击跳转到对应层级
- 双击文件夹进入该文件夹
- 编辑按钮打开 Monaco 编辑器（保留现有）

### 上传对话框

```
┌─────────────────────────────────────────┐
│  上传文件                            ✕  │
├─────────────────────────────────────────┤
│  统一设置网元版本：[▼ 选择网元版本 ]     │
├─────────────────────────────────────────┤
│  ┌─────────────────────────────────┐    │
│  │     拖拽文件到此处或点击选择     │    │
│  └─────────────────────────────────┘    │
├─────────────────────────────────────────┤
│  文件列表：                              │
│  file_a.mml   [▼ 版本1]  [×]           │
│  file_b.mml   [▼ 版本1]  [×]           │
│  file_c.txt   [▼ 版本3]  [×]           │
├─────────────────────────────────────────┤
│              [取消]  [上传]              │
└─────────────────────────────────────────┘
```

交互逻辑：
1. 选择统一版本 → 所有文件行自动填充该版本
2. 单个文件行可单独切换版本覆盖
3. 点击 [×] 移除某个文件
4. 所有文件都有 ne_version_id 后 [上传] 按钮才可用
5. 上传完成后关闭对话框，刷新当前目录

### 新建文件夹对话框

简单 NModal + NInput，输入文件夹名即可。

## 后端核心逻辑

### 删除
- 删除文件：删数据库记录 + 删磁盘文件
- 删除文件夹：递归查询所有子 entry → 删数据库记录（CASCADE 自动处理）→ `shutil.rmtree` 删磁盘目录

### 上传
1. 校验文件扩展名（.mml、.txt）
2. 校验 metadata 中每个文件都有 ne_version_id
3. 校验 parent_id 对应 entry 存在且类型为 folder（或 parent_id 为空=根目录）
4. 同名冲突：追加数字后缀
5. 逐个写入磁盘 + 插入数据库

## 影响范围

### 需修改

| 文件 | 变更 |
|------|------|
| `backend/plugins/mml_manager/main.py` | 替换 mml_file 表为 file_entry 表，重写文件管理 API |
| `frontend/src/views/plugins/MmlManager.vue` | 整体重写为文件管理器视图 |
| `frontend/src/api/mml-manager.ts` | 更新接口类型和 API 函数 |

### 不修改

| 文件 | 原因 |
|------|------|
| `backend/plugins/mml_manager/plugin.toml` | 路由前缀不变 |
| `backend/core/` | 核心插件系统不受影响 |
| `frontend/src/api/index.ts` | baseURL 不变 |
| `frontend/src/router/index.ts` | 路由不变 |
| `frontend/src/views/HomeView.vue` | 统计卡片不变 |

## 数据迁移

不做旧数据迁移（开发阶段），直接使用新表结构。
