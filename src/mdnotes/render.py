"""Markdown rendering using mistune."""

import mistune


def render_md(content: str) -> str:
    """
    Render Markdown content to HTML string.

    This function uses mistune (with default GFM rules) to safely render
    Markdown content. Raw HTML is disabled by default, providing XSS protection.

    Args:
        content: Raw Markdown text (may be empty string)

    Returns:
        Rendered HTML string
    """
    if content is None:
        content = ""
    markdown = mistune.create_markdown()
    return markdown(content)
