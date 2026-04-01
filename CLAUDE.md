# CLAUDE.md

本文件为 Claude Code 在本仓库中工作时提供说明。

## 共享代理协议

在开始任何实质性任务之前，先读取 [AGENTS.md](./AGENTS.md)，并将其作为 Claude Code 与 Codex 之间的共享协作协议来执行。

在本仓库中，默认分工如下：

- Claude Code：负责计划、实现、集成
- Codex：负责审查、查漏补缺、输出分析文档

Claude 在完成实现后，必须提供一份可供 Codex 审查的交接说明；在 Codex 的问题被修复或被明确处置之前，不应将任务视为完成。

**Claude 不得修改属于 Codex 职责的文档内容。** 具体来说：

- Claude 不得修改 Codex 产出的审查文档（`docs/analysis/` 下的 `codex-review.md`）。
- Claude 不得修改交接文档（`docs/handoffs/` 下的 `claude-handoff.md`）中的状态标记、处置结论等应由 Codex 回写的内容。Claude 只负责编写初始交接内容。
- 当 Claude 根据 Codex 审查意见完成代码修复后，应产出独立的交付说明文档（如 `docs/handoffs/YYYY-MM-DD-<task-slug>-claude-fix.md`），由 Codex 去回写 handoff 状态和 review 结论。

## 项目概述

CoreMaster 是一个基于插件化架构的 MML（人机语言）命令管理与解析平台，用于核心网配置管理。后端采用 FastAPI + 动态插件系统，前端采用 Vue 3 + Naive UI（亮色主题）。

## 开发命令

### 后端 (`backend/`)
```bash
cd backend
pip install -r requirements.txt          # 安装依赖
python -m uvicorn main:app --reload --port 8000  # 启动开发服务器（热重载）
pytest                                   # 运行全部测试
pytest tests/test_parser.py              # 运行单个测试文件
pytest -v                                # 详细输出运行测试
```

### 前端 (`frontend/`)
```bash
cd frontend
npm install                              # 安装依赖
npm run dev                              # 启动开发服务器（Vite，默认端口 5173）
npm run build                            # 类型检查 + 生产构建
npm run preview                          # 预览生产构建
```

前端通过 axios 的 `baseURL` 直接指向 `http://localhost:8000/api`（无 Vite 代理），后端需处理 CORS。

## 架构

### 后端插件系统

后端围绕插件架构构建，`main.py` 负责编排启动流程：

1. **启动流程（`lifespan`）**：创建 `ServiceRegistry` → 注册核心服务（`DatabaseService`、`ParserService`）→ `PluginLoader.scan()` 扫描插件目录 → 为每个插件创建 `PluginContext` 进行依赖注入 → 调用 `on_register()` → 检测插件 `router` 属性并自动挂载到 `routes_prefix` 路径
2. **ServiceRegistry**（`core/services/registry.py`）：以类型为 key 的字典容器，通过类类型注册和获取服务实例
3. **PluginLoader**（`core/plugin/loader.py`）：扫描 `plugins/` 下包含 `plugin.toml` 清单的子目录，返回按目录名排序的清单列表
4. **PluginContext**（`core/plugin/context.py`）：每个插件的运行上下文，提供 `get_service()`、`register_service()`、`register_menu()`、`get_menus()` 接口

**插件约定**：每个插件目录必须包含 `plugin.toml` 清单文件和一个入口 Python 文件，入口文件需导出 `Plugin` 类并实现 `async on_register(ctx: PluginContext)` 方法。插件可选地设置 `self.router`（FastAPI `APIRouter`），`main.py` 会自动将其挂载到 `plugin.toml` 中定义的 `routes_prefix` 路径下。目前只有 `on_register` 生命周期钩子，无 `on_destroy`。

**核心服务**：
- **MML 解析器**（`core/services/parser.py`）：基于正则的命令解析器，支持操作类型 `ADD|MOD|DEL|RMV|SET|GET|LST|DSP|ACT|DEA|BLK|UBL|REG|DEREG`，`parse_text()` 和 `parse_file()` 返回 `list[dict]`（包含 operation、name、params、raw_text、line_number）
- **数据库服务**（`core/services/database.py`）：SQLite + aiosqlite 异步访问，提供 `execute(sql, params)` 和 `query(sql, params)` 两个方法，无 Repository 层
- **Protocol 定义**（`core/services/protocols.py`）：`DatabaseServiceProtocol` 和 `ParserServiceProtocol` 两个 `@runtime_checkable` Protocol，目前仅作参考定义

### 已实现的插件

#### mml_manager（MML 文件管理器）

Web 文件管理器模式，支持多级目录导航、文件上传下载、在线编辑。

