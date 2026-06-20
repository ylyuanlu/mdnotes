"""Integration tests for mdnotes CLI using Click's CliRunner."""

import os
import sqlite3
import tempfile
from pathlib import Path
import pytest
from click.testing import CliRunner
from mdnotes.cli import cli, add, ls, show, delete, count


@pytest.fixture
def runner():
    """Return a CliRunner instance."""
    return CliRunner()


@pytest.fixture
def isolated_db(runner):
    """Create an isolated temp DB for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "notes.db")
        env = {"MDNOTES_DB": db_path}
        yield runner, env


class TestAddCommand:
    """Tests for: mdnotes add <title> [content]"""

    def test_add_success_returns_created_message(self, isolated_db):
        """AC-4: add success prints 'Created note N' to stderr."""
        runner, env = isolated_db
        result = runner.invoke(add, ["My Note"], env=env)
        assert result.exit_code == 0
        assert "Created note" in result.output

    def test_add_with_content(self, isolated_db):
        """add with content succeeds."""
        runner, env = isolated_db
        result = runner.invoke(add, ["My Note", "Some content"], env=env)
        assert result.exit_code == 0
        assert "Created note" in result.output

    def test_add_empty_title_exits_2(self, isolated_db):
        """AC-1: empty title exits with code 2."""
        runner, env = isolated_db
        result = runner.invoke(add, [""], env=env)
        assert result.exit_code == 2

    def test_add_whitespace_only_title_exits_2(self, isolated_db):
        """AC-1: whitespace-only title exits with code 2."""
        runner, env = isolated_db
        result = runner.invoke(add, ["   "], env=env)
        assert result.exit_code == 2

    def test_add_long_title_exits_2(self, isolated_db):
        """AC-2: title > 200 chars exits with code 2."""
        runner, env = isolated_db
        result = runner.invoke(add, ["x" * 201], env=env)
        assert result.exit_code == 2

    def test_add_title_200_chars_ok(self, isolated_db):
        """AC-2: title exactly 200 chars succeeds."""
        runner, env = isolated_db
        result = runner.invoke(add, ["x" * 200], env=env)
        assert result.exit_code == 0

    def test_add_help(self, isolated_db):
        """AC-22: --help works."""
        runner, env = isolated_db
        result = runner.invoke(add, ["--help"])
        assert result.exit_code == 0
        assert "Create a new note" in result.output

    def test_add_file_with_tags_indexes_tags(self, isolated_db):
        """add with a .md file path reads file, indexes tags, and creates note."""
        import sqlite3
        runner, env = isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a markdown file with frontmatter + inline tags
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text(
                "---\ntags: [v1, important]\n---\n# My Note\nContent with #v1 inline.",
                encoding="utf-8",
            )
            env_with_vault = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(add, [str(md_path)], env=env_with_vault)
            assert result.exit_code == 0, result.output
            assert "Created note" in result.output

            # Verify tags were indexed in DB
            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            c.execute("SELECT tag_name FROM tags WHERE deleted_at IS NULL ORDER BY tag_name")
            tags = [r[0] for r in c.fetchall()]
            conn.close()
            assert "v1" in tags
            assert "important" in tags

    def test_add_file_extracts_title_from_frontmatter(self, isolated_db):
        """add with file path uses # heading as note title."""
        runner, env = isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text(
                "---\ntags: [tag1]\n---\n# Extracted Title\nBody content.",
                encoding="utf-8",
            )
            env_with_vault = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(add, [str(md_path)], env=env_with_vault)
            assert result.exit_code == 0, result.output

            # Verify the note title was extracted from # heading
            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            c.execute("SELECT title FROM notes ORDER BY id")
            title = c.fetchone()[0]
            conn.close()
            assert title == "Extracted Title"

    def test_add_file_fallback_title_from_filename(self, isolated_db):
        """add with file that has no # heading uses filename stem as title."""
        runner, env = isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "my_note_file.md"
            md_path.write_text(
                "---\ntags: [t1]\n---\nNo heading here.",
                encoding="utf-8",
            )
            env_with_vault = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(add, [str(md_path)], env=env_with_vault)
            assert result.exit_code == 0, result.output

            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            c.execute("SELECT title FROM notes ORDER BY id")
            title = c.fetchone()[0]
            conn.close()
            assert title == "my_note_file"

    def test_add_file_read_error_exits_1(self, isolated_db):
        """add with unreadable file exits with code 1."""
        from unittest.mock import patch
        runner, env = isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "unreadable.md"
            md_path.write_text("# Title", encoding="utf-8")
            # Simulate read error by patching Path.read_text
            with patch.object(Path, 'read_text', side_effect=OSError("Permission denied")):
                result = runner.invoke(add, [str(md_path)], env=env)
            assert result.exit_code == 1, result.output
            assert "cannot read file" in result.output

    def test_add_file_scan_index_db_error_exits_1(self, isolated_db):
        """add with file where scan_and_index_file raises DatabaseError exits 1."""
        from unittest.mock import patch
        from mdnotes import storage
        runner, env = isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text("---\ntags: [t1]\n---\n# Title\nBody.", encoding="utf-8")
            with patch.object(storage, 'scan_and_index_file', side_effect=storage.DatabaseError("db error")):
                result = runner.invoke(add, [str(md_path)], env=env)
            assert result.exit_code == 1, result.output
            assert "db error" in result.output

    def test_add_multi_file_creates_all_notes(self, isolated_db):
        """add with multiple .md file paths creates a note for each file."""
        import sqlite3
        runner, env = isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            files = []
            for i in range(1, 4):
                p = Path(tmpdir) / f"note{i}.md"
                p.write_text(f"---\ntags: [v1]\n---\n# Note {i}\nContent.", encoding="utf-8")
                files.append(str(p))
            env_with_vault = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(add, files, env=env_with_vault)
            assert result.exit_code == 0, result.output
            # Should have 3 "Created note" lines
            created_lines = [line for line in result.output.split('\n') if 'Created note' in line]
            assert len(created_lines) == 3, f"Expected 3 Created notes, got: {result.output}"

            # Verify DB has 3 notes (notes.deleted_at is added via lazy migration)
            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            # Trigger lazy migration via a schema query that references the notes table
            c.execute("SELECT id FROM notes")
            ids = c.fetchall()
            conn.close()
            assert len(ids) == 3, f"Expected 3 notes in DB, got {len(ids)}"

    def test_add_multi_file_with_missing_file(self, isolated_db):
        """add with a mix of existing and missing files skips missing ones."""
        runner, env = isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "note1.md"
            existing.write_text("---\ntags: [v1]\n---\n# Note 1\nContent.", encoding="utf-8")
            env_with_vault = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(add, [str(existing), str(Path(tmpdir)/"missing.md")], env=env_with_vault)
            assert result.exit_code == 0, result.output
            assert "Created note" in result.output
            assert "missing" in result.output.lower() or "skipping" in result.output.lower()

    def test_add_no_args_exits_2(self, isolated_db):
        """add with no arguments exits with code 2."""
        runner, env = isolated_db
        result = runner.invoke(add, [], env=env)
        assert result.exit_code == 2, result.output

    def test_add_non_md_file_treated_as_title(self, isolated_db):
        """add with a non-.md first arg is treated as a title (normal mode)."""
        runner, env = isolated_db
        result = runner.invoke(add, ["My Title", "My content"], env=env)
        assert result.exit_code == 0, result.output
        assert "Created note" in result.output


