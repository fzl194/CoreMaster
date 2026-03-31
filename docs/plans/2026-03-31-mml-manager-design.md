# MML Manager 设计文档

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 MML 文件管理功能，包括按网元版本组织的文件上传/下载/在线展示/编辑/保存。

**Architecture:** mml_manager 作为 CoreMaster 的一个插件，后端使用 FastAPI + SQLite + 文件系统存储，前端使用 Naive UI + Monaco Editor。前端页面通过路由注册到 Shell 内容区。

**Tech Stack:** FastAPI, aiosqlite, Vue 3, Naive UI, Monaco Editor (@guolao/vue-monaco-editor)

---

## 1. 数据模型

### ne_version 表（网元版本）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| vendor | TEXT | 厂商，默认 `huawei` |
| ne_type | TEXT | 网元类型（如 5GC、EPC、MME） |
| version | TEXT | 软件版本号（如 V100R001） |
| created_at | DATETIME | 创建时间 |

约束：`vendor + ne_type + version` 唯一。

### mml_file 表（MML 文件元数据）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| filename | TEXT | 原始文件名 |
| ne_version_id | INTEGER FK | 关联 ne_version.id |
| file_path | TEXT | 磁盘相对路径（data/mml_files/下） |
| file_size | INTEGER | 文件大小（字节） |
| description | TEXT | 备注，可空 |
| created_at | DATETIME | 上传时间 |
| updated_at | DATETIME | 最后修改时间 |

### 磁盘目录结构

```
backend/data/mml_files/
├── huawei/
│   └── 5GC_V100R001/
│       ├── config_001.mml
│       └── config_002.txt
```

按 `{vendor}/{ne_type}_{version}/` 组织，文件名保留原始名。

---

## 2. 后端 API

所有路由前缀：`/api/plugins/mml_manager`

### 网元版本管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ne-versions` | 获取所有网元版本列表 |
| POST | `/ne-versions` | 新增网元版本（vendor 默认 huawei） |
| DELETE | `/ne-versions/{id}` | 删除网元版本（需确认无关联文件） |

### MML 文件管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/upload` | 上传文件（multipart，支持多文件，指定 ne_version_id） |
| GET | `/files` | 文件列表（支持 `?ne_version_id=` 筛选） |
| GET | `/files/{id}` | 文件详情 |
| GET | `/files/{id}/content` | 获取文件文本内容 |
| PUT | `/files/{id}/content` | 保存编辑后的文本内容 |
| GET | `/files/{id}/download` | 下载原始文件 |
| DELETE | `/files/{id}` | 删除文件（同时删除磁盘文件） |

### 上传接口详情

```
POST /api/plugins/mml_manager/upload
Content-Type: multipart/form-data

参数：
- files: File[]（支持多文件）
- ne_version_id: int（必填）

支持文件后缀：.mml, .txt
```

---

## 3. 前端页面

### 3.0 设计规范（UI/UX Pro Max）

与现有 CoreMaster Shell 保持一致：

| 规范项 | 值 |
|--------|------|
| 主题 | Dark Mode (OLED) |
| 主色 | #2563EB |
| 强调色 | #F97316 |
| 背景 | #13151a（内容区）、#16181f（卡片）、#0f1117（侧边栏） |
| 字体 | Fira Code（代码/数据）、Fira Sans（UI 文字） |
| 圆角 | 卡片 12px、按钮 8px |
| 图标 | @vicons/ionicons5，统一 outline 风格 |
| 交互反馈 | hover 200ms transition、按钮 loading 状态、操作完成 toast |

**UX 关键规则：**
- 所有异步操作 >300ms 显示 loading（按钮 disable + spinner）
- 删除操作需确认对话框（destructive emphasis，红色按钮）
- 上传中显示进度，完成后 toast 通知
- 空状态显示引导文案（如"暂无文件，点击上传"）
- 表格操作列：下载/编辑/删除，用图标按钮，hover 显示 tooltip

### 3.1 页面路由与结构

MML Manager 注册到侧边栏"功能模块"下，路由 `/plugins/mml-manager`，内容区显示该插件的页面。

页面内部状态切换（不用子路由，用组件内 v-if）：

```
状态1: 文件列表（默认）
状态2: 编辑器（点击编辑后）
```

### 3.2 文件列表视图

