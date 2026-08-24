"""
Channel Management Tool.
Add, remove, list, and configure YouTube channels.

Usage:
    python manage_channels.py list
    python manage_channels.py add --name "Beer Biceps" --handle "@beerbiceps" --id "UCk..."
    python manage_channels.py add --name "Channel" --handle "@handle" --prefix "CH" --all-time
    python manage_channels.py disable --name "Channel Name"
    python manage_channels.py enable --name "Channel Name"
    python manage_channels.py remove --name "Channel Name"
"""

import argparse
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

console = Console()
CHANNELS_FILE = Path("config/channels.yaml")


def load_channels() -> dict:
    with open(CHANNELS_FILE, "r") as f:
        return yaml.safe_load(f)


def save_channels(data: dict):
    with open(CHANNELS_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def list_channels():
    """Display all configured channels."""
    data = load_channels()
    channels = data.get("channels", [])

    table = Table(title="YouTube Channels")
    table.add_column("#", justify="center", style="dim")
    table.add_column("Name", style="cyan")
    table.add_column("Handle", style="blue")
    table.add_column("Prefix", style="magenta")
    table.add_column("ID", style="dim")
    table.add_column("Enabled", justify="center")
    table.add_column("Max", justify="center")
    table.add_column("Since", style="yellow")
    table.add_column("Min Dur", justify="center")

    for i, ch in enumerate(channels, 1):
        enabled = "✓" if ch.get("enabled", True) else "✗"
        enabled_style = "green" if ch.get("enabled", True) else "red"
        ch_id = ch.get("channel_id", "")
        id_display = ch_id[:15] + "..." if ch_id else "[red]NOT SET[/red]"
        max_v = str(ch.get("max_videos", 0)) if ch.get("max_videos", 0) > 0 else "ALL"
        since = ch.get("since_date", "") or "All time"
        min_dur = str(ch.get("min_duration_minutes", 0)) + "m" if ch.get("min_duration_minutes") else "—"

        table.add_row(
            str(i),
            ch["name"],
            ch.get("channel_handle", ""),
            ch.get("fo_prefix", "EP"),
            id_display,
            f"[{enabled_style}]{enabled}[/{enabled_style}]",
            max_v,
            since,
            min_dur,
        )

    console.print(table)
    console.print(f"\nTotal: {len(channels)} channels")

    # Check for missing IDs
    missing = [ch["name"] for ch in channels if not ch.get("channel_id")]
    if missing:
        console.print(f"\n[yellow]⚠ {len(missing)} channels need channel_id resolved:[/yellow]")
        for name in missing:
            console.print(f"  - {name}")
        console.print("\n  Run: [bold]python resolve_channels.py[/bold]")


def add_channel(
    name: str, handle: str, channel_id: str = "",
    prefix: str = "EP", max_videos: int = 0,
    since_date: str = "", min_duration: int = 15,
):
    """Add a new channel."""
    data = load_channels()

    # Check for duplicate handles
    existing_handles = {ch.get("channel_handle", "").lower() for ch in data.get("channels", [])}
    if handle.lower() in existing_handles:
        console.print(f"[red]Channel with handle '{handle}' already exists![/red]")
        return

    new_channel = {
        "name": name,
        "channel_handle": handle,
        "channel_id": channel_id,
        "enabled": True,
        "fo_prefix": prefix,
        "max_videos": max_videos,
        "since_date": since_date,
        "filter_shorts": True,
        "min_duration_minutes": min_duration,
    }

    data.setdefault("channels", []).append(new_channel)
    save_channels(data)
    console.print(f"[green]✓ Added: {name} ({handle})[/green]")
    if not channel_id:
        console.print(f"  [yellow]Run 'python resolve_channels.py' to get channel_id[/yellow]")


def toggle_channel(name: str, enable: bool):
    """Enable or disable a channel."""
    data = load_channels()

    for ch in data.get("channels", []):
        if ch["name"].lower() == name.lower():
            ch["enabled"] = enable
            save_channels(data)
            state = "enabled" if enable else "disabled"
            console.print(f"[green]✓ '{name}' {state}[/green]")
            return

    console.print(f"[red]Channel '{name}' not found[/red]")


def remove_channel(name: str):
    """Remove a channel."""
    data = load_channels()
    original_count = len(data.get("channels", []))

    data["channels"] = [
        ch for ch in data.get("channels", [])
        if ch["name"].lower() != name.lower()
    ]

    if len(data["channels"]) < original_count:
        save_channels(data)
        console.print(f"[green]✓ Removed: {name}[/green]")
    else:
        console.print(f"[red]Channel '{name}' not found[/red]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Channel Manager")
    subparsers = parser.add_subparsers(dest="command")

    # List
    subparsers.add_parser("list", help="List all channels")

    # Add
    add_parser = subparsers.add_parser("add", help="Add a channel")
    add_parser.add_argument("--name", required=True, help="Channel display name")
    add_parser.add_argument("--handle", required=True, help="@handle")
    add_parser.add_argument("--id", default="", help="Channel ID (UC...) - optional, can resolve later")
    add_parser.add_argument("--prefix", default="EP", help="FO_ID prefix (e.g., NK, LP)")
    add_parser.add_argument("--max-videos", type=int, default=0, help="Max videos (0 = ALL)")
    add_parser.add_argument("--since", default="", help="Only videos after YYYY-MM-DD")
    add_parser.add_argument("--min-duration", type=int, default=15, help="Min duration in minutes")

    # Enable / Disable / Remove
    enable_parser = subparsers.add_parser("enable", help="Enable a channel")
    enable_parser.add_argument("--name", required=True)

    disable_parser = subparsers.add_parser("disable", help="Disable a channel")
    disable_parser.add_argument("--name", required=True)

    remove_parser = subparsers.add_parser("remove", help="Remove a channel")
    remove_parser.add_argument("--name", required=True)

    args = parser.parse_args()

    if args.command == "list":
        list_channels()
    elif args.command == "add":
        add_channel(
            args.name, args.handle, args.id,
            args.prefix, args.max_videos, args.since, args.min_duration,
        )
    elif args.command == "enable":
        toggle_channel(args.name, True)
    elif args.command == "disable":
        toggle_channel(args.name, False)
    elif args.command == "remove":
        remove_channel(args.name)
    else:
        parser.print_help()
