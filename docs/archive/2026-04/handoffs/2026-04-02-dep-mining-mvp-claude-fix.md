# Fix Report — dep-mining-mvp-001 P1 Issues

> 日期：2026-04-02
> 关联审查：`docs/analysis/2026-04-02-dep-mining-mvp-codex-review.md`
> 提交：`fdea494`

## 修复清单

### P1-1: 解析器误删引号内 `/* ... */`

- **根因**：`parser.py:44` 使用全局 `re.sub(r"/\*.*?\*/", "", text)` 剥离块注释，不区分引号内外。
- **修复**：新增 `_strip_block_comments()` 静态方法，逐字符扫描并跟踪引号状态，仅在非引号上下文中移除块注释。
- **文件**：`backend/core/services/parser.py`
- **回归测试**：
  - `test_block_comment_inside_double_quotes_preserved` — 双引号内 `/* */` 保留
  - `test_block_comment_inside_single_quotes_preserved` — 单引号内 `/* */` 保留
  - `test_block_comment_mixed_with_quoted_values` — 真实注释移除 + 引号内保留共存

### P1-2: 重新生成候选覆盖人工终态

- **根因**：`main.py:733` 唯一键冲突时直接 `UPDATE ... SET status=?`，无条件覆盖。
- **修复**：改为 `SET status = CASE WHEN status IN ('accepted', 'rejected') THEN status ELSE ? END`，保留人工终态。
- **文件**：`backend/plugins/mml_manager/main.py`
- **回归测试**：
  - `test_regenerate_preserves_accepted_status` — Generate → Accept → Regenerate 状态保持
  - `test_regenerate_preserves_rejected_status` — Generate → Reject → Regenerate 状态保持

### P1-3: 前端"提取 & 生成"按钮未执行提取

- **根因**：`handleGenerate()` 只调用 `apiGenerate()`，无 extract 步骤。
- **修复**：
  - 后端新增 `POST /versions/{ne_version_id}/batch-extract` 端点，自动提取该版本所有脚本文件。
  - 前端 `handleGenerate()` 改为先调 `apiBatchExtract` 再调 `apiGenerate`。
- **文件**：
  - `backend/plugins/mml_manager/main.py` — 新增端点
  - `frontend/src/api/dependency-mining.ts` — 新增 `batchExtractCommands`
  - `frontend/src/views/plugins/DependencyMining.vue` — import + 流程修改
- **回归测试**：
  - `test_batch_extract_commands` — 批量提取后直接生成，无需逐文件调用

## 验证结果

- `python -m pytest tests/test_parser.py tests/test_parser_enhanced.py` — 31/31 PASS
- `python -m pytest tests/test_dependency_mining.py` — 14/14 PASS
- `python -m pytest tests/test_mml_manager.py` — 26/26 PASS（零回归）
- **总计 70/70 PASS**
- `npm run build` — 前端构建成功，无 TS 错误

## 未修复项

无。本轮修复覆盖了 Codex 审查中全部 3 个 P1 问题。
