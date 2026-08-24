"""
Channel ID Resolver.
Automatically resolves YouTube channel IDs from @handles.

Usage:
    python resolve_channels.py

This reads config/channels.yaml, finds any channels with empty channel_id,
resolves them using the YouTube API, and updates the file.
"""

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from googleapiclient.discovery import build
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()

CHANNELS_FILE = Path("config/channels.yaml")


def resolve_channel_id(youtube, handle: str) -> str:
    """Resolve a @handle to a UC... channel ID using YouTube API."""
    # Remove @ if present
    handle_clean = handle.lstrip("@")

    try:
        # Try searching by handle
        request = youtube.search().list(
            part="snippet",
            q=handle_clean,
            type="channel",
            maxResults=5,
        )
        response = request.execute()

        for item in response.get("items", []):
            channel_id = item["snippet"]["channelId"]
            channel_title = item["snippet"]["title"]
            # Verify by fetching channel details
            ch_request = youtube.channels().list(
                part="snippet",
                id=channel_id,
            )
            ch_response = ch_request.execute()
            
            for ch in ch_response.get("items", []):
                custom_url = ch["snippet"].get("customUrl", "")
                if custom_url.lower() == f"@{handle_clean}".lower():
                    return channel_id

        # Fallback: try forHandle parameter (newer API)
        request = youtube.channels().list(
            part="snippet",
            forHandle=handle_clean,
        )
        response = request.execute()
        
        items = response.get("items", [])
        if items:
            return items[0]["id"]

    except Exception as e:
        console.print(f"  [red]Error resolving {handle}: {e}[/red]")

    return ""


def main():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        console.print("[red]YOUTUBE_API_KEY not found in .env[/red]")
        console.print("Set it first: https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    youtube = build("youtube", "v3", developerKey=api_key)

    # Load channels
    with open(CHANNELS_FILE, "r") as f:
        data = yaml.safe_load(f)

    channels = data.get("channels", [])
    updated = False

    console.print("\n[bold]Resolving Channel IDs...[/bold]\n")

    table = Table(title="Channel Resolution")
    table.add_column("Channel", style="cyan")
    table.add_column("Handle", style="blue")
    table.add_column("Channel ID", style="green")
    table.add_column("Status")

    for ch in channels:
        handle = ch.get("channel_handle", "")
        existing_id = ch.get("channel_id", "")

        if existing_id:
            table.add_row(ch["name"], handle, existing_id[:20] + "...", "[green]Already set[/green]")
            continue

        if not handle:
            table.add_row(ch["name"], "—", "—", "[yellow]No handle[/yellow]")
            continue

        console.print(f"  Resolving {handle}...")
        channel_id = resolve_channel_id(youtube, handle)

        if channel_id:
            ch["channel_id"] = channel_id
            updated = True
            table.add_row(ch["name"], handle, channel_id[:20] + "...", "[green]✓ Resolved[/green]")
        else:
            table.add_row(ch["name"], handle, "—", "[red]✗ Failed[/red]")

    console.print(table)

    if updated:
        with open(CHANNELS_FILE, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        console.print(f"\n[green]✓ Updated {CHANNELS_FILE}[/green]")
    else:
        console.print("\n[dim]No changes needed.[/dim]")


if __name__ == "__main__":
    main()
