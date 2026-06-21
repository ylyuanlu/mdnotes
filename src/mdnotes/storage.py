"""SQLite storage layer for mdnotes."""

import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    content    TEXT,
    file_path  TEXT    DEFAULT NULL,
    tags       TEXT    DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

# FTS5 virtual table (stand-alone, not content= linked to notes)
# title + content + tag stored directly in FTS5 table.
# Sync maintained via manual triggers on notes CRUD.
ENSURE_FTS5_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title,
    content,
    tag,
    tokenize='unicode61'
);
"""

# Triggers fire on notes CRUD to keep FTS5 stand-alone table in sync.
# FTS5 rowid = notes.id (INTEGER PRIMARY KEY).
FTS5_TRIGGERS = [
    # INSERT: add new note to FTS5 (tag populated via separate UPDATE after set_note_tags)
    (
        "CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN "
        "INSERT INTO notes_fts(rowid, title, content, tag) "
        "VALUES (NEW.id, NEW.title, NEW.content, NEW.tags);"
        "END;"
    ),
    # UPDATE: delete old FTS5 entry + insert new one (for title/content/tags changes)
    (
        "CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN "
        "DELETE FROM notes_fts WHERE rowid = OLD.id; "
        "INSERT INTO notes_fts(rowid, title, content, tag) "
        "VALUES (NEW.id, NEW.title, NEW.content, NEW.tags);"
        "END;"
    ),
    # DELETE: remove FTS5 entry
    (
        "CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN "
        "DELETE FROM notes_fts WHERE rowid = OLD.id;"
        "END;"
    ),
]

# DB path resolution
_DB_DIR = os.path.expanduser("~/.mdnotes")
_DB_PATH = os.environ.get("MDNOTES_DB", os.path.join(_DB_DIR, "notes.db"))


def _get_db_path() -> str:
    """Return the resolved DB path."""
    return os.environ.get("MDNOTES_DB", os.path.join(_DB_DIR, "notes.db"))


def _ensure_dir(path: str) -> None:
    """Ensure the parent directory exists."""
    db_dir = os.path.dirname(path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def _get_connection(path: str) -> sqlite3.Connection:
    """Get a SQLite connection with the DB initialized."""
    _ensure_dir(path)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute(CREATE_TABLE_SQL)
    # Lazy migration: add tags and file_path columns if not exist
    try:
        conn.execute("ALTER TABLE notes ADD COLUMN tags TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE notes ADD COLUMN file_path TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Create tags table and index (split to avoid multi-statement warning)
    conn.execute("""
CREATE TABLE IF NOT EXISTS tags (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path  TEXT    NOT NULL,
    tag_name   TEXT    NOT NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_at TEXT    DEFAULT NULL
);
""")
    conn.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_file_tag
  ON tags(file_path, tag_name);
""")
    # Initialize FTS5 if not exists
    _ensure_fts5_conn(conn)
    return conn


def _retry_on_lock(func):
    """Decorator that retries on database locked errors with exponential backoff."""
    def wrapper(*args, **kwargs):
        retries = 3
        delays = [0.1, 0.2, 0.4]  # 100ms, 200ms, 400ms
        last_exc = None
        for attempt in range(retries):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    time.sleep(delays[attempt])
                    last_exc = e
                    continue
                raise
        if last_exc:
            raise last_exc
    return wrapper


class NoteNotFoundError(Exception):
    """Raised when a note with the given id does not exist."""
    pass


class DatabaseError(Exception):
    """Raised for database-level errors (corruption, write failure, etc.)."""
    pass


class TagNotFoundError(Exception):
    """Raised when the old tag does not exist in the database."""
    pass


class TagConflictError(Exception):
    """Raised when the rename would cause a tag conflict."""
    pass


class BackupError(Exception):
    """Raised when backup snapshot creation fails."""
    pass


# ---------------------------------------------------------------------------
# Tag-related functions
# ---------------------------------------------------------------------------

