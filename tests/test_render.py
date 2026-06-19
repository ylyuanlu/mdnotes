"""Tests for mdnotes.render module."""

from mdnotes.render import render_md


class TestRenderMd:
    """AC-14/AC-15: Markdown rendering tests."""

    def test_render_empty_string(self):
        """Empty content renders to empty string."""
        result = render_md("")
        assert result == ""

    def test_render_none(self):
        """None content is treated as empty string."""
        result = render_md(None)
        assert result == ""

    def test_render_heading(self):
        """Headings render correctly."""
        result = render_md("# Hello World")
        assert "<h1>" in result or "<h1 " in result

    def test_render_bullet_list(self):
        """Bullet lists render correctly."""
        result = render_md("- item 1\n- item 2")
        assert "<ul>" in result or "<li>" in result

    def test_render_code_block(self):
        """Code blocks render correctly."""
        result = render_md("```python\nprint('hi')\n```")
        assert "<code>" in result or "<pre>" in result

    def test_render_inline_code(self):
        """Inline code renders correctly."""
        result = render_md("`code`")
        assert "<code>" in result

    def test_render_link(self):
        """Links render correctly."""
        result = render_md("[mdnotes](https://example.com)")
        assert "<a href=" in result

    def test_render_strong_emphasis(self):
        """Bold/italic special chars do not break rendering (AC-15)."""
        result = render_md("**bold** and *italic* and _underscore_")
        assert "<strong>" in result or "<em>" in result

    def test_render_paragraph(self):
        """Paragraphs render correctly."""
        result = render_md("This is a paragraph.\n\nWith a blank line.")
        assert "<p>" in result

    def test_render_horizontal_rule(self):
        """Horizontal rules render correctly."""
        result = render_md("---\n\ntext")
        assert "<hr" in result


class TestRenderSecurity:
    """AC-15: XSS protection - raw HTML should be escaped/disallowed."""

    def test_raw_html_script_tag_not_rendered(self):
        """Raw HTML script tags are not rendered (XSS protection)."""
        result = render_md("<script>alert('xss')</script>")
        # mistune escapes raw HTML by default
        assert "<script>" not in result

    def test_html_entities_escaped(self):
        """HTML entities are escaped."""
        result = render_md("<img src=x onerror=alert(1)>")
        assert "<img" not in result or "&lt;" in result
