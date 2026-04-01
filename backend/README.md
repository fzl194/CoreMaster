# CoreMaster Backend

基于 FastAPI 的插件化 MML 命令管理与解析平台后端。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python -m uvicorn main:app --reload --port 8000
```

服务启动后访问 `http://localhost:8000/docs` 查看自动生成的 API 文档。

## 项目结构

```
backend/
├── main.py                  # FastAPI 应用入口，生命周期管理，插件加载
├── requirements.txt         # Python 依赖
├── core/
│   ├── config.py            # 全局路径常量（PLUGINS_DIR, DATA_DIR, DB_PATH）
│   ├── services/
│   │   ├── registry.py      # ServiceRegistry - 全局服务注册表
│   │   ├── protocols.py     # 服务接口定义（Protocol）
│   │   ├── database.py      # DatabaseService - SQLite 异步数据库服务
│   │   └── parser.py        # ParserService - MML 命令解析器
│   └── plugin/
│       ├── context.py       # PluginContext - 插件运行上下文
│       └── loader.py        # PluginLoader - 插件扫描与加载
├── plugins/
│   ├── mml_manager/         # MML 文件管理插件
│   │   ├── plugin.toml      # 插件清单
│   │   └── main.py          # 插件入口
│   └── db_manager/          # 数据库管理插件
│       ├── plugin.toml      # 插件清单
│       └── main.py          # 插件入口
├── data/                    # 运行时数据（gitignored）
│   ├── coremaster.db        # SQLite 数据库
│   └── mml_files/           # MML 文件磁盘存储
└── tests/
    ├── test_registry.py     # ServiceRegistry 单元测试
    ├── test_parser.py       # ParserService 单元测试
    ├── test_database.py     # DatabaseService 单元测试
    ├── test_plugin.py       # 插件系统单元测试
    ├── test_integration.py  # 核心端点集成测试
    ├── test_mml_manager.py  # MML 管理插件集成测试
    └── test_db_manager.py   # 数据库管理插件集成测试
```

## 插件系统

### 工作流程

1. 服务启动时，`PluginLoader` 扫描 `plugins/` 目录下所有包含 `plugin.toml` 的子目录
2. 通过 `importlib` 动态导入插件入口文件，实例化 `Plugin` 类
3. 调用 `Plugin.on_register(ctx)`，传入 `PluginContext`
4. 插件通过 `ctx` 获取服务、注册菜单、挂载路由

### plugin.toml 格式

```toml
[plugin]
name = "my_plugin"
version = "0.1.0"
description = "插件描述"

[plugin.backend]
entry = "main.py"
routes_prefix = "/api/plugins/my_plugin"

[plugin.frontend]
entry = "src/index.vue"
menu_title = "菜单名称"
icon = "icon-name"
```

### Plugin 类约定

插件入口文件必须导出一个名为 `Plugin` 的类，该类需实现 `on_register(ctx: PluginContext)` 异步方法，并可提供 `router` 属性用于挂载 API 路由。

### PluginContext 提供的能力

| 方法 | 说明 |
|------|------|
| `get_service(service_type)` | 从注册表获取服务实例 |
| `register_service(service_type, instance)` | 向注册表注册新服务 |
| `register_menu(title, icon, path)` | 注册前端菜单项 |
| `get_menus()` | 获取已注册的菜单列表 |

## ServiceRegistry

`ServiceRegistry` 是全局服务容器，采用类型作为 key 的简单字典模式：

```python
registry = ServiceRegistry()
registry.register(MyService, my_instance)

# 在插件中获取
svc = ctx.get_service(MyService)
```

当前已注册的服务：
- `DatabaseService` -- SQLite 异步数据库（aiosqlite）
- `ParserService` -- MML 命令解析器

