# CoreMaster 设计文档

## 1. 项目定位

个人 MML 工具平台，核心能力是管理核心网 MML 脚本文件，并从中挖掘知识。后期移交开发部。

- **数据源**：文件导入（华为、爱立信 MML 脚本）
- **核心流程**：MML 脚本 -> 解析 -> 结构化数据 -> 知识挖掘
- **部署方式**：单机本地为主

## 2. 整体架构

```
+--------------------------------------------------+
|  Vue 3 + Vite + Naive UI (前端 Shell)             |
|  +-----------+----------------------------------+ |
|  | 侧边栏     |          内容区                   | |
|  | (动态菜单) |  +----------+----------+-------+ | |
|  |           |  | MML管理   | 图谱     | 版本.. | | |
|  | 插件注册   |  | (核心页)  | (插件)   | (插件) | | |
|  +-----------+--+----------+----------+-------+ | |
+--------------------------------------------------+
         |  HTTP API
         v
+--------------------------------------------------+
|  FastAPI (后端)                                   |
|  +----------------------------------------------+|
|  |  core/services/  公共能力层                    ||
|  |  ├── registry.py     ServiceRegistry          ||
|  |  ├── protocols.py    服务协议定义               ||
|  |  ├── database.py     DatabaseService          ||
|  |  └── parser.py       ParserService            ||
|  +----------------------------------------------+|
|  |  core/plugin/  插件系统                        ||
|  |  ├── loader.py       插件扫描与加载             ||
|  |  └── context.py      PluginContext             ||
|  +----------------------------------------------+|
|  |  plugins/  子应用（可插拔）                     ||
|  |  ├── mml_manager/    MML 文件管理（核心页）      ||
|  |  ├── mml_graph/      图谱挖掘                  ||
|  |  ├── version_diff/   版本差异                  ||
|  |  ├── script_gen/     脚本生成                  ||
|  |  └── validator/      校验审计                  ||
|  +----------------------------------------------+|
|         |                                         |
|         v                                         |
|  SQLite (默认，接口可换)                            |
+--------------------------------------------------+
```

## 3. 技术选型

| 层         | 技术                    |
| ---------- | ----------------------- |
| 前端       | Vue 3 + Vite + Naive UI |
| 后端       | Python + FastAPI         |
| 数据库     | SQLite（默认，接口可换）  |
| 插件声明   | plugin.toml              |
| 插件协议   | Python Protocol          |
| 部署       | 单机本地                  |

## 4. 目录结构

```
CoreMaster/
+-- backend/
|   +-- core/
|   |   +-- services/
|   |   |   +-- registry.py          # ServiceRegistry 全局服务注册表
|   |   |   +-- protocols.py         # 所有服务 Protocol 定义
|   |   |   +-- database.py          # DatabaseService 实现
|   |   |   +-- parser.py            # ParserService 实现
|   |   +-- plugin/
|   |   |   +-- loader.py            # 插件扫描与加载
|   |   |   +-- context.py           # PluginContext
|   |   +-- config.py                # 全局配置
|   +-- plugins/
|   |   +-- mml_manager/             # MML 文件管理（核心页）
|   |   +-- mml_graph/               # 图谱挖掘
|   |   +-- version_diff/            # 版本差异分析
|   |   +-- script_gen/              # 配置脚本生成
|   |   +-- validator/               # 校验审计
|   +-- main.py                      # 入口
|   +-- requirements.txt
+-- frontend/
|   +-- src/
|   |   +-- views/
|   |   |   +-- core/                # 核心页面
|   |   |   +-- plugins/             # 插件前端页面
|   |   +-- components/
|   |   +-- plugin_loader.ts         # 前端插件加载器
|   +-- package.json
+-- docs/
|   +-- plans/
+-- README.md
```

## 5. 公共能力层：ServiceRegistry

所有公共能力以 Service 形式注册到 ServiceRegistry，插件通过统一接口获取。新增能力不影响已有插件。

### 5.1 ServiceRegistry

```python
class ServiceRegistry:
    _services: dict[type, object] = {}

    def register(self, service_type: type, instance: object) -> None:
        self._services[service_type] = instance

    def get(self, service_type: type) -> object:
        return self._services[service_type]

    def list_services(self) -> list[type]:
        return list(self._services.keys())
```

### 5.2 服务协议

每个公共能力定义 Protocol，插件依赖 Protocol 而非实现。

