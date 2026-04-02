# Codex 审查文档：项目初始全量审查

- 状态：已审查
- 审查日期：2026-04-01
- 审查分支：`master`
- 审查基线：`aed8b92f3546ee7889fafbb00ab8f8b10e105a07`
- 审查对象：当前工作区代码与 `HEAD` 一致的应用实现；工作区另有未跟踪的 `.claude/`、`docs/handoffs/`，不属于本次功能代码审查范围
- 最新提交：`aed8b92` `update workflow`
- 远程分支：`origin/master`
- Push 状态：未执行，当前会话未进行提交与推送

## 1. 审查背景

这是 AGENTS 协作协议建立后的首次基线审查。目标是对 CoreMaster 当前后端、插件、前端契约与测试覆盖做一次全量风险盘点，并形成后续修复优先级。

## 2. 审查范围

- 后端入口与生命周期：`backend/main.py`
- 数据库服务与插件加载：`backend/core/services/database.py`、`backend/core/plugin/loader.py`
- 插件实现：`backend/plugins/mml_manager/main.py`、`backend/plugins/db_manager/main.py`
- 前端 API 与插件页面：`frontend/src/api/*.ts`、`frontend/src/views/plugins/*.vue`
- 现有测试：`backend/tests/*`

## 3. 发现的问题

### P0：`db_manager` + `mml_manager` 组合形成任意文件读写链路

- 证据：
  - `db_manager` 允许编辑任意非自动列，`file_entry.file_path` 不在保护列表内，前端会把它暴露到编辑表单中：`frontend/src/views/plugins/DbManager.vue:125`、`frontend/src/views/plugins/DbManager.vue:136`、`frontend/src/views/plugins/DbManager.vue:238`
  - 后端 `db_manager` 直接将任意字段写回数据库，没有列白名单：`backend/plugins/db_manager/main.py:81`、`backend/plugins/db_manager/main.py:84`、`backend/plugins/db_manager/main.py:86`
  - `mml_manager` 在读内容、写内容、下载时直接信任数据库中的 `file_path`，未校验路径是否仍位于 `MML_STORAGE_ROOT` 下：`backend/plugins/mml_manager/main.py:403`、`backend/plugins/mml_manager/main.py:409`、`backend/plugins/mml_manager/main.py:417`、`backend/plugins/mml_manager/main.py:423`、`backend/plugins/mml_manager/main.py:435`、`backend/plugins/mml_manager/main.py:441`
- 影响：
  - 任何能访问 `db_manager` 的用户都可以把 `file_entry.file_path` 改成任意绝对路径或越界路径。
  - 之后通过 `/files/{id}/content`、`/files/{id}/download`、`PUT /files/{id}/content` 就可以读取或覆盖服务进程可访问的任意文件。
  - 这是一个可直接利用的高危本地文件读写漏洞，不是单纯的数据一致性问题。
- 建议修复：
  - 后端禁止 `db_manager` 对系统关键表和关键列的通用编辑，至少要屏蔽 `file_entry.file_path`、`id`、父子关系列等。
  - `mml_manager` 所有文件访问前统一做 `resolve()` 后的根目录 containment 校验，只允许 `MML_STORAGE_ROOT` 内路径。
  - 更稳妥的做法是根本不把物理路径当作可编辑业务字段暴露给通用表编辑器。

### P1：上传流程不是原子操作，磁盘写失败会留下损坏的 `file_entry`

- 证据：
  - 上传先插入数据库，再写磁盘，再回写 `file_path`：`backend/plugins/mml_manager/main.py:357` 到 `backend/plugins/mml_manager/main.py:383`
  - 读写内容接口假设 `file_path` 一定有效，直接 `Path(rows[0]["file_path"])`：`backend/plugins/mml_manager/main.py:409`、`backend/plugins/mml_manager/main.py:423`、`backend/plugins/mml_manager/main.py:441`
- 影响：
  - 一旦 `write_bytes()`、后续 `UPDATE file_path`、磁盘容量或权限步骤失败，数据库里会残留一条 `type='file'` 但 `file_path` 为空或失真的记录。
  - 后续访问该文件时会触发 500 或不可预期行为，而不是受控的 4xx/5xx 业务错误。
  - 多文件上传时还可能部分成功、部分失败，当前返回结构也没有明确区分失败项。
