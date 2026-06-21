"""mdnotes CLI - Click-based command interface."""

import os
import re
from pathlib import Path
from typing import Optional

import click

from mdnotes import __version__
from mdnotes import render as render_mod
from mdnotes import storage


class MdnotesError(click.ClickException):
    """Base exception for mdnotes CLI errors with exit codes."""

    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


class ParamError(MdnotesError):
    """Exit code 2: invalid arguments."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=2)


class NotFoundError(MdnotesError):
    """Exit code 3: resource not found."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


class SystemError(MdnotesError):
    """Exit code 1: system-level errors."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=1)


@click.group()
@click.version_option(version=__version__)
def cli():
    """mdnotes - A simple CLI notes app with Markdown support."""
    pass


def _extract_title_from_content(content: str) -> str | None:
    """Extract title from # heading in markdown content (after frontmatter)."""
    import re
    if content.startswith('---'):
        end = content.find('\n---\n', 4)
        if end != -1:
            body = content[end + 4:].lstrip()
        else:
            body = content
    else:
        body = content.lstrip()
    # First # Heading
    m = re.match(r'^#\s+(.+)$', body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return None


def _add_single_file(file_path: Path) -> int:
    """Add a single .md file: index tags + create note. Returns note_id."""
    if not file_path.is_file() or not file_path.suffix == '.md':
        raise ParamError(f"Not a markdown file: {file_path}")

    try:
        file_content = file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as e:
        raise SystemError(f"cannot read file: {e}")

    # Extract title from frontmatter or first # heading
    note_title = _extract_title_from_content(file_content)
    if not note_title:
        note_title = file_path.stem  # fallback to filename without .md

    abs_path = str(file_path.resolve())

    # Index tags from the file (updates tags table + returns found tags)
    try:
        found_tags = storage.scan_and_index_file(abs_path)
    except storage.DatabaseError as e:
        raise SystemError(str(e))

    # Create note with file content + file_path for FTS5 tag JOIN
    try:
        note_id = storage.add_note(note_title, file_content, file_path=abs_path)
    except ValueError as e:
        raise ParamError(str(e))
    except storage.DatabaseError as e:
        raise SystemError(str(e))

    # Sync denormalized tags string to notes table → FTS5 UPDATE trigger fires
    if found_tags:
        tags_string = ",".join(sorted(found_tags))
        try:
            storage.set_note_tags(note_id, tags_string)
        except storage.DatabaseError as e:
            raise SystemError(str(e))

    return note_id


@cli.command()
@click.argument("files", nargs=-1, required=False)
def add(files: tuple[str, ...]):
    """Create a new note.

    With no CONTENT, FILES must be one or more .md file paths: each file is
    read, its tags (frontmatter + inline) are indexed, and a note is created.

    With CONTENT, FILES is a single TITLE and optional note CONTENT.

    Examples:
      mdnotes add /path/to/note.md          # add one file
      mdnotes add f1.md f2.md f3.md         # add multiple files
      mdnotes add "My Title" "My content"    # create by title + content
    """
    if not files:
        click.echo("Error: no arguments given", err=True)
        raise SystemExit(2)

    # --- File-path mode: first arg is a .md file ---
    if files[0].endswith('.md') and Path(files[0]).is_file():
        note_ids = []
        for file_path_str in files:
            fp = Path(file_path_str)
            if not fp.is_file() or not fp.suffix == '.md':
                click.echo(f"Warning: skipping non-.md or non-existent path: {fp}", err=True)
                continue
            try:
                note_id = _add_single_file(fp)
                note_ids.append(note_id)
                click.echo(f"Created note {note_id}", err=True)
            except SystemError as e:
                click.echo(f"Error: {e.message}", err=True)
                raise SystemExit(1)
            except ParamError as e:
                click.echo(f"Error: {e.message}", err=True)
                raise SystemExit(2)
        if not note_ids:
            click.echo("Error: no valid files added", err=True)
            raise SystemExit(1)
        raise SystemExit(0)

    # --- Normal title + content case ---
    if len(files) == 0:
        click.echo("Error: title cannot be empty", err=True)
        raise SystemExit(2)

    title = files[0].strip()
    content = files[1] if len(files) > 1 else ""

    if len(title) == 0:
        click.echo("Error: title cannot be empty", err=True)
        raise SystemExit(2)
    if len(title) > 200:
        click.echo("Error: title exceeds 200 characters", err=True)
        raise SystemExit(2)

    try:
        note_id = storage.add_note(title, content)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"Created note {note_id}", err=True)
    raise SystemExit(0)


