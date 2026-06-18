"""mdnotes CLI - Click-based command interface."""

from typing import Optional

import click

from mdnotes import __version__
from mdnotes import render as render_mod
from mdnotes import storage


class MdnotesError(click.ClickException):
    """Base exception for mdnotes CLI errors with exit codes."""

    def __init__(self, message: str, exit_code: int):
        super().__init__(message)
        self.exit_code = exit_code


class ParamError(MdnotesError):
    """Exit code 2: invalid arguments."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=2)


class NotFoundError(MdnotesError):
    """Exit code 3: resource not found."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=3)


class SystemError(MdnotesError):
    """Exit code 1: system-level errors."""

    def __init__(self, message: str):
        super().__init__(message, exit_code=1)


@click.group()
@click.version_option(version=__version__)
def cli():
    """mdnotes - A simple CLI notes app with Markdown support."""
    pass


@cli.command()
@click.argument("title")
@click.argument("content", default="", required=False)
def add(title: str, content: str):
    """Create a new note with TITLE and optional CONTENT."""
    title = title.strip()
    if len(title) == 0:
        click.echo("Error: title cannot be empty", err=True)
        raise SystemExit(2)
    if len(title) > 200:
        click.echo("Error: title exceeds 200 characters", err=True)
        raise SystemExit(2)

    try:
        note_id = storage.add_note(title, content)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(2)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"Created note {note_id}", err=True)
    raise SystemExit(0)


@cli.command()
@click.option("--search", "search", default=None, help="Search keyword in title (LIKE)")
@click.option(
    "--sort",
    type=click.Choice(["created_at", "updated_at"], case_sensitive=False),
    default="created_at",
    help="Sort field",
)
@click.option(
    "--order",
    type=click.Choice(["asc", "desc"], case_sensitive=False),
    default="desc",
    help="Sort order",
)
def list(search: Optional[str], sort: str, order: str):
    """List all notes, newest first by default."""
    try:
        notes = storage.list_notes(search=search, sort=sort, order=order)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    if not notes:
        click.echo("No notes yet.")
        raise SystemExit(0)

    for note in notes:
        click.echo(f"[{note['id']}] {note['title']} ({note['created_at']})")

    raise SystemExit(0)


@cli.command()
@click.argument("id")
def show(id: str):
    """Display a note with the given ID."""
    try:
        note_id = int(id)
    except ValueError:
        click.echo("Error: id must be an integer", err=True)
        raise SystemExit(2)

    try:
        note = storage.get_note(note_id)
    except ValueError:
        click.echo("Error: id must be an integer", err=True)
        raise SystemExit(2)
    except storage.NoteNotFoundError:
        click.echo("Note not found", err=True)
        raise SystemExit(3)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    rendered = render_mod.render_md(note["content"] or "")
    click.echo(f"Title: {note['title']}")
    click.echo(f"Created: {note['created_at']}")
    click.echo("----")
    # Output raw HTML for now (MVP - v1.0 will add --format plain)
    click.echo(rendered)
    raise SystemExit(0)


@cli.command()
@click.argument("id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def delete(id: str, force: bool):
    """Delete a note by ID."""
    try:
        note_id = int(id)
    except ValueError:
        click.echo("Error: id must be an integer", err=True)
        raise SystemExit(2)

    # Check existence first for idempotent behavior
    try:
        storage.get_note(note_id)
    except storage.NoteNotFoundError:
        click.echo("Note not found", err=True)
        raise SystemExit(3)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    if not force:
        click.echo(f"Delete note {note_id}? [y/N] ", err=True)
        try:
            response = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = "n"
        if response not in ("y", "yes"):
            raise SystemExit(0)

    try:
        storage.delete_note(note_id)
    except storage.NoteNotFoundError:
        click.echo("Note not found", err=True)
        raise SystemExit(3)
    except storage.DatabaseError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"Deleted note {note_id}", err=True)
    raise SystemExit(0)


if __name__ == "__main__":
    cli()
