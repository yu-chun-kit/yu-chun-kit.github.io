from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .assets import download_conversation_images
from .client import OpenWebUIClient
from .config import Settings, load_settings
from .gemini import fetch_gemini_share_conversation
from .models import ChatSummary, Conversation
from .normalize import normalize_openwebui_chat, parse_timestamp
from .owui_local import LocalSourceConfig, LocalSourceError
from .owui_local import build_local_source as build_owui_local_source
from .owui_local import normalize_local_chat
from .render import write_hexo_post


app = typer.Typer(help="Publish OpenWebUI / Gemini conversations as Hexo dialog posts.")
console = Console()

_TAG_RE = re.compile(r"<[^>]+>")

#: How to reach an OpenWebUI chat: its HTTP API, the NAS database, a db file.
SOURCE_HELP = "OpenWebUI source: auto (API, then local db), api, ssh, sqlite."


def build_client(settings: Settings | None = None) -> OpenWebUIClient:
    settings = settings or load_settings()
    return OpenWebUIClient(settings.api_base, settings.api_token)


def _display_chat_table(chats: list[ChatSummary]) -> None:
    table = Table(title="OpenWebUI conversations")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Chat ID", overflow="fold")
    table.add_column("Updated")

    for index, chat in enumerate(chats, 1):
        updated = chat.updated_at.strftime("%Y-%m-%d") if chat.updated_at else "-"
        table.add_row(str(index), chat.title[:60], chat.id, updated)

    console.print(table)


def summarize_conversation(conversation: Conversation, preview_count: int = 4) -> list[str]:
    lines = [
        f"Title: {conversation.title}",
        f"Source: {conversation.source_provider}",
        f"Chat ID: {conversation.source_chat_id}",
        f"Date: {conversation.display_date.strftime('%Y-%m-%d %H:%M:%S') if conversation.display_date else '-'}",
        f"Models: {', '.join(conversation.models) if conversation.models else 'unknown'}",
        f"Messages: {conversation.message_count}",
        f"Branches: {conversation.branch_count}",
        "",
        "Preview:",
    ]

    current_id = conversation.root_id
    seen: set[str] = set()
    shown = 0
    while current_id and current_id not in seen and shown < preview_count:
        seen.add(current_id)
        node = conversation.messages.get(current_id)
        if node is None:
            break
        content = " ".join(_TAG_RE.sub(" ", node.content).split())
        if content:
            role = "User" if node.role == "user" else "AI"
            lines.append(f"  {role}: {content[:120]}{'...' if len(content) > 120 else ''}")
            shown += 1
        current_id = node.children_ids[0] if node.children_ids else ""

    return lines


def local_source_config(settings: Settings, kind: str = "ssh") -> LocalSourceConfig:
    return LocalSourceConfig(
        kind=kind,
        host=settings.owui_ssh_host,
        container=settings.owui_ssh_container,
        db_path=settings.owui_db_path,
        local_db_path=settings.owui_local_db,
        uploads_root=settings.owui_uploads_root,
    )


def fetch_conversation(
    chat_id: str,
    client: OpenWebUIClient | None = None,
    source: str = "api",
    settings: Settings | None = None,
) -> Conversation:
    """Read one OpenWebUI chat from the API, the NAS database, or a db file."""
    if source == "auto":
        try:
            return fetch_conversation(chat_id, client=client, source="api", settings=settings)
        except Exception as exc:  # noqa: BLE001 - the API is optional, the db is the fallback
            console.print(f"[yellow]OpenWebUI API unavailable ({exc}); reading the local database.[/yellow]")
            return fetch_conversation(chat_id, source="ssh", settings=settings)

    if source == "api":
        settings = settings or load_settings()
        client = client or build_client(settings)
        conversation = normalize_openwebui_chat(client.fetch_chat(chat_id))
        if not conversation.source_chat_id:
            conversation.source_chat_id = chat_id
        return conversation

    if source not in ("ssh", "sqlite"):
        raise ValueError(f"unknown source: {source}")

    settings = settings or load_settings()
    reader = build_owui_local_source(local_source_config(settings, "sqlite" if source == "sqlite" else "ssh"))
    return normalize_local_chat(reader.fetch_chat(chat_id))


def openwebui_asset_headers(settings: Settings) -> dict[str, str]:
    """Bearer header so OpenWebUI's protected ``/api/v1/files/...`` images work."""
    return {"Authorization": f"Bearer {settings.api_token}"} if settings.api_token else {}