@cli.command()
@click.option("--search", "search", default=None, help="Search keyword in title (LIKE)")
@click.option(
    "--sort",
    type=click.Choice(["created_at", "updated_at"], case_sensitive=False),
    default="created_at",
    help="Sort field",
)
@click.option(
    "--order",
    type=click.Choice(["asc", "desc"], case_sensitive=False),
    default="desc",
    help="Sort order",
)
def ls(search: Optional[str], sort: str, order: str):
    """List all notes, newest first by default."""
    try:
        notes = storage.list_notes(search=search, sort=sort, order=order)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    if not notes:
        click.echo("No notes yet.")
        raise SystemExit(0)

    for note in notes:
        click.echo(f"[{note['id']}] {note['title']} ({note['created_at']})")

    raise SystemExit(0)


@cli.command()
@click.argument("id")
def show(id: str):
    """Display a note with the given ID."""
    try:
        note_id = int(id)
    except ValueError:
        click.echo("Error: id must be an integer", err=True)
        raise SystemExit(2)

    try:
        note = storage.get_note(note_id)
    except ValueError:
        click.echo("Error: id must be an integer", err=True)
        raise SystemExit(2)
    except storage.NoteNotFoundError:
        click.echo("Note not found", err=True)
        raise SystemExit(3)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    rendered = render_mod.render_md(note["content"] or "")
    click.echo(f"Title: {note['title']}")
    click.echo(f"Created: {note['created_at']}")
    click.echo("----")
    # Output raw HTML for now (MVP - v1.0 will add --format plain)
    click.echo(rendered)
    raise SystemExit(0)


@cli.command()
@click.argument("id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def delete(id: str, force: bool):
    """Delete a note by ID."""
    try:
        note_id = int(id)
    except ValueError:
        click.echo("Error: id must be an integer", err=True)
        raise SystemExit(2)

    # Check existence first for idempotent behavior
    try:
        storage.get_note(note_id)
    except storage.NoteNotFoundError:
        click.echo("Note not found", err=True)
        raise SystemExit(3)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    if not force:
        click.echo(f"Delete note {note_id}? [y/N] ", err=True)
        try:
            response = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = "n"
        if response not in ("y", "yes"):
            raise SystemExit(0)

    try:
        storage.delete_note(note_id)
    except storage.NoteNotFoundError:
        click.echo("Note not found", err=True)
        raise SystemExit(3)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"Deleted note {note_id}", err=True)
    raise SystemExit(0)


@cli.command()
def count():
    """Count all active notes.

    Prints the total number of active (non-deleted) notes.
    Automatically initializes the database if it does not exist.
    """
    try:
        n = storage.count_notes()
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"Total notes: {n}")
    raise SystemExit(0)


# -----------------------------------------------------------------------
# tag subcommand group
# -----------------------------------------------------------------------

@cli.group()
def tag():
    """Manage tags."""
    pass


