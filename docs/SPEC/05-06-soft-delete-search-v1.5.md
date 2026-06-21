# v1.5 soft-delete + search 优化 - 技术规范

> **Task ID:** t_20260621_v150_032907
> **适用版本**: v1.5.0+
> **作者:** Architect Agent
> **依据:** PRD-05 (soft-delete) + PRD-06 (search optimization)
> **创建时间:** 2026-06-21T09:17:00+08:00

---

## 1. 概述与设计目标

本 spec 覆盖 mdnotes v1.5 两个 PRD 的技术实现：
- **PRD-05**：`delete` 默认软删除（可恢复）、`delete --physical` 物理删除、`restore` 恢复误删、`purge` 批量清理
- **PRD-06**：tag 组合搜索（AND/OR）、snippet 高亮（ANSI escape code）、中文搜索降级提示

**设计约束（来自 PRD 辩论共识）**：
- `deleted_at IS NULL` 是所有 list/count/search 查询的默认过滤条件
- FTS5 搜索入口过滤由应用层实现（不在 FTS5 层面）
- `deleted_at` 统一 UTC 存储，CLI 显示时转换本地时区
- AND 是 tag 组合默认语义，OR 通过 `--or` flag 切换
- snippet 高亮使用 `<mark>` 标签 + CLI 层 ANSI 转换

---

## 2. 现有代码审计

### 2.1 已有 `deleted_at` 迁移基础设施

`storage.py` 中已存在：
- `count_notes()` 有 lazy migration：`ALTER TABLE notes ADD COLUMN deleted_at TEXT`
- `search_notes()` 目前 **不**过滤 `deleted_at`（需修改）
- `list_notes()` 目前 **不**过滤 `deleted_at`（需修改）
- FTS5 trigger `notes_au`（AFTER UPDATE）已存在：`DELETE + INSERT` 到 notes_fts
- `tags` 表有 `deleted_at TEXT DEFAULT NULL` 字段
- `idx_tags_tag_name` 索引已存在

### 2.2 现有 `delete_note()` 的问题

当前 `delete_note()` 是物理删除 + VACUUM，不符合 PRD-05 要求：
- 默认行为需改为软删除（UPDATE `deleted_at`）
- 物理删除需要新 flag `--physical`

---

## 3. 数据结构变更

### 3.1 notes 表（已有，启用）

```sql
ALTER TABLE notes ADD COLUMN deleted_at TEXT DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_notes_deleted_at ON notes(deleted_at);
```

- `deleted_at IS NULL` = 活跃笔记
- `deleted_at IS NOT NULL` = 已软删除（UTC ISO 8601 时间戳）
- 索引支持 `WHERE deleted_at IS NULL` 快速查询

### 3.2 新增 CLI 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 系统错误（数据库锁定、损坏）|
| 2 | 参数错误 |
| 3 | 笔记不存在（idempotent for delete）|
| 4 | restore 冲突（用户选择）|

---

## 4. API / 存储层变更（storage.py）

### 4.1 `soft_delete_note(note_id: int) -> None`

```python
def soft_delete_note(note_id: int) -> None:
    """
    软删除笔记：UPDATE deleted_at = UTC NOW WHERE id = ? AND deleted_at IS NULL.
    幂等：对已软删除笔记不报错。
    Raises: NoteNotFoundError（笔记不存在）
    """
    # 1. 检查笔记存在（AND deleted_at IS NULL）
    # 2. UPDATE notes SET deleted_at = utcnow() WHERE id = ? AND deleted_at IS NULL
    # 3. 若 affected rows = 0，再查 deleted_at IS NOT NULL → 幂等成功（exit 0）
    # 4. notes_au trigger 自动同步 FTS5（DELETE 旧 + INSERT 新）
```

**关键 SQL**：
```sql
UPDATE notes
SET deleted_at = datetime('now')
WHERE id = ? AND deleted_at IS NULL;
-- affected rows = 0 时检查是否已软删除（幂等）
```

**FTS5 同步**：`notes_au` trigger 已在 soft-delete UPDATE 时自动触发（FTS5 保留，search 入口过滤）。

### 4.2 `physical_delete_note(note_id: int) -> None`

```python
def physical_delete_note(note_id: int) -> None:
    """
    物理删除笔记：DELETE FROM notes WHERE id = ?.
    不检查 deleted_at（可物理删除已软删除的笔记）。
    Raises: NoteNotFoundError（笔记不存在）
    """
    # DELETE FROM notes WHERE id = ?
    # notes_ad trigger 自动 DELETE FROM notes_fts
```

