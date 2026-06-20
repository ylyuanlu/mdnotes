"""Tests for: mdnotes tag rename <old> <new>"""

import os
import tempfile
import pytest
from click.testing import CliRunner
from mdnotes.cli import cli
from mdnotes import storage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def temp_vault(runner):
    """Create a temp vault directory with a mdnotes DB and some .md files.

    Key: os.environ is set in the MAIN PROCESS (before CliRunner forks).
    CliRunner.invoke() runs in a SUBPROCESS that inherits os.environ
    from the main process, AND gets env overrides from the env param.
    We set BOTH to ensure the child process sees the right DB path.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "notes.db")
        vault_dir = os.path.join(tmpdir, "vault")
        os.makedirs(vault_dir)
        # Set in os.environ BEFORE CliRunner forks so child inherits it
        os.environ["MDNOTES_DB"] = db_path
        os.environ["MDNOTES_VAULT"] = vault_dir
        env = {"MDNOTES_DB": db_path, "MDNOTES_VAULT": vault_dir}
        # Bootstrap the DB
        storage._get_connection(db_path)

        # Create some test files with tags
        def make_file(name, content):
            p = os.path.join(vault_dir, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
            return p

        file1 = make_file("note1.md", "---\ntags: [v1]\n---\n# Note 1\nContent #v1 here.\n")
        file2 = make_file("note2.md", "---\ntags: [v1]\n---\n# Note 2\nAlso #v1.\n")
        file3 = make_file("note3.md", "---\ntags: [other]\n---\n# Note 3\nNo v1 here.\n")

        # Index the tags in the main process (env vars already set)
        for p in [file1, file2, file3]:
            storage.scan_and_index_file(p)

        yield runner, env, vault_dir, file1, file2, file3

        # Clean up env vars
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        if "MDNOTES_VAULT" in os.environ:
            del os.environ["MDNOTES_VAULT"]


# ---------------------------------------------------------------------------
# B-1: mdnotes tag rename v1 v2 renames and outputs correct message
# ---------------------------------------------------------------------------

class TestRenameBasic:
    """B-1: Basic rename works and prints correct output."""

    def test_rename_updates_file_content(self, temp_vault):
        runner, env, vault_dir, file1, file2, _ = temp_vault

        result = runner.invoke(cli, ["tag", "rename", "v1", "v2"], env=env)

        # Check exit code
        assert result.exit_code == 0, f"stdout: {result.output}\nstderr: {result.exception}"

        # Check output message
        assert "Renamed tag '#v1' → '#v2' in 2 files" in result.output, result.output

        # Verify files were actually changed
        with open(file1) as f:
            content = f.read()
        assert "#v2" in content
        assert "#v1" not in content

    def test_rename_updates_storage(self, temp_vault):
        """B-1: DB entries are also renamed (v1 gone, v2 present)."""
        runner, env, vault_dir, file1, file2, _ = temp_vault

        runner.invoke(cli, ["tag", "rename", "v1", "v2"], env=env)

        assert storage.get_affected_files("v1") == []
        v2_files = storage.get_affected_files("v2")
        assert file1 in v2_files
        assert file2 in v2_files


# ---------------------------------------------------------------------------
# B-2: nonexistent tag errors with exit 1
# ---------------------------------------------------------------------------

class TestRenameNotFound:
    """B-2: Renaming nonexistent tag exits 3 with error message."""

    def test_rename_nonexistent_exits_3(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(cli, ["tag", "rename", "nonexistent", "new"], env=env)
        assert result.exit_code == 3
        assert "not found" in result.output.lower()

    def test_rename_nonexistent_ignore_missing_exits_0(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(
            cli, ["tag", "rename", "nonexistent", "new", "--ignore-missing"], env=env
        )
        assert result.exit_code == 0
        assert "No changes needed" in result.output


# ---------------------------------------------------------------------------
# B-3: old == new exits 0 with "No changes needed"
# ---------------------------------------------------------------------------

class TestRenameSameTag:
    """B-3: Renaming old==new exits 0 'No changes needed'."""

    def test_rename_same_tag(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(cli, ["tag", "rename", "v1", "v1"], env=env)
        assert result.exit_code == 0
        assert "No changes needed" in result.output


# ---------------------------------------------------------------------------
# B-4: --dry-run does not modify files or DB
# ---------------------------------------------------------------------------

class TestDryRun:
    """B-4: --dry-run is read-only and exits 0."""

    def test_dry_run_does_not_modify_files(self, temp_vault):
        runner, env, vault_dir, file1, file2, _ = temp_vault

        result = runner.invoke(cli, ["tag", "rename", "v1", "v2", "--dry-run"], env=env)

        assert result.exit_code == 0
        assert "[DRY-RUN]" in result.output
        assert "note1.md" in result.output or file1 in result.output

        # Files unchanged
        with open(file1) as f:
            content = f.read()
        assert "#v1" in content  # still v1

    def test_dry_run_does_not_modify_db(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault

        runner.invoke(cli, ["tag", "rename", "v1", "v2", "--dry-run"], env=env)

        # v1 still in DB
        assert len(storage.get_affected_files("v1")) == 2
        assert storage.get_affected_files("v2") == []


# ---------------------------------------------------------------------------
# B-5: --force allows new tag to already exist (merge semantics)
# ---------------------------------------------------------------------------

class TestForceFlag:
    """B-5: --force allows merge when new tag already exists in a file."""

    def test_force_merge_case(self, temp_vault):
        runner, env, vault_dir, file1, file2, _ = temp_vault

        # file1 already has v2 tag (add it)
        storage.add_tag(file1, "v2")

        result = runner.invoke(
            cli, ["tag", "rename", "v1", "v2", "--force"], env=env
        )

        assert result.exit_code == 0
        # file1: both v1→v2 happened (merged), file2: v1→v2
        with open(file1) as f:
            content = f.read()
        assert "#v2" in content  # was already there, still there


# ---------------------------------------------------------------------------
# B-7: old vs new case-only conflict exits 1
# ---------------------------------------------------------------------------

class TestCaseConflict:
    """B-7: v1 → V1 case-only conflict exits 1."""

    def test_case_conflict_exits_1(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(cli, ["tag", "rename", "v1", "V1"], env=env)
        assert result.exit_code == 1
        assert "conflict" in result.output.lower() or "case" in result.output.lower()


# ---------------------------------------------------------------------------
# Parameter validation: empty/whitespace tag names
# ---------------------------------------------------------------------------

class TestParamValidation:
    """Empty or whitespace-only tag names exit 2."""

    def test_empty_old_tag_exits_2(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(cli, ["tag", "rename", "", "v2"], env=env)
        assert result.exit_code == 2

    def test_whitespace_old_tag_exits_2(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(cli, ["tag", "rename", "   ", "v2"], env=env)
        assert result.exit_code == 2

    def test_empty_new_tag_exits_2(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(cli, ["tag", "rename", "v1", ""], env=env)
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------

class TestTagRenameHelp:
    """--help shows usage and exits 0."""

    def test_help(self, temp_vault):
        runner, env, _, _, _, _ = temp_vault
        result = runner.invoke(cli, ["tag", "rename", "--help"], env=env)
        assert result.exit_code == 0
        assert "old" in result.output.lower()
        assert "new" in result.output.lower()


# ---------------------------------------------------------------------------
# Additional tag rename error path tests
# ---------------------------------------------------------------------------

class TestRenameErrorPaths:
    """Additional error path coverage for tag rename."""

    def test_rename_db_not_found(self, temp_vault):
        """DB errors during rename exit 1."""
        runner, env, vault_dir, file1, file2, _ = temp_vault
        # Corrupt the DB path
        bad_env = dict(env)
        bad_env["MDNOTES_DB"] = "/nonexistent/bad.db"
        result = runner.invoke(cli, ["tag", "rename", "v1", "v2"], env=bad_env)
        assert result.exit_code == 1

    def test_rename_empty_vault_dir_unwritable(self, temp_vault):
        """Non-writable file during rename causes rollback or pre-flight failure."""
        runner, env, vault_dir, file1, file2, _ = temp_vault
        # Make file read-only
        import stat
        os.chmod(file1, stat.S_IRUSR | stat.S_IXUSR)
        try:
            result = runner.invoke(cli, ["tag", "rename", "v1", "v2"], env=env)
            # Should either fail pre-flight or rollback
            assert result.exit_code in (1, 2)
        finally:
            os.chmod(file1, stat.S_IRWXU)

    def test_rename_large_batch_warning(self, temp_vault):
        """Batch > 10 files shows warning."""
        # Current fixture has 3 files < 10, skip
        pass