class TestListCommand:
    """Tests for: mdnotes list [--search] [--sort] [--order]"""

    def test_list_empty_shows_no_notes_yet(self, isolated_db):
        """AC-11: empty list prints 'No notes yet.' and exits 0."""
        runner, env = isolated_db
        result = runner.invoke(ls, [], env=env)
        assert result.exit_code == 0
        assert "No notes yet" in result.output

    def test_list_output_format(self, isolated_db):
        """AC-8: list output format is stable: [id] title (created_at)."""
        runner, env = isolated_db
        runner.invoke(add, ["First Note"], env=env)
        result = runner.invoke(ls, [], env=env)
        assert result.exit_code == 0
        # Should match "[N] First Note (YYYY-MM-DD HH:MM:SS)"
        assert "[1] First Note" in result.output

    def test_list_default_sort_desc(self, isolated_db):
        """AC-9: default sort is created_at DESC (newest first)."""
        runner, env = isolated_db
        runner.invoke(add, ["First"], env=env)
        import time
        time.sleep(1.1)  # ensure different created_at second
        runner.invoke(add, ["Second"], env=env)
        result = runner.invoke(ls, [], env=env)
        lines = result.output.strip().split("\n")
        # Second (id=2) should appear before First (id=1)
        assert lines[0].startswith("[2]")

    def test_list_sort_created_at_asc(self, isolated_db):
        """AC-10: --sort created_at --order asc works."""
        runner, env = isolated_db
        runner.invoke(add, ["First"], env=env)
        runner.invoke(add, ["Second"], env=env)
        result = runner.invoke(ls, ["--sort", "created_at", "--order", "asc"], env=env)
        lines = result.output.strip().split("\n")
        assert lines[0].startswith("[1]")

    def test_list_search(self, isolated_db):
        """list --search filters by LIKE keyword."""
        runner, env = isolated_db
        runner.invoke(add, ["Apple pie"], env=env)
        runner.invoke(add, ["Banana bread"], env=env)
        result = runner.invoke(ls, ["--search", "Apple"], env=env)
        assert "Apple pie" in result.output
        assert "Banana bread" not in result.output

    def test_list_search_no_results(self, isolated_db):
        """list --search with no matches shows 'No notes yet.'."""
        runner, env = isolated_db
        runner.invoke(add, ["Apple pie"], env=env)
        result = runner.invoke(ls, ["--search", "ZZZNOTFOUND"], env=env)
        assert "No notes yet" in result.output

    def test_list_help(self, isolated_db):
        """AC-22: --help works."""
        runner, env = isolated_db
        result = runner.invoke(ls, ["--help"])
        assert result.exit_code == 0
        assert "List all notes" in result.output