### 4.3 `restore_note(note_id: int) -> RestoreResult`

```python
@dataclass
class RestoreResult:
    success: bool
    restored_id: int
    conflict: bool = False
    existing_note_id: Optional[int] = None
    existing_title: Optional[str] = None
    existing_updated_at: Optional[str] = None
    conflicting_deleted_title: Optional[str] = None
    conflicting_deleted_updated_at: Optional[str] = None
```

**冲突检测逻辑**：
```sql
-- Step 1：检查被软删除的笔记存在
SELECT id, title, updated_at FROM notes WHERE id = ? AND deleted_at IS NOT NULL;
-- Step 2：检查同名活跃笔记冲突（同 title，id 不同）
SELECT id, title, updated_at FROM notes
WHERE title = (SELECT title FROM notes WHERE id = ?) AND deleted_at IS NULL AND id != ?;
```

**无冲突 restore**：
```sql
UPDATE notes SET deleted_at = NULL WHERE id = ?;
-- notes_au trigger 自动同步 FTS5（DELETE 旧 + INSERT 新）
```

### 4.4 `purge_deleted_notes(confirm: bool, dry_run: bool) -> PurgeResult`

```python
@dataclass
class PurgeResult:
    deleted_count: int
    batch_count: int
    dry_run: bool
```

```python
def purge_deleted_notes(confirm: bool = False, dry_run: bool = False) -> PurgeResult:
    """
    批量物理删除已软删除笔记。
    - dry_run: SELECT COUNT(*) 返回数量，不实际删除
    - confirm required: 无 --confirm flag 时报错
    - 分批执行：每批 500 条，批次间 sleep(10ms)
    """
    if dry_run:
        count = conn.execute(
            "SELECT COUNT(*) FROM notes WHERE deleted_at IS NOT NULL"
        ).fetchone()[0]
        return PurgeResult(deleted_count=count, batch_count=0, dry_run=True)

    if not confirm:
        raise ParamError("purge requires --confirm flag")

    # 分批删除
    BATCH_SIZE = 500
    total_deleted = 0
    batch = 0
    while True:
        deleted = conn.execute(
            "DELETE FROM notes WHERE id IN "
            "(SELECT id FROM notes WHERE deleted_at IS NOT NULL LIMIT ?)",
            (BATCH_SIZE,)
        ).rowcount
        if deleted == 0:
            break
        total_deleted += deleted
        batch += 1
        time.sleep(0.01)  # 10ms between batches
    # notes_ad trigger 自动 DELETE FROM notes_fts
```

### 4.5 `get_note(note_id: int)` 变更

当前返回活跃笔记。变更后：
- 对已软删除笔记：抛出 `NoteNotFoundError`（`list`/`count`/`search` 已过滤，show 单独查看已删除需另建 API）
- 与 PRD-05 一致：`restore` 场景下才需要查已软删除笔记（单独 SQL 查询）

### 4.6 `list_notes()` 变更

所有 `list_notes()` 调用加 `WHERE deleted_at IS NULL`：
```sql
SELECT ... FROM notes WHERE deleted_at IS NULL ORDER BY ...
```

### 4.7 `count_notes()` 变更（已有）

```sql
SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL;
```

### 4.8 `search_notes()` 变更（PRD-06 核心）

#### 4.8.1 Tag 组合搜索（AND/OR）

**AND 语义（默认）**：
```sql
-- 子查询：同时有所有 tag 的 note_id
SELECT note_id FROM tags
WHERE tag_name IN ('python', 'dev') AND deleted_at IS NULL
GROUP BY note_id
HAVING COUNT(*) = ?
-- HAVING COUNT(*) = N（N = tag 数量）= 同时满足所有 tag
```

**OR 语义（`--or` flag）**：
```sql
SELECT note_id FROM tags
WHERE tag_name IN ('python', 'dev') AND deleted_at IS NULL
GROUP BY note_id
-- 无 HAVING，每条 GROUP BY 结果都是 OR
```

**硬限制**：单个搜索最多 50 个 `--tag`（超出报错 exit 2）。

**完整 search_notes 签名**：
```python
def search_notes(
    query: str,
    tags: Optional[list[str]] = None,   # 新增：多 tag
    tag_mode: str = "AND",             # "AND" | "OR"
    tag: Optional[str] = None,         # 保留旧接口兼容（单个 tag）
    limit: int = 100,
) -> list[dict[str, Any]]:
```

