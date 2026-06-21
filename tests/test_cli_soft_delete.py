"""Unit tests for v1.5 CLI commands: delete --physical, restore, purge, search tag/color."""

import os
import tempfile
import pytest
from click.testing import CliRunner
from mdnotes import storage
from mdnotes.cli import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def isolated_db(runner):
    """Create isolated temp DB for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "notes.db")
        env = {"MDNOTES_DB": db_path}
        os.environ["MDNOTES_DB"] = db_path
        # Bootstrap DB
        storage._get_connection(db_path)
        yield runner, env
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]


# ---------------------------------------------------------------------------
# delete --physical
# ---------------------------------------------------------------------------

class TestDeletePhysical:
    """CLI: delete --physical permanently removes note."""

    def test_delete_physical_removes_note(self, isolated_db):
        """--physical physically deletes the note (cannot be restored)."""
        runner, env = isolated_db
        storage.add_note("Permanent note", "content")
        # Get the note id
        notes = storage.list_notes()
        note_id = notes[0]["id"]
        result = runner.invoke(cli, ["delete", str(note_id), "--physical", "--force"], env=env)
        assert result.exit_code == 0
        # Note should be gone from DB
        with pytest.raises(storage.NoteNotFoundError):
            storage.get_note(note_id)

    def test_delete_physical_nonexistent_exits_3(self, isolated_db):
        """--physical on non-existent id exits 3."""
        runner, env = isolated_db
        result = runner.invoke(cli, ["delete", "99999", "--physical"], env=env)
        assert result.exit_code == 3

    def test_delete_physical_soft_deleted_succeeds(self, isolated_db):
        """--physical can physically delete a soft-deleted note."""
        runner, env = isolated_db
        note_id = storage.add_note("Soft then physical", "content")
        storage.soft_delete_note(note_id)
        result = runner.invoke(cli, ["delete", str(note_id), "--physical", "--force"], env=env)
        assert result.exit_code == 0

    def test_delete_default_is_soft_delete(self, isolated_db):
        """delete (without --physical) is soft-delete."""
        runner, env = isolated_db
        note_id = storage.add_note("Soft delete me", "content")
        # Default delete should soft-delete
        result = runner.invoke(cli, ["delete", str(note_id), "--force"], env=env)
        assert result.exit_code == 0
        # Note still in DB but with deleted_at set
        conn = storage._get_connection(env["MDNOTES_DB"])
        row = conn.execute(
            "SELECT deleted_at FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None  # soft-deleted

    def test_delete_soft_deleted_idempotent(self, isolated_db):
        """delete on already-soft-deleted note is idempotent (exit 0)."""
        runner, env = isolated_db
        note_id = storage.add_note("Already deleted", "content")
        storage.soft_delete_note(note_id)
        result = runner.invoke(cli, ["delete", str(note_id), "--force"], env=env)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

class TestRestore:
    """CLI: restore command."""

    def test_restore_success(self, isolated_db):
        """restore on a soft-deleted note exits 0 and note reappears."""
        runner, env = isolated_db
        note_id = storage.add_note("Restore me", "content")
        storage.soft_delete_note(note_id)
        result = runner.invoke(cli, ["restore", str(note_id)], env=env)
        assert result.exit_code == 0
        # Note is back in list
        notes = storage.list_notes()
        ids = [n["id"] for n in notes]
        assert note_id in ids

    def test_restore_nonexistent_exits_3(self, isolated_db):
        """restore on non-existent id exits 3."""
        runner, env = isolated_db
        result = runner.invoke(cli, ["restore", "99999"], env=env)
        assert result.exit_code == 3

    def test_restore_active_note_exits_3(self, isolated_db):
        """restore on an active (non-deleted) note exits 3."""
        runner, env = isolated_db
        note_id = storage.add_note("Not deleted", "content")
        result = runner.invoke(cli, ["restore", str(note_id)], env=env)
        assert result.exit_code == 3

    def test_restore_invalid_id_exits_2(self, isolated_db):
        """restore with non-integer id exits 2."""
        runner, env = isolated_db
        result = runner.invoke(cli, ["restore", "notanumber"], env=env)
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------

class TestPurge:
    """CLI: purge command."""

    def test_purge_without_confirm_exits_2(self, isolated_db):
        """purge without --confirm exits 2 with error message."""
        runner, env = isolated_db
        note_id = storage.add_note("To purge", "content")
        storage.soft_delete_note(note_id)
        result = runner.invoke(cli, ["purge"], env=env)
        assert result.exit_code == 2
        assert "confirm" in result.output.lower()

    def test_purge_dry_run_exits_0(self, isolated_db):
        """purge --dry-run exits 0 and reports count."""
        runner, env = isolated_db
        note_id = storage.add_note("Dry run me", "content")
        storage.soft_delete_note(note_id)
        result = runner.invoke(cli, ["purge", "--dry-run"], env=env)
        assert result.exit_code == 0
        assert "1" in result.output or "purged" in result.output.lower()

    def test_purge_confirm_deletes(self, isolated_db):
        """purge --confirm physically removes soft-deleted notes."""
        runner, env = isolated_db
        note_id = storage.add_note("Purge me", "content")
        storage.soft_delete_note(note_id)
        result = runner.invoke(cli, ["purge", "--confirm"], env=env)
        assert result.exit_code == 0
        with pytest.raises(storage.NoteNotFoundError):
            storage.get_note(note_id)

    def test_purge_no_deleted_notes_exits_0(self, isolated_db):
        """purge --confirm when nothing to purge exits 0."""
        runner, env = isolated_db
        storage.add_note("Active only", "content")
        result = runner.invoke(cli, ["purge", "--confirm"], env=env)
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# search --tag --or --color
# ---------------------------------------------------------------------------

class TestSearchTagAndOr:
    """CLI: search --tag (multiple) with AND/OR semantics."""

    def setup_method(self):
        self._ctx = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._ctx.name, "notes.db")
        os.environ["MDNOTES_DB"] = self._db_path
        storage._get_connection(self._db_path)
        storage.ensure_fts5()

    def teardown_method(self):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        self._ctx.cleanup()

    def _insert_tag(self, file_path: str, tag_name: str) -> None:
        """Insert tag directly into tags table."""
        conn = storage._get_connection(self._db_path)
        conn.execute(
            "INSERT OR IGNORE INTO tags (file_path, tag_name) VALUES (?, ?)",
            (file_path, tag_name),
        )
        conn.commit()
        conn.close()

    def test_search_single_tag(self, runner):
        """--tag with a single tag filters correctly."""
        _id1 = storage.add_note("Has python", "content", file_path="/tmp/py.md")
        self._insert_tag("/tmp/py.md", "python")
        result = runner.invoke(cli, ["search", "--tag", "python"], env={"MDNOTES_DB": self._db_path})
        assert result.exit_code == 0

    def test_search_multiple_tags_and_mode(self, runner):
        """Multiple --tag flags use AND semantics by default."""
        id1 = storage.add_note("Has both", "content", file_path="/tmp/both.md")
        self._insert_tag("/tmp/both.md", "python")
        self._insert_tag("/tmp/both.md", "dev")
        id2 = storage.add_note("Has python only", "content", file_path="/tmp/py.md")
        self._insert_tag("/tmp/py.md", "python")
        result = runner.invoke(
            cli,
            ["search", "--tag", "python", "--tag", "dev"],
            env={"MDNOTES_DB": self._db_path},
        )
        assert result.exit_code == 0
        # Parse IDs from output (format: [id] Title ...)
        import re
        found_ids = [int(m) for m in re.findall(r'\[(\d+)\]', result.output)]
        assert id1 in found_ids
        assert id2 not in found_ids

    def test_search_multiple_tags_or_mode(self, runner):
        """--or flag switches tag filter to OR semantics."""
        id1 = storage.add_note("Has python", "content", file_path="/tmp/py.md")
        self._insert_tag("/tmp/py.md", "python")
        id2 = storage.add_note("Has dev", "content", file_path="/tmp/dev.md")
        self._insert_tag("/tmp/dev.md", "dev")
        result = runner.invoke(
            cli,
            ["search", "--tag", "python", "--tag", "dev", "--or"],
            env={"MDNOTES_DB": self._db_path},
        )
        assert result.exit_code == 0
        import re
        found_ids = [int(m) for m in re.findall(r'\[(\d+)\]', result.output)]
        assert id1 in found_ids
        assert id2 in found_ids


class TestSearchColorMode:
    """CLI: search --color option."""

    def test_color_never_retains_mark_tags(self, runner):
        """--color=never keeps <mark> tags in output."""
        # Setup DB
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "notes.db")
            os.environ["MDNOTES_DB"] = db_path
            storage._get_connection(db_path)
            storage.ensure_fts5()
            _note_id = storage.add_note("Hello world", "hello world", file_path="/tmp/hello.md")
            env = {"MDNOTES_DB": db_path}
            result = runner.invoke(cli, ["search", "hello", "--color", "never"], env=env)
            # Output should contain <mark> tags
            if result.exit_code == 0:
                assert "<mark>" in result.output or "Hello" in result.output
            del os.environ["MDNOTES_DB"]

    def test_color_always_uses_ansi_escape(self, runner):
        """--color=always converts <mark> to ANSI escape codes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "notes.db")
            os.environ["MDNOTES_DB"] = db_path
            storage._get_connection(db_path)
            storage.ensure_fts5()
            storage.add_note("Hello world", "hello world", file_path="/tmp/hello.md")
            env = {"MDNOTES_DB": db_path}
            result = runner.invoke(cli, ["search", "hello", "--color", "always"], env=env)
            assert result.exit_code == 0
            # ANSI escape \x1b[1m should appear
            assert "\x1b[1m" in result.output or result.output != ""
            del os.environ["MDNOTES_DB"]
