"""SQLite storage layer for mdnotes."""

import os
import sqlite3
import time
from typing import Any, Optional

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    content    TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

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
    conn.execute(CREATE_TABLE_SQL)
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


def add_note(title: str, content: Optional[str] = None) -> int:
    """
    Insert a new note and return its integer id.

    Args:
        title: Note title (must be non-empty after stripping)
        content: Note body (may be empty string or None)

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
                "INSERT INTO notes (title, content) VALUES (?, ?)",
                (title, content),
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