#### 4.8.2 Snippet 高亮

FTS5 `snippet()` 函数使用 `<mark>` 标签：
```sql
snippet(notes_fts, 2, '<mark>', '</mark>', '...', 32)
-- 参数：column_index=2（content），前缀，后缀，省略符，最大词边界数
```

**CLI 层 ANSI 转换**（cli.py）：
```python
ANSI_MARK_OPEN = "\x1b[1m"   # 粗体
ANSI_MARK_CLOSE = "\x1b[0m"  # 重置

def _render_snippet(snippet: str, color_mode: str) -> str:
    if color_mode == "never":
        return snippet  # 保留 <mark> 标签
    elif color_mode == "always":
        return snippet.replace("<mark>", ANSI_MARK_OPEN).replace("</mark>", ANSI_MARK_CLOSE)
    elif color_mode == "auto":
        # 如果是 TTY：转换；否则保留 <mark> + 提示 less -R
        if sys.stdout.isatty():
            return snippet.replace("<mark>", ANSI_MARK_OPEN).replace("</mark>", ANSI_MARK_CLOSE)
        else:
            return snippet + "\n  (use less -R for color)"
```

#### 4.8.3 中文搜索降级提示（BC-17）

CJK 字符检测正则：`[\u4e00-\u9fff]`（中日韩统一表意文字）

```python
CJK_RE = re.compile(r'[\u4e00-\u9fff]')

def _is_cjk_query(query: str) -> bool:
    return bool(CJK_RE.search(query))

def _has_exact_quotes(query: str) -> bool:
    # 精确引号：整个 query 以 " 开头和结尾
    return query.strip().startswith('"') and query.strip().endswith('"')
```

触发条件：`search_notes` 含 CJK 字符 **且** 不是精确引号查询：
```python
if _is_cjk_query(query) and not _has_exact_quotes(query):
    result["cjk_hint"] = "中文模糊搜索已计划在 v1.6 实现，当前请使用精确匹配"
```

CLI 层输出：
```python
if result.get("cjk_hint"):
    click.echo(f"  💡 {result['cjk_hint']}", err=True)
```

#### 4.8.4 `deleted_at` 过滤

所有 `search_notes` SQL 加 `AND n.deleted_at IS NULL`：
```sql
WHERE notes_fts MATCH ?
  AND n.deleted_at IS NULL
  AND t.deleted_at IS NULL  -- tags JOIN 也要过滤
```

#### 4.8.5 search exit codes

| exit code | 含义 |
|-----------|------|
| 0 | 有结果 |
| 1 | 无结果 |
| 2 | 系统异常（FTS5 语法错误 / 数据库锁定）|

---

## 5. CLI 变更（cli.py）

### 5.1 `delete` 命令

```python
@cli.command()
@click.argument("id")
@click.option("--physical", is_flag=True, help="Permanently delete (skip soft-delete)")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def delete(id: str, physical: bool, force: bool):
    """
    Delete a note by ID.

    Default (no flag): soft-delete -笔记进入回收站，可通过 restore 恢复。
    --physical: permanently delete (cannot be restored).

    行为变更（v1.5）：delete 默认软删除，不再是物理删除。
    """
```

**Exit codes**：
- 0：成功（含幂等：对已软删除笔记再次 delete）
- 1：系统错误
- 2：参数错误（id 无效）
- 3：笔记不存在

### 5.2 `restore` 命令（新增）

```python
@cli.command()
@click.argument("id")
def restore(id: str):
    """
    Restore a soft-deleted note.

    若存在同名活跃笔记，显示冲突界面（两个版本的标题 + 修改时间），
    让用户选择覆盖（overwrite）或保留（keep）。

    Examples:
      mdnotes restore 42
    """
```

**Exit codes**：
- 0：恢复成功
- 1：系统错误
- 2：参数错误
- 3：笔记不存在或未软删除
- 4：restore 冲突（用户取消或选择保留）

### 5.3 `purge` 命令（新增）

```python
@cli.command()
@click.option("--confirm", is_flag=True, help="确认执行（必填）")
@click.option("--dry-run", is_flag=True, help="预览影响数量，不实际删除")
def purge(confirm: bool, dry_run: bool):
    """
    Permanently delete all soft-deleted notes.

    默认（无 --confirm）：报错退出
    --dry-run：只报告数量，exit 0
    --confirm：执行批量物理删除（分批，每批 500 条）

    Example:
      mdnotes purge --dry-run
      mdnotes purge --confirm
    """
```

