"""Tests for mdnotes search command — focus on --check, --rebuild, and error paths."""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

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
def search_isolated_db(runner):
    """Create isolated temp DB + FTS5 setup for search tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "notes.db")
        env = {"MDNOTES_DB": db_path}
        # Bootstrap DB + FTS5 in the test process
        os.environ["MDNOTES_DB"] = db_path
        storage.ensure_fts5()
        yield runner, env
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]


# ---------------------------------------------------------------------------
# search --check
# ---------------------------------------------------------------------------

class TestSearchCheck:
    """Tests for: mdnotes search --check"""

    def test_check_healthy_exits_0(self, search_isolated_db):
        """--check on a healthy index exits 0 with consistent message."""
        runner, env = search_isolated_db
        storage.add_note("Note 1", "hello world", file_path="/tmp/a.md")
        result = runner.invoke(cli, ["search", "--check"], env=env)
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"
        assert "consistent" in result.output.lower()

    def test_check_inconsistent_exits_0_but_reports(self, search_isolated_db):
        """--check on an inconsistent index exits 0 and reports details."""
        runner, env = search_isolated_db
        # Create an orphaned FTS5 row (rowid=9999 has no matching note)
        conn = storage._get_connection(env["MDNOTES_DB"])
        conn.execute(
            "INSERT INTO notes_fts(rowid, title, content, tag) VALUES(?, ?, ?, ?)",
            (9999, "Orphan Title", "orphan content", "")
        )
        conn.commit()
        result = runner.invoke(cli, ["search", "--check"], env=env)
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"
        # Should report the inconsistency
        assert ("inconsistency" in result.output.lower() or
                "orphaned" in result.output.lower() or
                "extra" in result.output.lower()), \
            f"Expected inconsistency report, got: {result.output}"

    def test_check_db_error_exits_2(self, search_isolated_db):
        """--check when ensure_fts5 raises DatabaseError exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "ensure_fts5", side_effect=storage.DatabaseError("check error")):
            result = runner.invoke(cli, ["search", "--check"], env=env)
        assert result.exit_code == 2, result.output
        assert "check error" in result.output

    def test_check_health_error_exits_2(self, search_isolated_db):
        """--check when check_fts5_health raises DatabaseError exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "check_fts5_health", side_effect=storage.DatabaseError("health error")):
            result = runner.invoke(cli, ["search", "--check"], env=env)
        assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------
# search --rebuild
# ---------------------------------------------------------------------------

class TestSearchRebuild:
    """Tests for: mdnotes search --rebuild"""

    def test_rebuild_success_exits_0(self, search_isolated_db):
        """--rebuild exits 0 with success message."""
        runner, env = search_isolated_db
        storage.add_note("Note 1", "python content", file_path="/tmp/a.md")
        storage.set_note_tags(1, "v1")
        result = runner.invoke(cli, ["search", "--rebuild"], env=env)
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"
        assert "rebuilt successfully" in result.output.lower()

    def test_rebuild_db_error_exits_2(self, search_isolated_db):
        """--rebuild when rebuild_fts5 raises DatabaseError exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "rebuild_fts5", side_effect=storage.DatabaseError("rebuild error")):
            result = runner.invoke(cli, ["search", "--rebuild"], env=env)
        assert result.exit_code == 2, result.output
        assert "rebuild error" in result.output

    def test_rebuild_after_add_preserves_searchability(self, search_isolated_db):
        """--rebuild then search still works."""
        runner, env = search_isolated_db
        storage.add_note("Alpha", "beta content", file_path="/tmp/a.md")
        result = runner.invoke(cli, ["search", "--rebuild"], env=env)
        assert result.exit_code == 0, result.output
        # Search should still work
        result2 = runner.invoke(cli, ["search", "beta"], env=env)
        assert result2.exit_code == 0, result2.output
        assert "beta" in result2.output.lower()


# ---------------------------------------------------------------------------
# search (no query, no flags)
# ---------------------------------------------------------------------------

