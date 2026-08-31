"""
Main Pipeline — YouTube Knowledge Extraction.

13-step pipeline with rich terminal animations:
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
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    MofNCompleteColumn,
)
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich.spinner import Spinner
from rich.status import Status

from src.models import ChannelConfig, VideoMetadata, Episode
from src.youtube import YouTubeCollector
from src.transcript import TranscriptExtractor
from src.gemini_client import GeminiClassifier
from src.ollama_client import OllamaClassifier
from src.nvidia_client import NvidiaAnalyzer
from src.processing_router import ProcessingRouter
from src.sheets import SheetsManager

load_dotenv()
console = Console()

# Timing benchmarks file
BENCHMARKS_FILE = Path("data/processed/timing_benchmarks.json")


# ─── Timing Benchmarks ────────────────────────────────────────────────

def load_benchmarks() -> dict:
    """Load saved timing benchmarks from previous runs."""
    if BENCHMARKS_FILE.exists():
        import json
        with open(BENCHMARKS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_benchmarks(benchmarks: dict):
    """Save timing benchmarks for future ETA estimation."""
    import json
    BENCHMARKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BENCHMARKS_FILE, "w") as f:
        json.dump(benchmarks, f, indent=2)


def estimate_time(benchmarks: dict, total_videos: int, skip_nvidia: bool) -> str:
    """Estimate total pipeline time based on benchmarks."""
    if not benchmarks:
        return "unknown (first run)"

    avg_transcript = benchmarks.get("avg_transcript_sec", 2.0)
    avg_classify = benchmarks.get("avg_classify_sec", 5.0)
    avg_nvidia = benchmarks.get("avg_nvidia_sec", 45.0)

    est = total_videos * (avg_transcript + avg_classify)
    if not skip_nvidia:
        est += total_videos * avg_nvidia

    if est < 60:
        return f"~{int(est)}s"
    elif est < 3600:
        return f"~{int(est // 60)}m {int(est % 60)}s"
    else:
        return f"~{int(est // 3600)}h {int((est % 3600) // 60)}m"


# ─── Progress Bar Factories ───────────────────────────────────────────

def make_step_progress() -> Progress:
    """Progress bar for step-level tasks (transcripts, classification)."""
    return Progress(
        SpinnerColumn("arc", style="yellow"),
        TextColumn("[cyan]{task.description}"),
        BarColumn(bar_width=25, complete_style="magenta", finished_style="bold magenta"),
        MofNCompleteColumn(),
        TextColumn("[dim]|"),
        TimeElapsedColumn(),
        TextColumn("[dim]~"),
        TimeRemainingColumn(),
        console=console,
    )


def make_spinner_progress() -> Progress:
    """Spinner-only progress for quick operations."""
    return Progress(
        SpinnerColumn("bouncingBall", style="green"),
        TextColumn("[bold]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    )


# ─── Config & Helpers ─────────────────────────────────────────────────

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


def format_speed(bytes_or_items: float, unit: str = "ep") -> str:
    """Format processing speed."""
    if bytes_or_items < 1:
        return f"--/{unit}"
    return f"{bytes_or_items:.1f} {unit}/min"


# ─── Main Pipeline ────────────────────────────────────────────────────

def run_pipeline(
    channel_names: list[str] = None,
    skip_nvidia: bool = False,
    skip_sheets: bool = False,
    max_videos_override: int = None,
    since_date: str = None,
    classifier_type: str = "gemini",
):
    """Run the full 13-step pipeline with rich animations."""
    pipeline_start = time.time()

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

    # ─── Header ───────────────────────────────────────────────────────

    # Load benchmarks for ETA estimation
    benchmarks = load_benchmarks()

    console.print()
    console.print(Panel.fit(
        "[bold white]YouTube Knowledge Pipeline[/bold white]\n"
        f"[dim]Channels: {len(channels)} | "
        f"NVIDIA: {'[red]OFF[/red]' if skip_nvidia else '[green]ON[/green]'} | "
        f"Sheets: {'[red]OFF[/red]' if skip_sheets else '[green]ON[/green]'}[/dim]",
        border_style="bright_cyan",
        padding=(1, 3),
    ))

    if benchmarks:
        console.print(
            f"  [dim]ETA based on previous runs: "
            f"Transcript ~{benchmarks.get('avg_transcript_sec', 0):.1f}s/ep | "
            f"Gemini ~{benchmarks.get('avg_classify_sec', 0):.1f}s/ep | "
            f"NVIDIA ~{benchmarks.get('avg_nvidia_sec', 0):.1f}s/ep[/dim]"
        )
    console.print()

    # ─── Initialize Components (with spinner) ─────────────────────────

    with console.status("[bold cyan]Initializing pipeline components...", spinner="dots2") as status:
        try:
            status.update("[bold cyan]Connecting to YouTube API...")
            youtube = YouTubeCollector()
            time.sleep(0.3)

            status.update("[bold cyan]Setting up transcript extractor...")
            transcript_extractor = TranscriptExtractor(
                preferred_languages=settings["transcript"]["preferred_languages"],
                fallback_to_auto=settings["transcript"]["fallback_to_auto"],
                chunk_size=settings["transcript"]["chunk_size"],
            )
            time.sleep(0.2)

            status.update(f"[bold cyan]Loading {classifier_type} classifier...")
            if classifier_type == "ollama":
                classifier = OllamaClassifier(
                    model=settings["ollama"]["model"],
                    base_url=settings["ollama"]["base_url"],
                    temperature=settings["ollama"]["temperature"],
                    categories=taxonomy.get("categories", []),
                    profile=taxonomy.get("profile", {}),
                )
            else:
                classifier = GeminiClassifier(
                    model=settings["gemini"]["model"],
                    temperature=settings["gemini"]["temperature"],
                    categories=taxonomy.get("categories", []),
                    profile=taxonomy.get("profile", {}),
                    rpm_limit=settings["gemini"].get("rpm_limit", 15),
                )
            time.sleep(0.2)

            nvidia = None
            if not skip_nvidia:
                status.update("[bold cyan]Connecting to NVIDIA API...")
                try:
                    nvidia = NvidiaAnalyzer(
                        model=settings["nvidia"]["model"],
                        base_url=settings["nvidia"]["base_url"],
                        temperature=settings["nvidia"]["temperature"],
                        max_tokens=settings["nvidia"]["max_tokens"],
                    )
                except ValueError as e:
                    console.print(f"  [yellow]⚠ NVIDIA: {e}[/yellow]")
                    skip_nvidia = True

            router = ProcessingRouter(
                classifier=classifier,
                nvidia=nvidia,
                nvidia_threshold=taxonomy.get("nvidia_threshold", 4.0),
                delay_between_requests=settings["processing"]["delay_between_requests"],
            )

            sheets = None
            if not skip_sheets:
                status.update("[bold cyan]Authenticating Google Sheets...")
                try:
                    sheets = SheetsManager()
                    sheets.setup_all_sheets(
                        categories=taxonomy.get("categories", []),
                        profile=taxonomy.get("profile", {}),
                    )
                except (ValueError, Exception) as e:
                    console.print(f"  [yellow]⚠ Sheets: {e}[/yellow]")
                    skip_sheets = True

        except Exception as e:
            console.print(f"[red]Initialization failed: {e}[/red]")
            return

    console.print("  [green]✓[/green] All components initialized")
    console.print()

    # ─── Health Checks (animated) ─────────────────────────────────────

    with console.status("[bold]Running health checks...", spinner="point") as status:
        status.update(f"[bold]Checking {classifier_type} classifier...")
        if not classifier.health_check():
            console.print(f"  [red]✗ {classifier_type.capitalize()} not available[/red]")
            if classifier_type == "gemini":
                console.print("    Check GEMINI_API_KEY in .env or try: pip install --upgrade google-genai")
            else:
                console.print("    Make sure Ollama is running: ollama serve")
            return
        classifier_label = (
            settings['gemini']['model'] if classifier_type == "gemini"
            else settings['ollama']['model']
        )
        console.print(f"  [green]✓[/green] {classifier_type.capitalize()} [dim]({classifier_label})[/dim]")

        if nvidia and not skip_nvidia:
            status.update("[bold]Checking NVIDIA API...")
            if nvidia.health_check():
                console.print("  [green]✓[/green] NVIDIA API [dim]({model})[/dim]".format(
                    model=settings['nvidia']['model']
                ))
            else:
                console.print("  [yellow]⚠[/yellow] NVIDIA health check failed [dim](will still attempt on episodes)[/dim]")

        if sheets:
            status.update("[bold]Checking Google Sheets...")
            if sheets.health_check():
                console.print("  [green]✓[/green] Google Sheets")
            else:
                console.print("  [yellow]✗[/yellow] Sheets [dim](skipping push)[/dim]")
                skip_sheets = True

    console.print()

    # ─── Process Each Channel ─────────────────────────────────────────

    all_episodes: list[Episode] = []
    all_transcript_times: list[float] = []
    all_classify_times: list[float] = []
    all_nvidia_times: list[float] = []

    for ch_idx, channel in enumerate(channels):
        console.print()
        console.print(Rule(
            f"[bold cyan]{channel.name}[/bold cyan] [dim]({ch_idx+1}/{len(channels)})[/dim]",
            style="cyan",
        ))

        # Step 1-2: Find videos
        with console.status("[cyan]Searching for videos...", spinner="dots"):
            max_vids = max_videos_override or channel.max_videos
            effective_since = since_date
            if not effective_since and channel.since_date:
                effective_since = f"{channel.since_date}T00:00:00Z"
            videos = youtube.get_channel_videos(
                channel, since_date=effective_since, max_results=max_vids
            )

        if not videos:
            console.print("  [dim]No videos found. Skipping.[/dim]")
            continue

        # Check existing
        if sheets and settings["processing"]["skip_already_processed"]:
            existing_urls = sheets.get_existing_urls()
            videos = [v for v in videos if v.url not in existing_urls]
            if not videos:
                console.print("  [dim]All episodes already processed.[/dim]")
                continue

        console.print(f"  [green]Found {len(videos)} new episodes[/green]")

        # Save raw data
        youtube.save_raw_data(channel.name, videos)

        # Create Episode objects
        existing_ids = sheets.get_existing_fo_ids() if sheets else set()
        prefix = channel.fo_prefix
        existing_count = sum(1 for fid in existing_ids if fid.startswith(prefix))

        episodes = []
        videos_dict = {}
        for i, video in enumerate(videos):
            fo_id = generate_fo_id(prefix, existing_count + i + 1)
            episode = Episode.from_video(video, fo_id)
            episodes.append(episode)
            videos_dict[video.video_id] = video

        # ─── Step 5: Transcripts (progress bar) ───────────────────

        transcripts_dict = {}
        transcript_times = []
        transcript_progress = make_step_progress()

        with transcript_progress:
            t_task = transcript_progress.add_task(
                "Fetching transcripts", total=len(videos)
            )

            for video in videos:
                transcript_progress.update(
                    t_task,
                    description=f"[cyan]Transcript: {video.title[:35]}..."
                )

                t_start = time.time()

                if transcript_extractor.has_transcript(video.video_id, video.channel_name):
                    transcript = transcript_extractor.load_transcript(
                        video.video_id, video.channel_name
                    )
                else:
                    transcript = transcript_extractor.get_transcript(video)

                if transcript:
                    path = transcript_extractor.save_transcript(video, transcript)
                    transcripts_dict[video.video_id] = transcript
                    for ep in episodes:
                        if ep.video_id == video.video_id:
                            ep.transcript_path = path
                            break

                transcript_times.append(time.time() - t_start)
                transcript_progress.advance(t_task)
                time.sleep(0.3)

            success_count = len(transcripts_dict)
            total_count = len(videos)
            color = "green" if success_count == total_count else "yellow"
            console.print(
                f"  [{color}]Transcripts: {success_count}/{total_count} fetched[/{color}]"
            )

        # ─── Steps 6-8: Ollama Classification (progress bar) ──────

        classify_times = []
        classify_progress = make_step_progress()

        with classify_progress:
            o_task = classify_progress.add_task(
                "Gemini classifying", total=len(episodes)
            )

            for i, episode in enumerate(episodes):
                if episode.ollama_status == "Done":
                    classify_progress.advance(o_task)
                    continue

                video = videos_dict.get(episode.video_id)
                if not video:
                    classify_progress.advance(o_task)
                    continue

                classify_progress.update(
                    o_task,
                    description=f"[cyan]Gemini: {episode.title[:35]}..."
                )

                o_start = time.time()
                transcript = transcripts_dict.get(episode.video_id)
                try:
                    classification = classifier.classify(video, transcript)
                    if classification:
                        episode.apply_ollama(classification)
                    else:
                        episode.ollama_status = "Failed"
                except Exception as e:
                    episode.ollama_status = "Failed"
                    logger.error(f"Gemini failed for {episode.title[:40]}: {e}")

                classify_times.append(time.time() - o_start)
                classify_progress.advance(o_task)

        ollama_done = sum(1 for ep in episodes if ep.ollama_status == "Done")
        console.print(
            f"  [green]Classified: {ollama_done}/{len(episodes)} episodes[/green]"
        )

        # ─── Steps 9-11: NVIDIA Deep Analysis ─────────────────────

        nvidia_times = []
        important = [
            ep for ep in episodes
            if ep.ollama_status == "Done"
            and ep.relevance >= taxonomy.get("nvidia_threshold", 4.0)
            and ep.nvidia_status != "Done"
        ]

        if important and nvidia and not skip_nvidia:
            nvidia_progress = make_step_progress()

            with nvidia_progress:
                n_task = nvidia_progress.add_task(
                    "NVIDIA deep analysis", total=len(important)
                )

                for i, episode in enumerate(important):
                    nvidia_progress.update(
                        n_task,
                        description=f"[cyan]NVIDIA: {episode.title[:35]}..."
                    )

                    video = videos_dict.get(episode.video_id)
                    transcript = transcripts_dict.get(episode.video_id)

                    if not video or not transcript:
                        episode.nvidia_status = "Skipped"
                        nvidia_progress.advance(n_task)
                        continue

                    n_start = time.time()
                    try:
                        analysis = nvidia.analyze(
                            video, transcript,
                            ollama_category=episode.primary_category,
                        )
                        if analysis:
                            episode.apply_nvidia(analysis)
                        else:
                            episode.nvidia_status = "Failed"
                    except Exception as e:
                        episode.nvidia_status = "Failed"
                        logger.error(f"NVIDIA failed for {episode.title[:40]}: {e}")

                    nvidia_times.append(time.time() - n_start)
                    nvidia_progress.advance(n_task)
                    if i < len(important) - 1:
                        time.sleep(settings["processing"]["delay_between_requests"] * 2)

            nvidia_done = sum(1 for ep in important if ep.nvidia_status == "Done")
            console.print(
                f"  [green]Deep-analyzed: {nvidia_done}/{len(important)} episodes[/green]"
            )
        elif not skip_nvidia and not nvidia:
            console.print("  [yellow]NVIDIA not configured — skipping deep analysis[/yellow]")
            for ep in episodes:
                if ep.nvidia_status == "Pending":
                    ep.nvidia_status = "Skipped"
        else:
            # Mark non-important as skipped
            for ep in episodes:
                if ep.nvidia_status == "Pending" and ep.ollama_status == "Done":
                    if ep.relevance < taxonomy.get("nvidia_threshold", 4.0):
                        ep.nvidia_status = "Skipped"
                    elif skip_nvidia:
                        ep.nvidia_status = "Skipped"

        # ─── Step 12: Local CSV Backup (always saves) ─────────────

        csv_path = Path("data/processed/episodes.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        _save_csv_backup(episodes, csv_path)
        console.print(f"  [green]✓[/green] CSV backup saved [dim]({csv_path})[/dim]")

        # ─── Step 12b: Google Sheets (optional) ───────────────────

        if sheets:
            try:
                with console.status("[cyan]Pushing to Google Sheets...", spinner="dots2"):
                    sheets.push_episodes(episodes)
                console.print("  [green]✓[/green] Google Sheets updated")
            except Exception as e:
                console.print(f"  [yellow]⚠ Sheets push failed: {e}[/yellow]")
                console.print("  [dim]Data is safe in CSV backup.[/dim]")

        # ─── Step 13: Done ────────────────────────────────────────

        console.print("  [bold green]✓ Channel complete[/bold green]")
        all_episodes.extend(episodes)

        # Collect timing data for benchmarks
        all_transcript_times.extend(transcript_times)
        all_classify_times.extend(classify_times)
        all_nvidia_times.extend(nvidia_times)

    # ─── Save Benchmarks ──────────────────────────────────────────────

    if all_transcript_times or all_classify_times or all_nvidia_times:
        new_benchmarks = {
            "avg_transcript_sec": (
                sum(all_transcript_times) / len(all_transcript_times)
                if all_transcript_times else benchmarks.get("avg_transcript_sec", 2.0)
            ),
            "avg_classify_sec": (
                sum(all_classify_times) / len(all_classify_times)
                if all_classify_times else benchmarks.get("avg_classify_sec", 5.0)
            ),
            "avg_nvidia_sec": (
                sum(all_nvidia_times) / len(all_nvidia_times)
                if all_nvidia_times else benchmarks.get("avg_nvidia_sec", 45.0)
            ),
            "last_run": datetime.now().isoformat(),
            "episodes_processed": len(all_episodes),
        }
        save_benchmarks(new_benchmarks)

    # ─── Final Summary ────────────────────────────────────────────────

    pipeline_elapsed = time.time() - pipeline_start
    _print_final_summary(all_episodes, taxonomy.get("nvidia_threshold", 4.0), pipeline_elapsed)


def _save_csv_backup(episodes: list[Episode], csv_path: Path):
    """
    Save episodes to local CSV. Appends to existing file (no duplicates by FO_ID).
    This ALWAYS runs — your data is never lost even if Sheets fails.
    """
    import csv

    headers = Episode.sheet_headers()

    # Load existing FO_IDs to avoid duplicates
    existing_ids = set()
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if row:
                    existing_ids.add(row[0])

    new_episodes = [ep for ep in episodes if ep.fo_id not in existing_ids]

    if not new_episodes:
        return

    # Write header if file is new
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(headers)
        for ep in new_episodes:
            writer.writerow(ep.to_sheet_row())


def _print_final_summary(episodes: list[Episode], threshold: float, elapsed: float):
    """Print final pipeline summary with stats."""
    console.print()

    if not episodes:
        console.print(Panel("[yellow]No episodes processed.[/yellow]", border_style="yellow"))
        return

    # Stats
    total = len(episodes)
    ollama_done = sum(1 for ep in episodes if ep.ollama_status == "Done")
    nvidia_done = sum(1 for ep in episodes if ep.nvidia_status == "Done")
    nvidia_skipped = sum(1 for ep in episodes if ep.nvidia_status == "Skipped")

    # Calculate speed
    minutes_elapsed = elapsed / 60
    speed = total / minutes_elapsed if minutes_elapsed > 0 else 0

    # Format elapsed time
    if elapsed < 60:
        time_str = f"{elapsed:.0f}s"
    elif elapsed < 3600:
        time_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
    else:
        time_str = f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m"

    # Summary panel
    summary_text = (
        f"[bold green]Pipeline Complete![/bold green]\n\n"
        f"  [white]Episodes processed:[/white]  [bold]{total}[/bold]\n"
        f"  [white]Ollama classified:[/white]   [bold]{ollama_done}[/bold]\n"
        f"  [white]NVIDIA analyzed:[/white]     [bold]{nvidia_done}[/bold]\n"
        f"  [white]NVIDIA skipped:[/white]      [dim]{nvidia_skipped}[/dim]\n\n"
        f"  [dim]Time: {time_str} | Speed: {speed:.1f} episodes/min[/dim]"
    )

    console.print(Panel(summary_text, border_style="green", padding=(1, 3)))

    # Top episodes table
    top_episodes = sorted(
        [ep for ep in episodes if ep.ollama_status == "Done"],
        key=lambda ep: ep.relevance,
        reverse=True,
    )[:10]

    if top_episodes:
        console.print()
        table = Table(
            title="[bold]Top Episodes by Relevance[/bold]",
            border_style="bright_cyan",
            header_style="bold cyan",
            show_lines=True,
        )
        table.add_column("ID", style="dim", width=7)
        table.add_column("Title", style="white", max_width=42)
        table.add_column("Category", style="yellow", max_width=25)
        table.add_column("Score", justify="center", style="bold green", width=6)
        table.add_column("NVIDIA", justify="center", width=7)

        for ep in top_episodes:
            nvidia_icon = "[green]✓[/green]" if ep.nvidia_status == "Done" else "[dim]—[/dim]"
            table.add_row(
                ep.fo_id,
                ep.title[:42],
                ep.primary_category,
                str(ep.relevance),
                nvidia_icon,
            )

        console.print(table)
    console.print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="YouTube Knowledge Pipeline")
    parser.add_argument(
        "--channels", nargs="+",
        help="Specific channel names to process (default: all enabled)",
    )
    parser.add_argument(
        "--classifier", choices=["gemini", "ollama"], default="gemini",
        help="Which LLM to use for classification (default: gemini)",
    )
    parser.add_argument(
        "--skip-nvidia", action="store_true",
        help="Skip NVIDIA deep analysis (classification only — fast & free)",
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

    # Logging — suppress loguru console output (rich handles display)
    logger.remove()
    logger.add("pipeline.log", rotation="10 MB", level="DEBUG")

    since_date = f"{args.since}T00:00:00Z" if args.since else None

    run_pipeline(
        channel_names=args.channels,
        skip_nvidia=args.skip_nvidia,
        skip_sheets=args.skip_sheets,
        max_videos_override=args.max_videos,
        since_date=since_date,
        classifier_type=args.classifier,
    )