def add_tag(file_path: str, tag_name: str) -> None:
    """
    Add a (file_path, tag_name) entry to the tags table.
    Idempotent: duplicate inserts are ignored via INSERT OR IGNORE.
    Also updates the file's frontmatter to include the tag.

    Args:
        file_path: Absolute path to the .md file.
        tag_name: Tag name without the '#' prefix.

    Raises:
        DatabaseError: On SQLite write failure.
    """
    db_path = _get_db_path()

    @_retry_on_lock
    def _insert():
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT OR IGNORE INTO tags (file_path, tag_name) VALUES (?, ?)",
                (file_path, tag_name),
            )
            conn.commit()
        finally:
            conn.close()

    try:
        _insert()
    except sqlite3.Error as e:
        raise DatabaseError(f"Database error: {e}") from e

    # Also update the file's frontmatter
    _update_file_frontmatter(file_path, tag_name, mode="add")


def get_affected_files(tag_name: str, vault_path: str | None = None) -> list[str]:
    """
    Return a list of absolute file paths that contain the given tag.

    Args:
        tag_name: Tag name without the '#' prefix.
        vault_path: If provided, only return files within this vault directory.

    Returns:
        List of file paths (may be empty).
    """
    import os as _os
    db_path = _get_db_path()
    vault = vault_path or _os.environ.get("MDNOTES_VAULT")
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT DISTINCT file_path FROM tags "
            "WHERE tag_name = ? AND deleted_at IS NULL",
            (tag_name,),
        )
        paths = [row[0] for row in cursor.fetchall()]
        if vault:
            vault_prefix = vault.rstrip("/") + "/"
            paths = [p for p in paths if p.startswith(vault_prefix)]
        return paths
    finally:
        conn.close()


def rename_tag_in_file(file_path: str, old_tag: str, new_tag: str) -> bool:
    """
    Rename a tag in a markdown file's frontmatter and body.

    Updates the YAML frontmatter (tags: [old_tag, ...] → tags: [new_tag, ...])
    and replaces all inline #old_tag occurrences with #new_tag.

    Args:
        file_path: Absolute path to the .md file.
        old_tag: Current tag name (without '#').
        new_tag: Target tag name (without '#').

    Returns:
        True if the file was modified, False if no changes were needed.

    Raises:
        OSError: If the file cannot be read or written.
    """
    import os as _os

    if not _os.path.isfile(file_path):
        return False

    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    original = content

    # --- Replace inline #old_tag → #new_tag ---
    tag_pattern = _build_tag_pattern_re(old_tag)
    content, n_inline = tag_pattern.subn(f"#{new_tag}", content)

    # --- Replace frontmatter tags ---
    content = _replace_frontmatter_tag(content, old_tag, new_tag)

    if content == original:
        return False

    # Atomic write
    tmp = Path(file_path).with_suffix(Path(file_path).suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, file_path)
    return True


def _build_tag_pattern_re(tag: str):
    """Build a compiled regex that matches #tag at a word boundary."""
    escaped = re.escape(tag)
    return re.compile(
        r"(?<![a-zA-Z0-9])#" + escaped + r"\b",
        flags=re.MULTILINE,
    )