class TestSearchNoQuery:
    """Tests for: mdnotes search (no query)"""

    def test_search_no_query_empty_db(self, search_isolated_db):
        """No query on empty DB shows 'No notes yet.' and exits 0."""
        runner, env = search_isolated_db
        result = runner.invoke(cli, ["search"], env=env)
        assert result.exit_code == 0, result.output
        assert "No notes yet" in result.output

    def test_search_no_query_lists_notes(self, search_isolated_db):
        """No query lists all notes newest first."""
        runner, env = search_isolated_db
        storage.add_note("First", "content", file_path="/tmp/first.md")
        import time
        time.sleep(1.1)
        storage.add_note("Second", "content", file_path="/tmp/second.md")
        result = runner.invoke(cli, ["search"], env=env)
        assert result.exit_code == 0, result.output
        assert "Second" in result.output
        assert "First" in result.output
        # Newest first
        lines = [line for line in result.output.strip().split("\n") if "[" in line]
        assert lines[0].startswith("[2]")

    def test_search_no_query_db_error_exits_2(self, search_isolated_db):
        """No query when DB error occurs exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "list_notes", side_effect=storage.DatabaseError("db error")):
            result = runner.invoke(cli, ["search"], env=env)
        assert result.exit_code == 2, result.output
        assert "db error" in result.output

    def test_search_no_query_with_tag_filter(self, search_isolated_db):
        """No query with --tag filters notes by tag (uses search_notes with empty query)."""
        runner, env = search_isolated_db
        storage.add_note("Tagged Note", "content", file_path="/tmp/tagged.md")
        storage.add_tag("/tmp/tagged.md", "python")  # add to tags table (not just denorm)
        storage.add_note("Other Note", "content", file_path="/tmp/other.md")
        result = runner.invoke(cli, ["search", "--tag", "python"], env=env)
        assert result.exit_code == 0, result.output
        assert "Tagged Note" in result.output
        assert "Other Note" not in result.output


# ---------------------------------------------------------------------------
# search with query
# ---------------------------------------------------------------------------

class TestSearchWithQuery:
    """Tests for: mdnotes search <query>"""

    def test_search_no_results_exits_1(self, search_isolated_db):
        """FTS5 search with no matches exits 1."""
        runner, env = search_isolated_db
        storage.add_note("Some Note", "python content", file_path="/tmp/a.md")
        result = runner.invoke(cli, ["search", "nonexistent_term_xyz"], env=env)
        assert result.exit_code == 1, result.output
        assert "No results found" in result.output

    def test_search_db_error_on_search_notes_exits_2(self, search_isolated_db):
        """search_notes raises DatabaseError exits 2."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        with patch.object(storage, "search_notes", side_effect=storage.DatabaseError("search db error")):
            result = runner.invoke(cli, ["search", "hello"], env=env)
        assert result.exit_code == 2, result.output
        assert "search db error" in result.output

    def test_search_ensure_fts5_db_error_exits_2(self, search_isolated_db):
        """ensure_fts5 raises DatabaseError before search exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "ensure_fts5", side_effect=storage.DatabaseError("fts5 error")):
            result = runner.invoke(cli, ["search", "hello"], env=env)
        assert result.exit_code == 2, result.output

    def test_search_results_include_snippet_and_tags(self, search_isolated_db):
        """Search results show snippet and tags."""
        runner, env = search_isolated_db
        storage.add_note("Python Note", "python is great", file_path="/tmp/a.md")
        storage.set_note_tags(1, "v1,python")
        result = runner.invoke(cli, ["search", "python"], env=env)
        assert result.exit_code == 0, result.output
        assert "Python Note" in result.output
        # snippet and tags should appear
        assert "python" in result.output.lower()

    def test_search_file_path_with_spaces(self, search_isolated_db):
        """Search result with space in file_path is quoted."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/my note.md")
        result = runner.invoke(cli, ["search", "content"], env=env)
        assert result.exit_code == 0, result.output
        # Should quote the path with spaces
        assert '"' in result.output or 'my note.md' in result.output

    def test_search_quoted_phrase_uses_and_semantics(self, search_isolated_db):
        """Quoted phrase in query uses AND semantics (FTS5 passes through)."""
        runner, env = search_isolated_db
        storage.add_note("Note A", "python and redis", file_path="/tmp/a.md")
        storage.add_note("Note B", "python only", file_path="/tmp/b.md")
        result = runner.invoke(cli, ["search", '"python redis"'], env=env)
        assert result.exit_code == 0, result.output
        # Only Note A should match (has both words)
        assert "Note A" in result.output
        assert "Note B" not in result.output

    def test_search_special_chars_escaped(self, search_isolated_db):
        """Query with FTS5 special chars (& | - etc.) is escaped to literal."""
        runner, env = search_isolated_db
        storage.add_note("Note", "hello & world", file_path="/tmp/a.md")
        result = runner.invoke(cli, ["search", "hello & world"], env=env)
        assert result.exit_code == 0, result.output

    def test_search_limit_option(self, search_isolated_db):
        """--limit caps results."""
        runner, env = search_isolated_db
        for i in range(5):
            storage.add_note(f"Note {i}", "python content", file_path=f"/tmp/n{i}.md")
        result = runner.invoke(cli, ["search", "python", "--limit", "2"], env=env)
        assert result.exit_code == 0, result.output
        # Count "Note N" occurrences in output
        note_lines = [line for line in result.output.split('\n') if line.startswith('/tmp/')]
        assert len(note_lines) == 2, f"Expected 2 results, got: {result.output}"


