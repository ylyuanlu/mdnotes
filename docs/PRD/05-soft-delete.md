# soft-delete 完整实现 - 产品需求文档

> **Task ID:** t_20260621_v150_032907
> **适用版本**: v1.5+
> **模块编号:** 05
> **作者:** PM Agent
> **创建时间:** 2026-06-21T09:08:27+08:00
> **辩论轮次:** 3 轮（product-champion / tech-reviewer / devil-advocate / quality-gatekeeper）
> **PRD 状态:** spec-ready

---

## 1. 任务一句话

实现 mdnotes v1.5 soft-delete 完整功能：`delete` 默认软删除（可恢复），`delete --physical` 物理删除，`list`/`count`/`search` 过滤已删除笔记，`restore` 恢复误删笔记，`purge` 批量彻底清理——让 mdnotes 用户拥有数据安全网，无需担心误删。

---

## 2. 用户故事

### US-1：误删可后悔
> 作为 mdnotes 用户，我在使用 `delete` 命令时不必担心误删，因为我可以随时用 `restore` 恢复——这样我既拥有数据安全感，又不必承担性能代价。

**验收标准：**
- `mdnotes delete <id>` 执行后，笔记从 `list` 输出消失，但数据仍在数据库
- `mdnotes restore <id>` 执行后，笔记重新出现在 `list` 中，内容完整
- exit code 0（成功）或 1（失败）

### US-2：物理删除保留路径
> 作为高级用户，我知道 `delete --physical` 可以彻底删除笔记（不经过回收站）——当我确定某条笔记不需要时，可以用物理删除跳过软删除阶段。

**验收标准：**
- `mdnotes delete --physical <id>` 立即从数据库物理删除（`DELETE FROM notes WHERE id=?`）
- `restore` 无法恢复已物理删除的笔记
- exit code 0（成功）或 1（笔记不存在或已软删除）

### US-3：数据库轻盈
> 作为定期整理笔记的用户，我用 `purge` 清理已删除笔记（deleted_at IS NOT NULL），保持数据库轻盈——这样我既有安全网（软删除），又有清理出口（purge）。

**验收标准：**
- `mdnotes purge --confirm` 物理删除所有 deleted_at IS NOT NULL 的笔记
- `mdnotes purge --dry-run` 只报告数量，不实际删除
- `mdnotes purge`（无 --confirm）报错："purge requires --confirm flag"
- purge 分批执行（每批 500 条），避免长时间锁表

### US-4：restore 冲突处理
> 作为有整理习惯的用户，我的笔记经常有重名。当我 restore 一条误删笔记时，如果已存在同名笔记，系统让我选择"用删除版本覆盖"还是"保留现有版本"——数据安全由我决定。

**验收标准：**
- restore 时检测 note_id 是否冲突
- 若冲突：输出差异（两个版本的 metadata：标题、修改时间），让用户选择覆盖或保留
- 若无冲突：直接 restore，`deleted_at` 恢复为 NULL

---

## 3. 业务流程

```
用户输入: mdnotes delete <id>
    │
    ▼
[1] CLI 参数解析
    - 无 --physical → soft-delete（默认）
    - 有 --physical → physical-delete
    │
    ▼
[2] 软删除（默认）
    UPDATE notes SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL
    │
    ▼
[3] 物理删除（--physical）
    DELETE FROM notes WHERE id = ?
    │
    ▼
[4] FTS5 同步
    - 软删除：notes_au trigger（UPDATE）标记 deleted_at，FTS5 记录保留（search 入口过滤）
    - 物理删除：notes_ad trigger（DELETE）自动清理 notes_fts
    │
    ▼
[5] Exit Code
    - 0：成功
    - 1：笔记不存在 / 已删除（幂等）
```

```
用户输入: mdnotes restore <id>
    │
    ▼
[1] 检测冲突
    - 查 notes WHERE id = ? AND deleted_at IS NOT NULL
    - 查 notes WHERE id = ? AND deleted_at IS NULL（同名冲突）
    │
    ▼
[2a] 无冲突：直接 restore
    UPDATE notes SET deleted_at = NULL WHERE id = ?
    → notes_au trigger 自动同步 FTS5
    │
    ▼
[2b] 有冲突：显示差异界面
    显示两个版本的 metadata（标题、修改时间）
    用户选择 "overwrite" 或 "keep"
    │
    ▼
[3] Exit Code
    - 0：成功
    - 1：笔记不存在 / 未软删除
```