@tag.command()
@click.argument("old_tag")
@click.argument("new_tag")
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying files or DB")
@click.option("--force", is_flag=True, help="Allow new tag to already exist (merge semantics)")
@click.option(
    "--ignore-missing",
    is_flag=True,
    help="Exit 0 if old tag does not exist",
)
@click.option(
    "--glob",
    default=None,
    help="Only process files matching glob (e.g. '*.md')",
)
@click.option(
    "--exclude",
    multiple=True,
    help="Exclude files/paths matching this pattern (can repeat)",
)
@click.pass_context
def rename(ctx, old_tag, new_tag, dry_run, force, ignore_missing, glob, exclude):
    """
    Rename tag OLD_TAG to NEW_TAG across all notes.

    This renames the tag in both the database index and in the actual
    markdown files (frontmatter and inline occurrences).

    A backup snapshot of all affected files is created before the rename.
    If the rename fails, the backup is kept for manual recovery.
    """
    import shutil
    import time
    from pathlib import Path
    from dataclasses import dataclass, field

    # --- Parameter validation ---
    def _tag_ok(t: str) -> bool:
        return bool(t and t.strip() and not t.strip().isspace())

    if not _tag_ok(old_tag):
        click.echo("Error: tag name cannot be empty or whitespace", err=True)
        raise SystemExit(2)
    if not _tag_ok(new_tag):
        click.echo("Error: tag name cannot be empty or whitespace", err=True)
        raise SystemExit(2)

    old_tag = old_tag.strip()
    new_tag = new_tag.strip()

    # old == new (identical)
    if old_tag == new_tag:
        click.echo("No changes needed")
        raise SystemExit(0)

    # Case-only conflict
    if old_tag.lower() == new_tag.lower() and old_tag != new_tag:
        click.echo(
            f"Tag '#{old_tag}' would conflict with '#{new_tag}' "
            f"(case-insensitive)",
            err=True,
        )
        raise SystemExit(1)

    # --- Build options object ---
    @dataclass
    class TagRenameOpts:
        ignore_missing: bool = False
        force: bool = False
        dry_run: bool = False
        glob: str | None = None
        exclude: list = field(default_factory=list)

    opts = TagRenameOpts(
        ignore_missing=ignore_missing,
        force=force,
        dry_run=dry_run,
        glob=glob,
        exclude=list(exclude),
    )

    # --- Get affected files ---
    try:
        all_affected = storage.get_affected_files(old_tag)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    if not all_affected:
        if ignore_missing:
            click.echo("No changes needed")
            raise SystemExit(0)
        click.echo(f"Tag '#{old_tag}' not found", err=True)
        raise SystemExit(3)

    # --- Apply glob / exclude filters ---
    def _match(path: str) -> bool:
        p = Path(path)
        if opts.glob:
            if not p.match(opts.glob):
                return False
        for ex in opts.exclude:
            if p.match(ex):
                return False
        return True

    affected = [f for f in all_affected if _match(f)]

    if not affected:
        click.echo("No changes needed")
        raise SystemExit(0)

    # --- Batch warning ---
    if len(affected) > 10:
        click.echo(
            f"This will rename {len(affected)} files. Use --dry-run to preview.",
            err=True,
        )

    # === PHASE 1: DRY-RUN + PRE-FLIGHT (no side effects) ===
    if dry_run:
        click.echo(
            f"[DRY-RUN] Would rename '#{old_tag}' → '#{new_tag}' "
            f"in {len(affected)} files:",
            err=True,
        )
        for f in affected:
            click.echo(f"  - {f}", err=True)
        raise SystemExit(0)

    # --- Pre-flight: check file writability ---
    non_writable = [fp for fp in affected if not os.access(fp, os.W_OK)]
    if non_writable:
        for fp in non_writable:
            click.echo(f"Error: file not writable: {fp}", err=True)
        click.echo(
            f"Error: {len(non_writable)} file(s) not writable; aborting. "
            f"No changes made.",
            err=True,
        )
        raise SystemExit(1)

    # === PHASE 2: REAL RENAME ===
    # --- Backup snapshot ---
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_base = Path.home() / ".mdnotes"
    backup_dir = backup_base / f"rename_backup_{timestamp}"

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        for fp in affected:
            src = Path(fp)
            dest = backup_dir / src.name
            shutil.copy2(src, dest)
    except (OSError, shutil.Error) as e:
        shutil.rmtree(backup_dir, ignore_errors=True)
        click.echo(f"Error: backup snapshot failed: {e}", err=True)
        raise SystemExit(1)

    # --- Rename in DB ---
    db_count = 0
    try:
        db_count = storage.rename_tag(old_tag, new_tag, opts)
    except storage.TagNotFoundError:
        shutil.rmtree(backup_dir, ignore_errors=True)
        click.echo(f"Tag '#{old_tag}' not found", err=True)
        raise SystemExit(3)
    except storage.TagConflictError as e:
        shutil.rmtree(backup_dir, ignore_errors=True)
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    except storage.DatabaseError as e:
        shutil.rmtree(backup_dir, ignore_errors=True)
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    # --- Rename in files (frontmatter + inline) ---
    failed_files: list[str] = []

    for fp in affected:
        try:
            storage.rename_tag_in_file(fp, old_tag, new_tag)
        except OSError as e:
            failed_files.append(f"{fp}: {e}")

    # === PHASE 3: ERROR HANDLING + ROLLBACK ===
    # If any files failed, rollback DB and report
    if failed_files:
        # Rollback: restore files from backup, then rollback DB
        for fp in affected:
            src = Path(backup_dir) / Path(fp).name
            if src.exists():
                try:
                    shutil.copy2(src, fp)
                except OSError:
                    pass  # already failed
        # Try to rollback DB
        try:
            storage._get_connection(storage._get_db_path()).execute("ROLLBACK")
        except Exception:
            pass
        for err in failed_files:
            click.echo(f"Warning: {err}", err=True)
        click.echo(
            f"Renamed tag '#{old_tag}' → '#{new_tag}' in "
            f"{db_count} files ({len(failed_files)} files failed); "
            f"changes rolled back.",
            err=True,
        )
        raise SystemExit(2)

    # Success: cleanup backup
    shutil.rmtree(backup_dir, ignore_errors=True)
    click.echo(f"Renamed tag '#{old_tag}' → '#{new_tag}' in {db_count} files")
    raise SystemExit(0)