def _replace_frontmatter_tag(content: str, old_tag: str, new_tag: str) -> str:
    """
    Replace old_tag → new_tag inside the YAML frontmatter tags array.

    Handles: tags: [old_tag]         → tags: [new_tag]
             tags: [old_tag, other]  → tags: [new_tag, other]
             tags: [other, old_tag]  → tags: [other, new_tag]

    Returns the content unchanged if no frontmatter or no tags array matches.
    """
    import re as _re

    if not content.startswith("---"):
        return content

    end = content.find("\n---\n", 4)
    if end == -1:
        return content

    frontmatter = content[3:end]
    body = content[end + 4:]

    # Check if old_tag is actually in the frontmatter tags array
    if not _FRONTMATTER_TAG_RE.search(frontmatter):
        return content

    # Check if the tags array contains old_tag (before substitution)
    inner_match = _FRONTMATTER_TAG_RE.match(frontmatter.strip())
    if not inner_match:
        return content

    inner = inner_match.group(1)
    escaped_old = _re.escape(old_tag)
    # Check if old_tag is present in the array
    tag_check_re = _re.compile(r"(^|, )" + escaped_old + r"(?![a-zA-Z0-9_-])")
    if not tag_check_re.search(inner):
        return content  # old_tag not in this tags array

    # Perform replacement
    new_inner = tag_check_re.sub(lambda m: (m.group(1) or "") + new_tag, inner)
    new_tags_line = f"tags: [{new_inner}]"

    # Reconstruct frontmatter with the new tags line
    # Replace only the tags line (first match in frontmatter)
    new_frontmatter = _FRONTMATTER_TAG_RE.sub(new_tags_line, frontmatter, count=1)

    # frontmatter may have leading newline from split; strip it for clean output
    new_frontmatter = new_frontmatter.lstrip("\n")

    return "---\n" + new_frontmatter + "\n---\n" + body


def rename_tag(
    old_tag: str,
    new_tag: str,
    options: Optional[Any] = None,
) -> int:
    """
    Rename all occurrences of old_tag to new_tag in the tags table.

    Args:
        old_tag: Current tag name.
        new_tag: Target tag name.
        options: TagRenameOptions dataclass (or duck-typed object) with fields:
            - ignore_missing: bool  (default False)
            - force: bool           (default False)

    Returns:
        Number of affected files.

    Raises:
        TagNotFoundError: old_tag does not exist (and ignore_missing=False).
        TagConflictError: new_tag already exists (and force=False), or
                          old/new differ only by case.
        DatabaseError: On SQLite write failure.
    """
    # Normalise options
    if options is None:
        class _Opts:
            ignore_missing = False
            force = False
            dry_run = False
            glob = None
            exclude = None
        options = _Opts()

    ignore_missing = getattr(options, "ignore_missing", False)
    force = getattr(options, "force", False)

    db_path = _get_db_path()

    @_retry_on_lock
    def _rename():
        conn = _get_connection(db_path)

        # --- Pre-checks ---
        # Check old_tag exists
        cursor = conn.execute(
            "SELECT COUNT(*) FROM tags WHERE tag_name = ? AND deleted_at IS NULL",
            (old_tag,),
        )
        old_count = cursor.fetchone()[0]

        if old_count == 0:
            conn.close()
            if ignore_missing:
                return 0
            raise TagNotFoundError(f"Tag '{old_tag}' not found")

        # Case-insensitive conflict check (old != new but same letters)
        if old_tag.lower() == new_tag.lower() and old_tag != new_tag:
            conn.close()
            raise TagConflictError(
                f"Tag '#{old_tag}' would conflict with existing tag '#{new_tag}' "
                f"(case-insensitive)"
            )

        # If new already exists and force=False, it's a conflict
        cursor = conn.execute(
            "SELECT COUNT(*) FROM tags WHERE tag_name = ? AND deleted_at IS NULL",
            (new_tag,),
        )
        new_exists = cursor.fetchone()[0] > 0

        if new_exists and not force:
            conn.close()
            raise TagConflictError(
                f"Tag '#{new_tag}' already exists; use --force to merge"
            )

        # --- Execute rename in a transaction ---
        conn.execute("BEGIN IMMEDIATE")
        try:
            # UPDATE existing new_tag rows to also be reachable (merge = keep both tags)
            # For force mode: INSERT OR IGNORE handles duplicates
            conn.execute(
                "INSERT OR IGNORE INTO tags (file_path, tag_name) "
                "SELECT file_path, ? FROM tags "
                "WHERE tag_name = ? AND deleted_at IS NULL",
                (new_tag, old_tag),
            )
            # DELETE old_tag rows
            conn.execute(
                "DELETE FROM tags WHERE tag_name = ? AND deleted_at IS NULL",
                (old_tag,),
            )
            conn.commit()

            # Count affected files
            cursor = conn.execute(
                "SELECT COUNT(DISTINCT file_path) FROM tags WHERE tag_name = ?",
                (new_tag,),
            )
            count = cursor.fetchone()[0]
            return count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    try:
        return _rename()
    except sqlite3.Error as e:
        raise DatabaseError(f"Database error: {e}") from e