def download_openwebui_assets(
    conversation: Conversation,
    settings: Settings,
    force: bool = False,
) -> None:
    """Fetch OpenWebUI images (auth header for the API, data URLs for local)."""
    assets = download_conversation_images(
        conversation,
        settings.repo_root / "source",
        base_url=settings.api_base,
        headers=openwebui_asset_headers(settings),
        force=force,
    )
    for failed_url, message in assets.failed:
        console.print(f"[yellow]Skipped image[/yellow] {failed_url}: {message}")
    if assets.total:
        console.print(
            f"[green]Images:[/green] {len(assets.downloaded)} downloaded, {len(assets.reused)} reused"
        )


def publish_conversation(
    chat_id: str,
    override_date: str | None = None,
    output: Path | None = None,
    client: OpenWebUIClient | None = None,
    settings: Settings | None = None,
    download_assets: bool = True,
    force_assets: bool = False,
    source: str = "auto",
) -> Path:
    settings = settings or load_settings()
    conversation = fetch_conversation(
        chat_id,
        client=client,
        source=source,
        settings=settings,
    )
    return finish_conversation(
        conversation,
        settings=settings,
        override_date=override_date,
        output=output,
        download_assets=download_assets,
        force_assets=force_assets,
    )


def finish_conversation(
    conversation: Conversation,
    settings: Settings,
    override_date: str | None = None,
    output: Path | None = None,
    download_assets: bool = True,
    force_assets: bool = False,
) -> Path:
    """Store images, then write the Hexo post for an already-loaded chat."""
    if download_assets:
        download_openwebui_assets(conversation, settings, force=force_assets)

    return write_hexo_post(
        conversation,
        posts_dir=settings.posts_dir,
        override_date=override_date,
        output=output,
    )


@app.command("list")
def list_command(
    limit: int = typer.Option(10, "--limit", "-n", min=1, help="Number of chats to show."),
    page: int = typer.Option(1, "--page", "-p", min=1, help="OpenWebUI page number."),
    source: str = typer.Option("api", "--source", help=SOURCE_HELP),
) -> None:
    """List recent OpenWebUI conversations."""
    if source == "api":
        chats = build_client().list_chats(limit=limit, page=page)
    else:
        settings = load_settings()
        reader = build_owui_local_source(
            local_source_config(settings, "sqlite" if source == "sqlite" else "ssh")
        )
        rows = reader.list_chats(limit=limit)
        chats = [
            ChatSummary(
                id=str(row.get("id") or ""),
                title=str(row.get("title") or "Untitled"),
                created_at=parse_timestamp(row.get("created_at")),
                updated_at=parse_timestamp(row.get("updated_at")),
            )
            for row in rows
            if row.get("id")
        ]

    if not chats:
        console.print("[yellow]No conversations returned by OpenWebUI.[/yellow]")
        raise typer.Exit(0)
    _display_chat_table(chats)


@app.command("show")
def show_command(
    chat_id: str = typer.Argument(..., help="OpenWebUI chat ID."),
    source: str = typer.Option("auto", "--source", help=SOURCE_HELP),
) -> None:
    """Show metadata and a short preview for one conversation."""
    conversation = fetch_conversation(chat_id, source=source)
    console.print("\n".join(summarize_conversation(conversation)))


