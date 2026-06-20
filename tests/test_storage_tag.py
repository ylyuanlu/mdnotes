"""Tests for tag storage operations (tag rename feature)."""

import os
import tempfile
from pathlib import Path
import pytest
from mdnotes import storage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class TagTestHelper:
    """Shared setup/teardown for tag storage tests."""

    def setup_method(self):
        self._orig_db_path = storage._get_db_path()
        self._temp_dir = tempfile.mkdtemp()
        self._temp_db = os.path.join(self._temp_dir, "notes.db")
        os.environ["MDNOTES_DB"] = self._temp_db
        # Initialise schema
        storage._get_connection(self._temp_db)

    def teardown_method(self):
        if "MDNOTES_DB" in os.environ:
            del os.environ["MDNOTES_DB"]
        import shutil
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def add_tag(self, file_path: str, tag_name: str) -> None:
        storage.add_tag(file_path, tag_name)

    def get_affected(self, tag_name: str) -> list[str]:
        return storage.get_affected_files(tag_name)


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------

class TestTagExceptions:
    """Exception classes are importable and have expected hierarchy."""

    def test_tag_not_found_error_exists(self):
        assert issubclass(storage.TagNotFoundError, Exception)

    def test_tag_conflict_error_exists(self):
        assert issubclass(storage.TagConflictError, Exception)

    def test_backup_error_exists(self):
        assert issubclass(storage.BackupError, Exception)


# ---------------------------------------------------------------------------
# add_tag
# ---------------------------------------------------------------------------

class TestAddTag(TagTestHelper):
    """add_tag inserts tag rows correctly."""

    def test_add_tag_basic(self):
        """A single tag can be added for a file."""
        storage.add_tag("/tmp/test.md", "v1")
        files = self.get_affected("v1")
        assert "/tmp/test.md" in files

    def test_add_tag_same_file_different_tags(self):
        """Two different tags for the same file are both tracked."""
        storage.add_tag("/tmp/test.md", "v1")
        storage.add_tag("/tmp/test.md", "v2")
        assert "/tmp/test.md" in self.get_affected("v1")
        assert "/tmp/test.md" in self.get_affected("v2")

    def test_add_tag_duplicate_is_ignored(self):
        """Adding the same (file, tag) pair twice is idempotent (INSERT OR IGNORE)."""
        storage.add_tag("/tmp/test.md", "v1")
        storage.add_tag("/tmp/test.md", "v1")  # duplicate
        files = self.get_affected("v1")
        # Should still appear only once
        count = sum(1 for f in files if f == "/tmp/test.md")
        assert count == 1


# ---------------------------------------------------------------------------
# get_affected_files
# ---------------------------------------------------------------------------

class TestGetAffectedFiles(TagTestHelper):
    """get_affected_files returns files that have the given tag."""

    def test_nonexistent_tag_returns_empty_list(self):
        """A tag that was never added returns []."""
        assert storage.get_affected_files("nonexistent") == []

    def test_returns_all_files_with_tag(self):
        """Multiple files with the same tag are all returned."""
        storage.add_tag("/tmp/a.md", "python")
        storage.add_tag("/tmp/b.md", "python")
        storage.add_tag("/tmp/c.md", "python")
        files = self.get_affected("python")
        assert len(files) == 3
        assert all(f in files for f in ["/tmp/a.md", "/tmp/b.md", "/tmp/c.md"])

    def test_does_not_return_files_without_tag(self):
        """Files without the tag are excluded."""
        storage.add_tag("/tmp/a.md", "v1")
        storage.add_tag("/tmp/b.md", "v2")
        assert "/tmp/b.md" not in self.get_affected("v1")


# ---------------------------------------------------------------------------
# rename_tag
# ---------------------------------------------------------------------------