def _update_file_frontmatter(file_path: str, tag_name: str, mode: str = "add") -> None:
    """
    Update the YAML frontmatter of a markdown file to add or remove a tag.

    Args:
        file_path: Absolute path to the .md file.
        tag_name: Tag name without the '#' prefix.
        mode: "add" to insert the tag, "remove" to delete it, "replace" to replace all occurrences.

    Does nothing if the file does not exist or has no frontmatter.
    """
    import os as _os

    if not _os.path.isfile(file_path):
        return

    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    if not content.startswith("---"):
        return

    end = content.find("\n---\n", 4)
    if end == -1:
        return

    frontmatter = content[3:end]
    body = content[end + 4:]

    # Try to update tags: [...] in frontmatter
    if mode == "replace":
        # Replace mode: should not reach here; caller should use rename_tag_in_file
        return
    else:
        new_frontmatter, n = _FRONTMATTER_TAG_RE.subn(
            lambda m: _update_tags_array(m.group(0), tag_name, mode),
            frontmatter,
        )

        if n == 0 and mode == "add":
            # No tags: [...] line yet — inject after the first line of frontmatter
            first_newline = frontmatter.find("\n")
            if first_newline == -1:
                # Single-line frontmatter (unlikely); append at end
                new_frontmatter = frontmatter + f"\ntags: [{tag_name}]\n"
            else:
                # Insert tags line after the first line
                new_frontmatter = (
                    frontmatter[:first_newline]
                    + f"\ntags: [{tag_name}]"
                    + frontmatter[first_newline:]
                )

    new_content = "---" + new_frontmatter + "\n---\n" + body

    try:
        Path(file_path).write_text(new_content, encoding="utf-8")
    except OSError:
        pass


def _update_tags_array(tag_line: str, tag_name: str, mode: str) -> str:
    """
    Given a 'tags: [a, b]' frontmatter line, add or remove tag_name.

    Returns the updated line string.
    """
    import re as _re

    inner_match = _re.match(r"^tags:\s*\[(.*)\]", tag_line.strip())
    if not inner_match:
        return tag_line

    inner = inner_match.group(1).strip()
    if not inner:
        # Empty list: [  ]
        return f"tags: [{tag_name}]"

    tags = [t.strip() for t in inner.split(",")]

    if mode == "add":
        if tag_name not in tags:
            tags.append(tag_name)
    elif mode == "remove":
        tags = [t for t in tags if t != tag_name]

    return f"tags: [{', '.join(tags)}]"


def _replace_tag_in_array(line: str, old_tag: str, new_tag: str) -> str:
    """
    Given a 'tags: [a, b]' line, replace old_tag with new_tag in the array.

    Handles both first-tag (no leading comma/space) and subsequent-tag cases.
    Returns the updated line string.
    """
    import re as _re

    inner_match = _re.match(r"^tags:\s*\[(.*)\]", line.strip())
    if not inner_match:
        return line

    inner = inner_match.group(1)
    escaped_old = _re.escape(old_tag)
    # Match old_tag as first element (^old_tag) or after comma+space (, old_tag)
    tag_re = _re.compile(
        r"(^|, )" + escaped_old + r"(?![a-zA-Z0-9_-])"
    )
    new_inner = tag_re.sub(lambda m: (m.group(1) or "") + new_tag, inner)

    return f"tags: [{new_inner}]"


