"""Tests for mdnotes FTS5 search functionality."""

import os
import sqlite3
import tempfile
import pytest
from mdnotes import storage


class TestFTS5Setup:
    """FTS5 initialization and schema tests."""

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
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_ensure_fts5_creates_virtual_table(self):
        """ensure_fts5() creates the notes_fts virtual table."""
        storage.ensure_fts5()
        conn = storage._get_connection(self._temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notes_fts'"
        )
        row = cursor.fetchone()
        assert row is not None, "notes_fts table should exist"

    def test_ensure_fts5_creates_triggers(self):
        """ensure_fts5() creates INSERT/UPDATE/DELETE triggers."""
        storage.ensure_fts5()
        conn = storage._get_connection(self._temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
        triggers = [r[0] for r in cursor.fetchall()]
        assert "notes_ai" in triggers, "INSERT trigger should exist"
        assert "notes_au" in triggers, "UPDATE trigger should exist"
        assert "notes_ad" in triggers, "DELETE trigger should exist"

    def test_ensure_fts5_idempotent(self):
        """ensure_fts5() can be called multiple times without error."""
        storage.ensure_fts5()
        storage.ensure_fts5()  # should not raise
        storage.ensure_fts5()

    def test_fts5_available(self):
        """_fts5_available() returns True on this system."""
        assert storage._fts5_available() is True

    def test_add_note_syncs_to_fts5(self):
        """add_note() creates an FTS5 entry via INSERT trigger."""
        storage.ensure_fts5()
        note_id = storage.add_note("Test", "hello world content")
        conn = storage._get_connection(self._temp_db)
        cursor = conn.execute(
            "SELECT rowid, title FROM notes_fts WHERE rowid = ?", (note_id,)
        )
        row = cursor.fetchone()
        assert row is not None, "FTS5 should have entry for new note"
        assert row[1] == "Test"

    def test_delete_note_removes_from_fts5(self):
        """delete_note() removes the FTS5 entry via DELETE trigger."""
        storage.ensure_fts5()
        note_id = storage.add_note("Test", "content")
        storage.delete_note(note_id)
        conn = storage._get_connection(self._temp_db)
        cursor = conn.execute(
            "SELECT rowid FROM notes_fts WHERE rowid = ?", (note_id,)
        )
        assert cursor.fetchone() is None, "FTS5 entry should be deleted"


class TestSearchNotes:
    """Unit tests for search_notes()."""

    def setup_method(self):
        """Create a temporary database."""
        self._orig_db_path = storage._get_db_path()
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db
        storage.ensure_fts5()

    def teardown_method(self):
        """Restore original DB path."""
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        storage._DB_PATH = self._orig_db_path
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_search_returns_results(self):
        """search_notes('hello') returns matching notes."""
        storage.add_note("Note A", "hello world")
        storage.add_note("Note B", "python code")
        results = storage.search_notes("hello")
        assert len(results) >= 1
        assert any(r["title"] == "Note A" for r in results)

    def test_search_empty_query_returns_empty(self):
        """search_notes('') returns empty list."""
        storage.add_note("Note", "content")
        results = storage.search_notes("")
        assert results == []

    def test_search_no_results(self):
        """search_notes for non-existent term returns empty list."""
        storage.add_note("Note", "python content")
        results = storage.search_notes("nonexistent_term_xyz")
        assert results == []

    def test_search_multiple_results(self):
        """Multiple notes matching return multiple results."""
        storage.add_note("Note A", "python rocks", file_path="/tmp/a.md")
        storage.set_note_tags(1, "v1")
        storage.add_note("Note B", "python is great", file_path="/tmp/b.md")
        storage.set_note_tags(2, "v1")
        storage.add_note("Note C", "ruby language", file_path="/tmp/c.md")
        storage.set_note_tags(3, "v2")
        results = storage.search_notes("python")
        assert len(results) == 2

    def test_search_with_tags(self):
        """search_notes respects the tag parameter."""
        storage.add_note("Note A", "content", file_path="/tmp/a.md")
        storage.set_note_tags(1, "python,v1")
        storage.add_note("Note B", "content", file_path="/tmp/b.md")
        storage.set_note_tags(2, "ruby")
        results = storage.search_notes("content", tag="python")
        assert len(results) == 1
        assert results[0]["id"] == 1

    def test_search_returns_snippet(self):
        """search_notes results include a snippet field."""
        storage.add_note("Note", "python is a great language")
        results = storage.search_notes("python")
        assert len(results) >= 1
        assert "snippet" in results[0]
        assert "python" in results[0]["snippet"]

    def test_search_returns_tags(self):
        """search_notes results include tags field."""
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        storage.set_note_tags(1, "v1,work")
        results = storage.search_notes("content")
        assert len(results) >= 1
        assert "v1" in results[0]["tags"]

    def test_search_bm25_ranking(self):
        """More relevant notes rank higher (BM25)."""
        n1 = storage.add_note("All Python", "python python python")
        storage.set_note_tags(n1, "v1")
        n2 = storage.add_note("Some Python", "python code")
        storage.set_note_tags(n2, "v1")
        results = storage.search_notes("python")
        assert len(results) == 2
        # Higher frequency "python" should rank higher (lower BM25 score)
        assert results[0]["id"] == n1

    def test_search_limit(self):
        """search_notes respects the limit parameter."""
        for i in range(5):
            storage.add_note(f"Note {i}", f"python content {i}")
        results = storage.search_notes("python", limit=3)
        assert len(results) == 3

    def test_search_update_sync(self):
        """Updating a note's title updates FTS5 (UPDATE trigger)."""
        note_id = storage.add_note("Original", "hello world")
        storage.set_note_tags(note_id, "v1")
        results = storage.search_notes("Original")
        assert len(results) == 1
        # Update the note title
        conn = storage._get_connection(self._temp_db)
        conn.execute("UPDATE notes SET title = ? WHERE id = ?", ("Updated", note_id))
        conn.commit()
        results_old = storage.search_notes("Original")
        results_new = storage.search_notes("Updated")
        assert len(results_old) == 0
        assert len(results_new) == 1


class TestSetNoteTags:
    """Unit tests for set_note_tags()."""

    def setup_method(self):
        self._orig_db_path = storage._get_db_path()
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db
        storage.ensure_fts5()

    def teardown_method(self):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        storage._DB_PATH = self._orig_db_path
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_set_note_tags_updates_fts5(self):
        """set_note_tags() updates the tag field in FTS5 via UPDATE trigger."""
        note_id = storage.add_note("Test", "content", file_path="/tmp/test.md")
        storage.set_note_tags(note_id, "python,redis")
        results = storage.search_notes("python")
        assert len(results) == 1
        assert results[0]["tags"] == "python,redis"

    def test_set_note_tags_not_found(self):
        """set_note_tags() with non-existent note_id raises NoteNotFoundError."""
        with pytest.raises(storage.NoteNotFoundError):
            storage.set_note_tags(9999, "tag")

    def test_set_note_tags_empty_string(self):
        """set_note_tags() with empty string clears tags."""
        note_id = storage.add_note("Test", "content", file_path="/tmp/test.md")
        storage.set_note_tags(note_id, "v1")
        storage.set_note_tags(note_id, "")
        results = storage.search_notes("v1")
        # Empty tag means v1 won't be in tags field
        results2 = storage.search_notes("content")
        assert len(results2) == 1


class TestFTS5Health:
    """Unit tests for check_fts5_health() and rebuild_fts5()."""

    def setup_method(self):
        self._orig_db_path = storage._get_db_path()
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db
        storage.ensure_fts5()

    def teardown_method(self):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        storage._DB_PATH = self._orig_db_path
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_check_fts5_health_consistent(self):
        """check_fts5_health() returns consistent=True for normal usage."""
        storage.add_note("Note 1", "content one", file_path="/tmp/a.md")
        storage.add_note("Note 2", "content two", file_path="/tmp/b.md")
        health = storage.check_fts5_health()
        assert health["consistent"] is True
        assert health["orphaned"] == 0
        assert health["extra"] == 0

    def test_rebuild_fts5_keeps_all_notes(self):
        """rebuild_fts5() preserves all existing notes."""
        n1 = storage.add_note("Note 1", "python content", file_path="/tmp/a.md")
        storage.set_note_tags(n1, "v1")
        n2 = storage.add_note("Note 2", "ruby content", file_path="/tmp/b.md")
        storage.set_note_tags(n2, "v2")
        storage.rebuild_fts5()
        results = storage.search_notes("python")
        assert len(results) == 1
        results2 = storage.search_notes("ruby")
        assert len(results2) == 1

    def test_rebuild_fts5_health_after_rebuild(self):
        """check_fts5_health() is consistent after rebuild."""
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        storage.set_note_tags(1, "v1")
        storage.rebuild_fts5()
        health = storage.check_fts5_health()
        assert health["consistent"] is True
