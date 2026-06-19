# count 子命令 - 技术规范

> **Task ID:** t_20260619_e91oh2
> **作者:** Architect Agent
> **依据:** `docs/PRD/02-count-command.md`（PM Agent 输出）
> **创建时间:** 2026-06-19T14:47:00.000Z

---

## 接口设计

### CLI 命令

- **`mdnotes count`**：输出活跃笔记总数
  - 输出：`Total notes: N`（N 为整数，exit 0）
  - 无 DB 时：自动创建空数据库，输出 "Total notes: 0"（exit 0）
  - 磁盘满时：exit 1，stderr 输出错误信息

- **`mdnotes count --help`**：显示帮助信息（exit 0）

### Storage 函数

- **`count_notes() -> int`**：返回 `deleted_at IS NULL` 的笔记数量
  - 内部调用 `_get_connection()` 复用建表逻辑
  - 内部使用 `_retry_on_lock` 装饰器
  - 异常时抛出 `DatabaseError`

---

## 数据结构

### 内部查询结果

```python
# count_notes() 返回值
int  # 活跃笔记数量，范围 [0, +∞)
```

### Schema 变更（storage.py）

```sql
-- notes 表新增 deleted_at 列（支持 v0.2 软删除）
ALTER TABLE notes ADD COLUMN deleted_at TEXT;
-- deleted_at IS NULL  → 活跃笔记
-- deleted_at IS NOT NULL → 已删除（软删除）
```

> **注意**：现有 `CREATE_TABLE_SQL` 保持不变（向后兼容）；`deleted_at` 通过 `ALTER TABLE` 增量添加，`count_notes()` 首次调用时触发迁移。

---

## 验收标准

### 业务标准（B）

- [ ] **B-1**：`mdnotes count` 在无 DB 时自动初始化，exit 0，stdout "Total notes: 0"
- [ ] **B-2**：`mdnotes count` 在有 N 条笔记时输出 "Total notes: N"，exit 0
- [ ] **B-3**：`mdnotes count --help` 显示用法，exit 0
- [ ] **B-4**：输出格式为 `Total notes: N`（N 为非负整数）
- [ ] **B-5**：count 语义 = 活跃笔记数（`WHERE deleted_at IS NULL`），为 v0.2 软删除预留接口
- [ ] **B-6**：auto-init 行为在 `--help` 中显式说明

### 技术标准（T）

- [ ] **T-1**：SQL 为 `SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL`
- [ ] **T-2**：storage 层新增 `count_notes() -> int` 公共函数
- [ ] **T-3**：复用 `_get_connection()` + `DatabaseError` + `_retry_on_lock`
- [ ] **T-4**：auto-init 复用 `CREATE TABLE IF NOT EXISTS`（在 `_get_connection()` 内自动触发，不重复实现 init 全部流程）
- [ ] **T-5**：CLI 层 `@cli.command()` + Click exit 2 参数校验默认行为
- [ ] **T-6**：幂等性：连续两次 count 结果一致（数据库只读，无副作用）
- [ ] **T-7**：`deleted_at` 列通过 `ALTER TABLE` 增量添加，不修改 `CREATE_TABLE_SQL`

---

## 边界情况

| 情况 | 处理方式 |
|---|---|
| **DB 文件不存在** | `_get_connection()` 自动创建 `~/.mdnotes/` + `notes.db` + `ALTER TABLE`，输出 "Total notes: 0" |
| **磁盘满（初始化时）** | `OSError` → `DatabaseError` → exit 1 + stderr 错误信息 |
| **DB 部分损坏** | SQLite 返回错误数字不抛异常（已知风险 R-2），不处理 |
| **DB 被误删** | 等同"DB 不存在"场景，exit 0 + "Total notes: 0"（已知风险 R-1） |
| **并发 count** | SQLite 只读不阻塞，`_retry_on_lock` 不介入只读场景 |
| **notes 表无 deleted_at 列**（升级场景） | `count_notes()` 首次执行 `ALTER TABLE ADD COLUMN`，向后兼容 |
| **空数据库（表不存在）** | `_get_connection()` 内 `CREATE TABLE IF NOT EXISTS` 建表，count 返回 0 |

---

## 依赖

### 内部模块

- `mdnotes.storage`：复用 `_get_connection()`、`DatabaseError`、`_retry_on_lock`
- `mdnotes.cli`：新增 `@cli.command()` 装饰的 `count` 函数

### 外部依赖

- **Python 标准库**：`sqlite3`、`os`（已有）
- **Click**：CLI 框架（已有 `pip install click`）

---

## 实施指南

1. **storage.py**：
   - 在 `count_notes()` 内部首次调用时执行 `ALTER TABLE notes ADD COLUMN deleted_at TEXT`（幂等，IF NOT EXISTS 语义）
   - SQL：`SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL`
   - 复用 `_retry_on_lock` 装饰器
   - 异常映射为 `DatabaseError`

2. **cli.py**：
   - 新增 `count` 函数，`@cli.command()` 装饰
   - 调用 `count_notes()`，捕获 `DatabaseError` → exit 1
   - 成功时 `click.echo(f"Total notes: {n}")` → exit 0
   - `--help` 由 Click 自动处理

3. **测试策略**：
   - 单元测试：无 DB 场景、有 DB 场景（0 条 / 多条）、损坏 DB 场景
   - 集成测试：`mdnotes count` 命令 end-to-end

---

## 已知风险（继承自 PRD）

| ID | 风险 | 缓解 |
|---|---|---|
| R-1 | DB 被误删静默返回 0 | v0.2 `verify` 命令检测 |
| R-2 | DB 部分损坏 SQLite 返回错误数字 | v0.2 加 `PRAGMA integrity_check` |
| R-3 | soft-delete 引入时需重审视 SQL | 已预埋 `deleted_at IS NULL` |