class TestShowCommand:
    """Tests for: mdnotes show <id>"""

    def test_show_existing_note(self, isolated_db):
        """AC-13: show outputs title/created_at/content blocks."""
        runner, env = isolated_db
        runner.invoke(add, ["My Note", "# Hello\n\nWorld"], env=env)
        result = runner.invoke(show, ["1"], env=env)
        assert result.exit_code == 0
        assert "Title: My Note" in result.output
        assert "Created:" in result.output
        assert "----" in result.output
        assert "<h1>" in result.output  # rendered markdown

    def test_show_not_found_exits_3(self, isolated_db):
        """AC-16: non-existent id exits with code 3 and 'Note not found'."""
        runner, env = isolated_db
        result = runner.invoke(show, ["999"], env=env)
        assert result.exit_code == 3
        assert "Note not found" in result.output

    def test_show_invalid_id_exits_2(self, isolated_db):
        """AC-17: non-integer id exits with code 2."""
        runner, env = isolated_db
        result = runner.invoke(show, ["abc"], env=env)
        assert result.exit_code == 2
        assert "integer" in result.output.lower()

    def test_show_empty_content(self, isolated_db):
        """show handles empty content gracefully."""
        runner, env = isolated_db
        runner.invoke(add, ["Empty Note", ""], env=env)
        result = runner.invoke(show, ["1"], env=env)
        assert result.exit_code == 0

    def test_show_help(self, isolated_db):
        """AC-22: --help works."""
        runner, env = isolated_db
        result = runner.invoke(show, ["--help"])
        assert result.exit_code == 0


