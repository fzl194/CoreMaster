# MML 依赖挖掘 MVP — Claude 交接文档

> 状态：待 Codex 审查
> 日期：2026-04-02
> 任务 ID：dep-mining-mvp-001

## 任务目标

实现 MML 命令依赖关系挖掘系统的 MVP 版本，包含：增强解析器、候选生成引擎、审核队列 API、最小前端界面。

## 本次实现范围

### 已完成

1. **解析器增强** (`backend/core/services/parser.py`)
   - 多行命令支持（无分号续行 + 反斜杠续行）
   - 引号感知参数切分（双引号、单引号内逗号不切分）
   - 转义字符处理（`\"`, `\\`）
   - 块注释 `/* ... */` 支持
   - 解析结果分类（parsed / skipped / unrecognized）
   - `parse_text_with_report()` 新方法，返回命令列表 + 解析报告
   - 向后兼容：`parse_text()` 接口不变

2. **数据库表** (`backend/plugins/mml_manager/main.py`)
   - `command_instance` — 从脚本提取的命令实例
   - `dependency_candidate` — 候选依赖关系
   - `graph_edge` — 已确认的图谱边
   - `graph_changelog` — 变更日志
   - 相应索引

3. **命令实例提取 API**
   - `POST /api/plugins/mml_manager/scripts/{file_id}/extract-commands`

4. **候选生成引擎** (`backend/plugins/mml_manager/candidate_engine.py`)
   - 值匹配聚合 + 脚本级去重
   - 多维评分：支持度、区分度、顺序一致性、名称相关度
   - 置信度计算（可配置权重）
   - 状态自动分类：auto_passed / llm_review / man_review

5. **候选生成 API**
   - `POST /api/plugins/mml_manager/candidates/generate`

6. **审核队列 API**
   - `GET /api/plugins/mml_manager/candidates` — 列表（支持 ne_version_id, status 过滤）
   - `POST /api/plugins/mml_manager/candidates/{id}/accept` — 确认（创建 graph_edge + changelog）
   - `POST /api/plugins/mml_manager/candidates/{id}/reject` — 拒绝（创建 changelog）

7. **前端**
   - API 模块：`frontend/src/api/dependency-mining.ts`
   - Vue 视图：`frontend/src/views/plugins/DependencyMining.vue`
   - 路由注册：`/plugins/dependency-mining`
   - 后端注册虚拟插件入口（git-branch 图标）

### 测试

- **新增 22 个解析器测试**（`test_parser_enhanced.py`）— 全部通过
- **新增 10 个依赖挖掘测试**（`test_dependency_mining.py`）— 全部通过
  - candidate_engine 单元测试 4 个
  - API 端到端测试 6 个
- **原有 26 个 mml_manager 测试** — 全部通过（零回归）
- **前端构建** — 通过，无 TS 错误

### 不在本次范围内

- LLM 集成层（第二期）
- 图谱变更日志完整 UI + 撤回机制（第二期）
- 现网核查 + 版本冷启动（第三期）
- 独立 `mml_graph` 插件拆分（功能稳定后）

## 改动文件清单

| 文件 | 操作 |
|------|------|
| `backend/core/services/parser.py` | 修改 |
| `backend/core/services/protocols.py` | 修改 |
| `backend/plugins/mml_manager/main.py` | 修改 |
| `backend/plugins/mml_manager/candidate_engine.py` | 新建 |
| `backend/tests/test_parser_enhanced.py` | 新建 |
| `backend/tests/test_dependency_mining.py` | 新建 |
| `frontend/src/api/dependency-mining.ts` | 新建 |
| `frontend/src/views/plugins/DependencyMining.vue` | 新建 |
| `frontend/src/router/index.ts` | 修改 |
| `frontend/src/layouts/MainLayout.vue` | 修改 |
| `backend/main.py` | 修改 |

## 关键设计决策

1. **MVP 在 `mml_manager` 内实现**，不急于拆分为独立插件
2. **候选引擎为纯函数模块** (`candidate_engine.py`)，可独立测试
3. **命令标识格式**：`"ADD APN"` (空格分隔)，数据库中 ref_command / def_command 使用此格式
4. **候选主键**：`(ne_version_id, ref_command, ref_param, def_command, def_param)` UNIQUE 约束
5. **解析器向后兼容**：`parse_text()` 签名不变，新功能通过 `parse_text_with_report()` 暴露

## 已执行验证

- `python -m pytest tests/test_parser.py tests/test_parser_enhanced.py` — 28/28 PASS
- `python -m pytest tests/test_dependency_mining.py` — 10/10 PASS
- `python -m pytest tests/test_mml_manager.py` — 26/26 PASS
- `cd frontend && npm run build` — 构建成功

## 未验证项

- 无真实现网 MML 脚本回归测试（需要 ≥20 条真实脚本样本）
- 无前端 E2E 测试（Cypress/Playwright）
- 未测试与 db_manager 插件的并发加载影响（但已有集成测试覆盖）

## 已知风险

1. **candidate_engine import 路径**：使用 `sys.path` 临时注入插件目录，非标准做法
2. **无迁移系统**：表结构通过 `CREATE TABLE IF NOT EXISTS` 管理，后续 DDL 变更需手动处理
3. **SQLite 并发限制**：`DatabaseService` 使用单连接，高并发下可能成为瓶颈
4. **前端无错误提示**：`window.$message` 调用已移除，使用 `console.error` 替代

## 指定给 Codex 的审查重点

1. **解析器正确性**：多行拼接、引号切分、转义处理是否有边界 case 遗漏
2. **候选引擎算法**：去重逻辑、评分公式是否与设计文档一致
3. **SQL 安全**：`list_candidates` 使用 f-string 拼接 WHERE 子句，是否有注入风险
4. **API 路由冲突**：新增路由是否与现有路由冲突
5. **前端组件**：类型安全、无未使用变量

## 管理员本轮直接介入记录

- 管理员指示"从技术设计文档开始开发"，全程自动化
- 管理员要求自动提交、完成后输出 Codex 交接件
