# Claude -> Codex 交接：项目初始全量审查

**状态：待 Codex 审查**

## 基本信息

- **任务：** 对 CoreMaster 项目进行首次全量代码审查，确认代码质量、架构一致性和潜在风险
- **范围：** 整个项目——后端核心框架、两个插件（mml_manager、db_manager）、前端全套 UI、测试、文档
- **日期：** 2026-04-01

## Git 上下文

- **当前分支：** `master`
- **最新提交：** `8a4d300` — `refactor: clean up dead code and add db_manager plugin`
- **远程分支：** `origin/master`（已同步）
- **Push 状态：** 已 push 到远程
- **工作区脏改动：** `AGENTS.md`（新增 Push 规则章节）、`.claude/`（Claude Code 配置目录，未跟踪）
- **总提交数：** 35

## 任务目标

这是项目建立 AGENTS.md 协作协议后的第一次交接。Codex 需要对整个项目进行全量审查，产出基线分析文档，覆盖：

1. 代码质量与一致性
2. 架构设计的合理性
3. API 契约的完备性
4. 安全性（SQL 注入、文件路径遍历等）
5. 测试覆盖的充分性
6. 前后端契约一致性
7. 文档与实际代码的偏差

## 项目结构概览

```
CoreMaster/
├── AGENTS.md                          # 多代理协作协议
├── CLAUDE.md                          # Claude Code 项目说明
├── backend/
│   ├── main.py                        # FastAPI 入口，生命周期管理，插件加载
│   ├── requirements.txt               # Python 依赖
│   ├── core/
│   │   ├── config.py                  # 路径常量 (PLUGINS_DIR, DATA_DIR, DB_PATH)
│   │   ├── plugin/
│   │   │   ├── context.py             # PluginContext (get_service, register_service)
│   │   │   └── loader.py             # PluginLoader (扫描 plugin.toml，按 order.toml 排序)
│   │   └── services/
│   │       ├── database.py            # DatabaseService (aiosqlite 异步封装)
│   │       ├── parser.py              # ParserService (MML 命令正则解析)
│   │       ├── protocols.py           # Protocol 定义 (仅作参考)
│   │       └── registry.py            # ServiceRegistry (类型→实例容器)
│   ├── plugins/
│   │   ├── order.toml                 # 插件显示顺序
│   │   ├── mml_manager/
│   │   │   ├── plugin.toml            # 插件清单
│   │   │   └── main.py               # MML 文件管理器 (499 行)
│   │   └── db_manager/
│   │       ├── plugin.toml            # 插件清单
│   │       └── main.py               # 数据库表浏览器 (100 行)
│   └── tests/                         # 6 个测试文件，约 36 个测试
├── frontend/
│   ├── index.html                     # HTML 入口 (Google Fonts: Exo 2, Fira Code, Fira Sans)
│   ├── package.json                   # Vue 3, Naive UI, Monaco Editor, Axios
│   ├── vite.config.ts                 # Vite 配置 (仅 vue 插件)
│   ├── src/
│   │   ├── main.ts                    # Vue 入口 (Router + Monaco CDN 加载)
│   │   ├── App.vue                    # 根组件 (亮色主题 + themeOverrides)
│   │   ├── router/index.ts            # 3 路由 (首页 + 2 插件)
│   │   ├── layouts/MainLayout.vue     # 侧边栏 + 顶栏 (毛玻璃效果)
│   │   ├── views/
│   │   │   ├── HomeView.vue           # 首页仪表盘 (指标卡片 + 鼠标跟踪效果)
│   │   │   └── plugins/
│   │   │       ├── MmlManager.vue     # 文件管理器 (767 行)
│   │   │       └── DbManager.vue      # 数据库浏览器 (414 行)
│   │   └── api/
│   │       ├── index.ts               # Axios 实例 + fetchPlugins
│   │       ├── mml-manager.ts         # MML API 模块
│   │       └── db-manager.ts          # DB API 模块
│   └── public/
│       ├── favicon.svg
│       └── icons.svg
└── docs/
    └── plans/                         # 6 份设计/计划文档
```

## 改动文件清单（相对于空仓库的完整项目）

所有文件均在 commit `8a4d300` 中。此为首次全量审查，建议 Codex 审查所有文件。

核心文件（按优先级排序）：

| 优先级 | 文件 | 行数 | 说明 |
|--------|------|------|------|
| P0 | `backend/plugins/mml_manager/main.py` | ~499 | 最大的插件，含文件 I/O、SQL、解析 |
| P0 | `frontend/src/views/plugins/MmlManager.vue` | ~767 | 最大的前端组件 |
| P0 | `backend/main.py` | ~120 | 应用入口，插件加载编排 |
| P1 | `backend/core/services/database.py` | ~50 | 数据库服务，所有 SQL 经过此处 |
| P1 | `backend/plugins/db_manager/main.py` | ~100 | 通用表 CRUD，SQL 注入风险点 |
| P1 | `frontend/src/views/plugins/DbManager.vue` | ~414 | 数据库 CRUD UI |
| P1 | `frontend/src/views/HomeView.vue` | ~300 | 首页，数据获取逻辑 |
| P2 | `backend/core/plugin/loader.py` | ~60 | 插件加载器 |
| P2 | `backend/core/plugin/context.py` | ~25 | 插件上下文 |
| P2 | `backend/core/services/parser.py` | ~80 | MML 解析器 |
| P2 | `frontend/src/layouts/MainLayout.vue` | ~250 | 主布局 |
| P2 | `frontend/src/api/*.ts` | ~180 | 3 个 API 模块 |
| P3 | `backend/tests/*.py` | ~500 | 6 个测试文件 |
| P3 | `frontend/src/App.vue` | ~200 | 根组件主题配置 |