@app.command("publish")
def publish_command(
    chat_id: str = typer.Argument(..., help="OpenWebUI chat ID."),
    date: Optional[str] = typer.Option(None, "--date", help="Override post date, e.g. 2026-01-15."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output Markdown file."),
    source: str = typer.Option("auto", "--source", help=SOURCE_HELP),
    download_assets: bool = typer.Option(True, "--download-assets/--no-download-assets", help="Download OpenWebUI images into source/images."),
    force_assets: bool = typer.Option(False, "--force-assets", help="Re-download images even when they are already on disk."),
) -> None:
    """Generate a Hexo post for one OpenWebUI conversation."""
    try:
        path = publish_conversation(
            chat_id,
            override_date=date,
            output=output,
            download_assets=download_assets,
            force_assets=force_assets,
            source=source,
        )
    except (LocalSourceError, ValueError, RuntimeError) as exc:
        console.print(f"[red]Could not read OpenWebUI chat:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Generated:[/green] {path}")


@app.command("import-gemini")
def import_gemini_command(
    url: str = typer.Argument(..., help="Public Gemini share URL."),
    date: Optional[str] = typer.Option(None, "--date", help="Override post date, e.g. 2026-01-15."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output Markdown file."),
    download_assets: bool = typer.Option(True, "--download-assets/--no-download-assets", help="Download Gemini images into source/images."),
    force_assets: bool = typer.Option(False, "--force-assets", help="Re-download images even when they are already on disk."),
    timeout_ms: int = typer.Option(60_000, "--timeout-ms", min=1_000, help="Browser load timeout."),
) -> None:
    """Generate a Hexo post from a public Gemini share URL."""
    settings = load_settings()
    try:
        conversation = fetch_gemini_share_conversation(url, timeout_ms=timeout_ms)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Could not import Gemini share:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("\n".join(summarize_conversation(conversation)))
    console.print()

    if download_assets:
        assets = download_conversation_images(
            conversation,
            settings.repo_root / "source",
            force=force_assets,
        )
        for failed_url, message in assets.failed:
            console.print(f"[yellow]Skipped image[/yellow] {failed_url}: {message}")
    else:
        assets = None

    path = write_hexo_post(conversation, posts_dir=settings.posts_dir, override_date=date, output=output)
    console.print(f"[green]Generated:[/green] {path}")
    if assets is not None and assets.total:
        console.print(
            f"[green]Images:[/green] {len(assets.downloaded)} downloaded, {len(assets.reused)} reused"
        )


def interactive_workflow(limit: int = 15, page: int = 1, source: str = "api") -> Path | None:
    settings = load_settings()
    client = None

    if source == "api":
        client = build_client(settings)
        chats = client.list_chats(limit=limit, page=page)
    else:
        reader = build_owui_local_source(
            local_source_config(settings, "sqlite" if source == "sqlite" else "ssh")
        )
        chats = [
            ChatSummary(
                id=str(row.get("id") or ""),
                title=str(row.get("title") or "Untitled"),
                created_at=parse_timestamp(row.get("created_at")),
                updated_at=parse_timestamp(row.get("updated_at")),
            )
            for row in reader.list_chats(limit=limit)
            if row.get("id")
        ]

    if not chats:
        console.print("[yellow]No conversations returned by OpenWebUI.[/yellow]")
        return None

    _display_chat_table(chats)
    selected_text = Prompt.ask(f"Choose conversation [1-{len(chats)}]")
    try:
        selected_index = int(selected_text) - 1
    except ValueError:
        console.print("[red]Invalid selection.[/red]")
        return None

    if selected_index < 0 or selected_index >= len(chats):
        console.print("[red]Selection out of range.[/red]")
        return None

    selected = chats[selected_index]
    conversation = fetch_conversation(selected.id, client=client, source=source, settings=settings)
    console.print()
    console.print("\n".join(summarize_conversation(conversation)))
    console.print()

    date = Prompt.ask("Override date (YYYY-MM-DD, empty keeps conversation date)", default="")
    output = Prompt.ask("Output file (empty uses default source/_posts path)", default="")

    if not Confirm.ask("Generate this post?", default=True):
        console.print("[yellow]Canceled.[/yellow]")
        return None

    path = finish_conversation(
        conversation,
        settings=settings,
        override_date=date or None,
        output=Path(output) if output else None,
    )
    console.print(f"[green]Generated:[/green] {path}")
    return path


@app.command("interactive")
def interactive_command(
    limit: int = typer.Option(15, "--limit", "-n", min=1, help="Number of chats to list."),
    page: int = typer.Option(1, "--page", "-p", min=1, help="OpenWebUI page number."),
    source: str = typer.Option("api", "--source", help=SOURCE_HELP),
) -> None:
    """Pick, preview, and generate a conversation post interactively."""
    interactive_workflow(limit=limit, page=page, source=source)


@app.command("gui")
def gui_command(
    port: int = typer.Option(8765, "--port", "-p", min=1, max=65535, help="Local port for the studio."),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Open the studio in the default browser."
    ),
) -> None:
    """Start the local studio: a checkbox list of chats that writes posts."""
    from .studio import serve

    serve(port=port, open_browser=open_browser)


@app.command("gemini-login")
def gemini_login_command() -> None:
    """Open the managed Chrome profile so you can sign in to Gemini once."""
    from . import gemini_web

    settings = load_settings()
    profile = (
        Path(settings.gemini_profile) if settings.gemini_profile else gemini_web.default_profile_dir()
    )
    gemini_web.open_for_login(profile, settings.gemini_port)
    console.print(f"[green]Opened Chrome[/green] with profile {profile}")
    console.print("Sign in to Google, then close that window; chatblog reuses the profile.")


@app.command("studio")
def studio_alias(
    port: int = typer.Option(8765, "--port", "-p", min=1, max=65535),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Alias for ``chatblog gui``."""
    gui_command(port=port, open_browser=open_browser)


if __name__ == "__main__":  # pragma: no cover - module entry point
    app()
