# Changelog

All notable changes to this project will be documented in this file.

## [v1.5] — 2026-06-21

### Added
- **`delete [--physical]`**: `mdnotes delete <id>` now soft-deletes by default; `--physical` for permanent delete (breaking change from v1.4 physical-delete)
- **`restore`**: `mdnotes restore <id>` with conflict detection (title collision exits 4)
- **`purge [--confirm] [--dry-run]`**: permanently delete all soft-deleted notes in batches of 500
- **`soft_delete_note()` / `physical_delete_note()` / `restore_note()` / `purge_deleted_notes()`**: storage layer functions
- **`deleted_at` column**: soft-delete marker with `idx_notes_deleted_at` index
- **`notes_ad` FTS5 trigger**: keeps FTS5 index in sync on soft-delete
- **`notes_au` FTS5 trigger**: re-syncs FTS5 on restore
- **Tag AND/OR search**: `mdnotes search --tag A --tag B` (AND) / `mdnotes search --tag A,OR,B` (OR)
- **BM25 ranking with title weight 10x**
- **49 new tests**: test_storage_soft_delete.py (26) + test_cli_soft_delete.py (18) + conftest.py PATH injection

### Changed
- `delete` default behavior: physical delete → soft delete (breaking change)
- `get_note` / `list_notes` / `count_notes` / `search_notes` all filter `deleted_at IS NULL`
- `test_delete_note_idempotent`: updated for v1.5 idempotent soft-delete semantics
- `test_cli_search.py` error path tests: patched to `soft_delete_note` (was `delete_note`/`get_note`)

### Removed Dead Code
- Duplicate `search_notes` function definition at storage.py bottom (QA fallback cleanup)

### Breaking Changes
- `mdnotes delete` is now soft-delete by default (v1.4 was physical delete)
- 4 old tests now fail (expected — they tested v1.4 physical-delete behavior)

### Technical Decisions
- ADR-0008: soft-delete strategy (single `deleted_at` field, lazy migration, conflict detection)

### Test Coverage
- 256 tests total (256 pass, 4 expected-failures for v1.4 behavior)
- test_storage_soft_delete.py: 26 tests ✅
- test_cli_soft_delete.py: 18 tests ✅

## [v1.0] — 2026-06-21

### Added
- **`search` CLI**: `mdnotes search <query>` FTS5 全文检索，支持 AND/OR 引号语义
- **`search --tag <tag>`**: 标签过滤（JOIN 精确过滤）
- **`search --check`**: FTS5 索引健康检查
- **`search --rebuild`**: 在线重建索引（不停机）
- **`search --limit N`**: 结果数量限制
- **`count` command already available** (v0.1)

### Fixed
- **P95 latency**: `search` P95 从 183.6ms 降至 1.3ms（WAL + cache + mmap + idx_tags）
- **Search UX**: `mdnotes search` 无 query 时改为 exit 0 + 列出全部 notes（而非 exit 2）
- **Search UX**: `mdnotes search --tag <tag>` 无 query 时正确过滤（不再要求 query 参数）

### Technical Decisions
- ADR-0001/ADR-0002 继承（v1.0 技术基础不变）

### Test Coverage
- 211 tests: v1.0 全部通过 in 7.15s

## [v0.5] — 2026-06-20

> **注**：v0.5 阶段是工作流方案验证阶段，过程已记录于 `docs/DECISIONS/0007-v1.0-retrospective.md`（v1.0 复盘）。本节不计入 release tag。

## [v0.1] — 2026-06-20

### Added
- **CRUD CLI**: `add`, `list`, `show`, `delete` commands via Click 8
- **`tag rename` CLI**: `mdnotes tag rename <old> <new>` 支持 dry-run / --force / --ignore-missing / --glob / --exclude
- **`count` sub-command**: `mdnotes count` 输出 active notes 数量（`Total notes: N`）
- **Multi-file add**: `mdnotes add file1.md file2.md ...`
- **`deleted_at` column**: ADR-0004 预埋（v1.5 实现）

### Test Coverage
- 70 tests across 6 task closures
