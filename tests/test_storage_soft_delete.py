"""Unit tests for soft-delete, restore, purge, and search v1.5 features in storage.py."""

import os
import tempfile
import pytest
from mdnotes import storage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _TestDB:
    """Shared test DB setup/teardown via context manager."""

    def __init__(self):
        self._orig = storage._get_db_path()
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "notes.db")
        self.env_patch = None

    def __enter__(self):
        os.environ["MDNOTES_DB"] = self.db_path
        # Reset any cached connection
        storage._get_db_path.cache_clear() if hasattr(storage._get_db_path, 'cache_clear') else None
        # Bootstrap DB
        storage._get_connection(self.db_path)
        return self

    def __exit__(self, *args):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# soft_delete_note
# ---------------------------------------------------------------------------

class TestSoftDeleteNote:
    """storage.soft_delete_note() behavior per spec §4.1."""

    def test_soft_delete_sets_deleted_at(self):
        """soft_delete sets deleted_at on the note."""
        with _TestDB() as ctx:
            note_id = storage.add_note("To soft-delete", "content")
            storage.soft_delete_note(note_id)
            conn = storage._get_connection(ctx.db_path)
            row = conn.execute(
                "SELECT deleted_at FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
            conn.close()
            assert row is not None
            assert row[0] is not None  # UTC timestamp set

    def test_soft_delete_idempotent(self):
        """soft_delete is idempotent: calling twice succeeds (exit 0)."""
        with _TestDB():
            note_id = storage.add_note("Idempotent delete", "content")
            storage.soft_delete_note(note_id)  # first call
            storage.soft_delete_note(note_id)  # second call — should not raise

    def test_soft_delete_nonexistent_raises(self):
        """soft_delete on non-existent id raises NoteNotFoundError."""
        with _TestDB():
            with pytest.raises(storage.NoteNotFoundError):
                storage.soft_delete_note(99999)

    def test_soft_delete_active_note_excluded_from_list(self):
        """After soft-delete, note does not appear in list_notes."""
        with _TestDB():
            note_id = storage.add_note("Will be hidden", "content")
            storage.soft_delete_note(note_id)
            notes = storage.list_notes()
            ids = [n["id"] for n in notes]
            assert note_id not in ids

    def test_soft_delete_active_note_excluded_from_count(self):
        """After soft-delete, note does not appear in count_notes."""
        with _TestDB():
            note_id = storage.add_note("Will be uncounted", "content")
            initial = storage.count_notes()
            storage.soft_delete_note(note_id)
            assert storage.count_notes() == initial - 1

    def test_soft_delete_excluded_from_get_note(self):
        """soft_deleted note raises NoteNotFoundError on get_note."""
        with _TestDB():
            note_id = storage.add_note("Hidden from get", "content")
            storage.soft_delete_note(note_id)
            with pytest.raises(storage.NoteNotFoundError):
                storage.get_note(note_id)


# ---------------------------------------------------------------------------
# physical_delete_note
# ---------------------------------------------------------------------------

class TestPhysicalDeleteNote:
    """storage.physical_delete_note() behavior per spec §4.2."""

    def test_physical_delete_removes_from_db(self):
        """physical_delete actually removes the note row from DB."""
        with _TestDB() as ctx:
            note_id = storage.add_note("Physically delete me", "content")
            storage.physical_delete_note(note_id)
            conn = storage._get_connection(ctx.db_path)
            row = conn.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone()
            conn.close()
            assert row is None

    def test_physical_delete_nonexistent_raises(self):
        """physical_delete on non-existent id raises NoteNotFoundError."""
        with _TestDB():
            with pytest.raises(storage.NoteNotFoundError):
                storage.physical_delete_note(99999)

    def test_physical_delete_soft_deleted_note_succeeds(self):
        """physical_delete can remove a note that was already soft-deleted."""
        with _TestDB():
            note_id = storage.add_note("Soft then physical", "content")
            storage.soft_delete_note(note_id)
            storage.physical_delete_note(note_id)  # should not raise
            with pytest.raises(storage.NoteNotFoundError):
                storage.get_note(note_id)

    def test_physical_delete_removed_from_count(self):
        """After physical delete, note not in count."""
        with _TestDB():
            note_id = storage.add_note("Gone from count", "content")
            storage.physical_delete_note(note_id)
            assert storage.count_notes() == 0


# ---------------------------------------------------------------------------
# restore_note
# ---------------------------------------------------------------------------

class TestRestoreNote:
    """storage.restore_note() behavior per spec §4.3."""

    def test_restore_clears_deleted_at(self):
        """restore clears deleted_at (sets to NULL)."""
        with _TestDB():
            note_id = storage.add_note("Will be restored", "content")
            storage.soft_delete_note(note_id)
            result = storage.restore_note(note_id)
            assert result.success is True
            assert result.restored_id == note_id
            assert result.conflict is False
            # Verify deleted_at is NULL
            conn = storage._get_connection(
                os.environ.get("MDNOTES_DB", storage._get_db_path())
            )
            row = conn.execute(
                "SELECT deleted_at FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
            conn.close()
            assert row[0] is None

    def test_restore_restored_note_appears_in_list(self):
        """After restore, note reappears in list_notes."""
        with _TestDB():
            note_id = storage.add_note("Restore me", "content")
            storage.soft_delete_note(note_id)
            storage.restore_note(note_id)
            notes = storage.list_notes()
            ids = [n["id"] for n in notes]
            assert note_id in ids

    def test_restore_nonexistent_raises(self):
        """restore on non-existent id raises NoteNotFoundError."""
        with _TestDB():
            with pytest.raises(storage.NoteNotFoundError):
                storage.restore_note(99999)

    def test_restore_non_deleted_note_raises(self):
        """restore on an active (non-deleted) note raises NoteNotFoundError."""
        with _TestDB():
            note_id = storage.add_note("Not deleted", "content")
            with pytest.raises(storage.NoteNotFoundError):
                storage.restore_note(note_id)

    def test_restore_conflict_returns_conflict_flag(self):
        """restore with a name clash returns conflict=True + existing note info."""
        with _TestDB():
            note_id_deleted = storage.add_note("Same Title", "old content")
            storage.soft_delete_note(note_id_deleted)
            note_id_active = storage.add_note("Same Title", "new content")
            result = storage.restore_note(note_id_deleted)
            assert result.success is False
            assert result.conflict is True
            assert result.existing_note_id == note_id_active
            assert result.existing_title == "Same Title"
            assert result.conflicting_deleted_title == "Same Title"

    def test_restore_conflict_no_false_positive_different_titles(self):
        """restore with different title (no real conflict) succeeds."""
        with _TestDB():
            note_id_deleted = storage.add_note("Old Title", "old content")
            storage.soft_delete_note(note_id_deleted)
            _note_id_active = storage.add_note("New Title", "new content")
            result = storage.restore_note(note_id_deleted)
            assert result.success is True
            assert result.conflict is False


# ---------------------------------------------------------------------------
# purge_deleted_notes
# ---------------------------------------------------------------------------

class TestPurgeDeletedNotes:
    """storage.purge_deleted_notes() behavior per spec §4.4."""

    def test_purge_without_confirm_raises(self):
        """purge with confirm=False raises ParamError."""
        with _TestDB():
            with pytest.raises(storage.ParamError, match="confirm"):
                storage.purge_deleted_notes(confirm=False, dry_run=False)

    def test_purge_dry_run_returns_count(self):
        """purge with dry_run=True returns count without modifying DB."""
        with _TestDB() as ctx:
            note_id = storage.add_note("To purge", "content")
            storage.soft_delete_note(note_id)
            result = storage.purge_deleted_notes(confirm=False, dry_run=True)
            assert result.dry_run is True
            assert result.deleted_count == 1
            assert result.batch_count == 0
            # Note still exists
            conn = storage._get_connection(ctx.db_path)
            row = conn.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone()
            conn.close()
            assert row is not None

    def test_purge_confirm_deletes(self):
        """purge with confirm=True physically deletes soft-deleted notes."""
        with _TestDB():
            note_id = storage.add_note("Will be purged", "content")
            storage.soft_delete_note(note_id)
            result = storage.purge_deleted_notes(confirm=True, dry_run=False)
            assert result.dry_run is False
            assert result.deleted_count == 1
            with pytest.raises(storage.NoteNotFoundError):
                storage.get_note(note_id)

    def test_purge_no_deleted_notes_returns_zero(self):
        """purge with no soft-deleted notes returns 0 deleted_count."""
        with _TestDB():
            storage.add_note("Active only", "content")
            result = storage.purge_deleted_notes(confirm=True, dry_run=False)
            assert result.deleted_count == 0

    def test_purge_multiple_batches(self):
        """purge deletes in batches of 500."""
        with _TestDB():
            # Add 3 notes and soft-delete them
            ids = [storage.add_note(f"Note {i}", f"content {i}") for i in range(3)]
            for id_ in ids:
                storage.soft_delete_note(id_)
            result = storage.purge_deleted_notes(confirm=True, dry_run=False)
            assert result.deleted_count == 3
            assert storage.count_notes() == 0


# ---------------------------------------------------------------------------
# list_notes / count_notes filter deleted_at IS NULL
# ---------------------------------------------------------------------------

class TestListNotesFiltered:
    """list_notes() and count_notes() default to WHERE deleted_at IS NULL."""

    def test_list_notes_excludes_soft_deleted(self):
        """Soft-deleted notes do not appear in list_notes."""
        with _TestDB():
            active_id = storage.add_note("Active note", "content")
            deleted_id = storage.add_note("Deleted note", "content")
            storage.soft_delete_note(deleted_id)
            notes = storage.list_notes()
            ids = [n["id"] for n in notes]
            assert active_id in ids
            assert deleted_id not in ids

    def test_count_notes_excludes_soft_deleted(self):
        """Soft-deleted notes are not counted."""
        with _TestDB():
            storage.add_note("Active", "content")
            deleted_id = storage.add_note("Deleted", "content")
            storage.soft_delete_note(deleted_id)
            assert storage.count_notes() == 1


# ---------------------------------------------------------------------------
# search_notes with deleted_at filter + tag AND/OR
# ---------------------------------------------------------------------------

class TestSearchNotesDeletedAtFilter:
    """search_notes() filters deleted_at IS NULL per spec §4.8.4."""

    def setup_method(self):
        self._ctx = _TestDB()
        self._ctx.__enter__()

    def teardown_method(self):
        self._ctx.__exit__(None, None, None)

    def test_search_excludes_soft_deleted(self):
        """FTS5 search does not return soft-deleted notes."""
        note_id = storage.add_note("Searchable deleted", "hello world", file_path="/tmp/deleted.md")
        storage.soft_delete_note(note_id)
        active_id = storage.add_note("Searchable active", "hello world", file_path="/tmp/active.md")
        storage.ensure_fts5()
        results = storage.search_notes("hello")
        ids = [r["id"] for r in results]
        assert active_id in ids
        assert note_id not in ids


class TestSearchNotesTagAndOr:
    """search_notes() tag AND/OR semantics per spec §4.8.1."""

    def setup_method(self):
        self._ctx = _TestDB()
        self._ctx.__enter__()
        storage.ensure_fts5()

    def teardown_method(self):
        self._ctx.__exit__(None, None, None)

    def _insert_tag(self, file_path: str, tag_name: str) -> None:
        """Insert a tag entry directly into the tags table."""
        conn = storage._get_connection(os.environ.get("MDNOTES_DB", storage._get_db_path()))
        conn.execute(
            "INSERT OR IGNORE INTO tags (file_path, tag_name) VALUES (?, ?)",
            (file_path, tag_name),
        )
        conn.commit()
        conn.close()

    def test_tag_and_returns_notes_with_all_tags(self):
        """AND mode returns notes that have ALL specified tags."""
        # Note with both tags
        id1 = storage.add_note("Has both", "content", file_path="/tmp/both.md")
        self._insert_tag("/tmp/both.md", "python")
        self._insert_tag("/tmp/both.md", "dev")
        # Note with only one tag
        id2 = storage.add_note("Has python only", "content", file_path="/tmp/py.md")
        self._insert_tag("/tmp/py.md", "python")
        results = storage.search_notes("", tags=["python", "dev"], tag_mode="AND")
        ids = [r["id"] for r in results]
        assert id1 in ids
        assert id2 not in ids

    def test_tag_or_returns_notes_with_any_tag(self):
        """OR mode returns notes that have ANY of the specified tags."""
        id1 = storage.add_note("Has python", "content", file_path="/tmp/py.md")
        self._insert_tag("/tmp/py.md", "python")
        id2 = storage.add_note("Has dev", "content", file_path="/tmp/dev.md")
        self._insert_tag("/tmp/dev.md", "dev")
        results = storage.search_notes("", tags=["python", "dev"], tag_mode="OR")
        ids = [r["id"] for r in results]
        assert id1 in ids
        assert id2 in ids

    def test_too_many_tags_raises(self):
        """More than 50 tags raises ParamError."""
        with pytest.raises(storage.ParamError, match="too many tags"):
            storage.search_notes("", tags=["tag"] * 51, tag_mode="AND")


# ---------------------------------------------------------------------------
# search_notes CJK hint
# ---------------------------------------------------------------------------

class TestSearchNotesCJKHint:
    """CJK query without quotes returns cjk_hint per spec §4.8.3."""

    def setup_method(self):
        self._ctx = _TestDB()
        self._ctx.__enter__()
        storage.ensure_fts5()

    def teardown_method(self):
        self._ctx.__exit__(None, None, None)

    def test_cjk_query_without_quotes_returns_hint(self):
        """Chinese characters without quotes include cjk_hint in results."""
        _note_id = storage.add_note("中文笔记", "内容", file_path="/tmp/cjk.md")
        results = storage.search_notes("中文")
        assert any("cjk_hint" in r for r in results)

    def test_cjk_query_with_quotes_no_hint(self):
        """CJK query wrapped in quotes does NOT include cjk_hint."""
        _note_id = storage.add_note("中文笔记", "内容", file_path="/tmp/cjk2.md")
        results = storage.search_notes('"中文"')
        # Results may or may not have hits, but cjk_hint should be absent
        for r in results:
            assert "cjk_hint" not in r

    def test_non_cjk_query_no_hint(self):
        """Non-CJK query does not include cjk_hint."""
        _note_id = storage.add_note("English note", "hello world", file_path="/tmp/en.md")
        results = storage.search_notes("hello")
        for r in results:
            assert "cjk_hint" not in r


# ---------------------------------------------------------------------------
# ParamError exists in storage
# ---------------------------------------------------------------------------

class TestStorageExceptions:
    """ParamError is accessible from storage module."""

    def test_param_error_is_defined(self):
        """storage.ParamError should be importable and inherit from Exception."""
        from mdnotes.storage import ParamError
        err = ParamError("test")
        assert isinstance(err, Exception)
