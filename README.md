# mdnotes

A simple CLI notes app with Markdown support, built with Click 8 + SQLite.

## Install

```bash
# Install from source
cd /path/to/mdnotes
pip install -e .

# Or use uv
uv pip install -e .
```

## Usage

```bash
mdnotes add "My Note Title" "Note content in **Markdown**"
mdnotes list
mdnotes list --search keyword
mdnotes show <id>
mdnotes delete <id>
mdnotes delete <id> --force
```

### Commands

| Command | Description |
|---|---|
| `add TITLE [CONTENT]` | Create a new note |
| `list` | List all notes (newest first) |
| `list --search KEYWORD` | Search notes by title/content (LIKE) |
| `show <id>` | Display note HTML (rendered) |
| `delete <id>` | Delete note by ID |
| `delete <id> --force` | Delete without confirmation |

## Deploy

```bash
# Local development install
pip install -e ".[dev]"

# Run tests
pytest -v --cov=src/mdnotes

# Lint
ruff check src/
```

## Architecture

- `src/mdnotes/cli.py` — Click 8 CLI commands
- `src/mdnotes/storage.py` — SQLite persistence (`~/.mdnotes.db`)
- `src/mdnotes/render.py` — Markdown → HTML rendering

## Version

v0.1.0-mvp — CRUD CLI MVP
