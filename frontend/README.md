# CoreMaster Frontend

基于 Vue 3 + TypeScript + Vite + Naive UI 的核心网 MML 配置管理前端，采用亮色主题。

## 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器（默认端口 5173）
npm run dev

# 类型检查 + 生产构建
npm run build

# 预览生产构建
npm run preview
```

前端通过 axios 直连后端 `http://localhost:8000/api`（无 Vite 代理），后端需处理 CORS。

## 技术栈

| 依赖 | 版本 | 用途 |
|------|------|------|
| vue | ^3.5.30 | 前端框架 |
| vue-router | ^4.6.4 | 路由管理 |
| naive-ui | ^2.44.1 | UI 组件库（亮色主题） |
| axios | ^1.14.0 | HTTP 客户端 |
| @guolao/vue-monaco-editor | ^1.6.0 | Monaco Editor 封装 |
| @vicons/ionicons5 | ^0.13.0 | 图标库 |
| vite | ^8.0.1 | 构建工具 |
| typescript | ~5.9.3 | 类型系统 |

## 项目结构

```
frontend/
├── src/
│   ├── main.ts              # 应用入口，注册 Router + Monaco Editor
│   ├── App.vue              # 根组件，Naive UI 亮色主题 + 自定义主题覆盖
│   ├── router/
│   │   └── index.ts         # 路由定义（首页、MML 管理、数据库管理）
│   ├── layouts/
│   │   └── MainLayout.vue   # 主布局：可折叠侧边栏 + 顶栏面包屑
│   ├── views/
│   │   ├── HomeView.vue     # 首页仪表盘（Hero 区 + 指标卡片网格）
│   │   └── plugins/
│   │       ├── MmlManager.vue   # MML 文件管理器视图
│   │       └── DbManager.vue    # 数据库管理视图
│   └── api/
│       ├── index.ts         # Axios 实例 + fetchPlugins()
│       ├── mml-manager.ts   # MML 管理插件 API 模块
│       └── db-manager.ts    # 数据库管理插件 API 模块
├── package.json
├── vite.config.ts
└── tsconfig.json
```

## 页面说明

### 首页（`/`）

仪表盘页面，包含：
- Hero 区域：标题 + 描述 + 鼠标追踪光效
- 指标卡片网格：显示已加载模块数、MML 文件数/网元版本数、数据库表数等实时统计
- 卡片支持鼠标追踪 3D 倾斜效果，点击可跳转到对应插件页面

### MML 管理（`/plugins/mml-manager`）

文件管理器视图，功能包括：
- 面包屑导航 + 多级目录浏览
- NDataTable 列表展示（单击进入文件夹、双击编辑文件）
- Monaco Editor 在线编辑（C++ 语法高亮、亮色主题 vs）
- 文件上传（支持全局/逐文件设置网元版本）
- 新建文件夹、删除文件/文件夹

### 数据库管理（`/plugins/db-manager`）

数据库浏览器视图，功能包括：
- 左侧表列表 + 右侧数据表格
- 查看表 Schema（列信息）
- 行级 CRUD（模态框编辑）
- 分页浏览（50 行/页）

## API 模块

### `api/index.ts`

Axios 实例配置，baseURL 为 `http://localhost:8000/api`，导出 `fetchPlugins()` 获取已加载插件列表。

### `api/mml-manager.ts`

封装 MML 管理插件全部 API：网元版本 CRUD、目录浏览、文件上传/下载/编辑、统计信息。

### `api/db-manager.ts`

封装数据库管理插件全部 API：表列表、Schema 查询、行级 CRUD。

## 设计规范

- **主题**：Naive UI 亮色主题，主色 `#2563EB`，背景 `#F0F4F8`，卡片白色
- **字体**：UI 使用 Fira Sans，代码使用 Fira Code，标题使用 Exo 2
- **组件库**：Naive UI，全部通过 `themeOverrides` 自定义样式
- **状态管理**：无外部状态管理库，所有状态通过组件内 `ref()` / `reactive()` 管理
- **路由**：所有视图组件采用懒加载