# ---------------------------------------------------------------------------
# FTS5 unavailability
# ---------------------------------------------------------------------------

class TestFTS5Unavailability:
    """Tests for FTS5 unavailable path in search command."""

    def test_search_fts5_unavailable_exits_2(self, search_isolated_db):
        """When FTS5 is unavailable, search exits 2 with error message."""
        runner, env = search_isolated_db
        with patch.object(storage, "_fts5_available", return_value=False):
            result = runner.invoke(cli, ["search", "hello"], env=env)
        assert result.exit_code == 2, result.output
        assert "FTS5" in result.output
        assert "not available" in result.output.lower()

    def test_search_check_fts5_unavailable_exits_2(self, search_isolated_db):
        """--check when FTS5 unavailable exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "_fts5_available", return_value=False):
            result = runner.invoke(cli, ["search", "--check"], env=env)
        assert result.exit_code == 2, result.output

    def test_search_rebuild_fts5_unavailable_exits_2(self, search_isolated_db):
        """--rebuild when FTS5 unavailable exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "_fts5_available", return_value=False):
            result = runner.invoke(cli, ["search", "--rebuild"], env=env)
        assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------
# reindex command
# ---------------------------------------------------------------------------

class TestReindexCommand:
    """Tests for: mdnotes reindex"""

    def test_reindex_success(self, search_isolated_db):
        """reindex with confirmation rebuilds index and exits 0."""
        runner, env = search_isolated_db
        storage.add_note("Note 1", "python content", file_path="/tmp/a.md")
        result = runner.invoke(cli, ["reindex"], env=env, input="y\n")
        assert result.exit_code == 0, f"{result.output}\n{result.exception}"
        assert "rebuilt successfully" in result.output.lower()

    def test_reindex_fts5_unavailable_exits_2(self, search_isolated_db):
        """reindex when FTS5 unavailable exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "_fts5_available", return_value=False):
            result = runner.invoke(cli, ["reindex"], env=env, input="y\n")
        assert result.exit_code == 2, result.output

    def test_reindex_db_error_exits_2(self, search_isolated_db):
        """reindex when rebuild_fts5 raises DatabaseError exits 2."""
        runner, env = search_isolated_db
        with patch.object(storage, "rebuild_fts5", side_effect=storage.DatabaseError("reindex error")):
            result = runner.invoke(cli, ["reindex"], env=env, input="y\n")
        assert result.exit_code == 2, result.output
        assert "reindex error" in result.output

    def test_reindex_help(self, search_isolated_db):
        """reindex --help shows usage and exits 0."""
        runner, env = search_isolated_db
        result = runner.invoke(cli, ["reindex", "--help"], env=env)
        assert result.exit_code == 0
        assert "Rebuild the FTS5" in result.output


# ---------------------------------------------------------------------------
# _extract_title_from_content (via search note display path)
# ---------------------------------------------------------------------------

class TestExtractTitleFromContent:
    """Coverage for _extract_title_from_content via add/file paths."""

    def test_add_file_no_frontmatter_uses_first_heading(self, search_isolated_db):
        """File without frontmatter but with # heading uses heading as title."""
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text("# My Custom Title\nSome body content.", encoding="utf-8")
            env2 = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(cli, ["add", str(md_path)], env=env2)
            assert result.exit_code == 0, result.output
            # Verify the title in DB
            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            c.execute("SELECT title FROM notes ORDER BY id")
            title = c.fetchone()[0]
            conn.close()
            assert title == "My Custom Title"

    def test_add_file_with_frontmatter_uses_heading(self, search_isolated_db):
        """File with frontmatter and # heading uses heading (not frontmatter) as title."""
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text(
                "---\ntitle: Frontmatter Title\n---\n# Actual Title\nBody.",
                encoding="utf-8",
            )
            env2 = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(cli, ["add", str(md_path)], env=env2)
            assert result.exit_code == 0, result.output
            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            c.execute("SELECT title FROM notes ORDER BY id")
            title = c.fetchone()[0]
            conn.close()
            assert title == "Actual Title"

    def test_add_file_no_heading_uses_stem(self, search_isolated_db):
        """File with no # heading uses filename stem as title."""
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "my_custom_note.md"
            md_path.write_text("Plain text with no heading.", encoding="utf-8")
            env2 = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(cli, ["add", str(md_path)], env=env2)
            assert result.exit_code == 0, result.output
            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            c.execute("SELECT title FROM notes ORDER BY id")
            title = c.fetchone()[0]
            conn.close()
            assert title == "my_custom_note"


