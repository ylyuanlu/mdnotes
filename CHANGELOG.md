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
