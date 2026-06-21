# mdnotes search - 技术规范

> **Task ID:** t_20260620_67128
> **作者:** Architect Agent
> **依据:** `docs/PRD/04-search-command.md`（PM Agent 输出）+ `.tasks/t_20260620_67128/debate-log.md`（3 轮辩论）
> **创建时间:** 2026-06-20T23:05:00+08:00
> **辩论收敛:** 7 共识 + 4 仲裁（Round 3 PM 汇总）

---

## 接口设计

### CLI 命令签名

```
mdnotes search <query> [OPTIONS]
mdnotes search --check
mdnotes search --rebuild
```

**位置参数：**
- `query`（string）：搜索关键词，**必填**。无 query 时 exit code 2。

**选项标志：**
- `--tag <name>`：仅返回 tag_name = `<name>` 的笔记（JOIN tags 表）
- `--color <mode>`：高亮模式，`auto`（默认）| `always` | `never`
- `--limit <N>`：最多返回 N 条结果，默认 100

**维护子命令：**
- `--check`：索引健康检查（rowid 对照方案），无 query 时执行
- `--rebuild`：在线重建 FTS5 索引（原子替换，无 downtime），无 query 时执行

### CLI 引号语义（Query 预处理）

| 用户输入 | 预处理后 FTS5 语义 |
|---|---|
| `mdnotes search python redis`（无引号）| `python OR redis` |
| `mdnotes search "python redis"`（有引号）| `python AND redis` |

**特殊字符转义：** FTS5 特殊字符 `& | - " *` 在 CLI 层预处理或友好报错（exit code 2）。

### Exit Code 语义

| Exit Code | 语义 |
|---|---|
| 0 | 有结果（≥ 1 条匹配） |
| 1 | 无结果（0 条匹配） |
| 2 | 系统异常（FTS5 语法错误 / 数据库锁定 / FTS5 不可用 / 缺 query） |

### API 端点（内部模块）

- `storage.ensure_fts5()`：初始化 FTS5 virtual table + 3 个 trigger（幂等）
- `storage.search_notes(query, tag=None, limit=100)`：执行 FTS5 MATCH，返回笔记列表
- `storage.check_fts5_health()`：rowid 对照方案，返回 `{consistent: bool, orphaned: int, extra: int}`
- `storage.rebuild_fts5()`：原子在线 rebuild，无 downtime

---

## 数据结构

### FTS5 Virtual Table Schema（关联型）

```sql
-- notes_fts 是 notes 表的全文索引视图，不冗余存储内容
CREATE VIRTUAL TABLE notes_fts USING fts5(
    title,
    content,
    tag,              -- denormalized TEXT，逗号分隔多标签
    content='notes',  -- 关联到 notes 表
    content_rowid='id',
    tokenize='unicode61'  -- 中文 / Unicode 唯一可用分词器
);
```

**字段说明：**
- `title` / `content`：`notes` 表对应列的直接引用（`content='notes'`）
- `tag`：存储 `notes.tags` 文本（逗号分隔），用于无 `--tag` 筛选时的全文匹配
- `content_rowid='id'`：`notes` 表的 integer PK（notes 表需新增 integer `id` 列，或使用 `rowid` 别名）

**UUID + rowid 双 ID 策略：**
- `notes` 表现有 UUID text PK，新增 `id INTEGER PRIMARY KEY` 映射到 `rowid`
- FTS5 用 `rowid` 关联 `notes`，保持 UUID 可追溯性

### Trigger 自动同步（3 个）

```sql
-- INSERT trigger：notes 新增时同步写入 notes_fts
CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content, tag)
    VALUES (NEW.id, NEW.title, NEW.content, NEW.tags);
END;

-- UPDATE trigger：notes 更新时先删后插（FTS5 content= 关联模式必须 DELETE+INSERT）
CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
    DELETE FROM notes_fts WHERE rowid = OLD.id;
    INSERT INTO notes_fts(rowid, title, content, tag)
    VALUES (NEW.id, NEW.title, NEW.content, NEW.tags);
END;

-- DELETE trigger：notes 删除时同步删除 FTS5 行
CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
    DELETE FROM notes_fts WHERE rowid = OLD.id;
END;
```

**statement-level trigger 批量 update 限制：**
- tag rename 涉及多条时，statement-level trigger 只同步最后一条
- MVP 缓解：单次 rename 影响 > 10 条时输出 warning："FTS5 索引可能不一致，建议运行 mdnotes search --rebuild"
- auto-check：rename 后自动执行 `--check`，发现不一致时提示 rebuild

### Search Results Schema

```python
@dataclass
class SearchResult:
    file_path: str        # 例如 "notes/python-api.md"
    title: str            # 笔记标题
    snippet: str          # 匹配上下文，关键词高亮（ANSI escape）
    score: float          # BM25 相关性评分（FTS5 原生）
    tags: list[str]       # 该笔记关联的 tag 列表

@dataclass
class SearchResponse:
    results: list[SearchResult]
    total: int            # 实际匹配总数（可能 > limit）
    truncated: bool       # 是否被 limit 截断
    elapsed_ms: float     # 查询耗时
```