class TestRenameTag(TagTestHelper):
    """rename_tag renames tags in the database correctly."""

    def test_rename_basic(self):
        """rename_tag updates tag_name from old to new in DB."""
        storage.add_tag("/tmp/test.md", "v1")
        count = storage.rename_tag("v1", "v2")
        assert count == 1
        assert self.get_affected("v1") == []
        assert "/tmp/test.md" in self.get_affected("v2")

    def test_rename_multiple_files(self):
        """rename_tag updates all files with the old tag."""
        storage.add_tag("/tmp/a.md", "old")
        storage.add_tag("/tmp/b.md", "old")
        storage.add_tag("/tmp/c.md", "old")
        count = storage.rename_tag("old", "new")
        assert count == 3
        assert self.get_affected("old") == []
        assert len(self.get_affected("new")) == 3

    def test_rename_nonexistent_raises_tag_not_found_error(self):
        """Renaming a nonexistent tag raises TagNotFoundError."""
        with pytest.raises(storage.TagNotFoundError):
            storage.rename_tag("nonexistent", "new")

    def test_rename_nonexistent_with_ignore_missing_returns_zero(self):
        """Renaming nonexistent with ignore_missing=True returns 0."""
        from dataclasses import dataclass
        @dataclass
        class Opts:
            ignore_missing: bool = True
            force: bool = False
            dry_run: bool = False
            glob: str | None = None
            exclude: list = None
        opts = Opts()
        count = storage.rename_tag("nonexistent", "new", opts)
        assert count == 0

    def test_rename_same_tag_raises_conflict_error(self):
        """Renaming old==new when the tag exists raises TagConflictError (CLI checks old==new first)."""
        storage.add_tag("/tmp/test.md", "v1")
        with pytest.raises(storage.TagConflictError):
            storage.rename_tag("v1", "v1")

    def test_rename_case_conflict_raises(self):
        """Renaming to a name that differs only by case raises TagConflictError."""
        storage.add_tag("/tmp/test.md", "v1")
        with pytest.raises(storage.TagConflictError):
            storage.rename_tag("v1", "V1")

    def test_rename_force_allows_duplicate_new_tag(self):
        """With force=True, renaming when new already exists merges tags."""
        storage.add_tag("/tmp/test.md", "v1")
        storage.add_tag("/tmp/test.md", "v2")
        from dataclasses import dataclass
        @dataclass
        class Opts:
            ignore_missing: bool = False
            force: bool = True
            dry_run: bool = False
            glob: str | None = None
            exclude: list = None
        opts = Opts()
        count = storage.rename_tag("v1", "v2", opts)
        assert count == 1
        # v2 now has the file; v1 is gone
        assert self.get_affected("v1") == []
        assert "/tmp/test.md" in self.get_affected("v2")

    def test_rename_without_force_errors_on_conflict(self):
        """Without force=True, renaming to an existing tag raises TagConflictError."""
        storage.add_tag("/tmp/test.md", "v1")
        storage.add_tag("/tmp/test.md", "v2")
        from dataclasses import dataclass
        @dataclass
        class Opts:
            ignore_missing: bool = False
            force: bool = False
            dry_run: bool = False
            glob: str | None = None
            exclude: list = None
        opts = Opts()
        with pytest.raises(storage.TagConflictError):
            storage.rename_tag("v1", "v2", opts)

    def test_rename_returns_affected_file_count(self):
        """rename_tag returns the number of affected files."""
        storage.add_tag("/tmp/a.md", "old")
        storage.add_tag("/tmp/b.md", "old")
        storage.add_tag("/tmp/c.md", "old")
        count = storage.rename_tag("old", "new")
        assert count == 3


# ---------------------------------------------------------------------------
# scan_and_index_file
# ---------------------------------------------------------------------------

class TestScanAndIndexFile(TagTestHelper):
    """scan_and_index_file reads tags from a markdown file and updates the DB."""

    def test_scan_extracts_tags_from_frontmatter(self):
        """Tags in YAML frontmatter are extracted and indexed."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("---\ntags: [python, v1]\n---\n# Hello\n")
            f.flush()
            path = f.name
        try:
            storage.scan_and_index_file(path)
            assert "/".join(["python", path]) in ["{}/{}".format(t, path) for t in self.get_affected("python")] or True
            # Verify by checking affected files contain the path
            python_files = [f for f in self.get_affected("python") if f == path]
            v1_files = [f for f in self.get_affected("v1") if f == path]
            assert len(python_files) == 1
            assert len(v1_files) == 1
        finally:
            os.unlink(path)

    def test_scan_extracts_inline_tags(self):
        """Inline #tags in body content are extracted."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("# My Note\n\nTagged with #python and #v2.\n")
            f.flush()
            path = f.name
        try:
            storage.scan_and_index_file(path)
            python_files = [f for f in self.get_affected("python") if f == path]
            v2_files = [f for f in self.get_affected("v2") if f == path]
            assert len(python_files) == 1
            assert len(v2_files) == 1
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# rename_tag_in_file
# ---------------------------------------------------------------------------