```
用户输入: mdnotes purge --confirm
    │
    ▼
[1] 检查 --confirm flag
    - 无 flag → exit 1，报错 "purge requires --confirm flag"
    │
    ▼
[2] --dry-run 模式
    - SELECT COUNT(*) WHERE deleted_at IS NOT NULL
    - 输出数量，exit 0，不实际删除
    │
    ▼
[3] 分批物理删除（每批 500 条）
    BEGIN TRANSACTION;
    DELETE FROM notes WHERE id IN (SELECT id WHERE deleted_at IS NOT NULL LIMIT 500);
    COMMIT;
    → notes_ad trigger 自动清理 notes_fts
    │
    ▼
[4] Exit Code
    - 0：成功
    - 1：没有已删除笔记 / 参数错误
```

---

## 4. 业务价值 / ROI

### 解决的问题
- 用户误删笔记后无法恢复（当前 delete 是物理删除）
- 数据库膨胀：用户不敢删除，只能任由已删除笔记占用空间
- 协作场景误操作：帮别人删笔记导致数据永久丢失

### 预期收益
| 维度 | 现状 | soft-delete 后 |
|------|------|----------------|
| 误删恢复 | 0（不可恢复）| restore 命令即时恢复 |
| 清理策略 | 不敢删（怕丢）| purge 可选清理（确认后执行）|
| 用户信心 | "删了=没了" | "删了=暂存，可以后悔" |
| DB 膨胀 | 线性增长 | 可控（purge 清理出口）|

### ROI 估算
- **开发成本：** 6-10 小时（storage 层 3 个 SQL + CLI 3 个命令 + FTS5 trigger 审计 + 测试）
- **用户收益：** 每个用户都有误删场景，数据安全感难以量化但真实存在
- **ROI 节点：** 用户第一次成功 restore 误删笔记即回本

### 优先级
**P0（v1.5 必须）**：soft-delete + restore + purge 全链路

---

## 5. 范围边界

### 包含
- `delete` 默认软删除（UPDATE deleted_at）
- `delete --physical` 物理删除
- `list` / `count` / `search` 过滤已删除（WHERE deleted_at IS NULL）
- `restore <id>` 恢复软删除笔记
- `purge --confirm` 批量物理删除
- `purge --dry-run` 预览影响数量
- FTS5 同步（软删除笔记在 search 结果中过滤）

### 不包含
- 多用户权限体系（v2.0）
- `restore --all` 批量恢复（v1.6）
- 软删除笔记的"回收站"列表命令（v1.6）
- GDPR 数据导出（v1.7+）
- 非 UUID 的字符串 ID 路由（当前实现已经是 UUID）

---

## 6. 验收标准

### 功能验收
- [ ] `mdnotes delete <id>` 后，`list` 不显示该笔记，但数据库中 `deleted_at` 有值
- [ ] `mdnotes delete <id>` 对已软删除笔记幂等（不报错，exit 0）
- [ ] `mdnotes delete <id>` 对不存在笔记报错（exit 1）
- [ ] `mdnotes delete --physical <id>` 物理删除，`restore` 无法恢复
- [ ] `mdnotes delete --physical <id>` 对不存在笔记报错（exit 1）
- [ ] `mdnotes restore <id>` 后笔记重新出现在 `list`，`deleted_at` 为 NULL
- [ ] `mdnotes restore <id>` 对不存在或未软删除笔记报错（exit 1）
- [ ] restore 冲突时显示差异界面，用户可选择覆盖或保留
- [ ] `mdnotes purge --dry-run` 输出数量，exit 0，不实际删除
- [ ] `mdnotes purge`（无 --confirm）报错 "purge requires --confirm flag"，exit 1
- [ ] `mdnotes purge --confirm` 分批物理删除已删除笔记
- [ ] `mdnotes purge --confirm` 执行后，所有 `deleted_at IS NOT NULL` 笔记被删除
- [ ] `mdnotes list` 不显示已删除笔记（deleted_at IS NULL）
- [ ] `mdnotes count` 只统计活跃笔记（deleted_at IS NULL）
- [ ] `mdnotes search` 不返回已删除笔记的 snippet

