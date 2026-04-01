# Codex 审查结论：安全审计修复复审

- 状态：已审查
- 审查分支：`master`
- 审查基线：`aed8b92`
- 审查对象：提交 `4b62c51` 及其后续 handoff 文档提交 `11af24c`
- 审查范围：`backend/core/services/database.py`、`backend/plugins/mml_manager/main.py`、`backend/plugins/db_manager/main.py`、`backend/tests/test_mml_manager.py`、`frontend/src/api/mml-manager.ts`、`frontend/src/views/plugins/DbManager.vue`、`frontend/src/views/plugins/MmlManager.vue`
- 工作区说明：存在未纳入本次审查范围的脏工作区改动/未跟踪文件（如 `.claude/`、`docs/analysis/` 目录状态）；以下结论仅针对上述 diff

## 1. 背景

本次复审针对 `docs/analysis/2026-04-01-initial-project-review-codex-review.md` 中提出的 P0-P2 问题修复。Claude 的 handoff 指定以 `aed8b92..4b62c51` 为主要审查范围，重点检查：

- `mml_manager` 路径归属校验
- `db_manager` 受保护列与写接口校验
- SQLite 外键约束启用位置
- 上传失败回滚

## 2. 审查范围

- Git 状态：`git status --short`
- 提交与 diff：`git log --oneline --decorate -n 10`、`git show --stat --summary 4b62c51`、`git diff aed8b92..4b62c51 -- <paths>`
- 代码检查：逐文件核对上述 7 个改动文件
- 验证命令：`python -m pytest backend/tests/test_mml_manager.py backend/tests/test_integration.py -q`

## 3. 发现的问题

### P0：`_safe_file_path()` 的前缀判断仍可被同前缀兄弟目录绕过

- 位置：[backend/plugins/mml_manager/main.py](/D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L14) [backend/plugins/mml_manager/main.py](/D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L19) [backend/plugins/mml_manager/main.py](/D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L424) [backend/plugins/mml_manager/main.py](/D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L438) [backend/plugins/mml_manager/main.py](/D:/mywork/CoreMaster/backend/plugins/mml_manager/main.py#L458)
- 问题：当前实现使用 `str(resolved).startswith(str(MML_STORAGE_ROOT))` 判断路径是否位于存储根目录下。这不是目录归属校验，只是字符串前缀比较。
- 影响：如果攻击者能把 `file_path` 写成与根目录同前缀的兄弟路径，例如 `<root>_backup\secret.txt`，该判断会误判为合法，`get_file_content`、`update_file_content`、`download_file`、`delete_entry` 仍可能读写或删除根目录之外的文件。也就是说，本轮要修复的路径逃逸主问题仍未真正关闭。
- 复现思路：当 `MML_STORAGE_ROOT` 为 `...\data\mml_files` 时，`...\data\mml_files_backup\secret.txt` 会通过 `startswith` 检查，但它并不在 `mml_files` 目录树内。
- 建议修复：改为真正的路径包含关系校验，例如先对 `MML_STORAGE_ROOT` 做一次 `resolve()`，再使用 `resolved.relative_to(root)` 或 `resolved.is_relative_to(root)`（Python 3.9+）判断；同时补一条针对“同前缀兄弟目录”的回归测试。

## 4. 测试缺口

- 缺少 `_safe_file_path()` 负向测试，尤其是“同前缀兄弟目录”“符号链接/链接点”“非法 `file_path` 被读取/下载/覆盖”的用例。
- 本轮后端测试通过，但没有覆盖 `db_manager` 的新增校验逻辑，仍缺少：
  - 受保护列不可写测试
  - 非法列名返回 400 测试
  - 表不存在返回 404 测试
  - `PRAGMA foreign_keys = ON` 的行为验证
- 前端未执行构建或类型检查，`UploadResult` 变更仅靠静态阅读确认，没有 `npm run build` 级别验证。

## 5. 回归风险

- `backend/core/services/database.py` 中启用 `PRAGMA foreign_keys = ON` 的位置本身没有问题，[database.py](/D:/mywork/CoreMaster/backend/core/services/database.py#L12) 到 [database.py](/D:/mywork/CoreMaster/backend/core/services/database.py#L16) 的连接初始化顺序可接受；但如果现有库里已有脏数据，后续更新/删除可能报外键错误，首次部署仍有数据一致性风险。
- `db_manager` 的列名校验和 `file_path` 保护方向正确，当前未发现本轮新引入的功能回归；但它仍采用黑名单策略，新加列默认可编辑，这属于后续治理风险，不是这轮 diff 的阻断问题。
- 上传返回结构从数组变为 `{uploaded, failed}` 后，当前已同步调整 API 类型和主界面调用，现有 diff 中未看到遗漏消费者。

## 6. 建议修复项

1. 先修复 `mml_manager` 的目录归属判断，替换 `startswith` 为真正的路径祖先校验。
2. 增加针对路径逃逸的回归测试，至少覆盖：
   - 根目录外但字符串同前缀的路径
   - 合法根目录内路径
   - `None` / 空路径
3. 为 `db_manager` 的 INSERT/UPDATE/DELETE 新增后端测试，避免当前仅靠人工阅读保证安全语义。
4. 在修复完成后补跑一次前端构建或类型检查，确认上传返回结构变更没有遗漏。

## 7. 无法确认的残余风险

- 未模拟 Windows 链接点/短文件名等平台相关路径边界。
- 未对数据库中已存在的历史脏数据做一致性核查，无法确认启用外键后线上数据是否会触发异常。
- 未验证磁盘写入成功但后续数据库更新失败的异常路径，上传流程仍不具备严格事务性。

## 8. 验证说明

- 已执行：`python -m pytest backend/tests/test_mml_manager.py backend/tests/test_integration.py -q`
- 结果：`25 passed`
- 未执行：前端构建、`db_manager` 新增接口专项测试、路径逃逸专项测试

## 9. 最终评估

本轮修复覆盖了多数上轮审查意见，`db_manager` 校验、上传返回结构调整、外键启用位置都朝正确方向推进，且现有后端测试通过。

但 `mml_manager` 最核心的路径校验仍然使用字符串前缀判断，存在明确绕过路径，因此本轮结论不能视为“安全问题已闭环”。建议状态按 `部分处置` 管理，在修复上述 P0 问题并补充对应回归测试后再结束本轮处置。