## 关键设计决策

1. **插件架构**：基于 `plugin.toml` 清单 + `PluginLoader` 扫描 + `importlib` 动态加载。无 on_destroy 钩子，无插件热卸载。

2. **数据库**：SQLite + aiosqlite，无 ORM、无 Repository 层、无迁移系统。表通过 `CREATE TABLE IF NOT EXISTS` 在插件注册时创建。`DatabaseService` 只暴露 `execute()` 和 `query()` 两个原始方法。

3. **磁盘文件存储**：MML 文件以 `entry_id` 命名存储在 `data/mml_files/{parent_entry_id}/` 下，用户通过数据库 `name` 字段看到可读名称。

4. **前端无状态管理库**：所有状态通过组件内 `ref()`/`reactive()` 管理，无 Pinia/Vuex。

5. **Monaco Editor**：通过 CDN (jsdelivr) 加载 v0.45.0，使用 C++ 语法高亮。

6. **无认证**：无用户系统，CORS 允许所有来源。

7. **API 请求体**：全部使用 `dict` 类型而非 Pydantic 模型（尽管 requirements.txt 包含 pydantic）。

## 已验证内容

- 后端测试通过（`pytest`，约 36 个测试覆盖核心服务和两个插件的 API）
- 前端构建通过（`npm run build`）
- 基本端到端流程验证：首页加载 → 侧边栏导航 → 文件管理器 CRUD → 数据库管理器 CRUD

## 已知假设

1. 项目为内部工具，暂不需要认证和权限控制
2. SQLite 单文件数据库足以满足当前使用规模
3. 文件存储使用 entry_id 命名而非可读名称，避免重名冲突
4. `plugin.toml` 的 `[frontend]` 节信息由后端 `/api/plugins` 统一返回给前端
5. 前端直接通过 `baseURL: "http://localhost:8000/api"` 访问后端，无 Vite 代理

## 已知风险和未验证区域

### 安全

1. **mml_manager 文件路径遍历**：文件上传/下载使用 `entry_id` 从数据库查找路径，但需确认不存在路径遍历可能
2. **db_manager SQL 注入**：表名通过正则 `^[a-zA-Z_][a-zA-Z0-9_]*$` 校验，但行数据的 INSERT/UPDATE 使用 f-string 构建 SQL
3. **CORS 全开放**：`allow_origins=["*"]`
4. **无文件类型/大小限制**：上传未限制文件大小

### 架构

1. **无数据库迁移**：schema 变更只能通过手动 ALTER 或重建
2. **Protocol 未被继承**：`protocols.py` 定义的 Protocol 类未被实际服务类继承，仅作参考
3. **Pydantic 已引入但未使用**：API 请求体使用 dict 而非 Pydantic model
4. **无错误码规范**：API 错误响应格式不统一
5. **前端硬编码 API 地址**：`baseURL: "http://localhost:8000/api"` 不便于部署

### 测试

1. **前端零测试**：无 Vitest/Jest 测试
2. **集成测试使用独立 test app**：`test_mml_manager.py` 创建独立 FastAPI 应用，可能与真实应用有细微差异
3. **无端到端测试**：未验证前端→后端完整链路

## 审查重点（指定给 Codex）

### 必须重点审查

1. **`backend/plugins/mml_manager/main.py`**：
   - 文件上传/下载的路径构建是否安全（路径遍历风险）
   - 递归删除文件夹是否正确清理磁盘文件
   - SQL 查询是否有注入风险
   - 错误处理是否完备（文件不存在、磁盘满等）

2. **`backend/plugins/db_manager/main.py`**：
   - 行数据 CRUD 的 SQL 构建是否安全（值是否参数化）
   - 表名正则校验是否充分
   - 是否存在可利用 db_manager 读取/修改系统表的可能

3. **`backend/main.py`**：
   - 插件加载异常处理是否合理
   - lifespan 资源释放是否完备（插件加载失败时数据库是否正确关闭）

### 建议审查

4. **前后端 API 契约一致性**：前端 API 模块（`api/mml-manager.ts`、`api/db-manager.ts`）的请求/响应类型是否与后端端点匹配
5. **设计文档与实现偏差**：原始设计文档（3月31日）描述的功能与实际实现（4月1日重设计）的差异是否已完全覆盖
6. **测试覆盖盲区**：哪些 API 端点/代码路径没有被测试覆盖

---

## Codex 审查结论

*（待 Codex 填写）*

- 状态：
- 发现的问题：
- 测试缺口：
- 建议修复：
- 剩余风险：

---

## Codex Review 回写

- Review 文档：`docs/analysis/2026-04-01-initial-project-review-codex-review.md`
- Review 状态：已审查