**Exit codes**：
- 0：成功（含无已删除笔记的情况）
- 1：系统错误
- 2：参数错误

### 5.4 `search` 命令（扩展）

```python
@cli.command()
@click.argument("query", required=False)
@click.option("--tag", "tag_filter", multiple=True, help="Filter by tag (可重复，AND 语义）")
@click.option("--or", "tag_or", is_flag=True, help="OR 语义组合 tag（默认 AND）")
@click.option("--color", type=click.Choice(["auto", "always", "never"]), default="auto")
@click.option("--limit", default=100)
@click.option("--check", "check_flag", is_flag=True)
@click.option("--rebuild", "rebuild_flag", is_flag=True)
def search(query, tag_filter, tag_or, color, limit, check_flag, rebuild_flag):
```

**参数变更**：
- `--tag` 从 `default=None` 改为 `multiple=True`（可重复）
- 新增 `--or` flag（切换 AND/OR 语义）
- 新增 `--color=auto|always|never`

### 5.5 `ls` / `list` 命令

无需改动（`list_notes()` 已统一加 `WHERE deleted_at IS NULL`）。

---

## 6. 关键算法

### 6.1 tag 组合 AND 查询（关键）

```python
def _build_tag_filter_sql(tags: list[str], mode: str) -> tuple[str, tuple]:
    """
    构建 tag 组合过滤 SQL 子查询。
    返回 (sql_fragment, params)。
    """
    n = len(tags)
    if mode == "AND":
        sql = """
            SELECT note_id FROM tags
            WHERE tag_name IN (%s) AND deleted_at IS NULL
            GROUP BY note_id
            HAVING COUNT(*) = ?
        """ % ",".join(["?"] * n)
        return sql, (*tags, n)
    else:  # OR
        sql = """
            SELECT note_id FROM tags
            WHERE tag_name IN (%s) AND deleted_at IS NULL
            GROUP BY note_id
        """ % ",".join(["?"] * n)
        return sql, (*tags,)
```

### 6.2 restore 冲突处理（关键）

```python
def _handle_restore_conflict(deleted_note, existing_note) -> str:
    """
    显示冲突界面，返回用户选择：'overwrite' | 'keep' | None（取消）
    """
    click.echo("⚠️  冲突：同名笔记已存在")
    click.echo(f"  已删除版本：{deleted_note['title']} | 修改于 {deleted_note['updated_at']}")
    click.echo(f"  现有版本：  {existing_note['title']} | 修改于 {existing_note['updated_at']}")
    click.echo("选择：[overwrite] 覆盖现有版本 | [keep] 保留现有版本")
    choice = input("> ").strip().lower()
    if choice in ("overwrite", "y"):
        return "overwrite"
    else:
        return "keep"
```

---

## 7. 边界情况

| 边界情况 | 处理方式 |
|----------|----------|
| `delete` 已软删除笔记 | 幂等：exit 0，不报错 |
| `delete` 不存在笔记 | exit 3，报错 "Note not found" |
| `delete --physical` 不存在笔记 | exit 3，报错 "Note not found" |
| `restore` 未软删除笔记 | exit 3，报错 "Note is not soft-deleted" |
| `restore` 不存在笔记 | exit 3，报错 "Note not found" |
| `restore` 冲突 + 用户选 keep | exit 4，恢复取消 |
| `purge` 无 `--confirm` flag | exit 2，报错 "purge requires --confirm flag" |
| `purge` 无已删除笔记 | exit 0，输出 "0 notes purged" |
| `--tag` 超过 50 个 | exit 2，报错 "too many tags (max 50)" |
| CJK 搜索无引号 | 正常返回结果 + hint，不报错 |
| 并发 `delete` + `restore` 同一笔记 | WAL 模式乐观锁，最后执行者胜出（用户承担结果）|
| FTS5 语法错误 | exit 2，报错 "FTS5 syntax error" |

---

## 8. 向后兼容

### 8.1 行为变更（需在 CHANGELOG 说明）

- `delete` 从物理删除 → 默认软删除（breaking change）
- `list` / `count` / `search` 自动过滤已删除笔记（符合预期，非 breaking）

### 8.2 数据库迁移