_TAG_ESCAPE_RE_SENTINEL = object()


def _build_tag_pattern(tag: str) -> re.Pattern:
    """Build a compiled regex that matches #tag at a word boundary."""
    # Escape special regex chars in the tag name
    escaped = re.escape(tag)
    # Word boundary: not preceded by alphanumeric (or start of string)
    # and not followed by alphanumeric
    return re.compile(
        r"(?<![a-zA-Z0-9])#" + escaped + r"\b",
        flags=re.MULTILINE,
    )


# -----------------------------------------------------------------------
# search command
# -----------------------------------------------------------------------

def _escape_fts5_special_char(token: str) -> str:
    """
    Escape FTS5 special characters in a token by wrapping in double quotes.

    FTS5 special characters: & | - ( ) " *
    Wrapping in "..." makes them literal text.
    """
    FTS5_SPECIAL = '&|-"()*'
    if any(c in token for c in FTS5_SPECIAL):
        # Escape each special char by wrapping token in double quotes
        # Double-quote the token (FTS5 literal string)
        return '"' + token + '"'
    return token


def _preprocess_query(raw_query: str) -> str:
    """
    Convert user query to FTS5 syntax.

    Unquoted → OR semantics (Google-style).
    Quoted ("...") → AND semantics.
    Special FTS5 chars (& | - " * etc.) are escaped so they're treated as
    literal text rather than FTS5 operators.
    """
    raw = raw_query.strip()
    if not raw:
        return raw
    # Detect quoted phrase: entire query wrapped in double quotes
    if raw.startswith('"') and raw.endswith('"') and len(raw) > 2:
        # Strip quotes → FTS5 AND semantics (inner content)
        return raw[1:-1]
    # Unquoted: split on whitespace → OR
    # Escape FTS5 special chars in each token so they're literal
    tokens = raw.split()
    escaped = [_escape_fts5_special_char(t) for t in tokens]
    return " ".join(escaped)