## API 端点

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/plugins` | 获取已加载插件列表和菜单 |

### MML 管理插件（`/api/plugins/mml_manager`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/parse` | 上传文件解析 MML 命令（multipart） |
| POST | `/parse-text` | 发送文本解析 MML 命令（JSON） |
| GET | `/ne-versions` | 列出所有网元版本 |
| POST | `/ne-versions` | 创建网元版本 |
| DELETE | `/ne-versions/{id}` | 删除网元版本（有关联文件时拒绝） |
| GET | `/entries?parent_id=` | 列出目录内容（文件夹在前） |
| GET | `/entries/{id}/path` | 获取面包屑路径链 |
| POST | `/entries` | 创建文件夹 |
| DELETE | `/entries/{id}` | 删除文件/文件夹（文件夹递归删除） |
| POST | `/upload` | 上传文件（FormData：metadata JSON + files） |
| GET | `/files/{id}/content` | 获取文件文本内容 |
| PUT | `/files/{id}/content` | 更新文件文本内容 |
| GET | `/files/{id}/download` | 下载文件 |
| PUT | `/files/{id}` | 更新文件元数据（名称、网元版本） |
| GET | `/stats` | 获取文件和网元版本计数 |

### 数据库管理插件（`/api/plugins/db_manager`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/tables` | 列出所有非系统表及行数 |
| GET | `/tables/{name}/schema` | 获取列信息（PRAGMA table_info） |
| GET | `/tables/{name}/rows` | 分页浏览行（limit/offset） |
| POST | `/tables/{name}/rows` | 插入行 |
| PUT | `/tables/{name}/rows/{row_id}` | 按 rowid 更新行 |
| DELETE | `/tables/{name}/rows/{row_id}` | 按 rowid 删除行 |

表名通过正则 `^[a-zA-Z_][a-zA-Z0-9_]*$` 校验防止注入，`file_path` 列为受保护列，不可编辑。

## 创建新插件

以创建一个名为 `my_plugin` 的插件为例：

**第一步：创建目录和清单**

```bash
mkdir -p plugins/my_plugin
```

创建 `plugins/my_plugin/plugin.toml`：

```toml
[plugin]
name = "my_plugin"
version = "0.1.0"
description = "我的插件"

[plugin.backend]
entry = "main.py"
routes_prefix = "/api/plugins/my_plugin"

[plugin.frontend]
entry = "src/index.vue"
menu_title = "我的插件"
icon = "tool"
```

**第二步：编写插件入口**

创建 `plugins/my_plugin/main.py`：

```python
from fastapi import APIRouter
from core.plugin.context import PluginContext


class Plugin:
    def __init__(self):
        self.router = APIRouter()

    async def on_register(self, ctx: PluginContext) -> None:
        ctx.register_menu("我的插件", "tool", "/plugins/my_plugin")

        @self.router.get("/hello")
        async def hello():
            return {"message": "hello from my_plugin"}
```

**第三步：重启服务**

重启后插件会自动加载。访问 `/api/plugins` 确认插件已注册，访问 `/api/plugins/my_plugin/hello` 测试端点。

## 运行测试

```bash
# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/test_parser.py

# 运行集成测试（需要插件目录存在）
pytest tests/test_integration.py

# 显示详细输出
pytest -v
```

测试依赖（已包含在 requirements.txt 中）：
- pytest + pytest-asyncio：测试框架
- httpx：集成测试中的异步 HTTP 客户端

## 依赖

| 包 | 用途 |
|----|------|
| fastapi >= 0.115.0 | Web 框架 |
| uvicorn[standard] >= 0.30.0 | ASGI 服务器 |
| aiosqlite >= 0.20.0 | SQLite 异步访问 |
| toml >= 0.10.2 | 解析 plugin.toml |
| pydantic >= 2.0.0 | 数据校验 |
| httpx >= 0.27.0 | 测试用 HTTP 客户端 |
| pytest >= 8.0.0 | 测试框架 |
| pytest-asyncio >= 0.24.0 | 异步测试支持 |