# ---------------------------------------------------------------------------
# Tag scanning from markdown files
# ---------------------------------------------------------------------------

_FRONTMATTER_TAG_RE = re.compile(r'^tags:\s*\[([^\]]+)\]', re.MULTILINE)
_INLINE_TAG_RE = re.compile(r'(?<![a-zA-Z0-9])#([a-zA-Z][a-zA-Z0-9_-]*)\b')


def _extract_tags_from_content(content: str) -> list[str]:
    """
    Extract all tag names from markdown content.

    Checks YAML frontmatter first (tags: [a, b]), then falls back to
    scanning inline #tag occurrences in the rest of the content.
    """
    tags: set[str] = set()

    # Split off frontmatter
    if content.startswith('---'):
        end = content.find('\n---\n', 4)
        if end != -1:
            frontmatter = content[3:end]
            body = content[end + 4:]
            m = _FRONTMATTER_TAG_RE.match(frontmatter.strip())
            if m:
                for t in m.group(1).split(','):
                    tags.add(t.strip())
        else:
            body = content
    else:
        body = content

    # Inline tags in body
    for m in _INLINE_TAG_RE.finditer(body):
        tags.add(m.group(1))

    return list(tags)


def scan_and_index_file(file_path: str) -> list[str]:
    """
    Scan a markdown file for tags (frontmatter + inline) and update the DB.

    Removes any previously indexed tags for this file and re-adds the current set.

    Args:
        file_path: Absolute path to the .md file.

    Returns:
        List of tag names found in the file.
    """
    path = Path(file_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    tags = _extract_tags_from_content(content)

    db_path = _get_db_path()

    @_retry_on_lock
    def _update():
        conn = _get_connection(db_path)
        try:
            # Soft-delete old tags for this file
            conn.execute(
                "UPDATE tags SET deleted_at = datetime('now', 'localtime') "
                "WHERE file_path = ?",
                (str(path),),
            )
            # Insert current tags
            for tag in tags:
                conn.execute(
                    "INSERT OR IGNORE INTO tags (file_path, tag_name) VALUES (?, ?)",
                    (str(path), tag),
                )
            conn.commit()
        finally:
            conn.close()

    try:
        _update()
    except sqlite3.Error as e:
        raise DatabaseError(f"Database error: {e}") from e

    return tags


# ---------------------------------------------------------------------------
# Note CRUD (existing)
# ---------------------------------------------------------------------------

def add_note(title: str, content: Optional[str] = None, file_path: Optional[str] = None) -> int:
    """
    Insert a new note and return its integer id.

    Args:
        title: Note title (must be non-empty after stripping)
        content: Note body (may be empty string or None)
        file_path: Optional source file path (for FTS5 tag JOIN with tags table)

    Returns:
        The integer id of the newly created note

    Raises:
        ValueError: If title is empty or too long (> 200 chars after strip)
        DatabaseError: On SQLite write failure or corruption
    """
    title = title.strip()
    if len(title) == 0:
        raise ValueError("title cannot be empty")
    if len(title) > 200:
        raise ValueError("title exceeds 200 characters")

    content = content or ""

    db_path = _get_db_path()

    @_retry_on_lock
    def _insert():
        conn = _get_connection(db_path)
        try:
            cursor = conn.execute(
                "INSERT INTO notes (title, content, file_path) VALUES (?, ?, ?)",
                (title, content, file_path),
            )
            conn.commit()
            _check_integrity(conn)
            return cursor.lastrowid
        finally:
            conn.close()

    try:
        note_id = _insert()
    except sqlite3.Error as e:
        raise DatabaseError(f"Database error: {e}") from e

    return note_id


def get_note(note_id: int) -> dict[str, Any]:
    """
    Retrieve a single note by id.

    Args:
        note_id: Integer note id

    Returns:
        Dict with keys: id, title, content, created_at, updated_at

    Raises:
        NoteNotFoundError: If no note with this id exists
        ValueError: If note_id is not a valid integer
    """
    if not isinstance(note_id, int):
        raise ValueError("id must be an integer")

    db_path = _get_db_path()
    conn = _get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT id, title, content, created_at, updated_at FROM notes WHERE id = ?",
            (note_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if row is None:
        raise NoteNotFoundError(f"Note {note_id} not found")

    return {
        "id": row[0],
        "title": row[1],
        "content": row[2],
        "created_at": row[3],
        "updated_at": row[4],
    }


def list_notes(
    search: Optional[str] = None,
    sort: str = "created_at",
    order: str = "desc",
) -> list[dict[str, Any]]:
    """
    List all notes, optionally filtered and sorted.

    Args:
        search: If provided, filter by title LIKE '%search%'
        sort: Sort field ("created_at" or "updated_at")
        order: Sort direction ("asc" or "desc")

    Returns:
        List of dicts with keys: id, title, content, created_at, updated_at
    """
    if sort not in ("created_at", "updated_at"):
        sort = "created_at"
    if order not in ("asc", "desc"):
        order = "desc"

    db_path = _get_db_path()
    conn = _get_connection(db_path)
    try:
        if search:
            cursor = conn.execute(
                f"SELECT id, title, content, created_at, updated_at "
                f"FROM notes WHERE title LIKE ? ORDER BY {sort} {order.upper()}",
                (f"%{search}%",),
            )
        else:
            cursor = conn.execute(
                f"SELECT id, title, content, created_at, updated_at "
                f"FROM notes ORDER BY {sort} {order.upper()}",
            )
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "created_at": row[3],
            "updated_at": row[4],
        }
        for row in rows
    ]