@cli.command()
@click.argument("query", required=False)
@click.option("--tag", "tag_filter", default=None, help="Filter by tag name (JOINs tags table)")
@click.option("--limit", default=100, help="Max results (default 100)")
@click.option("--check", "check_flag", is_flag=True, help="Check FTS5 index health")
@click.option("--rebuild", "rebuild_flag", is_flag=True, help="Rebuild FTS5 index from notes table")
def search(query: Optional[str], tag_filter: Optional[str], limit: int, check_flag: bool, rebuild_flag: bool):
    """
    Search notes by keyword using FTS5 full-text index.

    QUERY is the search phrase. Without quotes, uses OR semantics
    (e.g. "python redis" finds notes with python OR redis).
    With quotes, uses AND semantics ("python redis" finds both).

    Exit codes:
      0 = results found (or --check/--rebuild succeeded)
      1 = no results
      2 = error (missing query, FTS5 unavailable, etc.)

    Examples:
      mdnotes search python
      mdnotes search "python redis"
      mdnotes search --tag v1
      mdnotes search --check
      mdnotes search --rebuild
    """
    # Check FTS5 availability first
    if not storage._fts5_available():
        click.echo("Error: FTS5 is not available in this SQLite installation.", err=True)
        raise SystemExit(2)

    # --check: run health check (no query needed)
    if check_flag:
        try:
            storage.ensure_fts5()
        except storage.DatabaseError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(2)
        try:
            health = storage.check_fts5_health()
        except storage.DatabaseError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(2)
        consistent = health.get("consistent", False)
        orphaned = health.get("orphaned", 0)
        extra = health.get("extra", 0)
        if consistent:
            click.echo("FTS5 index is consistent.")
        else:
            click.echo("FTS5 index inconsistency detected:", err=True)
            click.echo(f"  orphaned FTS5 rows (no matching note): {orphaned}", err=True)
            click.echo(f"  notes without FTS5 entry: {extra}", err=True)
            click.echo("Run 'mdnotes search --rebuild' to fix.", err=True)
        raise SystemExit(0)

    # --rebuild: rebuild index (no query needed)
    if rebuild_flag:
        try:
            storage.ensure_fts5()
            storage.rebuild_fts5()
        except storage.DatabaseError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(2)
        click.echo("FTS5 index rebuilt successfully.")
        raise SystemExit(0)

    # Normal search path
    if not query or not query.strip():
        click.echo("Error: missing query argument.", err=True)
        click.echo("Usage: mdnotes search <query>", err=True)
        raise SystemExit(2)

    processed = _preprocess_query(query)

    try:
        storage.ensure_fts5()
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)

    try:
        results = storage.search_notes(processed, tag=tag_filter, limit=limit)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)

    if not results:
        click.echo("No results found.", err=True)
        raise SystemExit(1)

    # Display results
    for r in results:
        snippet = r["snippet"] or ""
        tags_str = r["tags"] or ""
        file_path = ""
        if r.get("file_path"):
            fp = r["file_path"]
            if " " in fp:
                file_path = f'"{fp}"'
            else:
                file_path = fp
        click.echo(f"{file_path}: {r['title']}")
        if snippet:
            click.echo(f"  {snippet}")
        if tags_str:
            click.echo(f"  tags: {tags_str}")

    raise SystemExit(0)


# -----------------------------------------------------------------------
# reindex command
# -----------------------------------------------------------------------

@cli.command()
@click.confirmation_option(prompt="Rebuild FTS5 index from scratch? ")
def reindex():
    """
    Rebuild the FTS5 full-text search index.

    Drops and recreates the notes_fts virtual table, then re-indexes
    all existing notes. Run this if search results seem out of sync.

    Examples:
      mdnotes reindex
    """
    if not storage._fts5_available():
        click.echo("Error: FTS5 is not available.", err=True)
        raise SystemExit(2)

    try:
        storage.ensure_fts5()
        storage.rebuild_fts5()
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)

    click.echo("FTS5 index rebuilt successfully.")
    raise SystemExit(0)


if __name__ == "__main__":
    cli()