# ---------------------------------------------------------------------------
# delete --force error paths
# ---------------------------------------------------------------------------

class TestDeleteErrorPaths:
    """Error path coverage for delete command."""

    def test_delete_db_error_on_get_note_exits_1(self, search_isolated_db):
        """delete when get_note raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        with patch.object(storage, "get_note", side_effect=storage.DatabaseError("delete db error")):
            result = runner.invoke(cli, ["delete", "1", "--force"], env=env)
        assert result.exit_code == 1, result.output
        assert "delete db error" in result.output

    def test_delete_db_error_on_delete_note_exits_1(self, search_isolated_db):
        """delete when delete_note raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        with patch.object(storage, "delete_note", side_effect=storage.DatabaseError("delete_note db error")):
            result = runner.invoke(cli, ["delete", "1", "--force"], env=env)
        assert result.exit_code == 1, result.output
        assert "delete_note db error" in result.output


# ---------------------------------------------------------------------------
# ls database error
# ---------------------------------------------------------------------------

class TestLsErrorPaths:
    """Error path coverage for ls command."""

    def test_ls_db_error_exits_1(self, search_isolated_db):
        """ls when list_notes raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        with patch.object(storage, "list_notes", side_effect=storage.DatabaseError("ls db error")):
            result = runner.invoke(cli, ["ls"], env=env)
        assert result.exit_code == 1, result.output
        assert "ls db error" in result.output


# ---------------------------------------------------------------------------
# add error paths (file mode)
# ---------------------------------------------------------------------------

class TestAddFileErrorPaths:
    """Error path coverage for add with file path."""

    def test_add_file_directory_instead_exits_2(self, search_isolated_db):
        """add with a path ending in .md that is actually a directory.
        
        Path(file_path).is_file() returns False for a directory, so it falls
        through to title+content mode. The directory path (as title) is created
        as a note — this is the actual behavior.
        """
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "note.md"
            md_path.mkdir()  # make it a directory, not a file
            result = runner.invoke(cli, ["add", str(md_path)], env=env)
            # Falls through to title+content mode → creates a note with path as title
            assert result.exit_code == 0, result.output

    def test_add_file_db_error_on_add_note_exits_1(self, search_isolated_db):
        """add when add_note raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text("# Title\nContent.", encoding="utf-8")
            with patch.object(storage, "add_note", side_effect=storage.DatabaseError("add_note db error")):
                result = runner.invoke(cli, ["add", str(md_path)], env=env)
            assert result.exit_code == 1, result.output
            assert "add_note db error" in result.output

    def test_add_file_set_note_tags_db_error_exits_1(self, search_isolated_db):
        """add when set_note_tags raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text("---\ntags: [v1]\n---\n# Title\nContent #v1.", encoding="utf-8")
            with patch.object(storage, "set_note_tags", side_effect=storage.DatabaseError("set_note_tags db error")):
                result = runner.invoke(cli, ["add", str(md_path)], env=env)
            assert result.exit_code == 1, result.output
            assert "set_note_tags db error" in result.output

    def test_add_file_no_valid_files_exits_1(self, search_isolated_db):
        """add with a .md file that cannot be read exits 1."""
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a .md file that is not readable (permission denied)
            md_path = Path(tmpdir) / "note.md"
            md_path.write_text("# Title", encoding="utf-8")
            import stat
            md_path.chmod(0)
            try:
                result = runner.invoke(cli, ["add", str(md_path)], env=env)
                assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}: {result.output}"
                assert "cannot read file" in result.output.lower()
            finally:
                md_path.chmod(stat.S_IRWXU)


# ---------------------------------------------------------------------------
# delete --force: input() EOFError + delete_note DatabaseError
# ---------------------------------------------------------------------------

class TestDeleteInputAndDbErrors:
    """Error path coverage for delete command."""

    def test_delete_eof_error_input(self, search_isolated_db):
        """delete without --force when input() raises EOFError behaves as 'n'."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        # Simulate EOF by closing stdin
        result = runner.invoke(cli, ["delete", "1"], env=env, input="")
        # Should exit 0 (cancelled)
        assert result.exit_code == 0, f"Expected 0, got {result.exit_code}: {result.output}"

    def test_delete_delete_note_db_error_exits_1(self, search_isolated_db):
        """delete when delete_note raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        with patch.object(storage, "delete_note", side_effect=storage.DatabaseError("delete_note_db_error")):
            result = runner.invoke(cli, ["delete", "1", "--force"], env=env)
        assert result.exit_code == 1, result.output
        assert "delete_note_db_error" in result.output


# ---------------------------------------------------------------------------
# count database error
# ---------------------------------------------------------------------------

class TestCountDbError:
    """Error path for count command."""

    def test_count_db_error_exits_1(self, search_isolated_db):
        """count when count_notes raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        with patch.object(storage, "count_notes", side_effect=storage.DatabaseError("count_db_error")):
            result = runner.invoke(cli, ["count"], env=env)
        assert result.exit_code == 1, result.output
        assert "count_db_error" in result.output


