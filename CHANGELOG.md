# Changelog

All notable changes to this project will be documented in this file.

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
