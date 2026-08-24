"""
Main Pipeline — YouTube Knowledge Extraction.

The exact 13-step pipeline from scale.md:

  1. Check YouTube channel
  2. Find new episodes
  3. Add new rows to Google Sheets
  4. Download metadata
  5. Obtain transcript
  6. Send metadata → Ollama
  7. Categorize episode
  8. Calculate relevance
  9. Identify important episodes
  10. Send selected transcripts → NVIDIA
  11. Deep-analyze them
  12. Update Google Sheets
  13. Mark processing complete

Then when a new episode appears, you only need to run the pipeline again.
"""

import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.table import Table

from src.models import ChannelConfig, VideoMetadata, Episode
from src.youtube import YouTubeCollector
from src.transcript import TranscriptExtractor
from src.ollama_client import OllamaClassifier
from src.nvidia_client import NvidiaAnalyzer
from src.processing_router import ProcessingRouter
from src.sheets import SheetsManager

load_dotenv()
console = Console()


def load_config() -> dict:
    """Load all YAML configuration files."""
    config_dir = Path("config")

    with open(config_dir / "settings.yaml", "r") as f:
        settings = yaml.safe_load(f)

    with open(config_dir / "channels.yaml", "r") as f:
        channels_data = yaml.safe_load(f)

    with open(config_dir / "taxonomy.yaml", "r") as f:
        taxonomy = yaml.safe_load(f)

    return {
        "settings": settings,
        "channels": channels_data,
        "taxonomy": taxonomy,
    }


def get_enabled_channels(channels_data: dict) -> list[ChannelConfig]:
    """Parse enabled channels from config."""
    channels = []
    for ch in channels_data.get("channels", []):
        if not ch.get("enabled", True):
            continue
        if not ch.get("channel_id"):
            logger.warning(
                f"Skipping '{ch['name']}' — no channel_id. "
                f"Run: python resolve_channels.py"
            )
            continue
        channels.append(ChannelConfig(
            name=ch["name"],
            channel_handle=ch.get("channel_handle", ""),
            channel_id=ch["channel_id"],
            enabled=True,
            fo_prefix=ch.get("fo_prefix", "EP"),
            max_videos=ch.get("max_videos", 0),
            since_date=ch.get("since_date", ""),
            filter_shorts=ch.get("filter_shorts", True),
            min_duration_minutes=ch.get("min_duration_minutes", 0),
        ))
    return channels


def generate_fo_id(prefix: str, index: int) -> str:
    """Generate FO_ID like FO514, BB023, AW107."""
    return f"{prefix}{index:03d}"


