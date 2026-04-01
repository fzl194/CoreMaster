# Claude 代码修复交付：Codex 安全审查复审反馈

- 任务：根据 `docs/analysis/2026-04-01-security-fixes-codex-review.md` 的审查结论，修复代码并补充测试
- 分支：`master`
- 审查基线：`11af24c`
- 关联 handoff：`docs/handoffs/2026-04-01-security-fixes-claude-handoff.md`
- 关联 review：`docs/analysis/2026-04-01-security-fixes-codex-review.md`

## Codex 审查发现的问题及处置

### P0: `_safe_file_path()` 的 `startswith` 可被同前缀兄弟目录绕过

**处置：已修复**

`_safe_file_path()` 从 `str(resolved).startswith(str(MML_STORAGE_ROOT))` 替换为 `resolved.is_relative_to(MML_STORAGE_ROOT)`。

改动位置：`backend/plugins/mml_manager/main.py` 第 14-27 行

具体变更：
- 使用 `Path.is_relative_to()`（Python 3.9+）做真正的路径祖先校验
- 添加 `try/except (OSError, ValueError)` 防御非法路径输入
- `MML_STORAGE_ROOT` 本身已在模块级做了 `resolve()`，无需重复处理

### 测试缺口：缺少路径逃逸负向测试

**处置：已补充**

新增 4 个单元测试（`backend/tests/test_mml_manager.py` test_23-test_26）：

| 测试 | 验证内容 |
|------|----------|
| `test_23_safe_path_rejects_sibling_prefix` | 同前缀兄弟目录（如 `mml_files_backup`）被拒绝 |
| `test_24_safe_path_accepts_valid` | 合法根目录内路径被接受 |
| `test_25_safe_path_rejects_none` | None/空路径返回 None |
| `test_26_safe_path_rejects_traversal` | `../../etc/passwd` 路径穿越被拒绝 |

### 测试缺口：缺少 db_manager 后端测试

**处置：已补充**

新增 `backend/tests/test_db_manager.py`（14 个测试）：

| 测试范围 | 测试用例 |
|----------|----------|
| 表不存在 404 | schema/rows/insert/update/delete 对不存在表均返回 404 |
| 非法表名 400 | 注入式表名返回 400 |
| 列名校验 400 | 不存在的列名返回 400 |
| 受保护列过滤 | `file_path` 字段被 `_filter_protected` 移除，不产生异常 |
| 正常 CRUD | insert/update/delete 正常工作 |
| 空字段 400 | 空 fields 返回 400 |

### 前端构建未验证

**处置：已验证**

```bash
cd frontend && npm run build
# vue-tsc + vite build 成功
```

## 改动文件清单

| 文件 | 改动说明 |
|------|----------|
| `backend/plugins/mml_manager/main.py` | `_safe_file_path()` 从 `startswith` 改为 `is_relative_to()` |
| `backend/tests/test_mml_manager.py` | 新增 4 个路径逃逸测试 + 导入 `_safe_file_path` |
| `backend/tests/test_db_manager.py` | 新增 14 个 db_manager 后端测试 |
| `CLAUDE.md` | 新增"Claude 不得修改 Codex 职责文档"准则 |

## 验证结果

```bash
cd backend && python -m pytest tests/ -v
# 56 passed

cd frontend && npm run build
# vue-tsc + vite build 成功
```

## 残余风险（未在本轮处置）

以下来自 Codex 审查第 7 节，本轮未处置：

- Windows 链接点/短文件名等平台相关路径边界未验证
- 数据库中已存在的历史脏数据未做一致性核查，启用外键后可能触发异常
- 磁盘写入成功但后续数据库更新失败的异常路径未验证
- `_get_valid_columns()` 的 TOCTOU 竞态未处理（SQLite 单写者模型下实际风险极低）

## 待 Codex 动作

1. 审查本交付文档中的代码修改
2. 回写 `docs/handoffs/2026-04-01-security-fixes-claude-handoff.md` 的状态
3. 如认为本轮处置闭环，更新 `docs/analysis/2026-04-01-security-fixes-codex-review.md` 的最终评估

## Codex Review 回写

- Review 文档：`docs/analysis/2026-04-01-security-fixes-round2-codex-review.md`
- Review 状态：已审查
- 审查版本：`29b12d6`
