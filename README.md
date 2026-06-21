# mdnotes

A fast CLI notes app with Markdown support, FTS5 full-text search, and tag-based filtering.

**Current version**: v1.0.1
**Status**: Stable — 211 tests pass, 86% coverage, 1.3ms P95 search latency

## Features

### v1.0.0+ (search)
- **FTS5 full-text search** — `mdnotes search <query>` with BM25 ranking (title weight 10x)
- **Tag filtering** — `mdnotes search --tag <tag>` precise JOIN filter
- **Health check** — `mdnotes search --check` verifies FTS5 index consistency
- **Online reindex** — `mdnotes search --rebuild` atomic rebuild with no downtime
- **Result limit** — `mdnotes search --limit N` (default 100)

### v0.1.1+ (count)
- **`count` sub-command** — `mdnotes count` returns total active notes
- **Auto-init** — DB auto-created on first use

### v0.1.0+ (tag operations)
- **`tag rename`** — `mdnotes tag rename <old> <new>` with `--dry-run` / `--force` / `--ignore-missing` / `--glob` / `--exclude`
- **Multi-file add** — `mdnotes add file1.md file2.md ...`

### v0.1.0-mvp (CRUD)
- **`add`** — create note with title + Markdown content
- **`list` / `ls`** — list all notes (newest first)
- **`show <id>`** — display note as HTML
- **`delete <id>`** — soft-aware delete (with `--force`)

## Install

```bash
# From source
git clone https://github.com/ylyuanlu/mdnotes.git
cd mdnotes
pip install -e ".[dev]"
# or
uv pip install -e ".[dev]"
```

## Usage

```bash
# Add a note
mdnotes add "My Note" "Content in **Markdown**"

# List all notes
mdnotes list

# Search by query (FTS5)
mdnotes search "meeting notes"

# Search by tag
mdnotes search --tag work

# Search + tag combined
mdnotes search "meeting" --tag work

# Count notes
mdnotes count

# Tag operations
mdnotes tag rename old-tag new-tag --dry-run

# Index management
mdnotes search --check    # verify FTS5 consistency
mdnotes search --rebuild  # atomic reindex
```

## Architecture

- **`src/mdnotes/cli.py`** — Click 8 CLI commands (~450 LoC)
- **`src/mdnotes/storage.py`** — SQLite + FTS5 persistence (~490 LoC)
- **`src/mdnotes/render.py`** — Markdown → HTML rendering

### Storage design
- **DB path**: `~/.mdnotes.db` (user-level, single DB)
- **Journal mode**: WAL (concurrent reads)
- **FTS5**: standalone table `notes_fts` + 3 manual triggers (`notes_ai` / `notes_au` / `notes_ad`)
- **Tags**: separate `tags` table with JOIN for filtering
- **Soft-delete**: `deleted_at` column reserved (v1.5+ feature)

## Development

```bash
# Run tests
pytest --cov=src --cov-report=term-missing --cov-fail-under=80

# Lint
ruff check src tests

# Type check (optional)
mypy src/mdnotes/
```

### Test coverage (v1.0.1)

| Module | Coverage |
|---|---|
| `cli.py` | 85% |
| `storage.py` | 87% |
| `render.py` | 100% |
| `__init__.py` | 100% |
| **Total** | **86%** |

**Test count**: 211 (unit + integration + CLI)

## CI/CD

GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push to main and every PR:

1. **lint** — `ruff check src tests`
2. **test (Python 3.10 / 3.11 / 3.12)** — `pytest --cov=src --cov-report=term-missing --cov-fail-under=80`
3. **demo-deploy** — echo deploy info on main

All checks must pass before merge.

## Performance

| Operation | P95 latency | Notes |
|---|---|---|
| `search` (single query) | 1.3ms | WAL + mmap + cache + idx_tags |
| `search` (with --tag) | 1.3ms | JOIN on tags table |
| `add` | ~5ms | Insert + 3 FTS5 triggers |
| `list` (1000 notes) | ~20ms | ORDER BY created_at DESC |

## Documentation

- `docs/PRD/` — Product Requirements (4 modules: cli-mvp, count-command, tag-rename, search-command)
- `docs/SPEC/` — Technical Specifications (4 modules)
- `docs/DECISIONS/` — Architecture Decision Records (ADR-0001 ~ ADR-0007)
- `CHANGELOG.md` — Release history

## License

MIT
