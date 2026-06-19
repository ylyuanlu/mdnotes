# count 子命令 - 产品需求文档

> **Task ID:** t_20260619_e91oh2
> **作者:** PM Agent（主帅接权汇总 Round 3 收敛）
> **创建时间:** 2026-06-19T14:45:00.000Z

---

## 用户故事

- 作为 **mdnotes 用户**，我想要 **`mdnotes count` 命令**，以便**快速了解已索引笔记的总数量**，确认笔记是否全部同步/备份。
- 作为 **CLI 工具用户**，我想要**零配置启动**（无 DB 时自动初始化），以便**开箱即用，无需手动 init**。

---

## 业务流程

1. 用户运行 `mdnotes count`
2. 系统检查 `~/.mdnotes/index.db` 是否存在
   - 若不存在 → 自动创建（`CREATE TABLE IF NOT EXISTS`）→ exit 0，stdout "0"
   - 若存在 → 执行 `SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL`
3. 系统输出计数结果，exit 0

---

## 边界情况（非目标）

以下场景**不**在 MVP scope，标注为已知风险：

| 场景 | 行为 | 备注 |
|---|---|---|
| DB 文件被误删 | exit 0 + stdout "0" | 不检测数据丢失——这是 `verify` 命令的 future scope |
| DB schema 截断/部分损坏 | SQLite 行为 | 可能返回错误数字，不抛异常——PRD 标注为已知风险 |
| 磁盘满（初始化时）| `OSError` → exit 1 + stderr | 需标注磁盘满处理 |
| 并发 count | SQLite 只读不阻塞只读 | 不测并发 count，并发 add/count 由 `_retry_on_lock` 处理 |

---

## 验收标准

### 业务标准（B）

| ID | 标准 |
|---|---|
| B-1 | `mdnotes count` 在无 DB 时自动初始化，exit 0，stdout "0" |
| B-2 | `mdnotes count` 在有 N 条笔记时输出 "N"，exit 0 |
| B-3 | `mdnotes count --help` 显示用法，exit 0 |
| B-4 | 输出格式：`Total notes: N`（N 为整数）|
| B-5 | count 语义 = 活跃笔记数（`deleted_at IS NULL`），为 v0.2 软删除预留接口 |
| B-6 | auto-init 行为在 `--help` 或文档中显式说明 |

### 技术标准（T）

| ID | 标准 |
|---|---|
| T-1 | `SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL` |
| T-2 | storage 层新增 `count_notes() -> int` 公共函数 |
| T-3 | 复用 `_get_connection()` + `DatabaseError` + `_retry_on_lock` |
| T-4 | auto-init 复用 `CREATE TABLE IF NOT EXISTS`（复用 init 的建表逻辑，不重复实现 init 的全部流程）|
| T-5 | CLI 层 `@cli.command()` + Click exit 2 参数校验默认行为 |
| T-6 | 幂等性：结果幂等（连续两次 count 结果一致，不要求场景幂等）|

---

## 已知风险

- **R-1**: `count` 不检测数据丢失（DB 被误删静默返回 0）——future scope `verify` 命令
- **R-2**: DB 部分损坏时 SQLite 可能返回错误数字而不抛异常——v0.2 考虑加 `PRAGMA integrity_check`
- **R-3**: v0.2 soft-delete 引入时需重新审视 count SQL 是否需要改为 `WHERE deleted_at IS NULL`（已预埋）
