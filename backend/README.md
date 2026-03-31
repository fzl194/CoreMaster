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
│   └── mml_manager/         # MML 管理插件（示例/首个插件）
│       ├── plugin.toml      # 插件清单
│       └── main.py          # 插件入口
└── tests/
    ├── test_registry.py     # ServiceRegistry 单元测试
    ├── test_parser.py       # ParserService 单元测试
    ├── test_database.py     # DatabaseService 单元测试
    ├── test_plugin.py       # 插件系统单元测试
    └── test_integration.py  # API 集成测试
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

`protocols.py` 中定义了 `DatabaseServiceProtocol` 和 `ParserServiceProtocol` 接口。当前这两个接口仅作为参考定义，实际服务类并未继承 Protocol，后续会逐步完善实现。

## API 端点

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/plugins` | 获取已加载插件列表和菜单 |

### MML 管理插件端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/plugins/mml_manager/parse` | 上传文件解析 MML 命令（multipart） |
| POST | `/api/plugins/mml_manager/parse-text` | 发送文本解析 MML 命令（JSON） |

请求示例：

```bash
# 解析文本
curl -X POST http://localhost:8000/api/plugins/mml_manager/parse-text \
  -H "Content-Type: application/json" \
  -d '{"text": "ADD APN: APN=\"test\", BINDVPN=ENABLE;"}'

# 上传文件
curl -X POST http://localhost:8000/api/plugins/mml_manager/parse \
  -F "file=@commands.mml"
```

响应格式：

```json
{
  "commands": [
    {
      "operation": "ADD",
      "name": "APN",
      "params": [{"name": "APN", "value": "test"}, {"name": "BINDVPN", "value": "ENABLE"}],
      "raw_text": "ADD APN: APN=\"test\", BINDVPN=ENABLE;",
      "line_number": 1
    }
  ],
  "count": 1
}
```

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

## 当前状态说明

本项目处于早期开发阶段（v0.1.0），已实现的部分：

- 插件扫描、加载、路由挂载机制
- ServiceRegistry 全局服务容器
- DatabaseService（SQLite 异步封装）
- ParserService（MML 命令解析，支持 ADD/MOD/DEL/GET/LST 等操作类型）
- MML 管理示例插件
- 核心和插件的单元测试及集成测试

尚未实现 / 规划中的部分：

- `protocols.py` 中定义的 Protocol 接口目前仅作参考，未强制约束
- 插件前端部分（Vue 组件）的加载机制
- 用户认证与权限系统
- 数据库迁移机制
- 插件间依赖管理
- 生产环境部署配置