def run_pipeline(
    channel_names: list[str] = None,
    skip_nvidia: bool = False,
    skip_sheets: bool = False,
    max_videos_override: int = None,
    since_date: str = None,
):
    """
    Run the full 13-step pipeline.
    
    Args:
        channel_names: Specific channel names to process (None = all enabled)
        skip_nvidia: Skip NVIDIA deep analysis entirely
        skip_sheets: Skip Google Sheets push (useful for testing)
        max_videos_override: Override max_videos per channel
        since_date: Only fetch videos after this date (ISO format)
    """
    config = load_config()
    settings = config["settings"]
    taxonomy = config["taxonomy"]

    # Get channels
    all_channels = get_enabled_channels(config["channels"])
    if channel_names:
        channels = [
            ch for ch in all_channels
            if ch.name.lower() in [n.lower() for n in channel_names]
        ]
    else:
        channels = all_channels

    if not channels:
        console.print("[red]No enabled channels found in config/channels.yaml[/red]")
        return

    console.print(f"\n[bold green]{'═'*50}[/bold green]")
    console.print(f"[bold green]  YouTube Knowledge Pipeline[/bold green]")
    console.print(f"[bold green]{'═'*50}[/bold green]")
    console.print(f"  Channels: {len(channels)}")
    console.print(f"  NVIDIA: {'Disabled' if skip_nvidia else 'Enabled (threshold: ' + str(taxonomy.get('nvidia_threshold', 4.0)) + ')'}")
    console.print(f"  Sheets: {'Disabled' if skip_sheets else 'Enabled'}")
    console.print()

    # ─── Initialize Components ────────────────────────────────────────

    try:
        # YouTube collector
        youtube = YouTubeCollector()

        # Transcript extractor
        transcript_extractor = TranscriptExtractor(
            preferred_languages=settings["transcript"]["preferred_languages"],
            fallback_to_auto=settings["transcript"]["fallback_to_auto"],
            chunk_size=settings["transcript"]["chunk_size"],
        )

        # Ollama (always needed)
        ollama = OllamaClassifier(
            model=settings["ollama"]["model"],
            base_url=settings["ollama"]["base_url"],
            temperature=settings["ollama"]["temperature"],
            categories=taxonomy.get("categories", []),
            profile=taxonomy.get("profile", {}),
        )

        # NVIDIA (optional)
        nvidia = None
        if not skip_nvidia:
            try:
                nvidia = NvidiaAnalyzer(
                    model=settings["nvidia"]["model"],
                    base_url=settings["nvidia"]["base_url"],
                    temperature=settings["nvidia"]["temperature"],
                    max_tokens=settings["nvidia"]["max_tokens"],
                )
            except ValueError as e:
                console.print(f"  [yellow]NVIDIA skipped: {e}[/yellow]")
                skip_nvidia = True

        # Processing router
        router = ProcessingRouter(
            ollama=ollama,
            nvidia=nvidia,
            nvidia_threshold=taxonomy.get("nvidia_threshold", 4.0),
            delay_between_requests=settings["processing"]["delay_between_requests"],
        )

        # Google Sheets
        sheets = None
        if not skip_sheets:
            try:
                sheets = SheetsManager()
                # Initialize all 3 sheets
                sheets.setup_all_sheets(
                    categories=taxonomy.get("categories", []),
                    profile=taxonomy.get("profile", {}),
                )
            except (ValueError, Exception) as e:
                console.print(f"  [yellow]Sheets skipped: {e}[/yellow]")
                skip_sheets = True

    except Exception as e:
        console.print(f"[red]Initialization failed: {e}[/red]")
        return

    # ─── Health Checks ────────────────────────────────────────────────

    console.print("[bold]Health Checks:[/bold]")
    if not ollama.health_check():
        console.print("  [red]✗ Ollama not available[/red]")
        console.print(f"    Run: ollama pull {settings['ollama']['model']}")
        return
    console.print("  [green]✓ Ollama[/green]")

    if nvidia and not skip_nvidia:
        if nvidia.health_check():
            console.print("  [green]✓ NVIDIA API[/green]")
        else:
            console.print("  [yellow]✗ NVIDIA (skipping deep analysis)[/yellow]")
            skip_nvidia = True

    if sheets:
        if sheets.health_check():
            console.print("  [green]✓ Google Sheets[/green]")
        else:
            console.print("  [yellow]✗ Google Sheets (skipping push)[/yellow]")
            skip_sheets = True

    console.print()

    # ─── Process Each Channel (13 Steps) ──────────────────────────────

    all_episodes: list[Episode] = []

    for channel in channels:
        console.print(f"[bold cyan]{'─'*50}[/bold cyan]")
        console.print(f"[bold cyan]  Channel: {channel.name}[/bold cyan]")
        console.print(f"[bold cyan]{'─'*50}[/bold cyan]")

        # Step 1: Check YouTube channel
        console.print("  [1/13] Checking channel...")

        # Step 2: Find new episodes
        console.print("  [2/13] Finding new episodes...")
        max_vids = max_videos_override or channel.max_videos
        # Use CLI since_date override, or per-channel since_date from config
        effective_since = since_date
        if not effective_since and channel.since_date:
            effective_since = f"{channel.since_date}T00:00:00Z"
        videos = youtube.get_channel_videos(
            channel, since_date=effective_since, max_results=max_vids
        )

        if not videos:
            console.print("  No videos found. Skipping.")
            continue

        # Step 3: Check against existing (skip already processed)
        if sheets and settings["processing"]["skip_already_processed"]:
            existing_urls = sheets.get_existing_urls()
            videos = [v for v in videos if v.url not in existing_urls]
            if not videos:
                console.print("  All episodes already processed. Skipping.")
                continue

        console.print(f"  [3/13] {len(videos)} new episodes to process")

        # Step 4: Download metadata (already done by collector)
        console.print("  [4/13] Metadata collected ✓")

        # Save raw data backup
        youtube.save_raw_data(channel.name, videos)

        # Create Episode objects with FO_IDs
        existing_ids = sheets.get_existing_fo_ids() if sheets else set()
        # Count existing episodes for this channel prefix
        prefix = channel.fo_prefix
        existing_count = sum(1 for fid in existing_ids if fid.startswith(prefix))

        episodes = []
        videos_dict = {}
        for i, video in enumerate(videos):
            fo_id = generate_fo_id(prefix, existing_count + i + 1)
            episode = Episode.from_video(video, fo_id)
            episodes.append(episode)
            videos_dict[video.video_id] = video

        # Step 5: Obtain transcripts
        console.print(f"  [5/13] Fetching transcripts...")
        transcripts_dict = {}
        for video in videos:
            # Check if already saved locally
            if transcript_extractor.has_transcript(video.video_id, video.channel_name):
                transcript = transcript_extractor.load_transcript(
                    video.video_id, video.channel_name
                )
            else:
                transcript = transcript_extractor.get_transcript(video)

            if transcript:
                # Save to file, get path reference
                path = transcript_extractor.save_transcript(video, transcript)
                transcripts_dict[video.video_id] = transcript

                # Update episode with transcript path
                for ep in episodes:
                    if ep.video_id == video.video_id:
                        ep.transcript_path = path
                        break

            time.sleep(0.5)  # Be gentle with YouTube

        console.print(
            f"  Transcripts: {len(transcripts_dict)}/{len(videos)} fetched"
        )

        # Steps 6-8: Ollama classifies ALL episodes
        console.print("  [6-8/13] Ollama classification (all episodes)...")

        # Steps 9-11: Identify important → NVIDIA deep analysis
        console.print("  [9-11/13] Smart routing → NVIDIA for important...")

        # Run the full routing pipeline
        episodes = router.full_process(episodes, videos_dict, transcripts_dict)

        # Step 12: Update Google Sheets
        if sheets:
            console.print("  [12/13] Updating Google Sheets...")
            sheets.push_episodes(episodes)

        # Step 13: Mark processing complete
        console.print("  [13/13] Processing complete ✓")

        all_episodes.extend(episodes)

    # ─── Final Summary ────────────────────────────────────────────────

    _print_final_summary(all_episodes, taxonomy.get("nvidia_threshold", 4.0))