```python
def _migrate_v15(conn: sqlite3.Connection) -> None:
    """v1.5 migration: add deleted_at column + index."""
    try:
        conn.execute("ALTER TABLE notes ADD COLUMN deleted_at TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass  # already exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_deleted_at ON notes(deleted_at)")
```

迁移时机：`count_notes()` 首次调用时触发（lazy migration），或 `storage.py` 初始化时统一迁移。

### 8.3 现有 FTS5 入口过滤

`search_notes()` 中加入 `AND n.deleted_at IS NULL` 不会影响活跃笔记的搜索结果（因为所有现有笔记的 `deleted_at` 均为 NULL），完全向后兼容。

---

## 9. 风险点与缓解

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| restore 后 FTS5 未同步 | 低 | `notes_au` trigger（UPDATE 时自动 DELETE+INSERT）已存在 |
| purge 分批期间中断 | 低 | 断点续传：每批独立事务，中断后可重新运行 |
| 并发 delete+restore 死锁 | 低 | WAL 模式 + 乐观锁 + 幂等设计 |
| CJK 搜索质量差 | 中（已知局限）| BC-17 降级提示，v1.6 trigram 升级路径 |
| 非 ANSI 终端显示 | 低 | `--color=never` 纯文本模式 |
| `delete --physical` 数据永久丢失 | 高（设计如此）| `--confirm` 确认；CHANGELOG 说明 |

---

## 10. 依赖

### 10.1 内部模块

- `storage.py`：全部受影响（soft-delete/restore/purge/search 优化）
- `cli.py`：新增 restore/purge 命令；search/ls/delete 改造
- `render.py`：不受影响

### 10.2 Python 标准库

- `re`（CJK 检测）
- `time.sleep`（purge 批次间隔）
- `sqlite3`（已使用）

### 10.3 无新增外部依赖

---

## 11. 实施顺序

**阶段 1：PRD-05 先交付（storage 层）**
1. `_migrate_v15()` 添加 `deleted_at` 列 + 索引
2. `soft_delete_note()` / `physical_delete_note()` / `restore_note()` / `purge_deleted_notes()`
3. 修改 `list_notes()` / `count_notes()` 加 `WHERE deleted_at IS NULL`
4. 修改 `get_note()` 对已删除笔记抛 `NoteNotFoundError`
5. 修改 `search_notes()` 加 `AND n.deleted_at IS NULL`

**阶段 2：CLI 层（PRD-05 + PRD-06 并行）**
1. `delete --physical` 命令
2. `restore` 命令（含冲突界面）
3. `purge --confirm --dry-run` 命令
4. `search --tag --or --color` 扩展

**阶段 3：PRD-06 search 优化**
1. tag 组合 AND/OR SQL builder
2. snippet 高亮（`<mark>` + ANSI 转换）
3. CJK 降级提示
4. `--limit` 截断提示

**阶段 4：集成测试**
1. soft-delete 全链路测试（delete → list 不显示 → restore → list 显示）
2. FTS5 一致性测试（add/delete/restore/search 相互影响）
3. 并发 delete+restore 测试
4. purge 分批测试

---

## 12. 验收标准（技术层面）

- [ ] `soft_delete_note()` 幂等（已软删除笔记再次 soft_delete 不报错）
- [ ] `physical_delete_note()` 物理删除后 FTS5 记录同步清除
- [ ] `restore_note()` 无冲突时 `deleted_at = NULL`，FTS5 同步
- [ ] `restore_note()` 有冲突时返回 `RestoreResult(conflict=True)`
- [ ] `purge_deleted_notes(confirm=False)` 抛出 `ParamError`
- [ ] `purge_deleted_notes(dry_run=True)` 不修改数据库
- [ ] `purge_deleted_notes(confirm=True)` 分批执行，批次间 10ms 间隔
- [ ] `search_notes(tags=[...], tag_mode="AND")` 只返回同时含所有 tag 的笔记
- [ ] `search_notes(tags=[...], tag_mode="OR")` 返回含任一 tag 的笔记
- [ ] snippet 高亮标签替换正确（`--color=always` 时 ANSI）
- [ ] CJK 无引号查询返回 `cjk_hint` 字段
- [ ] 所有 list/count/search 查询默认 `WHERE deleted_at IS NULL`
- [ ] `idx_notes_deleted_at` 索引存在
- [ ] `idx_tags_tag_name` 索引被查询计划命中
- [ ] Python 3.10/3.11/3.12 GHA CI 均通过
- [ ] 覆盖率 ≥ 86%（整体），新增代码 ≥ 90%
