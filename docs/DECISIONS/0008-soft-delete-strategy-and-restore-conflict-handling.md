# ADR-0008 — soft-delete 策略与 restore 冲突处理

> **日期**：2026-06-21
> **状态**：Accepted
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/05-soft-delete.md` `docs/SPEC/05-06-soft-delete-search-v1.5.md`

---

## 背景

v1.5 需要从物理删除迁移到默认软删除（可恢复），同时提供物理删除出口（`--physical`）和批量清理（`purge`）。三个关键技术决策需要明确：
1. 软删除状态存储：`deleted_at` 字段放在 `notes` 表还是独立 `deleted_notes` 表？
2. restore 后 FTS5 同步策略：restore UPDATE 触发 `notes_au`（DELETE+INSERT），够用吗？
3. restore 冲突处理：自动 merge / 静默覆盖 / 交互式选择，哪个是正确边界？

---

## 决策

**采用 `deleted_at` 单字段方案 + `notes_au` trigger 自动 FTS5 同步 + 交互式冲突选择界面**。

具体：
- `notes` 表加 `deleted_at TEXT DEFAULT NULL` 字段（`IS NULL` = 活跃，`IS NOT NULL` = 已删除）
- restore 时 `UPDATE notes SET deleted_at = NULL` → `notes_au` trigger 自动 DELETE+INSERT 到 notes_fts（FTS5 同步）
- 冲突时显示两个版本的 metadata，让用户选择 "overwrite" 或 "keep"（不做自动 merge）

---

## 考虑的替代方案

### 方案 A：`deleted_at` 单字段方案（采纳）

- ✅ 简单：单一表，无需 JOIN 或额外表
- ✅ 索引支持好：`WHERE deleted_at IS NULL` 走 `idx_notes_deleted_at` 索引
- ✅ restore 简单：`UPDATE notes SET deleted_at = NULL` 即可
- ✅ 现有 lazy migration 代码（`count_notes()`）已覆盖此字段
- ❌ 已删除笔记占用主表空间（但 purge 提供清理出口）

### 方案 B：独立 `deleted_notes` 表

- ✅ 主表始终轻盈（只有活跃笔记）
- ❌ restore 需要 `DELETE FROM deleted_notes + INSERT INTO notes`（两条 SQL）
- ❌ 跨表一致性更难保证（无 transaction 保护下可能丢数据）
- ❌ 辩论中 Tech Reviewer 指出：独立表增加了 trigger 复杂度

### 方案 C：软删除标记位（布尔 `is_deleted`）

- ❌ `is_deleted` 不保留删除时间（无法做"最近 30 天删除"等查询）
- ❌ `deleted_at` UTC 时间戳是审计标准做法
- ❌ 迁移成本更高（无历史时间信息）

**拒绝方案 B、C 的理由**：单字段方案最简单，索引支持好，与现有 lazy migration 基础设施兼容，且 purge 提供了清理出口。

---

## 考虑的替代方案（restore FTS5 同步）

### 方案 A：`notes_au` trigger 自动同步（DELETE + INSERT）（采纳）

- ✅ 无需额外代码：现有 `notes_au` trigger 覆盖 restore 场景
- ✅ restore 时 `UPDATE notes SET deleted_at = NULL` → trigger 感知 OLD ≠ NEW → 触发 DELETE + INSERT
- ✅ 与 add/update 共享同一 trigger，维护成本低
- ❌ 窗口期：trigger 执行期间毫秒级，FTS5 可能短暂不一致（可接受）

### 方案 B：restore 时手动 DELETE + INSERT 到 notes_fts

- ✅ 更显式：代码清晰可见同步逻辑
- ❌ 重复代码：add/update/restore 都要写类似逻辑
- ❌ 需要维护两处同步逻辑，bug 风险加倍

### 方案 C：restore 时只 UPDATE notes_fts（不 DELETE）

- ✅ 更轻量
- ❌ 如果笔记内容在软删除期间被修改（不太可能，但理论上），旧 FTS5 内容会残留
- ❌ 不符合"以 notes 表为唯一真实来源"原则

**拒绝方案 B、C 的理由**：`notes_au` trigger 是已验证的基础设施，restore 场景恰好触发其逻辑，无需额外代码。

---

## 考虑的替代方案（restore 冲突处理）

### 方案 A：交互式选择（overwrite / keep）（采纳）

- ✅ 用户掌控：数据安全由用户决定
- ✅ 可见差异：显示两个版本的标题和修改时间，决策信息充分
- ✅ 符合 PM spec 的明确要求

### 方案 B：自动 merge（diff3 风格）

- ❌ 实现复杂度高：需要文本 diff 算法
- ❌ 语义歧义：merge 结果可能不是用户期望的
- ❌ 辩论中 Quality Gatekeeper 指出：merge 失败率在真实场景下很高

### 方案 C：静默覆盖（不询问，直接覆盖现有笔记）

- ❌ 数据丢失风险：用户不知道已存在的笔记被覆盖
- ❌ 与 soft-delete 的"数据安全网"理念矛盾

### 方案 D：静默保留（不恢复，返回错误）

- ❌ 用户需要自己处理冲突，体验差
- ❌ 误删恢复场景下，冲突是常态（用户整理习惯导致重名）

**拒绝方案 B/C/D 的理由**：交互式选择是 spec 明确要求，且是用户控制权和实现复杂度的最佳平衡点。

---

## 决定

**采纳方案 A（单字段 + `notes_au` trigger + 交互式冲突选择）**。

理由：
1. 单字段方案与现有 lazy migration 基础设施无缝衔接，开发成本最低
2. `notes_au` trigger 是已验证代码，无需额外维护
3. 交互式冲突选择明确符合 PM spec，且是用户控制权和实现复杂度的最佳平衡

## 后果

### 正面

- ✅ 架构简单：单一 `deleted_at` 字段，无需额外表或视图
- ✅ FTS5 同步零额外代码：复用 `notes_au` trigger
- ✅ 冲突处理用户体验明确：用户选择，无歧义
- ✅ purge 提供清理出口：主表不会无限膨胀

### 负面

- ❌ 已删除笔记占用主表空间（缓解：purge 清理出口）
- ❌ restore 冲突时需要用户交互（CLI 自动化场景不友好，但符合 spec）
- ❌ `delete` 行为变更（从物理删除到软删除）是 breaking change，需在 CHANGELOG 明确说明

---

## 可逆性

**中度可逆**：若未来发现 `deleted_at` 方案有性能问题，可以迁移到独立 `deleted_notes` 表（需要一次性数据迁移脚本）。trigger 策略和冲突处理策略可随时调整（CLI 行为变更），无需 DB 迁移。

---

*Architect Agent — v1.5 spec 阶段决策记录*