def _print_final_summary(episodes: list[Episode], threshold: float):
    """Print final pipeline summary."""
    if not episodes:
        console.print("\n[yellow]No episodes processed.[/yellow]")
        return

    console.print(f"\n[bold green]{'═'*50}[/bold green]")
    console.print("[bold green]  Pipeline Complete![/bold green]")
    console.print(f"[bold green]{'═'*50}[/bold green]\n")

    # Stats
    total = len(episodes)
    ollama_done = sum(1 for ep in episodes if ep.ollama_status == "Done")
    nvidia_done = sum(1 for ep in episodes if ep.nvidia_status == "Done")
    nvidia_skipped = sum(1 for ep in episodes if ep.nvidia_status == "Skipped")

    console.print(f"  Total episodes: {total}")
    console.print(f"  Ollama classified: {ollama_done}")
    console.print(f"  NVIDIA deep-analyzed: {nvidia_done}")
    console.print(f"  NVIDIA skipped (relevance < {threshold}): {nvidia_skipped}")
    console.print()

    # Top episodes (highest relevance)
    top_episodes = sorted(
        [ep for ep in episodes if ep.ollama_status == "Done"],
        key=lambda ep: ep.relevance,
        reverse=True,
    )[:10]

    if top_episodes:
        table = Table(title="🔥 Top Episodes by Relevance")
        table.add_column("FO_ID", style="dim")
        table.add_column("Title", style="cyan", max_width=40)
        table.add_column("Category", style="yellow")
        table.add_column("Relevance", justify="center", style="bold green")
        table.add_column("NVIDIA", justify="center")

        for ep in top_episodes:
            nvidia_icon = "✓" if ep.nvidia_status == "Done" else "—"
            table.add_row(
                ep.fo_id,
                ep.title[:40],
                ep.primary_category,
                str(ep.relevance),
                nvidia_icon,
            )

        console.print(table)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="YouTube Knowledge Pipeline")
    parser.add_argument(
        "--channels", nargs="+",
        help="Specific channel names to process (default: all enabled)",
    )
    parser.add_argument(
        "--skip-nvidia", action="store_true",
        help="Skip NVIDIA deep analysis (Ollama only — fast & free)",
    )
    parser.add_argument(
        "--skip-sheets", action="store_true",
        help="Skip Google Sheets push (useful for testing)",
    )
    parser.add_argument(
        "--max-videos", type=int, default=None,
        help="Override max videos per channel",
    )
    parser.add_argument(
        "--since", type=str, default=None,
        help="Only process videos after this date (YYYY-MM-DD)",
    )

    args = parser.parse_args()

    # Logging
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add("pipeline.log", rotation="10 MB", level="DEBUG")

    since_date = f"{args.since}T00:00:00Z" if args.since else None

    run_pipeline(
        channel_names=args.channels,
        skip_nvidia=args.skip_nvidia,
        skip_sheets=args.skip_sheets,
        max_videos_override=args.max_videos,
        since_date=since_date,
    )