### 技术验收
- [ ] deleted_at 有索引（`CREATE INDEX IF NOT EXISTS idx_notes_deleted_at ON notes(deleted_at)`）
- [ ] purge 分批执行（batch_size=500，批次间 sleep(10ms)）
- [ ] 乐观锁机制：并发 delete+restore 无死锁
- [ ] WAL 模式：并发读写不阻塞
- [ ] FTS5 一致性：add/delete/restore 后 search 结果正确
- [ ] `notes_au` trigger（AFTER UPDATE）正确处理 restore 场景（deleted_at 从非 NULL 变 NULL）
- [ ] Python 3.10/3.11/3.12 三个版本 GHA CI 均通过

### 质量验收
- [ ] `mdnotes delete --help` 说明软删除行为
- [ ] `mdnotes delete --physical --help` 说明物理删除行为
- [ ] `mdnotes restore --help` 说明恢复行为和冲突处理
- [ ] `mdnotes purge --help` 说明 --confirm 和 --dry-run 参数
- [ ] CLI 参数格式统一（`--flag` 风格）
- [ ] 覆盖率：单元 ≥ 90%，整体 ≥ 86%，新增代码 ≥ 90%
- [ ] 覆盖率环比不下降 > 1%（BC-13）

### 风险指标（触发阻断合并）
- [ ] CI 任意一个 Python 版本失败 → 阻断合并
- [ ] 覆盖率跌破 86% → 阻断合并
- [ ] delete 后 list 仍显示该笔记 → 阻断合并
- [ ] restore 后 FTS5 不可搜 → 阻断合并
- [ ] purge 后 deleted_notes 残留率 > 0 → CI 告警（非阻断）
- [ ] 并发 delete+restore 产生死锁 → 阻断合并
- [ ] P99 > 500ms → 性能告警（非阻断）

---

## 7. 关键约束（辩论共识）

以下约束来自 3 轮辩论收敛共识：

### 约束 1：软删除是默认行为
- `delete` 默认软删除（UPDATE deleted_at），`delete --physical` 才是物理删除
- 这是行为变更，需要在 CHANGELOG 和 `--help` 中明确说明

### 约束 2：FTS5 搜索入口过滤
- search 结果必须 `WHERE deleted_at IS NULL`（应用层过滤，不是 FTS5 层面）
- restore 后 FTS5 trigger 自动同步（`notes_au` → DELETE + INSERT 到 notes_fts），窗口期毫秒级

### 约束 3：purge 必须有 --confirm
- `purge` 无 --confirm flag 时报错，不可执行
- purge 必须支持 --dry-run 预览

### 约束 4：deleted_at 统一 UTC 存储
- 数据库存储 UTC（ISO 8601），CLI 显示时转换本地时区
- 多时区环境下时间比较无歧义

### 约束 5：restore 冲突处理
- 冲突时显示差异（metadata：标题、修改时间），用户选择覆盖或保留
- 不做自动 merge，不做静默覆盖

---

## 8. 风险提示

### 风险 1：并发 delete+restore（已解决）
- **描述：** 两个 session 同时对同一笔记执行 delete 和 restore
- **缓解：** WAL 模式 + 乐观锁（version counter）+ 幂等性设计
- **剩余风险：** 最后执行的操作覆盖先执行的（由用户决定，不阻塞）

### 风险 2：FTS5 索引不一致（已解决）
- **描述：** restore 后 FTS5 记录未同步
- **缓解：** `notes_au` trigger 验证 + 集成测试覆盖
- **触发条件：** SQLite 版本 < 3.26 时 content= 关联行为不稳定

### 风险 3：purge 误触发（已解决）
- **描述：** 用户误执行 purge --confirm 导致数据永久丢失
- **缓解：** --confirm flag 强制；--dry-run 预览；分批执行可中断
- **剩余风险：** 确认后数据不可恢复（设计如此）

### 风险 4：deleted_at 时区问题（已解决）
- **描述：** UTC 存储 + 本地显示转换，多进程/多机器时间比较
- **缓解：** 统一 UTC 存储，ISO 8601 格式，CLI 显示时转换本地时区
- **剩余风险：** 极低（标准做法）

### 风险 5：GDPR 合规（已知局限）
- **描述：** purge 后 DB 物理文件碎片可能残留已删除数据
- **缓解：** purge 后执行 VACUUM（可选，作为 v1.6 增强）
- **升级条件：** v1.7 考虑数据导出功能

---

*PM 辩论收敛完成。SPEC 由 Architect 依据本 PRD 自主撰写。*