```python
class DatabaseService(Protocol):
    async def query(self, sql: str, params: dict = None) -> list[dict]: ...
    async def execute(self, sql: str, params: dict = None) -> None: ...
    async def get_repo(self, table: str) -> IRepository: ...

class ParserService(Protocol):
    def parse_text(self, text: str) -> list[ParsedCommand]: ...
    def parse_file(self, path: str) -> list[ParsedCommand]: ...
```

### 5.3 新增公共能力流程

1. 在 `core/services/protocols.py` 定义 Protocol
2. 在 `core/services/` 下写实现
3. 在 `main.py` 启动时注册到 ServiceRegistry
4. 插件即可通过 `ctx.get_service()` 使用

## 6. 插件系统

### 6.1 插件生命周期

```
注册 -> 安装(初始化) -> 运行 -> 卸载
```

### 6.2 插件声明 (plugin.toml)

```toml
[plugin]
name = "version_diff"
version = "0.1.0"
description = "MML 版本差异分析"

[plugin.backend]
entry = "main.py"
routes_prefix = "/api/plugins/version_diff"

[plugin.frontend]
entry = "src/index.vue"
menu_title = "版本差异分析"
icon = "diff"
```

### 6.3 插件后端协议

```python
class Plugin:
    async def on_register(self, ctx: PluginContext) -> None:
        """注册时调用"""

    async def on_destroy(self) -> None:
        """卸载时清理"""
```

### 6.4 PluginContext

```python
class PluginContext:
    def get_service(self, service_type: type) -> object:
        """获取公共服务"""

    def register_router(self, router) -> None:
        """注册 API 路由"""

    def register_menu(self, title: str, icon: str, path: str) -> None:
        """注册前端菜单项"""

    def register_service(self, service_type: type, instance: object) -> None:
        """注册服务供其他插件使用"""
```

### 6.5 启动流程

```
main.py 启动
  -> 初始化 ServiceRegistry，注册 DatabaseService、ParserService 等
  -> 扫描 plugins/ 目录
  -> 读取每个 plugin.toml
  -> 创建 PluginContext，调用 Plugin.on_register()
  -> 收集所有路由和菜单
  -> 挂载到 FastAPI app
  -> 启动服务
```

## 7. 前端架构

### 7.1 Shell 布局

```
+--------------------------------------------------+
|  CoreMaster                           [设置]      |  <- 顶栏（固定）
+-----------+--------------------------------------+
|           |                                      |
|  MML 管理  |  +----------------------------------+|
|           |  |                                  ||
|  --------  |  |     子应用内容区                  ||
|  图谱     |  |     （插件动态渲染）               ||
|  版本差异  |  |                                  ||
|  脚本生成  |  +----------------------------------+|
|  校验审计  |                                      |
|           |                                      |
+-----------+--------------------------------------+
  侧边栏（动态，来自插件注册）
```

### 7.2 插件前端加载

后端 `/api/plugins` 接口返回已注册插件列表，前端动态加载组件并注册路由和菜单。

### 7.3 风格一致性

所有插件使用 Naive UI 组件库，禁止自定义主题。通过 plugin-loader 提供统一布局容器。

## 8. MML 解析器

通用解析，不按厂商分策略。

### 8.1 MML 格式

```
// 注释行（以 // 开头）
ADD APN: APN="test_apn", BINDVPN=ENABLE, VRFNAME="vpn";
```

- 命令格式：`操作类型 命令名: 参数列表;`
- 参数格式：`参数名=参数值`，逗号分隔
- 注释：`//` 开头

### 8.2 解析输出

```python
@dataclass
class ParsedCommand:
    name: str                    # 命令名（如 APN）
    operation: str               # 操作类型（ADD/MOD/DEL/RMV）
    params: list[ParsedParam]    # 参数列表
    raw_text: str                # 原始文本
    line_number: int             # 行号

@dataclass
class ParsedParam:
    name: str                    # 参数名
    value: str | None            # 参数值
```

## 9. 子应用规划

| 子应用       | 功能                      | 优先级 |
| ------------ | ------------------------- | ------ |
| mml_manager  | MML 文件导入、管理、浏览   | P0     |
| mml_graph    | MML 命令图谱构建与可视化   | P1     |
| version_diff | 不同版本 MML 命令差异对比  | P1     |
| script_gen   | 根据配置生成 MML 脚本      | P2     |
| validator    | MML 脚本语法检查与审计     | P2     |