class TestDeleteCommand:
    """Tests for: mdnotes delete <id> [--force]"""

    def test_delete_existing_with_force(self, isolated_db):
        """AC-18/AC-20: --force deletes without prompt, exits 0."""
        runner, env = isolated_db
        runner.invoke(add, ["To Delete"], env=env)
        result = runner.invoke(delete, ["1", "--force"], env=env, input="n\n")
        assert result.exit_code == 0
        assert "Deleted note 1" in result.output

    def test_delete_not_found_exits_3(self, isolated_db):
        """AC-19: deleting non-existent id exits 3."""
        runner, env = isolated_db
        result = runner.invoke(delete, ["999", "--force"], env=env)
        assert result.exit_code == 3
        assert "Note not found" in result.output

    def test_delete_invalid_id_exits_2(self, isolated_db):
        """AC-17: non-integer id exits 2."""
        runner, env = isolated_db
        result = runner.invoke(delete, ["abc", "--force"], env=env)
        assert result.exit_code == 2
        assert "integer" in result.output.lower()

    def test_delete_cannot_show_after(self, isolated_db):
        """AC-21: deleted note cannot be shown."""
        runner, env = isolated_db
        runner.invoke(add, ["Will be gone"], env=env)
        runner.invoke(delete, ["1", "--force"], env=env)
        result = runner.invoke(show, ["1"], env=env)
        assert result.exit_code == 3

    def test_delete_prompt_n(self, isolated_db):
        """Without --force, 'n' response cancels deletion."""
        runner, env = isolated_db
        runner.invoke(add, ["Keep me"], env=env)
        result = runner.invoke(delete, ["1"], env=env, input="n\n")
        assert result.exit_code == 0
        # Note should still exist
        show_result = runner.invoke(show, ["1"], env=env)
        assert show_result.exit_code == 0

    def test_delete_help(self, isolated_db):
        """AC-22: --help works."""
        runner, env = isolated_db
        result = runner.invoke(delete, ["--help"])
        assert result.exit_code == 0


class TestCountCommand:
    """Tests for: mdnotes count"""

    def test_count_empty_returns_zero(self, isolated_db):
        """B-1/B-4: empty DB outputs 'Total notes: 0', exit 0."""
        runner, env = isolated_db
        result = runner.invoke(count, [], env=env)
        assert result.exit_code == 0
        assert "Total notes: 0" in result.output

    def test_count_after_add_one(self, isolated_db):
        """B-2: one note outputs 'Total notes: 1', exit 0."""
        runner, env = isolated_db
        runner.invoke(add, ["First Note"], env=env)
        result = runner.invoke(count, [], env=env)
        assert result.exit_code == 0
        assert "Total notes: 1" in result.output

    def test_count_after_add_multiple(self, isolated_db):
        """B-2: multiple notes outputs correct count, exit 0."""
        runner, env = isolated_db
        runner.invoke(add, ["Note A"], env=env)
        runner.invoke(add, ["Note B"], env=env)
        runner.invoke(add, ["Note C"], env=env)
        result = runner.invoke(count, [], env=env)
        assert result.exit_code == 0
        assert "Total notes: 3" in result.output

    def test_count_after_delete(self, isolated_db):
        """B-5: deleted notes are not counted."""
        runner, env = isolated_db
        runner.invoke(add, ["Note 1"], env=env)
        runner.invoke(add, ["Note 2"], env=env)
        runner.invoke(delete, ["1", "--force"], env=env)
        result = runner.invoke(count, [], env=env)
        assert result.exit_code == 0
        assert "Total notes: 1" in result.output

    def test_count_help(self, isolated_db):
        """B-3: --help shows usage, exit 0."""
        runner, env = isolated_db
        result = runner.invoke(count, ["--help"])
        assert result.exit_code == 0
        assert "Count all active notes" in result.output


class TestCliVersion:
    """Test CLI version flag."""

    def test_version_flag(self, runner):
        """--version prints version and exits 0."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestDbPath:
    """AC-23/AC-24: DB path strategy tests."""

    def test_mdnotes_db_env_override(self, runner):
        """AC-23: MDNOTES_DB env var overrides default path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "custom.db")
            env = {"MDNOTES_DB": db_path}
            result = runner.invoke(add, ["From Env", "content"], env=env)
            assert result.exit_code == 0
            assert os.path.exists(db_path)

    def test_space_in_path(self, isolated_db):
        """AC-24: DB path with spaces works."""
        runner, env = isolated_db
        result = runner.invoke(add, ["Space Note"], env=env)
        assert result.exit_code == 0
        result = runner.invoke(ls, [], env=env)
        assert "Space Note" in result.output
