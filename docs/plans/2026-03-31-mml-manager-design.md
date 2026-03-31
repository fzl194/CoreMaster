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

### 3.1 页面结构

MML Manager 作为独立插件，点击侧边栏 "MML 管理" 后内容区显示该插件的页面。

页面内使用 Tab 切换两个视图：

```
┌─────────────────────────────────────────────────┐
│  [文件管理]  [网元版本管理]                        │  ← Tab 切换
├─────────────────────────────────────────────────┤
│                                                 │
│  文件管理 Tab:                                   │
│  ┌─────────────────────────────────────────────┐│
│  │ 筛选: [网元版本 ▼]    [上传文件]             ││
│  ├─────────────────────────────────────────────┤│
│  │ 文件名  │ 网元  │ 版本  │ 大小  │ 时间 │ 操作││
│  │ xxx.mml │ 5GC  │ V100 │ 2KB  │ ... │ ↙ ✎ ✗ ││
│  │ ...     │      │      │      │     │        ││
│  └─────────────────────────────────────────────┘│
│                                                 │
│  网元版本管理 Tab:                                │
│  ┌─────────────────────────────────────────────┐│
│  │ [新增版本]                                   ││
│  ├─────────────────────────────────────────────┤│
│  │ 厂商      │ 网元类型 │ 版本号     │ 操作     ││
│  │ huawei   │ 5GC     │ V100R001  │ ✗         ││
│  └─────────────────────────────────────────────┘│
└─────────────────────────────────────────────────┘
```

### 3.2 编辑器视图

点击文件的"编辑"按钮后，切换到编辑器视图（同页面内切换，不是新路由）：

```
┌─────────────────────────────────────────────────┐
│  ← 返回列表          xxx.mml       [保存]        │
├─────────────────────────────────────────────────┤
│  1 │ // 配置文件                                  │
│  2 │ ADD APN: APN="cmnet", BINDVPN=ENABLE;        │
│  3 │ MOD APN: APN="internet", VRFNAME="vpn";      │
│  4 │                                              │
│  ...│                                             │
└─────────────────────────────────────────────────┘
```

- 使用 Monaco Editor
- 语言模式设为 C++（近似 MML 语法高亮）
- 保存时写入磁盘文件并更新 updated_at

### 3.3 上传对话框

- 选择网元版本（下拉，数据来自 /ne-versions）
- 拖拽上传区域，支持多文件
- 仅接受 .mml 和 .txt 文件
- 显示上传进度和结果

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
