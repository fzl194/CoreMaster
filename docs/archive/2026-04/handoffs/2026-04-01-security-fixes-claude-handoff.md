# Claude -> Codex 交接：安全审计 P0-P2 问题修复

- 状态：待 Codex 审查
- 任务：基于 `docs/analysis/2026-04-01-initial-project-review-codex-review.md` 中发现的问题，逐项实现修复
- 分支：`master`
- 审查基线：`aed8b92`
- 关键提交：`4b62c51` `fix: 修复安全审计发现的 P0-P2 级别问题`
- 远程分支：`origin/master`
- Push 状态：未执行，待审查后统一推送

## 任务目标

修复 Codex 首次基线审查中发现的全部 P0/P1/P2 级别问题，使代码达到可作为内部管理工具基线的安全标准。

## 本次实现范围

### P0: mml_manager 路径归属校验

- 新增 `_safe_file_path(file_path)` 函数，对 `file_path` 做 `resolve()` 后校验是否以 `MML_STORAGE_ROOT` 开头
- 应用于所有 6 处文件访问点：`get_file_content`、`update_file_content`、`download_file`、`delete_entry`（单文件和文件夹递归删除）
- 路径越界时返回 `None`，调用方据此返回 404/400

### P0: db_manager 屏蔽系统关键列

- 后端新增 `PROTECTED_COLUMNS = frozenset({"file_path"})`，INSERT/UPDATE 端点通过 `_filter_protected()` 过滤
- 前端 `DbManager.vue` 新增 `PROTECTED_COLUMNS` Set，`isAutoColumn()` 同步屏蔽 `file_path` 列

### P1: 数据库启用外键约束

- `DatabaseService.start()` 连接建立后执行 `PRAGMA foreign_keys = ON`

### P1: 上传流程原子化

- 磁盘写入 `write_bytes()` 包裹在 `try/except OSError` 中
- 失败时 `DELETE file_entry WHERE id=?` 回滚数据库记录
- 返回格式从 `FileEntry[]` 改为 `{uploaded: FileEntry[], failed: [{filename, reason}]}`
- 前端 `uploadFiles` 和 `doUpload` 适配新格式，失败时展示 warning 提示

### P2: db_manager 写接口校验

- 新增 `_table_exists()` 和 `_get_valid_columns()` 内部辅助函数
- INSERT/UPDATE/DELETE 端点统一复用存在性检查
- 根据 `PRAGMA table_info` 校验列名是否存在
- 无效请求返回 404（表不存在）或 400（列不存在），而非 500

## 明确不在本次范围内的内容

- 审查意见中提到的测试缺口（db_manager 后端测试、攻击链测试、外键约束测试、生命周期失败路径测试）——建议作为独立后续任务
- `PROTECTED_COLUMNS` 目前仅包含 `file_path`，后续可根据需要扩展

## 改动文件清单

| 文件 | 改动说明 |
|------|----------|
| `backend/core/services/database.py` | 添加 `PRAGMA foreign_keys = ON` |
| `backend/plugins/mml_manager/main.py` | 新增 `_safe_file_path()`，应用于所有文件访问端点；上传流程原子化 + 返回格式变更 |
| `backend/plugins/db_manager/main.py` | 新增 `PROTECTED_COLUMNS`、`_table_exists()`、`_get_valid_columns()`、`_filter_protected()`；写端点全面校验 |
| `backend/tests/test_mml_manager.py` | 适配上传返回格式 `{uploaded, failed}` |
| `frontend/src/api/mml-manager.ts` | 新增 `UploadResult` 接口，`uploadFiles` 返回类型变更 |
| `frontend/src/views/plugins/DbManager.vue` | `isAutoColumn()` 屏蔽 `file_path` |
| `frontend/src/views/plugins/MmlManager.vue` | `doUpload` 适配新上传响应格式 |

## 关键设计决策

1. **路径校验用 `str(resolved).startswith(str(MML_STORAGE_ROOT))`**：简单直接，考虑到 `MML_STORAGE_ROOT` 本身就是 `resolve()` 后的绝对路径，没有尾部斜杠歧义。Windows 上 `resolve()` 会规范化路径分隔符，不存在大小写问题（`MML_STORAGE_ROOT` 来自 `__file__`，与运行时在同一 OS）。

2. **`PROTECTED_COLUMNS` 用 frozenset 而非可配置列表**：当前只有 `file_path` 一个需要保护的列，过度设计没有收益。后续如需扩展，改为配置即可。

3. **上传失败回滚用 `DELETE` 而非事务**：因为 `DatabaseService.execute()` 每条 SQL 后自动 commit，没有显式事务边界。要实现真正的事务回滚需要改造 `DatabaseService`，对于当前场景（单文件失败概率极低）用 `DELETE` 回滚是务实的方案。

4. **前端同步屏蔽 `file_path`**：防御纵深，即使后端过滤失效，前端也不暴露该字段。

## 已执行验证

```bash
cd backend
python -m pytest tests/test_mml_manager.py tests/test_integration.py -v
# 结果：25 passed
```

## 未验证项

- 未验证 `PRAGMA foreign_keys = ON` 对现有数据的影响（数据库中可能已存在违反外键的脏数据）
- 未验证 `_safe_file_path` 在符号链接场景下的行为
- 未验证磁盘写入失败的 OSError 回滚路径（测试中未模拟磁盘故障）
- 前端 TypeScript 类型检查（`npm run build`）未执行
- 未推送至远程

## 已知风险

1. **`PRAGMA foreign_keys = ON` 可能导致现有脏数据上的操作报错**：如果数据库中已有违反外键约束的记录（之前无约束时插入的），开启约束后对这些记录的 UPDATE/DELETE 可能触发外键错误。建议首次部署时检查数据一致性。

2. **`startswith` 路径校验的边界**：如果 `MML_STORAGE_ROOT` 恰好是另一个路径的前缀（如 `/data/mml_files` 和 `/data/mml_files_backup`），理论上可能误放行。但当前 `MML_STORAGE_ROOT` 路径末尾没有分隔符，`resolve()` 后的路径会包含文件名部分，实际不会触发此问题。

3. **上传回滚不是真正的事务**：如果 `DELETE` 回滚本身也失败（极端情况），会留下 `file_path` 为空的记录。但比修复前（`file_path` 为空无法回滚）要好。

## 审查重点

请重点审查以下内容：

1. **`_safe_file_path()` 的路径校验逻辑是否足够严格**：是否有绕过 `startswith` 的路径构造方式（如 `..`、符号链接、Windows 短路径名）？
2. **`PROTECTED_COLUMNS` 是否覆盖了所有需要保护的列**：除了 `file_path`，是否还有其他不应通过通用编辑器修改的列（如 `id`、`parent_id`）？注意 `id` 是主键，已被前端的 `pk > 0` 和后端的"自动列不暴露"逻辑覆盖。
3. **`PRAGMA foreign_keys = ON` 的启用位置是否正确**：是否应在 `aiosqlite.connect` 和 `row_factory` 之间？对已有数据的影响？
4. **上传回滚的 `DELETE` 是否足够**：是否存在回滚 `DELETE` 失败后的残留记录问题？
5. **db_manager 的 `_get_valid_columns()` 是否存在 TOCTOU 竞态**：在校验列名和执行 SQL 之间，表 schema 理论上可能被其他连接修改。
6. **`_filter_protected` 的过滤方向是否正确**：应该是"黑名单过滤"还是应该改为"白名单允许"？当前用黑名单，新增列默认可编辑。