### Tags JOIN Schema（--tag 筛选）

```sql
-- --tag 筛选时 JOIN tags 表做精确 tag_name 匹配
SELECT notes_fts.rowid, notes_fts.title, notes_fts.content, notes_fts.tag
FROM notes_fts
JOIN tags ON tags.note_id = notes.rowid
WHERE tags.tag_name = :tag_name
  AND tags.deleted_at IS NULL
  AND notes_fts MATCH :query
ORDER BY bm25(notes_fts, 10.0, 1.0, 1.0);  -- BM25 评分排序
```

---

## 验收标准（技术层面）

### 功能验收

- [ ] `mdnotes search "keyword"` 返回 title/content/tag 含 keyword 的笔记列表
- [ ] `mdnotes search --tag "python"` 只返回 tag_name='python' 的笔记（JOIN tags 表）
- [ ] `mdnotes search`（无 query）→ exit code 2，提示"用法：mdnotes search <query>"
- [ ] FTS5 语法错误时 → exit code 2，提示具体 FTS5 错误信息
- [ ] `mdnotes search --check` 返回索引健康状态（orphaned rowid + extra rowid 数量）
- [ ] `mdnotes search --rebuild` 重建索引，幂等可重复执行

### 交互验收

- [ ] `mdnotes search python redis`（无引号）= OR 语义（返回含 python 或 redis 的笔记）
- [ ] `mdnotes search "python redis"`（有引号）= AND 语义（返回同时含两者的笔记）
- [ ] 特殊字符 `& | - " *` CLI 预处理转义或友好报错（exit code 2）
- [ ] `--color=auto` 时 terminal 直出高亮，pipe less 时提示 `less -R`
- [ ] 结果 > 100 条时截断，输出"显示前 100 条，共 N 条"

### 同步验收

- [ ] `mdnotes add` 新笔记后立即 `search` 能搜到（trigger 同步）
- [ ] `mdnotes delete` 删除后立即 `search` 搜不到（trigger 同步）
- [ ] `mdnotes tag rename v1 v2` 后，`search --tag v2` 立即搜到，`search --tag v1` 搜不到
- [ ] rename 影响 > 10 条时输出 warning（statement-level trigger 限制）
- [ ] `mdnotes search --check` 能检测到 trigger 漏触发的索引不一致

### 性能验收

- [ ] 1000 笔记 P95 冷缓存响应时间 ≤ 100ms（`EXPLAIN QUERY PLAN` + 真实计时）
- [ ] 中文查询 `"性能优化"` 正常工作（unicode61 tokenize）
- [ ] rebuild 期间搜索服务不中断（旧索引表服务）

### 边界 Case 验收（8 个必跑）

| # | 边界 Case | 预期行为 |
|---|---|---|
| BC-1 | empty query（无 query 参数）| exit code 2 + 友好提示 |
| BC-2 | special chars（`' " & | - " *`）| CLI 预处理或 exit code 2 |
| BC-3 | Chinese characters（中文连续词 + 单字）| 正常工作 |
| BC-4 | large result set（> 100 条）| 截断 + "显示前 100 条，共 N 条" |
| BC-5 | no result（0 条匹配）| exit code 1 + "未找到匹配笔记" |
| BC-6 | multi-file results（多 .md 文件匹配）| 每行显示文件路径 |
| BC-7 | file path with spaces（含空格路径）| 路径加引号 `"my notes/test.md"` |
| BC-8 | vault with no .md files（空 vault）| exit code 1 + "未找到匹配笔记" |

---

## 边界情况

| 情况 | 处理方式 |
|---|---|
| **FTS5 模块不可用** | CLI 启动时报错 "FTS5 not available"，exit code 2；CI fail-fast |
| **Query 含 FTS5 保留字** | CLI 层转义 `& | - " *`，无法转义时报错 exit code 2 |
| **tag rename 批量 > 10 条** | 输出 warning，auto-check 发现不一致时提示 rebuild |
| **并发 add + search** | SQLite 写锁保护，search 读不阻塞 write |
| **Rebuild 期间新 add** | Rebuild 完成后新笔记通过 trigger 自然同步 |
| **notes 表与 FTS5 rowid 不一致** | `--check` 检测，`--rebuild` 修复 |
| **空 query** | exit code 2 + 语法提示，不查数据库 |

---

## 依赖

### 外部依赖检查（FTS5 模块可用性）

```python
def _fts5_available() -> bool:
    """检查 SQLite FTS5 模块是否可用。"""
    import sqlite3
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        return True
    except sqlite3.OperationalError:
        return False
```

**m920x 验证结果：** ✅ Python 3.14 + SQLite 3.46.1，FTS5 可用。

