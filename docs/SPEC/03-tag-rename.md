# tag rename - 技术规范（SPEC 对齐 PRD 03-tag-rename）

> **Task ID:** t_20260620_9278f7
> **作者:** Architect Agent
> **依据:** `docs/PRD/03-tag-rename.md`（PM Agent 输出，3 轮辩论收敛）
> **创建时间:** 2026-06-20T15:14:00+08:00

---

## 1. 实施顺序（关键）

> **v1 失败根因：** dev 反复调试既有代码，没有明确分阶段步骤。本 spec 强制 3 阶段顺序开发，每阶段独立可验证。

### Phase 1 — dry-run 框架 + Pre-flight 检查（优先实现）
**目标：** 完整打通 `mdnotes tag rename foo bar --dry-run` 端到端，不碰真实文件/DB。

1. 在 `cli.py` 的 `tag` 命令组下新增 `rename` subcommand，argparse 参数解析
2. 参数校验：old/new 非空、不相等、case-only-conflict 检测
3. 调用 `storage.get_affected_files(old_tag)` 查 DB 获取文件列表
4. 实现 `--dry-run` 分支：只输出「将影响 N 个文件：[list]」，exit 0
5. **实现 Pre-flight 可写性检查**（关键门禁）：
   - 对每个 affected file 检查 `os.access(fp, os.W_OK)`
   - 任一文件不可写 → 输出不可写文件列表 → exit 1，**不继续**
6. 批量警告：affected > 10 时输出「This will rename N files. Use --dry-run to preview.」

**验收：** `mdnotes tag rename foo bar --dry-run` 输出文件列表且不修改任何数据。

### Phase 2 — 真实 rename 逻辑
**目标：** 实现文件 rewrite + DB update 的完整 rename 流程。

1. **Pre-flight 之后**（Phase 1 完成），实现真实 rename 分支（非 dry-run）
2. **文件 rewrite**：遍历 affected files，对每个文件：
   - `path.read_text(encoding="utf-8")`
   - 用 regex `(?<![a-zA-Z0-9])#<old_tag>\b` 替换为 `#<new_tag>`（保持原有大小写形式）
   - **原子性写**：写 `.tmp` 再 `os.replace()`（Linux `rename()` 原子保证）
3. **DB transaction**：
   - `BEGIN IMMEDIATE`（排他锁）
   - `INSERT OR IGNORE INTO tags (file_path, tag_name) SELECT ... WHERE tag_name = <old>`
   - `DELETE FROM tags WHERE tag_name = <old>`
   - `COMMIT`
4. **case-preserving**：用户输入 `old=foo new=Foo`，tag 替换后文件内为 `#Foo`，DB 存 `Foo`
5. **new tag 已存在处理**：若 `new_tag` 在 DB 已存在（非 force 模式）→ `TagConflictError` exit 1；force 模式 → merge（INSERT OR IGNORE + DELETE old）

**验收：** `mdnotes tag rename foo bar` 成功修改文件 + DB，exit 0。

### Phase 3 — Error Handling + 回滚边界
**目标：** 完善错误处理，明确回滚边界。

1. **文件 rewrite 失败处理**：
   - 捕获 `OSError` → 记录到 `failed_files` list → **不中断**，继续处理剩余文件
   - **DB rollback**：文件 rewrite 全部完成后，commit DB；若 commit 前发现 failed_files → rollback + exit 1
   - **回滚边界诚实说明**：MVP 不支持文件系统自动回滚（极端 race condition 下 backup/restore 不可靠）；Pre-flight 检查降低运行时失败率
2. **部分成功报告**：
   - 有 failed_files 时 exit 2，输出「Renamed ... (N files failed)」
3. **exit code 规范**：
   - 0 = 成功
   - 1 = 系统错误（DB 失败、Pre-flight 失败、参数校验失败）
   - 2 = 部分成功（有 failed files）或参数错误
   - 3 = 资源不存在（tag not found）
4. **CHANGELOG + help 文档**：不可逆操作提示；overwrite 策略明确说明

**验收：** 文件写失败时 DB rollback，输出失败列表，exit 1。

---

## 2. 接口设计