- 建议修复：
  - 将“建记录 + 落盘 + 回写路径”包成一个事务化流程；失败时回滚数据库记录并清理临时文件。
  - 对 `file_path` 为空、文件缺失、IOError/OSError` 给出受控错误响应。
  - 明确多文件上传的失败语义，至少返回成功项与失败项。

### P1：数据库层未开启外键约束，当前 schema 的引用关系基本不生效

- 证据：
  - `DatabaseService.start()` 仅建立连接，没有执行 `PRAGMA foreign_keys = ON`：`backend/core/services/database.py:12` 到 `backend/core/services/database.py:15`
  - `file_entry` 和 `ne_version` 的 schema 明确声明了外键与 `ON DELETE CASCADE`：`backend/plugins/mml_manager/main.py:36` 到 `backend/plugins/mml_manager/main.py:47`
- 影响：
  - SQLite 默认不启用外键约束，这意味着当前 `REFERENCES` 和 `ON DELETE CASCADE` 在运行时并不可靠。
  - `db_manager` 可以插入无效 `parent_id` / `ne_version_id`，或删除父记录后保留悬挂子记录，破坏目录树和版本关联。
  - 代码里很多“靠 schema 保证一致性”的假设并不成立。
- 建议修复：
  - 数据库连接建立后立即执行 `PRAGMA foreign_keys = ON`。
  - 为关键写路径补充违反外键时的错误处理与测试。
  - 审视 `db_manager` 是否允许直接操作这些业务表；如果保留，需要加保护。

### P2：`db_manager` 的写接口缺少存在性与列名校验，异常会直接冒泡成 500

- 证据：
  - 读接口会先检查表是否存在：`backend/plugins/db_manager/main.py:33` 到 `backend/plugins/db_manager/main.py:48`
  - 写接口没有同样的存在性检查，也没有对 `fields` 的列名做白名单/转义校验：`backend/plugins/db_manager/main.py:57` 到 `backend/plugins/db_manager/main.py:99`
- 影响：
  - 对一个符合正则但不存在的表执行写操作时，会抛出 SQLite 异常并返回 500，而不是与读接口一致的 404。
  - 恶意或错误的列名同样会直接导致未处理异常。
  - 这会让通用表编辑器在用户输入错误时表现为“服务器故障”。
- 建议修复：
  - 写接口复用读接口的存在性检查逻辑。
  - 根据 `PRAGMA table_info` 校验 `fields` 中的列名是否真实存在。
  - 捕获数据库异常，映射成稳定的 4xx/409 响应。

## 4. 尚未证明安全的缺口

- `mml_manager` 没有针对异常 IO、损坏 `file_path`、非法内容编码的测试。
- `db_manager` 没有任何独立后端测试，当前测试集只覆盖 `mml_manager` 和基础服务。
- 生命周期失败路径未验证：`backend/main.py:20` 到 `backend/main.py:59` 中，如果某个插件注册失败，数据库连接是否一定能释放，没有测试证明。

## 5. 测试缺口

- `backend/tests` 中未发现 `db_manager` 的接口测试。
- 未覆盖“编辑 `file_entry.file_path` 后调用文件内容接口”的攻击链路。
- 未覆盖上传过程中磁盘写失败、数据库回写失败、重复文件名冲突等异常分支。
- 未覆盖外键约束相关场景，因此当前测试无法暴露 `PRAGMA foreign_keys` 缺失问题。

## 6. 验证说明

- 代码审查：逐文件检查后端入口、数据库层、两个插件、前端 DB 编辑器与 API 调用。
- 命令验证：
  - `git status --short`
  - `git log --oneline --decorate -n 10`
  - `pytest tests`
  - `pytest tests\\test_integration.py tests\\test_mml_manager.py`
- 结果：
  - `pytest tests\\test_integration.py tests\\test_mml_manager.py` 通过，`25 passed`
  - `pytest tests` 未完全通过，其中 `13 passed, 25 errors`
  - 全量失败主要是环境/文件占用问题：`tmp_path` 无法写入系统临时目录，以及 `backend/data/test_mml.db` 被占用；这说明当前测试环境依赖较脆弱，但不改变上述代码风险判断

## 7. 建议的后续动作

1. 先修复任意文件读写链路：封锁 `file_path` 编辑入口，并为 `mml_manager` 加路径归属校验。
2. 修复上传原子性，确保数据库与磁盘状态一致。
3. 在数据库连接启用外键约束，并补回归测试。
4. 为 `db_manager` 增加后端测试，至少覆盖表不存在、列不存在、关键表保护和错误映射。

## 8. 最终评估

当前版本具备基本功能可用性，但还不能视为安全或稳健的基线版本。最关键的问题不是样式或小缺陷，而是 `db_manager` 与 `mml_manager` 组合后产生的高危文件系统访问能力；在此问题修复前，我不建议把该实现作为可信的内部管理工具基线。
