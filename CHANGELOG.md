# Changelog

All notable changes to this project will be documented in this file.

## [v1.0.1] — 2026-06-21

### Fixed
- **P95 latency**: `search` P95 从 183.6ms 降至 1.3ms（WAL + cache + mmap + idx_tags）
- **Search UX**: `mdnotes search` 无 query 时改为 exit 0 + 列出全部 notes（而非 exit 2）
- **Search UX**: `mdnotes search --tag <tag>` 无 query 时正确过滤（不再要求 query 参数）

### Added
- **`tests/test_cli_search.py`**: 新增 46 个测试，cli.py coverage 72% → 85%（v0.5 决策 3 ≥80% gate pass）
- **211 tests**: v1.0.1 全部通过 in 7.15s

### Technical Decisions
- ADR-0005/ADR-0006 继承（v1.0.0 技术基础不变）

### Review Notes
- Review verdict: pass（minor=3，不阻塞：tag-only search 无 ORDER BY / SPEC gap BC-1 / 46 vs 44 tests 数量差）
- QA P95=79.93ms ✅（target ≤100ms）

## [v1.0.0] — 2026-06-21

### Added
- **`search` CLI**: `mdnotes search <query>` FTS5 全文检索，支持 AND/OR 引号语义
- **`--tag` filter**: JOIN tags 表精确筛选（`tag_name = ? AND deleted_at IS NULL`）
- **`--check` health check**: FTS5 rowid 对照方案检测索引一致性
- **`--rebuild` index rebuild**: 原子在线重建 FTS5 索引，无 downtime
- **`--limit N`**: 最大返回 N 条，默认 100
- **BM25 排序**: `bm25(notes_fts, 10.0, 1.0, 1.0)` title 权重 10x
- **3 个 FTS5 trigger**: `notes_ai` / `notes_au` / `notes_ad` 保持索引同步
- **165 tests**: 22 unit + 11 integration，全部通过

### Technical Decisions
- ADR-0005: FTS5 vs LIKE 技术选型（最终采纳 FTS5）
- ADR-0006: search scope 决策（standalone FTS5 + manual trigger，SQLite 3.53.1 约束）

### Constraints
- SQLite 3.53.1: `content='notes'` 关联型 FTS5 auto-sync 不工作，降级为 standalone FTS5 + 3 manual trigger（功能等价）

### Test Coverage
- 165 tests pass
- storage.py FTS5 函数覆盖率 93.9%
- storage.py 整体覆盖率 86%

### Review Notes
- Review verdict: fail（1 critical C-1: spec gap — SPEC §Data Structures 未文档化 SQLite 3.53.1 约束）
- C-1 spec gap 已关闭：ADR-0005 + SPEC §Data Structures 已更新文档
- C-2/C-3/C-4: 全部修复 ✅

## [v0.1.0] — 2026-06-20

### Added
- **`tag rename` CLI**: `mdnotes tag rename <old> <new>` 支持 dry-run / --force / --ignore-missing / --glob / --exclude
- **Storage `rename_tag_in_file`**: 同时改 frontmatter YAML `tags:` 和 inline `#tag`
- **Storage `scan_and_index_file` add 时索引**: frontmatter + inline tag 双索引
- **CLI `add` 多文件支持**: `mdnotes add file1.md file2.md` (nargs='+')
- **CLI `list` → `ls`**: 避开 Python builtin shadowing (`list` keyword)
- **132 tests**: unit + multi-file 集成 + 边界覆盖

### Technical Decisions
- ADR-0001: dry-run MVP simplified rollback boundary preflight
- ADR-0002: rollback boundary preflight（CLI 层校验 before storage 层执行）

### Test Coverage
- 132 tests pass（task 3 v2 第 6 次尝试通过）
- Ruff: zero errors

## [v0.1.0-mvp] — 2026-06-18

### Added
- **CRUD CLI**: `add`, `list`, `show`, `delete` commands via Click 8
- **SQLite storage**: notes persisted in `~/.mdnotes.db` with WAL journal mode
- **`list --search`**: LIKE-based substring search across title + content
- **TDD test suite**: 62 tests covering core + supplementary scenarios (81% coverage)

### Changed
- Project structure: `src/mdnotes/{cli,storage,render}.py`
- Ruff linter pass with zero errors

### Technical Decisions
- ADR-0001: Markdown renderer (html2text pipeline)
- ADR-0002: SQLite WAL journal mode for concurrency
- ADR-0003: DB path `~/.mdnotes.db` (user-level, not repo-level)

## [v0.1.1] — 2026-06-19

### Added
- **`count` sub-command**: `mdnotes count` 输出 active notes 数量（`Total notes: N`）
- **auto-init behavior**: 无 DB 时自动初始化（`CREATE TABLE IF NOT EXISTS`）
- **`deleted_at` 字段**: v0.2 soft-delete 预留接口（`WHERE deleted_at IS NULL`）
- **PRD/SPEC/ADR-0004**: count sub-command 完整产品 + 技术文档

### Changed
- `tests/test_render.py` / `tests/test_storage.py`: 删除 unused import + variable

### Technical Decisions
- ADR-0004: count SQL 预埋 `deleted_at IS NULL` 条件，为 v0.2 soft-delete 预留接口（方案 B：惰性迁移）

### Test Coverage
- 70 tests pass (前 62 + count-specific 8)
- Coverage: 80% (硬门禁)
- Ruff: 全绿

## [v0.5-stage-close] — 2026-06-20

> **注**：v0.5 阶段是工作流方案验证阶段，过程已记录于 `docs/DECISIONS/0007-v1.0-retrospective.md`（v1.0 复盘）。本节不计入 release tag。