### CLI 命令
```
mdnotes tag rename <old_tag> <new_tag>
  [--dry-run]
  [--force]          # 允许 new_tag 已存在（merge 语义）
  [--ignore-missing] # old_tag 不存在时 exit 0 而非 exit 1
  [--glob <pattern>] # 只处理匹配 glob 的文件
  [--exclude <pat>]  # 排除匹配的文件（可重复）
```

### Exit Codes
| Code | 含义 |
|------|------|
| 0 | 成功（或 old/new 相同，无需操作） |
| 1 | 系统错误：Pre-flight 失败 / DB 错误 / 参数校验失败 |
| 2 | 部分成功（有文件 rewrite 失败） |
| 3 | tag 不存在 |

### 标准输出/错误约定
- 正常输出 → stdout
- 错误信息 → stderr
- dry-run 输出 → stderr（避免管道重定向丢失预览）

---

## 3. 数据结构

```python
@dataclass
class TagRenameOpts:
    dry_run: bool = False
    force: bool = False          # 允许 new_tag 已存在（merge）
    ignore_missing: bool = False # old_tag 不存在时 exit 0
    glob: str | None = None      # 文件 glob 过滤
    exclude: list[str] = field(default_factory=list)  # 排除模式

@dataclass
class TagRenameResult:
    old_tag: str
    new_tag: str
    affected_count: int          # 成功 rename 的文件数
    failed_files: list[str]      # 失败文件列表（absolute path + 原因）
    dry_run: bool
```

---

## 4. 验收标准

### B 级（业务验收）
- [ ] `mdnotes tag rename foo bar` 成功时 exit 0，输出「Renamed tag 'foo' → 'bar' in <N> file(s).」
- [ ] `mdnotes tag rename foo bar --dry-run` 不写 DB 不写文件，只输出受影响文件数量和列表
- [ ] `<old>` tag 不存在时 exit 3，stderr 输出「Tag '<old>' not found」
- [ ] `<old>` 不存在但有近似 tag 时，提示「Tag '<old>' not found, did you mean '<suggestion>'?」
- [ ] `<old>` 和 `<new>` 相同时输出「Old and new tag are identical, nothing to do.」并 exit 0
- [ ] `<old>` 存在且 `<new>` 也存在时（force=False）：exit 1，「Tag '<new>' already exists; use --force to merge」
- [ ] 受影响文件数 > 10 时输出警告「This will rename <N> files. Use --dry-run to preview.」
- [ ] 任一文件 frontmatter 写回失败时：db rollback，exit 1，输出失败文件列表
- [ ] Pre-flight 检查失败时（文件不可写）：提前失败，列出不可写文件，不做任何修改

### T 级（技术验收）
- [ ] Phase 1 完成后：`mdnotes tag rename foo bar --dry-run` 独立可测试
- [ ] Phase 2 完成后：真实 rename 端到端可测试，DB transaction 正确提交/回滚
- [ ] Phase 3 完成后：错误处理覆盖所有边界 case
- [ ] 通过 `ruff check` + `mypy` 类型检查
- [ ] `test_tag_rename.py` 覆盖率 ≥ 80%（按 Phase 1/2/3 分组 fixture）
- [ ] dry-run 模式下 DB 连接数 = 0（无 side effect）
- [ ] Pre-flight 检查在 rename 之前执行（顺序可验证）

---

## 5. 边界情况

| 情况 | 处理方式 |
|------|----------|
| old_tag 为空或纯空白 | exit 2，「tag name cannot be empty or whitespace」 |
| old == new（完全相同） | exit 0，「No changes needed」 |
| old 和 new 仅大小写不同（如 `Foo` vs `foo`） | exit 1，「Tag 'Foo' would conflict with 'foo' (case-insensitive)」 |
| old_tag 不存在，new_tag 不存在 | exit 3，「Tag '<old>' not found」 |
| old_tag 不存在但有近似 tag | exit 3，「Tag '<old>' not found, did you mean '<suggestion>'?」 |
| new_tag 已存在（force=False） | exit 1，「Tag '<new>' already exists; use --force to merge」 |
| new_tag 已存在（force=True） | merge：old+new 共存，old 被删除 |
| 目标文件不可写（Pre-flight） | exit 1，列出不可写文件，无任何修改 |
| 文件 rewrite 部分失败 | db rollback，exit 1，列出 failed_files |
| 文件 rewrite 全部失败 | db rollback，exit 1 |
| affected files > 10 | 输出批量警告 |
| dry-run 模式 | 无 DB 连接，无文件写入 |
| 并发 rename 同一 tag | WAL 排他锁保护 DB；文件系统层无锁（单用户工具，接受风险） |

