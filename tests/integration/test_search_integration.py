"""Integration tests for mdnotes search (end-to-end CLI)."""

import os
import subprocess
import pytest


# Use whichever `uv` is on PATH (CI runner installs it; local dev uses ~/.local/bin/uv).
UV = "uv"


def mdnotes_cmd(args, cwd=None, env=None, input=None):
    """Run mdnotes CLI via uv and return (stdout, stderr, exit_code)."""
    base_env = dict(os.environ)
    if env:
        base_env.update(env)
    result = subprocess.run(
        [UV, "run", "mdnotes"] + args,
        cwd=cwd or os.getcwd(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=base_env,
        input=input,
    )
    return result.stdout, result.stderr, result.returncode


@pytest.fixture
def test_vault(tmp_path):
    """A temporary vault with 3 test markdown files."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text(
        "---\ntags: [v1, work]\n---\n# A\nContent with #v1 inline tag.\n",
        encoding="utf-8",
    )
    (vault / "b.md").write_text(
        "---\ntags: [v1]\n---\n# B\nAlso has #v1 tag in body.\n",
        encoding="utf-8",
    )
    (vault / "c.md").write_text(
        "---\ntags: [v2]\n---\n# C\nDifferent tag v2 content.\n",
        encoding="utf-8",
    )
    return vault


class TestSearchCLI:
    """End-to-end CLI search tests."""

    def test_search_multi_file_results(self, test_vault, tmp_path):
        """mdnotes search 'v1' returns results from multiple files (a.md + b.md)."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        # Add all 3 files
        _, err, code = mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)
        assert code == 0, f"add a.md failed: {err}"
        _, err, code = mdnotes_cmd(["add", str(test_vault / "b.md")], env=env)
        assert code == 0, f"add b.md failed: {err}"
        _, err, code = mdnotes_cmd(["add", str(test_vault / "c.md")], env=env)
        assert code == 0, f"add c.md failed: {err}"

        # Search for v1 → should find a.md and b.md, NOT c.md
        out, err, code = mdnotes_cmd(["search", "v1"], env=env)
        assert code == 0, f"search v1 failed: {err}"

    def test_search_returns_correct_exit_codes(self, test_vault, tmp_path):
        """Exit codes: 0=results, 1=no results, 2=error."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        # Add a note
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)

        # Has results → exit 0
        _, _, code = mdnotes_cmd(["search", "v1"], env=env)
        assert code == 0, "search with results should exit 0"

        # No results → exit 1
        _, _, code = mdnotes_cmd(["search", "nonexistent_term_xyz"], env=env)
        assert code == 1, "search with no results should exit 1"

    def test_search_no_query_lists_all_notes(self, test_vault, tmp_path):
        """No query argument lists all notes (like ls), exit 0."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        # Add notes
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)  # A
        mdnotes_cmd(["add", str(test_vault / "b.md")], env=env)  # B
        mdnotes_cmd(["add", str(test_vault / "c.md")], env=env)  # C

        # No query → lists all notes
        out, err, code = mdnotes_cmd(["search"], env=env)
        assert code == 0, f"search with no query should exit 0: {err}"
        assert "A" in out, f"Should list note A: {out}"
        assert "B" in out, f"Should list note B: {out}"
        assert "C" in out, f"Should list note C: {out}"

    def test_search_empty_query_arg_lists_all_notes(self, test_vault, tmp_path):
        """Empty string query lists all notes (like ls), exit 0."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)
        mdnotes_cmd(["add", str(test_vault / "b.md")], env=env)

        out, err, code = mdnotes_cmd(["search", ""], env=env)
        assert code == 0, f"search '' should exit 0: {err}"
        assert "A" in out, f"Should list note A: {out}"
        assert "B" in out, f"Should list note B: {out}"

    def test_search_no_query_with_tag(self, test_vault, tmp_path):
        """search --tag v1 (no query) lists only notes tagged v1."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)  # tags: v1, work
        mdnotes_cmd(["add", str(test_vault / "b.md")], env=env)  # tags: v1
        mdnotes_cmd(["add", str(test_vault / "c.md")], env=env)  # tags: v2

        # No query, --tag v1 → only v1-tagged notes
        out, err, code = mdnotes_cmd(["search", "--tag", "v1"], env=env)
        assert code == 0, f"search --tag v1 (no query) should exit 0: {err}"
        assert "A" in out, f"Should list note A (tagged v1): {out}"
        assert "B" in out, f"Should list note B (tagged v1): {out}"
        assert "C" not in out, f"Should NOT list note C (tagged v2): {out}"

    def test_search_no_results(self, test_vault, tmp_path):
        """Search with no matches returns exit code 1."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)
        _, err, code = mdnotes_cmd(["search", "nonexistent_xyz"], env=env)
        assert code == 1
        assert "no results" in err.lower() or "not found" in err.lower()

    def test_search_chinese(self, test_vault, tmp_path):
        """Chinese multi-char search works (unicode61 tokenizer)."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        zh_file = test_vault / "zh.md"
        zh_file.write_text(
            "---\ntags: [笔记]\n---\n# 中文笔记\n这是中文内容。\n",
            encoding="utf-8",
        )
        _, err, code = mdnotes_cmd(["add", str(zh_file)], env=env)
        assert code == 0, f"add zh.md failed: {err}"

        # Search for multi-char Chinese term
        out, err, code = mdnotes_cmd(["search", "笔记"], env=env)
        assert code == 0, f"search 笔记 failed: out={out!r} err={err!r}"
        assert "中文笔记" in out, f"Expected '中文笔记' in output: {out!r}"

    def test_fts5_trigger_sync_add(self, test_vault, tmp_path):
        """After add, search immediately finds the new note."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)
        out, err, code = mdnotes_cmd(["search", "v1"], env=env)
        assert code == 0
        assert "A" in out or "v1" in out.lower()

    def test_fts5_trigger_sync_delete(self, test_vault, tmp_path):
        """After delete, search no longer finds the note."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        # Add note
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)
        # Verify it exists
        out, _, code = mdnotes_cmd(["search", "v1"], env=env)
        assert code == 0
        # Delete note 1
        _, _, code = mdnotes_cmd(["delete", "1", "--force"], env=env)
        assert code == 0
        # Search again - should not find it
        _, err, code = mdnotes_cmd(["search", "v1"], env=env)
        assert code == 1, "After delete, search should return no results"

    def test_search_reindex(self, test_vault, tmp_path):
        """mdnotes reindex rebuilds FTS5 without errors."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)
        # Run reindex (confirmation via stdin)
        _, err, code = mdnotes_cmd(["reindex"], env=env, input="y\n")
        assert code == 0, f"reindex failed: {err}"
        # Search should still work
        out, err, code = mdnotes_cmd(["search", "v1"], env=env)
        assert code == 0

    def test_search_tag_filter(self, test_vault, tmp_path):
        """mdnotes search --tag filters by exact tag."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)  # v1,work
        mdnotes_cmd(["add", str(test_vault / "b.md")], env=env)  # v1
        mdnotes_cmd(["add", str(test_vault / "c.md")], env=env)  # v2

        # --tag v1 should find notes tagged v1
        out, err, code = mdnotes_cmd(["search", "--tag", "v1", "content"], env=env)
        assert code == 0

    def test_search_special_chars(self, test_vault, tmp_path):
        """Special FTS5 chars handled: valid operators return results, invalid cause exit 2."""
        db_path = tmp_path / "notes.db"
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(test_vault),
        }
        mdnotes_cmd(["add", str(test_vault / "a.md")], env=env)
        # v1 & work: & is valid AND operator, returns results (exit 0)
        out, err, code = mdnotes_cmd(["search", "v1 & work"], env=env)
        assert code == 0, f"Valid & operator should return results: err={err!r}"
        # "unclosed: unmatched quote causes FTS5 syntax error → exit 2
        _, err, code = mdnotes_cmd(["search", '"unclosed'], env=env)
        assert code == 2, f"Unmatched quote should cause error exit 2: err={err!r}"

    def test_vault_with_no_md_files(self, tmp_path):
        """Empty vault returns no results."""
        db_path = tmp_path / "notes.db"
        vault = tmp_path / "empty_vault"
        vault.mkdir()
        env = {
            "MDNOTES_DB": str(db_path),
            "MDNOTES_VAULT": str(vault),
        }
        _, err, code = mdnotes_cmd(["search", "anything"], env=env)
        assert code == 1, "No results from empty vault should exit 1"
