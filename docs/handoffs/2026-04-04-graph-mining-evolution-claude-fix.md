# Claude Fix 文档 – graph-mining-evolution-001

## 修复时间
2026-04-04
## 修复人

Claude
（完成 Codex 官查后的修复）

## 修复范围

修复并关闭 `file.content_replaced` 事件处理器中的 `_on_file_content_replaced`：
1. 清理旧贡献，保留 `file_mining_record` 但 `mined=0`, 显示 "changed" 状态
2. 文件 `/files` API: 新增 `changed` 瘾态状态（文件显示 "已变动")
3. `/files` API: 补齐 `GET /jobs` (mining 类型, + `GET /jobs/{job_id}` (job 详情) + 取消) 后端路由
 GET `/jobs/{job_id}/cancel` 取消运行中的任务)
5. 化选文件后批量选择已绑定到 `selectedFiles`， `mining` tab 补齐 `job` 列表/队列 Tab + 自动刷新
6. 文件管理 tab 巻加挖掘队列页， 动态展示 job/文件状态
7. 前端 `checked-row-keys` 绑定修复（`checked-row-keys` 不写回 `selectedFiles`)
8. `fileColumns` 中新增 `changed` 猖态状态:
9. `statusFilterOptions` 新增 `changed` 选项
10. 候选 Tab: "挖掘队列"
 新增 `statusFilterOptions` 新增 "队列" 选项
11. 页面增加"刷新" 按钮加载队列 + 按钮刷新
 + 取消)
12 - Tab change 时加载 queue 数据
8. `onTabChange` 补充 `loadQueue` 加载 `loadCandidates() + `loadEdges():
      break
    case "candidates":
      break
    case "edges":
      break;
  }
}

### 修复文档与设计文档 §11 的差异

修复项
Codex 审查文档和 descriptions:

 "旧库迁移缺失" 等会要求在 `graph_mining` 的 `_create_tables` 中补齐 `ALTER TABLE` 迁移逻辑， `CREATE TABLE IF NOT EXISTS` 的模式，对旧表添加了新列。

迁移失败会静默跳过不影响： - 文件更新后不应标记为已变动而非自动挖掘。
 - 文件更新后清理贡献并标记为已变动，保留记录， → 用户看到"已变动"后手动选择重挖)

 - 队列 Tab: 补齐队列 API + 挖掘队列 Tab 页（文件状态动态展示）
- 修复批量选择绑定问题
- 范例： test `test_09` - 验证清理贡献+标记已变动，而非自动重挖
 `- 测试矩阵更新: 补充测试用例
- 测试数量更新为 10 expected

 10 passed