**数据库表**：
- `ne_version`：网元版本（vendor、ne_type、version），UNIQUE(vendor, ne_type, version)
- `file_entry`：统一存储文件夹和文件（`type` 字段区分 folder/file），通过 `parent_id` 递归构建目录树，文件必须关联 `ne_version_id`

**磁盘存储**：`data/mml_files/` 为根目录，以 `entry_id` 命名，用户通过数据库 `name` 字段看到可读名称。

**API 端点**（前缀 `/api/plugins/mml_manager`）：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/parse` | 解析上传的 MML 文件 |
| POST | `/parse-text` | 解析 JSON 中的 MML 文本 |
| GET/POST/DELETE | `/ne-versions[/{id}]` | 网元版本 CRUD |
| GET | `/entries?parent_id=` | 列出目录内容（文件夹在前） |
| GET | `/entries/{id}/path` | 获取面包屑路径链 |
| POST | `/entries` | 创建文件夹 |
| DELETE | `/entries/{id}` | 删除文件/文件夹（文件夹递归删除） |
| POST | `/upload` | 上传文件（FormData：metadata JSON + files，支持逐文件 ne_version_id） |
| GET/PUT | `/files/{id}/content` | 获取/更新文件文本内容 |
| GET | `/files/{id}/download` | 下载文件 |
| PUT | `/files/{id}` | 更新文件元数据 |
| GET | `/stats` | 文件和网元版本计数 |

**设计文档**：`docs/plans/2026-04-01-mml-file-manager-design.md`

#### db_manager（数据库管理器）

数据库表浏览器，支持查看任意表的 schema、浏览/增/删/改行数据。

**API 端点**（前缀 `/api/plugins/db_manager`）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tables` | 列出所有非系统表及行数 |
| GET | `/tables/{name}/schema` | 获取列信息（PRAGMA table_info） |
| GET | `/tables/{name}/rows` | 分页浏览行（limit/offset） |
| POST | `/tables/{name}/rows` | 插入行 |
| PUT | `/tables/{name}/rows/{row_id}` | 按 rowid 更新行 |
| DELETE | `/tables/{name}/rows/{row_id}` | 按 rowid 删除行 |

表名通过正则 `^[a-zA-Z_][a-zA-Z0-9_]*$` 校验防止注入。

### 前端结构

- **App.vue**：根组件，使用 Naive UI **亮色主题** + 自定义 `themeOverrides`（主色 `#2563EB`，背景 `#F0F4F8`，卡片白色，字体 Fira Sans / Fira Code）
- **main.ts**：注册 Vue Router 和 Monaco Editor 插件（CDN 加载 `monaco-editor@0.45.0`）
- **MainLayout.vue**：可折叠侧边栏（240px/68px）+ 顶栏，从 `/api/plugins` 获取菜单，按固定顺序排列（mml-manager → version-diff → mml-graph → script-gen → validator → db-manager），底部显示服务连接状态
- **HomeView.vue**：首页仪表盘，Hero 区 + 指标卡片网格，从 mml_manager 和 db_manager 获取实时统计数据，卡片可点击跳转
- **MmlManager.vue**：文件管理器视图，面包屑导航 + NDataTable（单击进入文件夹），内嵌 Monaco Editor（C++ 语法高亮、亮色主题）在线编辑 MML 文件，上传对话框支持全局/逐文件网元版本设置
- **DbManager.vue**：数据库管理视图，左侧表列表 + 右侧数据表格，支持行级 CRUD（模态框编辑），分页 50 行/页
- **api/**：`index.ts`（Axios 实例 + `fetchPlugins`）、`mml-manager.ts`、`db-manager.ts`（各插件的完整 API 模块）

**路由**：`/`（首页）、`/plugins/mml-manager`、`/plugins/db-manager`，所有视图组件懒加载。

### 关键路径

- 插件目录：`backend/plugins/<plugin_name>/`
- 插件清单：`backend/plugins/<name>/plugin.toml`
- 数据库：`backend/data/coremaster.db`（SQLite，aiosqlite 异步访问）
- MML 文件存储：`backend/data/mml_files/`
- 配置常量：`backend/core/config.py`（PLUGINS_DIR、DATA_DIR、DB_PATH）
- 测试：`backend/tests/`（含 22 个 mml_manager 集成测试，使用独立 test DB）

## 约定

- 代码注释、UI 文案、文档主要使用中文
- 后端：异步 Python（FastAPI + aiosqlite），全面使用类型注解
- 前端：Vue 3 `<script setup>` 单文件组件，TypeScript，Naive UI 组件库，`@vicons/ionicons5` 图标，`@guolao/vue-monaco-editor` 代码编辑器
- 前端无状态管理库，所有状态通过组件内 `ref()`/`reactive()` 管理
- 前后端均未配置 linter 或 formatter
