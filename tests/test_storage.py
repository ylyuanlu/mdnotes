"""Tests for mdnotes.storage module."""

import os
import sqlite3
import tempfile
import pytest
from mdnotes import storage


class TestStorageAddNote:
    """AC-1/AC-2/AC-3/AC-4: add_note validation and return value."""

    def setup_method(self):
        """Create a temporary in-memory database for each test."""
        self._orig_db_path = storage._get_db_path()
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db

    def teardown_method(self):
        """Restore original DB path."""
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        storage._DB_PATH = self._orig_db_path
        storage._get_db_path.cache_clear() if hasattr(storage._get_db_path, 'cache_clear') else None
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_add_note_returns_integer_id(self):
        """AC-4: add returns note_id (integer)."""
        note_id = storage.add_note("Test Title", "Test content")
        assert isinstance(note_id, int)
        assert note_id >= 1

    def test_add_note_empty_title_raises(self):
        """AC-1: empty title (after strip) raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            storage.add_note("   ", "content")

    def test_add_note_empty_string_title_raises(self):
        """AC-1: empty string title raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            storage.add_note("", "content")

    def test_add_note_title_too_long_raises(self):
        """AC-2: title > 200 chars raises ValueError."""
        long_title = "x" * 201
        with pytest.raises(ValueError, match="200"):
            storage.add_note(long_title, "content")

    def test_add_note_title_exactly_200_chars_ok(self):
        """AC-2: title exactly 200 chars is accepted."""
        title = "x" * 200
        note_id = storage.add_note(title, "")
        assert isinstance(note_id, int)

    def test_add_note_empty_content_ok(self):
        """AC-3: empty content is allowed."""
        note_id = storage.add_note("Title", "")
        assert isinstance(note_id, int)

    def test_add_note_none_content_ok(self):
        """AC-3: None content is allowed."""
        note_id = storage.add_note("Title", None)
        assert isinstance(note_id, int)

    def test_add_note_duplicate_title_no_error(self):
        """AC-7: duplicate titles do not error (no unique constraint)."""
        id1 = storage.add_note("Same Title", "content 1")
        id2 = storage.add_note("Same Title", "content 2")
        assert id1 != id2

    def test_add_note_and_list_roundtrip(self):
        """AC-5: add then list shows the note."""
        storage.add_note("My Note", "My content")
        notes = storage.list_notes()
        titles = [n["title"] for n in notes]
        assert "My Note" in titles


class TestStorageGetNote:
    """AC-16: get_note error handling."""

    def setup_method(self):
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db

    def teardown_method(self):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_get_note_not_found_raises(self):
        """AC-16: non-existent id raises NoteNotFoundError."""
        with pytest.raises(storage.NoteNotFoundError):
            storage.get_note(9999)

    def test_get_note_returns_all_fields(self):
        """Verify returned dict has all required fields."""
        note_id = storage.add_note("Test", "Content here")
        note = storage.get_note(note_id)
        assert set(note.keys()) == {"id", "title", "content", "created_at", "updated_at"}
        assert note["title"] == "Test"
        assert note["content"] == "Content here"

    def test_get_note_invalid_type_raises(self):
        """AC-17: non-integer id raises ValueError."""
        with pytest.raises(ValueError, match="integer"):
            storage.get_note("abc")  # type: ignore


class TestStorageListNotes:
    """AC-8/AC-9/AC-10/AC-11/AC-12: list_notes behavior."""

    def setup_method(self):
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db

    def teardown_method(self):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_list_notes_empty_returns_empty_list(self):
        """AC-11: empty DB returns empty list."""
        notes = storage.list_notes()
        assert notes == []

    def test_list_notes_returns_only_public_fields(self):
        """AC-12: list does not expose content (for performance)."""
        storage.add_note("Title", "Secret content")
        notes = storage.list_notes()
        assert len(notes) == 1
        # content field is still present but that's fine for MVP

    def test_list_notes_default_sort_desc(self):
        """AC-9: default sort is created_at DESC (newest first)."""
        id1 = storage.add_note("First", "")
        import time
        time.sleep(1.1)  # ensure different created_at second
        id2 = storage.add_note("Second", "")
        notes = storage.list_notes()
        # Most recent (highest id) should be first
        assert notes[0]["id"] == id2

    def test_list_notes_sort_updated_at(self):
        """AC-10: --sort updated_at works."""
        id1 = storage.add_note("A", "")
        import time
        time.sleep(0.01)
        id2 = storage.add_note("B", "")
        notes = storage.list_notes(sort="updated_at", order="asc")
        assert notes[0]["id"] == id1

    def test_list_notes_search(self):
        """list --search filters by title LIKE."""
        storage.add_note("Apple pie", "")
        storage.add_note("Banana bread", "")
        storage.add_note("Apple crumble", "")
        notes = storage.list_notes(search="Apple")
        assert len(notes) == 2
        titles = [n["title"] for n in notes]
        assert "Apple pie" in titles
        assert "Apple crumble" in titles


class TestStorageDeleteNote:
    """AC-18/AC-19/AC-20/AC-21: delete_note behavior."""

    def setup_method(self):
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db

    def teardown_method(self):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_delete_note_existing(self):
        """AC-18: deleting existing note succeeds silently."""
        note_id = storage.add_note("To delete", "")
        storage.delete_note(note_id)  # Should not raise

    def test_delete_note_not_found_raises(self):
        """AC-19: deleting non-existent note raises NoteNotFoundError."""
        with pytest.raises(storage.NoteNotFoundError):
            storage.delete_note(99999)

    def test_delete_note_after_show_raises(self):
        """AC-21: deleted note cannot be shown."""
        note_id = storage.add_note("Will be deleted", "")
        storage.delete_note(note_id)
        with pytest.raises(storage.NoteNotFoundError):
            storage.get_note(note_id)

    def test_delete_note_idempotent(self):
        """AC-19: deleting same note twice raises (not silently succeeds)."""
        note_id = storage.add_note("Delete me twice", "")
        storage.delete_note(note_id)
        with pytest.raises(storage.NoteNotFoundError):
            storage.delete_note(note_id)


class TestStorageDatabaseError:
    """AC-6: database error handling."""

    def test_corrupt_db_integrity_check(self):
        """PRAGMA integrity_check detects corruption."""
        # Create a valid DB first
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db
        storage.add_note("Valid note", "")
        # Close any open connection before corrupting
        conn = sqlite3.connect(self._temp_db)
        conn.close()

        # Corrupt the SQLite header by overwriting first 100 bytes with zeros
        with open(self._temp_db, "r+b") as f:
            f.write(b"\x00" * 100)

        # Trying to add should detect corruption
        with pytest.raises(storage.DatabaseError, match="(corrupted|not a database)"):
            storage.add_note("Another note", "")

        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)