class TestRenameTagInFile(TagTestHelper):
    """rename_tag_in_file renames tags in a single file's frontmatter and body."""

    def test_rename_frontmatter_only(self):
        """Renaming updates tags: [v1] → tags: [v2] in frontmatter."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("---\ntags: [v1]\n---\n# Note\nBody.\n")
            f.flush()
            path = f.name
        try:
            result = storage.rename_tag_in_file(path, "v1", "v2")
            assert result is True
            content = Path(path).read_text()
            assert "tags: [v2]" in content
            assert "tags: [v1]" not in content
        finally:
            os.unlink(path)

    def test_rename_frontmatter_multiple_tags(self):
        """Renaming updates tags: [v1, other] → tags: [v2, other]."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("---\ntags: [v1, important]\n---\n# Note\nBody.\n")
            f.flush()
            path = f.name
        try:
            result = storage.rename_tag_in_file(path, "v1", "v2")
            assert result is True
            content = Path(path).read_text()
            assert "tags: [v2, important]" in content
            assert "tags: [v1" not in content
        finally:
            os.unlink(path)

    def test_rename_frontmatter_last_tag(self):
        """Renaming handles tags: [other, v1] → tags: [other, v2]."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("---\ntags: [other, v1]\n---\n# Note\nBody.\n")
            f.flush()
            path = f.name
        try:
            result = storage.rename_tag_in_file(path, "v1", "v2")
            assert result is True
            content = Path(path).read_text()
            assert "tags: [other, v2]" in content
            assert "tags: [other, v1]" not in content
        finally:
            os.unlink(path)

    def test_rename_inline_only(self):
        """Renaming updates inline #v1 → #v2 in body."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("# Note\nContent #v1 here.\n")
            f.flush()
            path = f.name
        try:
            result = storage.rename_tag_in_file(path, "v1", "v2")
            assert result is True
            content = Path(path).read_text()
            assert "#v2" in content
            assert "#v1" not in content
        finally:
            os.unlink(path)

    def test_rename_both_frontmatter_and_inline(self):
        """Renaming updates both frontmatter and inline #v1 → #v2."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("---\ntags: [v1]\n---\n# Note\nContent #v1 here.\n")
            f.flush()
            path = f.name
        try:
            result = storage.rename_tag_in_file(path, "v1", "v2")
            assert result is True
            content = Path(path).read_text()
            assert "tags: [v2]" in content
            assert "#v2" in content
            assert "tags: [v1]" not in content
            assert "#v1" not in content
        finally:
            os.unlink(path)

    def test_rename_no_matching_tag_returns_false(self):
        """rename_tag_in_file returns False when file has no matching tag."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            # File has no v1 in frontmatter or inline
            f.write("---\ntitle: My Note\n---\n# Note\nContent #other here.\n")
            f.flush()
            path = f.name
        try:
            result = storage.rename_tag_in_file(path, "v1", "v2")
            assert result is False
            # File content must be unchanged
            with open(path) as fh:
                content = fh.read()
            assert "title: My Note" in content
            assert "#other" in content
        finally:
            os.unlink(path)

    def test_rename_nonexistent_file_returns_false(self):
        """rename_tag_in_file returns False for non-existent file."""
        result = storage.rename_tag_in_file("/nonexistent/file.md", "v1", "v2")
        assert result is False

    def test_rename_single_tag_list(self):
        """Renaming tag that is alone in array: tags: [v1] → tags: [v2]."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("---\ntags: [v1]\n---\n# Note\nBody.\n")
            f.flush()
            path = f.name
        try:
            result = storage.rename_tag_in_file(path, "v1", "v2")
            assert result is True
            content = Path(path).read_text()
            assert "tags: [v2]" in content
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# _replace_tag_in_array (direct unit tests)
# ---------------------------------------------------------------------------

class TestReplaceTagInArray:
    """Unit tests for _replace_tag_in_array helper."""

    def test_replace_first_tag(self):
        """_replace_tag_in_array handles tag at start of array."""
        line = "tags: [v1, other]"
        result = storage._replace_tag_in_array(line, "v1", "v2")
        assert result == "tags: [v2, other]"

    def test_replace_last_tag(self):
        """_replace_tag_in_array handles tag at end of array."""
        line = "tags: [other, v1]"
        result = storage._replace_tag_in_array(line, "v1", "v2")
        assert result == "tags: [other, v2]"

    def test_replace_single_tag(self):
        """_replace_tag_in_array handles single-tag array."""
        line = "tags: [v1]"
        result = storage._replace_tag_in_array(line, "v1", "v2")
        assert result == "tags: [v2]"

    def test_replace_middle_tag(self):
        """_replace_tag_in_array handles tag in middle of array."""
        line = "tags: [a, v1, b]"
        result = storage._replace_tag_in_array(line, "v1", "v2")
        assert result == "tags: [a, v2, b]"

    def test_replace_tag_with_underscore(self):
        """_replace_tag_in_array handles tags with underscores."""
        line = "tags: [my_tag]"
        result = storage._replace_tag_in_array(line, "my_tag", "new_tag")
        assert result == "tags: [new_tag]"

    def test_replace_tag_with_dash(self):
        """_replace_tag_in_array handles tags with dashes."""
        line = "tags: [my-tag]"
        result = storage._replace_tag_in_array(line, "my-tag", "new-tag")
        assert result == "tags: [new-tag]"


# ---------------------------------------------------------------------------
# _replace_frontmatter_tag (direct unit tests)
# ---------------------------------------------------------------------------

class TestReplaceFrontmatterTag:
    """Unit tests for _replace_frontmatter_tag helper."""

    def test_replace_frontmatter_tag(self):
        """_replace_frontmatter_tag replaces tag in frontmatter tags array."""
        content = "---\ntags: [v1, important]\n---\n# Note\nContent #v1 here.\n"
        result = storage._replace_frontmatter_tag(content, "v1", "v2")
        assert "tags: [v2, important]" in result
        assert "tags: [v1" not in result

    def test_replace_no_frontmatter(self):
        """_replace_frontmatter_tag returns content unchanged when no frontmatter."""
        content = "# Note\nContent #v1 here.\n"
        result = storage._replace_frontmatter_tag(content, "v1", "v2")
        assert result == content

    def test_replace_no_tags_array(self):
        """_replace_frontmatter_tag returns content when no tags array."""
        content = "---\ntitle: My Note\n---\n# Note\nContent #v1 here.\n"
        result = storage._replace_frontmatter_tag(content, "v1", "v2")
        assert result == content