**依赖要求：**
- Python 3.14+（内置 SQLite 3.46.1，内置 FTS5 模块，无需额外 pip 包）
- 不支持精简版 SQLite / 移动端 Python
- FTS5 不可用时 CLI 启动报错，CI fail-fast，**不提供 LIKE fallback**

### 新增依赖

| 包 | 版本 | 用途 |
|---|---|---|
| `click` | ^8.1.0 | CLI 框架（已存在于 pyproject.toml） |
| `sqlite3` | Python 3.14 内置 | FTS5 数据库（无需安装） |

**无需新增 pip 包**，FTS5 是 Python 3.14 / SQLite 3.46.1 内置模块。

### 内部模块

- `src/mdnotes/storage.py`：扩展 `ensure_fts5()` / `search_notes()` / `check_fts5_health()` / `rebuild_fts5()`
- `src/mdnotes/cli.py`：扩展 `search` 命令组（`search`、`search-check`、`search-rebuild`）

---

## 错误处理

### Exit Code 语义

| Exit Code | 触发条件 | 错误信息示例 |
|---|---|---|
| 0 | ≥ 1 条匹配 | （无错误，正常输出） |
| 1 | 0 条匹配（正常无结果）| "未找到匹配笔记" |
| 2 | 系统异常 / FTS5 不可用 / 缺 query | "FTS5 not available" / "缺少 query 参数" / "FTS5 syntax error" |

### FTS5 不可用错误

```
Error: FTS5 is not available in this SQLite installation.
Required: Python 3.14+ with SQLite 3.46.1+
Install: sqlite3 is built-in; ensure your Python was compiled with FTS5 support.
```

### FTS5 语法错误

```
Error: Invalid FTS5 query syntax: <原始错误>
Hint: Use quotes for multi-word AND queries: mdnotes search "python redis"
```

### Rebuild 错误

```
Error: Failed to rebuild FTS5 index: <原因>
Hint: Ensure no other mdnotes process is running.
```

---

## 实施指南

### 实施顺序

**第 1 步：Schema 迁移（storage.py）**
1. 为 `notes` 表新增 `id INTEGER PRIMARY KEY` 列（UUID 保留，新增 `id` 对应 `rowid`）
2. 实现 `ensure_fts5()`：创建 FTS5 virtual table + 3 个 trigger（幂等，`IF NOT EXISTS`）
3. 实现 `check_fts5_health()`：rowid 对照 SQL，检查 notes 与 notes_fts 一致性
4. 实现 `rebuild_fts5()`：原子替换（`ALTER TABLE notes_fts RENAME TO notes_fts_old`，重建，再删 old）

**第 2 步：Search 核心（storage.py）**
1. 实现 `search_notes(query, tag=None, limit=100)`：FTS5 MATCH + BM25 排序
2. 实现 query 预处理：无引号 → OR，有引号 → AND，特殊字符转义
3. 实现 `--tag` 筛选：JOIN tags 表做精确 tag_name 匹配
4. 集成 `--color` 高亮：ANSI escape snippet 标注

**第 3 步：CLI 命令（cli.py）**
1. 新增 `search` 命令组：`search <query>` / `search --check` / `search --rebuild`
2. 参数解析：query 必填检查（缺时 exit code 2）
3. exit code 逻辑：0=有结果，1=无结果，2=异常
4. `--color=auto`：检测 `isatty()`，非 terminal 时提示 `less -R`

**第 4 步：单元测试（tests/）**
1. mock FTS5：测试 CLI 参数解析、query 预处理、exit code
2. 测试空 query、特殊字符、中文 query、limit 截断
3. 测试 tag rename warning（> 10 条）

**第 5 步：集成测试（tests/）**
1. 真 FTS5 + 100 条笔记：测试 trigger 同步（add / delete / update）
2. 真 FTS5 + 1000 条笔记：性能 P95 ≤ 100ms 门禁测试
3. 边界 case 8 个必跑（见验收标准 BC-1~BC-8）
4. FTS5 不可用时 CI fail 验证（`pytest -v`）

### 性能门禁

```
集成测试性能门禁：
  1000 笔记，FTS5 MATCH P95（冷缓存）≤ 100ms

测量方法：
  $ time mdnotes search "keyword"  # cold cache
  $ sqlite3 notes.db "EXPLAIN QUERY PLAN SELECT ... FROM notes_fts WHERE notes_fts MATCH 'keyword'"
```

### Multi-file 结果处理

搜索结果按文件路径分组，每个匹配笔记显示：
```
file/path.md: 标题  ...匹配snippet（含ANSI高亮）...
"my notes/test.md": 另一标题  ...匹配snippet...
```

路径含空格时加双引号。每个文件一行，无重复文件路径。

---

## 关联 ADR

- `docs/DECISIONS/0005-fts5-vs-like.md`：FTS5 vs LIKE 决策
- `docs/DECISIONS/0006-search-scope.md`：search scope 决策（MVP 三字段 vs 完整扩展）

---

*Architect 完成 spec-ready → coding 切换。FTS5 模块检查：✅ m920x 可用。*