---

## 6. 依赖

### 新增依赖
无新增外部依赖，使用 Python 3.10+ 标准库。

### 内部模块
- `mdnotes.storage`：现有 `get_affected_files()`、`rename_tag()`、`TagNotFoundError`、`TagConflictError`、`DatabaseError`
- `mdnotes.cli`：现有 Click 命令框架、异常类体系（`ParamError`、`NotFoundError`、`SystemError`）

### 需扩展的 storage 函数
- `get_affected_files(tag_name)`：已有，验证返回 `file_path` 列表
- `rename_tag(old, new, options)`：已有，验证 transaction 行为

---

## 7. 关键实现细节

### Pre-flight 可写性检查（Phase 1 必须实现）
```python
# Phase 1 中实现，不依赖 Phase 2
def _check_writable(file_paths: list[str]) -> list[str]:
    """Return list of non-writable file paths."""
    return [fp for fp in file_paths if not os.access(fp, os.W_OK)]
```
检查在获取 affected files 之后、任何写入操作之前执行。

### 原子性文件写（Phase 2）
```python
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(new_text, encoding="utf-8")
os.replace(tmp, path)  # 原子 rename
```

### Case-sensitive tag 比较（PRD 约束 3）
- SQL 层：`WHERE tag_name = ?`（精确匹配，大小写敏感）
- 文件内容 regex：`(?<![a-zA-Z0-9])#<old_tag>\b`（精确匹配 old_tag 的大小写形式）
- rename 后保持用户输入的大小写：`old=foo new=Bar` → 文件内 `#foo` → `#Bar`，DB 存 `Bar`

### 近似 tag 建议（需在 `storage.py` 实现 `suggest_similar_tag(old_tag)`）
```sql
-- 简单实现：编辑距离 ≤ 2 的候选
SELECT tag_name FROM tags WHERE deleted_at IS NULL
 AND ABS(LENGTH(tag_name) - LENGTH(?)) <= 2
 AND <edit_distance(tag_name, ?) <= 2
```
MVP 可用 `difflib.get_close_matches(old_tag, candidates, n=1, cutoff=0.6)` 实现。

---

## 8. 测试用例（T 级）

### Phase 1 测试（dry-run + Pre-flight）
- `test_rename_dry_run_no_db_write`：dry-run 后 DB 无变化
- `test_rename_dry_run_no_file_write`：dry-run 后文件无变化
- `test_rename_preflight_file_not_writable`：不可写文件提前失败
- `test_rename_batch_warning_gt_10`：>10 文件输出警告
- `test_rename_identical_tags`：old==new exit 0
- `test_rename_empty_tag`：空 tag exit 2

### Phase 2 测试（真实 rename）
- `test_rename_success_single_file`：单文件 rename 成功
- `test_rename_success_multiple_files`：多文件 rename 成功
- `test_rename_db_updated`：DB 中 old_tag 消失，new_tag 存在
- `test_rename_file_content_updated`：文件内 #old → #new
- `test_rename_case_preserving`：`foo → Foo` 后文件内为 `#Foo`
- `test_rename_atomic_write`：写入中途 kill 信号，源文件未损坏
- `test_rename_new_exists_force_merge`：force=True 时 merge 语义

### Phase 3 测试（Error + Rollback）
- `test_rename_file_write_failure_rollback`：文件写失败 DB 回滚
- `test_rename_partial_failure_exit2`：部分文件失败 exit 2
- `test_rename_db_lock_retry`：DB locked 时 retry 3 次后成功
- `test_rename_tag_not_found_exit3`：tag 不存在 exit 3
- `test_rename_suggestion_shown`：不存在时提示近似 tag

---

## 9. 不包含在 MVP 的内容

以下作为 v1.1 迭代项，**不在本 spec scope**：
- dry-run 显示完整 diff（前/后 YAML 对比）
- 文件系统层面完整原子性自动回滚
- 跨项目全局 rename
- glob 模式过滤（仅限当前 MVP `--glob` 过滤器）
- rename 操作的事务性审计日志