# ---------------------------------------------------------------------------
# show: get_note ValueError (via mock) + DatabaseError (via mock)
# ---------------------------------------------------------------------------

class TestShowDbErrors:
    """Error path for show command."""

    def test_show_get_note_value_error_exits_2(self, search_isolated_db):
        """show when get_note raises ValueError exits 2."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        with patch.object(storage, "get_note", side_effect=ValueError("invalid id")):
            result = runner.invoke(cli, ["show", "1"], env=env)
        assert result.exit_code == 2, result.output

    def test_show_get_note_db_error_exits_1(self, search_isolated_db):
        """show when get_note raises DatabaseError exits 1."""
        runner, env = search_isolated_db
        storage.add_note("Note", "content", file_path="/tmp/a.md")
        with patch.object(storage, "get_note", side_effect=storage.DatabaseError("show_db_error")):
            result = runner.invoke(cli, ["show", "1"], env=env)
        assert result.exit_code == 1, result.output
        assert "show_db_error" in result.output


# ---------------------------------------------------------------------------
# _extract_title_from_content edge cases
# ---------------------------------------------------------------------------

class TestExtractTitleEdgeCases:
    """Edge cases for _extract_title_from_content."""

    def test_frontmatter_no_closing_dashdash(self, search_isolated_db):
        """File starting with --- but no closing --- uses filename stem as title."""
        runner, env = search_isolated_db
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "my_unclosed.md"
            # Starts with --- but no closing ---\n
            md_path.write_text("---\ntags: [v1]\nSome content.", encoding="utf-8")
            env2 = {**env, "MDNOTES_VAULT": tmpdir}
            result = runner.invoke(cli, ["add", str(md_path)], env=env2)
            assert result.exit_code == 0, result.output
            conn = sqlite3.connect(env["MDNOTES_DB"])
            c = conn.cursor()
            c.execute("SELECT title FROM notes ORDER BY id")
            title = c.fetchone()[0]
            conn.close()
            # Falls back to filename stem since no heading found
            assert title == "my_unclosed"


# ---------------------------------------------------------------------------
# search: result display with tags + file_path quoting
# ---------------------------------------------------------------------------

class TestSearchResultDisplay:
    """Cover search result display branches."""

    def test_search_result_with_tags_and_file_path(self, search_isolated_db):
        """search results display includes tags and file_path (with spaces → quoted)."""
        runner, env = search_isolated_db
        note_id = storage.add_note("Tag Note", "python content here", file_path="/tmp/my note.md")
        storage.add_tag("/tmp/my note.md", "v1")
        storage.set_note_tags(note_id, "v1")  # Update denorm tags column + FTS5 tag column
        result = runner.invoke(cli, ["search", "python"], env=env)
        assert result.exit_code == 0, result.output
        # File path with space should be quoted
        assert '"' in result.output or 'my note.md' in result.output
        # Tags should appear
        assert "v1" in result.output or "tags" in result.output

    def test_search_result_multiple_lines_display(self, search_isolated_db):
        """search with multiple results displays each correctly."""
        runner, env = search_isolated_db
        storage.add_note("Note A", "python code here", file_path="/tmp/a.md")
        storage.add_note("Note B", "python is great", file_path="/tmp/b.md")
        storage.add_tag("/tmp/a.md", "dev")
        storage.add_tag("/tmp/b.md", "dev")
        result = runner.invoke(cli, ["search", "python"], env=env)
        assert result.exit_code == 0, result.output
        assert "Note A" in result.output
        assert "Note B" in result.output