def delete_note(note_id: int, force: bool = False) -> None:
    """
    Physically delete a note by id and VACUUM the database.

    Args:
        note_id: Integer note id
        force: Ignored (kept for API compatibility)

    Raises:
        NoteNotFoundError: If no note with this id exists (idempotent: exit 3)
        ValueError: If note_id is not a valid integer
        DatabaseError: On SQLite error
    """
    if not isinstance(note_id, int):
        raise ValueError("id must be an integer")

    db_path = _get_db_path()

    @_retry_on_lock
    def _delete():
        conn = _get_connection(db_path)
        try:
            cursor = conn.execute(
                "SELECT id FROM notes WHERE id = ?",
                (note_id,),
            )
            row = cursor.fetchone()
            if row is None:
                conn.close()
                raise NoteNotFoundError(f"Note {note_id} not found")
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()
            _check_integrity(conn)
            # VACUUM to reclaim disk space
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()

    try:
        _delete()
    except NoteNotFoundError:
        raise
    except sqlite3.Error as e:
        raise DatabaseError(f"Database error: {e}") from e


def count_notes() -> int:
    """
    Return the number of active (non-deleted) notes.

    Active notes are those with deleted_at IS NULL.
    On first call, performs lazy migration to add the deleted_at column.

    Returns:
        Non-negative integer count of active notes

    Raises:
        DatabaseError: On SQLite error
    """
    db_path = _get_db_path()

    @_retry_on_lock
    def _count():
        conn = _get_connection(db_path)
        try:
            # Lazy migration: ensure deleted_at column exists (idempotent)
            try:
                conn.execute("ALTER TABLE notes ADD COLUMN deleted_at TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
            cursor = conn.execute(
                "SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL"
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    try:
        return _count()
    except sqlite3.Error as e:
        raise DatabaseError(f"Database error: {e}") from e


def _check_integrity(conn: sqlite3.Connection) -> None:
    """
    Run PRAGMA integrity_check and raise DatabaseError on corruption.

    Args:
        conn: Active sqlite3 connection (inside transaction or after commit)
    """
    cursor = conn.execute("PRAGMA integrity_check")
    result = cursor.fetchone()
    if result is None or result[0] != "ok":
        # Run quick_check as second opinion
        cursor2 = conn.execute("PRAGMA quick_check")
        result2 = cursor2.fetchone()
        if result2 is None or result2[0] != "ok":
            raise DatabaseError("Database corrupted")


# ---------------------------------------------------------------------------
# FTS5 full-text search
# ---------------------------------------------------------------------------

def _fts5_available() -> bool:
    """Check if SQLite FTS5 module is available."""
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False


def _ensure_fts5_conn(conn: sqlite3.Connection) -> None:
    """Initialize FTS5 virtual table and triggers on an existing connection."""
    if not _fts5_available():
        raise DatabaseError("FTS5 is not available in this SQLite installation")
    conn.execute(ENSURE_FTS5_SQL)
    for trigger_sql in FTS5_TRIGGERS:
        try:
            conn.execute(trigger_sql)
        except sqlite3.OperationalError:
            pass  # trigger already exists
    conn.commit()


def ensure_fts5() -> None:
    """
    Ensure FTS5 virtual table and triggers exist (idempotent).

    Raises:
        DatabaseError: If FTS5 is not available
    """
    if not _fts5_available():
        raise DatabaseError("FTS5 is not available in this SQLite installation")
    db_path = _get_db_path()

    @_retry_on_lock
    def _ensure():
        conn = _get_connection(db_path)
        try:
            _ensure_fts5_conn(conn)
        finally:
            conn.close()

    _ensure()


def set_note_tags(note_id: int, tags_string: str) -> None:
    """
    Update the tags column of a note and sync to FTS5 via UPDATE trigger.

    Args:
        note_id: Integer note id
        tags_string: Comma-separated tag string (e.g. "python,redis,v1")

    Raises:
        NoteNotFoundError: If note does not exist
        DatabaseError: On SQLite error
    """
    if not isinstance(note_id, int):
        raise ValueError("note_id must be an integer")
    db_path = _get_db_path()

    @_retry_on_lock
    def _update():
        conn = _get_connection(db_path)
        try:
            # Check note exists
            cursor = conn.execute("SELECT id FROM notes WHERE id = ?", (note_id,))
            if cursor.fetchone() is None:
                conn.close()
                raise NoteNotFoundError(f"Note {note_id} not found")
            conn.execute("UPDATE notes SET tags = ? WHERE id = ?", (tags_string, note_id))
            conn.commit()
        finally:
            conn.close()

    try:
        _update()
    except NoteNotFoundError:
        raise
    except sqlite3.Error as e:
        raise DatabaseError(f"Database error: {e}") from e


def search_notes(
    query: str,
    tag: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Search notes using FTS5 full-text index.

    Args:
        query: FTS5 query string. Unquoted → OR semantics, quoted → AND semantics.
               Special chars & | - " * are passed as-is (FTS5 handles them).
        tag: If provided, filter to notes with this exact tag_name via JOIN on tags table.
        limit: Maximum number of results to return (default 100).

    Returns:
        List of dicts with keys: id, title, content, tags, snippet, score, file_path.
        Empty list if no results.

    Raises:
        DatabaseError: On FTS5 errors
    """
    if not query or not query.strip():
        if not tag:
            return []
        query = ""

    query = query.strip()
    db_path = _get_db_path()

    @_retry_on_lock
    def _search():
        conn = _get_connection(db_path)
        try:
            if tag:
                # JOIN tags table for exact tag_name match (per spec)
                # FTS5 query is the user query; tags table does exact filter
                fts5_query = query if query else "*"
                sql = """
                SELECT n.id, n.title, n.content, n.tags,
                       snippet(notes_fts, 1, '<mark>', '</mark>', '...', 32) AS snippet,
                       bm25(notes_fts, 10.0, 1.0, 1.0) AS score,
                       n.file_path
                FROM notes n
                JOIN notes_fts f ON n.id = f.rowid
                JOIN tags t ON t.file_path = n.file_path
                WHERE notes_fts MATCH ?
                  AND t.tag_name = ?
                  AND t.deleted_at IS NULL
                ORDER BY score
                LIMIT ?
                """
                cursor = conn.execute(sql, (fts5_query, tag, limit))
            else:
                sql = """
                SELECT n.id, n.title, n.content, n.tags,
                       snippet(notes_fts, 1, '<mark>', '</mark>', '...', 32) AS snippet,
                       bm25(notes_fts, 10.0, 1.0, 1.0) AS score,
                       n.file_path
                FROM notes n
                JOIN notes_fts f ON n.id = f.rowid
                WHERE notes_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """
                cursor = conn.execute(sql, (query, limit))

            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append({
                    "id": row[0],
                    "title": row[1],
                    "content": row[2],
                    "tags": row[3] or "",
                    "snippet": row[4] or "",
                    "score": row[5],
                    "file_path": row[6] or "",
                })
            return results
        finally:
            conn.close()

    try:
        return _search()
    except sqlite3.Error as e:
        raise DatabaseError(f"FTS5 search error: {e}") from e


def check_fts5_health() -> dict[str, Any]:
    """
    Check FTS5 index health via rowid consistency check.

    Returns:
        Dict with keys: consistent (bool), orphaned (int), extra (int)
    """
    db_path = _get_db_path()

    @_retry_on_lock
    def _check():
        conn = _get_connection(db_path)
        try:
            # Find rowids in notes_fts that have no matching notes row
            orphaned = conn.execute("""
                SELECT COUNT(*) FROM notes_fts f
                WHERE NOT EXISTS (SELECT 1 FROM notes n WHERE n.id = f.rowid)
            """).fetchone()[0]

            # Find notes rows with no FTS5 entry
            extra = conn.execute("""
                SELECT COUNT(*) FROM notes n
                WHERE NOT EXISTS (SELECT 1 FROM notes_fts f WHERE f.rowid = n.id)
            """).fetchone()[0]

            consistent = (orphaned == 0 and extra == 0)
            return {"consistent": consistent, "orphaned": orphaned, "extra": extra}
        finally:
            conn.close()

    try:
        return _check()
    except sqlite3.Error as e:
        raise DatabaseError(f"FTS5 health check error: {e}") from e


def rebuild_fts5() -> None:
    """
    Rebuild FTS5 index atomically (drop and recreate from notes table).

    This is an online rebuild: drops the old FTS5 table and recreates it
    by re-inserting all notes. FTS5 triggers ensure consistency.

    Raises:
        DatabaseError: On SQLite errors
    """
    db_path = _get_db_path()

    @_retry_on_lock
    def _rebuild():
        conn = _get_connection(db_path)
        try:
            # Drop existing FTS5 triggers first
            conn.execute("DROP TRIGGER IF EXISTS notes_ai")
            conn.execute("DROP TRIGGER IF EXISTS notes_au")
            conn.execute("DROP TRIGGER IF EXISTS notes_ad")
            # Drop existing FTS5 virtual table
            conn.execute("DROP TABLE IF EXISTS notes_fts")
            conn.commit()

            # Recreate FTS5 table
            _ensure_fts5_conn(conn)

            # Reinsert all notes into FTS5
            cursor = conn.execute(
                "SELECT id, title, content, tags FROM notes"
            )
            for row in cursor.fetchall():
                conn.execute(
                    "INSERT INTO notes_fts(rowid, title, content, tag) VALUES (?, ?, ?, ?)",
                    (row[0], row[1], row[2], row[3] or ""),
                )
            conn.commit()
        finally:
            conn.close()

    try:
        _rebuild()
    except sqlite3.Error as e:
        raise DatabaseError(f"FTS5 rebuild error: {e}") from e
