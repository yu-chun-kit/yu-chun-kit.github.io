from __future__ import annotations

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
from .normalize import normalize_openwebui_chat
from .render import write_hexo_post


app = typer.Typer(help="Publish OpenWebUI conversations as Hexo dialog posts.")
console = Console()


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
        content = " ".join(node.content.strip().split())
        if content:
            role = "User" if node.role == "user" else "AI"
            lines.append(f"  {role}: {content[:120]}{'...' if len(content) > 120 else ''}")
            shown += 1
        current_id = node.children_ids[0] if node.children_ids else ""

    return lines


def fetch_conversation(chat_id: str, client: OpenWebUIClient | None = None) -> Conversation:
    client = client or build_client()
    conversation = normalize_openwebui_chat(client.fetch_chat(chat_id))
    if not conversation.source_chat_id:
        conversation.source_chat_id = chat_id
    return conversation


def publish_conversation(
    chat_id: str,
    override_date: str | None = None,
    output: Path | None = None,
    client: OpenWebUIClient | None = None,
    settings: Settings | None = None,
) -> Path:
    settings = settings or load_settings()
    conversation = fetch_conversation(chat_id, client=client or build_client(settings))
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
) -> None:
    """List recent OpenWebUI conversations."""
    chats = build_client().list_chats(limit=limit, page=page)
    if not chats:
        console.print("[yellow]No conversations returned by OpenWebUI.[/yellow]")
        raise typer.Exit(0)
    _display_chat_table(chats)


@app.command("show")
def show_command(chat_id: str = typer.Argument(..., help="OpenWebUI chat ID.")) -> None:
    """Show metadata and a short preview for one conversation."""
    conversation = fetch_conversation(chat_id)
    console.print("\n".join(summarize_conversation(conversation)))


@app.command("publish")
def publish_command(
    chat_id: str = typer.Argument(..., help="OpenWebUI chat ID."),
    date: Optional[str] = typer.Option(None, "--date", help="Override post date, e.g. 2026-01-15."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output Markdown file."),
) -> None:
    """Generate a Hexo post for one OpenWebUI conversation."""
    path = publish_conversation(chat_id, override_date=date, output=output)
    console.print(f"[green]Generated:[/green] {path}")


@app.command("import-gemini")
def import_gemini_command(
    url: str = typer.Argument(..., help="Public Gemini share URL."),
    date: Optional[str] = typer.Option(None, "--date", help="Override post date, e.g. 2026-01-15."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output Markdown file."),
    download_assets: bool = typer.Option(True, "--download-assets/--no-download-assets", help="Download Gemini images into source/images."),
    timeout_ms: int = typer.Option(60_000, "--timeout-ms", min=1_000, help="Browser load timeout."),
) -> None:
    """Generate a Hexo post from a public Gemini share URL."""
    settings = load_settings()
    conversation = fetch_gemini_share_conversation(url, timeout_ms=timeout_ms)
    downloaded = download_conversation_images(conversation, settings.repo_root / "source") if download_assets else []
    path = write_hexo_post(conversation, posts_dir=settings.posts_dir, override_date=date, output=output)
    console.print(f"[green]Generated:[/green] {path}")
    if downloaded:
        console.print(f"[green]Downloaded images:[/green] {len(downloaded)}")


def interactive_workflow(limit: int = 15, page: int = 1) -> Path | None:
    client = build_client()
    chats = client.list_chats(limit=limit, page=page)
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
    conversation = fetch_conversation(selected.id, client=client)
    console.print()
    console.print("\n".join(summarize_conversation(conversation)))
    console.print()

    date = Prompt.ask("Override date (YYYY-MM-DD, empty keeps conversation date)", default="")
    output = Prompt.ask("Output file (empty uses default source/_posts path)", default="")

    if not Confirm.ask("Generate this post?", default=True):
        console.print("[yellow]Canceled.[/yellow]")
        return None

    settings = load_settings()
    path = write_hexo_post(
        conversation,
        posts_dir=settings.posts_dir,
        override_date=date or None,
        output=Path(output) if output else None,
    )
    console.print(f"[green]Generated:[/green] {path}")
    return path


@app.command("interactive")
def interactive_command(
    limit: int = typer.Option(15, "--limit", "-n", min=1, help="Number of chats to list."),
    page: int = typer.Option(1, "--page", "-p", min=1, help="OpenWebUI page number."),
) -> None:
    """Pick, preview, and generate a conversation post interactively."""
    interactive_workflow(limit=limit, page=page)
