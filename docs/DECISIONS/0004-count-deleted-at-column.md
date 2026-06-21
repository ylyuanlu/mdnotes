# ADR-0004 — count 命令的 deleted_at 列策略

> **日期**：2026-06-19
> **状态**：Accepted
> **适用版本**：v1.5+
> **决策者**：Architect Agent
> **相关文档**：`docs/PRD/02-count-command.md` / `docs/SPEC/02-count-command.md`

## 背景

PRD 验收标准 T-1 要求 `SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL`，但现有 `CREATE_TABLE_SQL` 不含 `deleted_at` 列（该列为 v0.2 软删除预留）。count 命令需要在 v0.1 实现，而 `WHERE deleted_at IS NULL` 在无该列时会触发 SQLite 语法错误。

需要在两条路径中做出选择：
1. **count 命令先不用 `deleted_at IS NULL`**，等 v0.2 加列后再改
2. **现在就加 `deleted_at` 列**，通过 `ALTER TABLE` 增量添加，不改 `CREATE_TABLE_SQL`

## 决策

**采纳方案 B：现在加 `deleted_at` 列（通过 `ALTER TABLE` 增量迁移）**。

## 考虑的替代方案

### 方案 A：count 暂不使用 deleted_at（等 v0.2）

- ❌ v0.1 count = 全量笔记，与 PRD 语义不符（PRD 要求活跃笔记 = `deleted_at IS NULL`）
- ❌ v0.2 加列后需改 count SQL，导致回退测试
- ❌ 如果 v0.2 `delete` 命令用 `deleted_at` 标记软删除，v0.1 count 结果在 v0.2 语义下会不准确（包含已删除笔记）

### 方案 B：ALTER TABLE 增量添加 deleted_at 列（采纳）

- ✅ SQL 语义与 PRD T-1 完全一致（`WHERE deleted_at IS NULL`）
- ✅ 向后兼容：`ALTER TABLE ... ADD COLUMN` 对已有记录会填充 NULL
- ✅ 不修改 `CREATE_TABLE_SQL`：现有 `add_note`/`list_notes` 行为不受影响
- ✅ v0.2 soft-delete 直接复用同一列，无需迁移
- ❌ 首次 count 时执行 DDL（幂等，可接受）

### 方案 C：修改 CREATE_TABLE_SQL 加入 deleted_at 列

- ❌ 改动核心 schema，涉及所有现有测试
- ❌ 需要完整的 migration 脚本（v0.1 → v0.2 迁移路径复杂化）
- ❌ 违背"最小变更"原则

## 决定

**采纳方案 B：`ALTER TABLE notes ADD COLUMN deleted_at TEXT` 增量迁移**。

理由：PRD 明确要求 `deleted_at IS NULL` 语义，且标注"为 v0.2 软删除预留接口"——说明 PM 预期该列会存在。通过 `ALTER TABLE` 添加是 SQLite 支持的标准操作，对已有数据无害（NULL 填充），不破坏现有 `add_note`/`list_notes` 的兼容性。count 首次执行时触发列迁移，属于惰性迁移（lazy migration）模式，简化初始化逻辑。

## 后果

### 正面

- ✅ count 语义与 PRD T-1 完全对齐
- ✅ 为 v0.2 软删除预埋列，无需二次迁移
- ✅ 向后兼容：已有笔记的 `deleted_at = NULL`，自然视为"活跃笔记"

### 负面

- ❌ 首次 count 触发 DDL（在事务外执行，`ALTER TABLE` 是 DDL，自动提交）
  - **缓解**：幂等操作，`IF NOT EXISTS` 不可用但 `CREATE TABLE IF NOT EXISTS` 结果集不含 `deleted_at` 列时 `ALTER` 会成功；多次执行结果一致
- ❌ 如果 v0.2 soft-delete 改变列类型（如 `INTEGER` 而非 `TEXT`），需 migration
  - **升级路径**：v0.2 migration 脚本处理列类型变更，count 命令不涉及

### 实现约束

```python
def count_notes() -> int:
    db_path = _get_db_path()
    conn = _get_connection(db_path)
    try:
        # 惰性迁移：确保 deleted_at 列存在（幂等）
        conn.execute("ALTER TABLE notes ADD COLUMN deleted_at TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在，跳过
    cursor = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL"
    )
    return cursor.fetchone()[0]
```
