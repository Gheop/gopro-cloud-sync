import asyncio
import sys
from pathlib import Path

import click
import httpx
from rich.console import Console
from rich.table import Table

from . import auth, config
from .api import list_all_media
from .db import SyncDB
from .downloader import download_all

console = Console()


def _get_authenticated_token():
    """Load token from config, fail with helpful message if missing."""
    token = config.get_token()
    if not token:
        console.print("[red]Not logged in.[/red] Run [bold]gopro-sync login[/bold] or [bold]gopro-sync login-token <TOKEN>[/bold]")
        sys.exit(1)
    return token


async def _ensure_valid_token(token):
    """Refresh token if expired, save updated token, return valid token."""
    if not auth.is_expired(token):
        return token

    if not token.refresh_token:
        console.print("[red]Token expired.[/red] Please login again.")
        sys.exit(1)

    console.print("[yellow]Token expired, refreshing...[/yellow]")
    async with httpx.AsyncClient() as client:
        try:
            token = await auth.refresh(token, client)
            config.set_token(token)
            console.print("[green]Token refreshed.[/green]")
            return token
        except auth.AuthError as e:
            console.print(f"[red]Refresh failed:[/red] {e}")
            sys.exit(1)


@click.group()
@click.version_option(package_name="gopro-cloud-sync")
def main():
    """Sync GoPro cloud media to local storage."""
    pass


@main.command()
@click.option("--email", prompt="Email", help="GoPro account email")
@click.option("--password", prompt="Password", hide_input=True, help="GoPro account password")
def login(email, password):
    """Authenticate with email and password."""

    async def _login():
        async with httpx.AsyncClient() as client:
            try:
                token = await auth.login_password(email, password, client)
                config.set_token(token)
                console.print("[green]Logged in successfully![/green]")
            except auth.TwoFactorRequired as e:
                console.print(f"[yellow]{e}[/yellow]")
                sys.exit(1)
            except auth.AuthError as e:
                console.print(f"[red]Login failed:[/red] {e}")
                sys.exit(1)

    asyncio.run(_login())


@main.command("login-token")
@click.argument("token")
def login_token(token):
    """Save a manually obtained access token (for 2FA accounts).

    Get your token from: plus.gopro.com → DevTools → Application → Cookies → gp_access_token
    """
    token_data = auth.token_from_manual(token)
    config.set_token(token_data)
    console.print("[green]Token saved![/green]")
    if auth.is_expired(token_data):
        console.print("[yellow]Warning: this token appears to be expired.[/yellow]")


@main.command()
def logout():
    """Remove saved credentials."""
    config.clear_token()
    console.print("Logged out.")


@main.command()
@click.option("-o", "--output", default="~/GoPro", show_default=True, help="Download directory")
@click.option("-c", "--concurrency", default=5, show_default=True, help="Parallel downloads")
@click.option("--dry-run", is_flag=True, help="List what would be downloaded")
def sync(output, concurrency, dry_run):
    """Sync all GoPro cloud media to local storage."""
    asyncio.run(_sync(output, concurrency, dry_run))


async def _sync(output: str, concurrency: int, dry_run: bool):
    token = _get_authenticated_token()
    token = await _ensure_valid_token(token)

    output_dir = Path(output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    db = SyncDB()

    try:
        async with httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Origin": "https://gopro.com",
                "Referer": "https://gopro.com/",
            },
            timeout=httpx.Timeout(30, read=300),
        ) as client:
            # Phase 1: List all media from cloud
            console.print("[bold]Fetching media list from GoPro cloud...[/bold]")
            count = 0
            async for item in list_all_media(client):
                db.upsert_media(item)
                count += 1
                if count % 100 == 0:
                    console.print(f"  Found {count} items...")

            console.print(f"  Total in cloud: [bold]{count}[/bold] items")

            # Phase 2: Check what needs downloading
            pending = db.get_pending()
            stats = db.get_stats()

            if not pending:
                console.print(f"[green]Already up to date![/green] ({stats['done']} items synced)")
                return

            total_size = sum(i.file_size for i in pending)
            size_str = _format_size(total_size) if total_size else "unknown size"
            console.print(
                f"\n[bold]{len(pending)}[/bold] new items to download ({size_str})"
                f" — {stats['done']} already synced"
            )

            if dry_run:
                console.print("\n[yellow]Dry run — nothing downloaded.[/yellow]")
                for item in pending[:20]:
                    console.print(f"  {item.media_type:10s} {item.capture_time:%Y-%m-%d %H:%M}  {item.filename}")
                if len(pending) > 20:
                    console.print(f"  ... and {len(pending) - 20} more")
                return

            # Phase 3: Download
            console.print(f"\nDownloading to [bold]{output_dir}[/bold] ({concurrency} parallel)...\n")
            success, errors = await download_all(pending, output_dir, client, db, concurrency)

        console.print(f"\n[green]Done![/green] {success} downloaded, {errors} errors")
        if errors:
            console.print("Run [bold]gopro-sync sync[/bold] again to retry failed items, or [bold]gopro-sync status[/bold] to inspect.")
    finally:
        db.close()


@main.command()
def status():
    """Show sync statistics."""
    db = SyncDB()
    try:
        stats = db.get_stats()
    finally:
        db.close()

    table = Table(title="GoPro Cloud Sync Status")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Total", str(stats["total"]))
    table.add_row("Downloaded", str(stats["done"]), style="green")
    table.add_row("Pending", str(stats["pending"]), style="yellow")
    table.add_row("Errors", str(stats["error"]), style="red" if stats["error"] else "dim")
    table.add_row("In progress", str(stats["downloading"]), style="blue")

    console.print(table)


@main.command()
@click.option("--force", is_flag=True, help="Skip confirmation")
def reset(force):
    """Reset sync state — mark all items for re-download."""
    if not force:
        click.confirm("This will re-download all media. Continue?", abort=True)

    db = SyncDB()
    try:
        count = db.reset_all()
    finally:
        db.close()

    console.print(f"Reset {count} items to pending.")


def _format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