```
┌─────────────────────────────────────────────────────┐
│  ┌──────────────┐ ┌──────────────┐                  │
│  │ 文件管理      │ │ 网元版本管理   │  ← NTabs       │
│  └──────────────┘ └──────────────┘                  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌────────────────┐  ┌─────────────────────────────┐│
│  │网元版本 ▼      │  │  [上传文件]  按钮primary      ││
│  └────────────────┘  └─────────────────────────────┘│
│                                                     │
│  ┌─────────────────────────────────────────────────┐│
│  │ 文件名        │ 网元版本     │ 大小 │ 时间 │ 操作 ││
│  │───────────────│─────────────│──────│──────│──────││
│  │ config_001.mml│ 5GC V100   │ 2KB │ 3/31 │ ↙✎✗  ││
│  │ setup.txt     │ 5GC V100   │ 8KB │ 3/30 │ ↙✎✗  ││
│  │               │            │      │      │      ││
│  └─────────────────────────────────────────────────┘│
│                                                     │
│  空状态:                                             │
│  ┌─────────────────────────────────────────────────┐│
│  │         暂无 MML 文件                            ││
│  │    选择网元版本后上传文件                          ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘

操作列图标:
  ↙ 下载 (DownloadOutline)  tooltip="下载"
  ✎ 编辑 (CreateOutline)    tooltip="编辑"
  ✗ 删除 (TrashOutline)     tooltip="删除"  红色 hover
```

**表格使用 NDataTable**，暗色主题自带。
**筛选用 NSelect**，数据从 `/ne-versions` API 获取。

### 3.3 编辑器视图

点击编辑后，文件列表隐藏，编辑器全屏展示：

```
┌─────────────────────────────────────────────────────┐
│  ← 返回          config_001.mml          [保存]     │
│  NButton text    NText code-style   NButton primary │
├─────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐│
│  │  1 │ // 配置文件                                ││
│  │  2 │ ADD APN: APN="cmnet", BINDVPN=ENABLE;      ││
│  │  3 │ MOD APN: APN="internet", VRFNAME="vpn";    ││
│  │  4 │                                            ││
│  │    Monaco Editor, C++ language mode              ││
│  │    theme: vs-dark                               ││
│  │    minimap: enabled                             ││
│  │    fontSize: 14, fontFamily: Fira Code           ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

- 编辑器高度 `calc(100vh - 56px - 48px)` 撑满内容区
- 保存按钮 loading 状态，保存成功 toast 提示
- 返回按钮无确认（未修改时）；修改后返回弹出确认

### 3.4 上传对话框（NModal）

```
┌──────────────────────────────────────┐
│  上传 MML 文件                  [×]  │
├──────────────────────────────────────┤
│  网元版本 *                          │
│  ┌──────────────────────────────┐    │
│  │ 5GC_V100R001          ▼     │    │
│  └──────────────────────────────┘    │
│                                      │
│  ┌──────────────────────────────┐    │
│  │                              │    │
│  │   将 .mml / .txt 文件拖到此处 │    │  ← 拖拽区域
│  │   或 [点击选择文件]           │    │
│  │                              │    │
│  └──────────────────────────────┘    │
│                                      │
│  已选择:                              │
│  ┌ config_001.mml  2KB    [×] ┐      │
│  └ setup.txt      8KB    [×] ┘      │
│                                      │
│              [取消]  [上传 2 个文件]  │
└──────────────────────────────────────┘
```

- NUpload 组件，drag 模式，accept=".mml,.txt"
- NSelect 选择网元版本（必填，校验）
- 文件列表显示文件名和大小，可移除
- 上传中按钮 disable + loading
- 完成后关闭对话框，刷新文件列表，toast 提示

### 3.5 网元版本管理 Tab

```
┌─────────────────────────────────────────────────────┐
│  [新增版本] 按钮 primary                             │
├─────────────────────────────────────────────────────┤
│  厂商       │ 网元类型  │ 版本号      │ 文件数 │ 操作 │
│  huawei    │ 5GC      │ V100R001   │ 3     │ ✗    │
│  huawei    │ EPC      │ V200R003   │ 0     │ ✗    │
└─────────────────────────────────────────────────────┘
```

- 新增版本弹出 NModal（vendor 默认 huawei，填 ne_type 和 version）
- 删除前确认：有关联文件时提示"该版本下有 N 个文件，无法删除"

---

## 4. 首页指标更新

MML Manager 插件注册时，提供一个统计指标 API：

```
GET /api/plugins/mml_manager/stats
返回: { "file_count": 42, "ne_version_count": 5 }
```

首页 HomeView 的 "MML 脚本" 指标卡片改为从该 API 获取真实数据。

---

## 5. 数据库管理（占位，不实现）

在首页指标区域预留一个 "数据库管理" 入口卡片，后续用于查看/管理后台 SQLite 数据库。当前仅显示占位状态，不可点击。

---

## 6. 不在本期范围

- MML 文件解析（由独立插件/服务负责）
- 数据库管理界面（仅占位）
- 文件内容搜索
- 文件版本对比
