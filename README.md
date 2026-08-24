# Podcast Intelligence Pipeline

Automated system that pulls videos from YouTube channels, extracts transcripts, classifies content using a local LLM (Ollama), runs deep analysis on high-value episodes via NVIDIA API, and pushes structured results to Google Sheets.

Built for podcast-heavy channels. Filters out shorts and clips automatically. Processes hundreds of episodes without manual intervention.

## How It Works

```
YouTube Channels (multiple)
        |
        v
  Video Metadata Collector
  (title, URL, date, duration, views)
        |
        v
  Transcript Extractor
  (manual > auto-generated > any language)
        |
        v
  +-----+-----+
  |           |
  v           v
Ollama       NVIDIA API
(local)      (cloud, selective)
  |           |
  |           +-- detailed summary
  |           +-- key insights
  |           +-- business lessons
  |           +-- claims to verify
  |
  +-- category
  +-- subcategory
  +-- tags
  +-- relevance score
  +-- short summary
        |
        v
  Google Sheets
  (3 sheets: EPISODES, CATEGORIES, PROFILE)
```

Ollama processes every episode locally and for free. NVIDIA only gets called for episodes that score above your relevance threshold. You do not burn API credits on low-value content.

## Channels Configured

| Channel | Handle | Scope |
|---------|--------|-------|
| Raj Shamani | @rajshamani | All 500+ episodes |
| Nikhil Kamath (WTF / People by WTF) | @nikhil.kamath | All podcasts, 15min+ |
| Lenny's Podcast | @LennysPodcast | Last 2 years, 20min+ |
| David Senra (Founders) | @DavidSenra | All long-form, 15min+ |
| The Knowledge Project | @tkppodcast | Last 2 years, 15min+ |

Add or remove channels by editing `config/channels.yaml` or using the CLI tool.

## Requirements

- Python 3.10+
- Ollama installed and running locally (https://ollama.com)
- YouTube Data API v3 key
- NVIDIA API key (https://build.nvidia.com)
- Google Sheets service account credentials

## Setup

```
git clone <repo-url>
cd <repo-folder>
.\pipeline.bat
```

Select option 1 (Setup). The script will:

1. Check your Python version
2. Install all packages from requirements.txt with progress
3. Ask you to paste each API key (skippable, fills in later)
4. Resolve YouTube channel IDs from handles
5. Verify Ollama is reachable

The .env file is created automatically during setup. No manual file copying needed.

## Usage

Run the terminal control panel:

```
.\pipeline.bat
```

Or directly in PowerShell:

```
.\pipeline.ps1
```

Menu options:

```
[1] Setup     Install packages, configure keys, check Ollama
[2] Full      Run full pipeline (Ollama + NVIDIA + Sheets)
[3] Fast      Run Ollama only (skip NVIDIA, free and local)
[4] Test      Process 3 videos, no Sheets push (dry run)
[5] Resolve   Fetch channel IDs from YouTube handles
[6] Channels  List configured channels
[7] Health    Check all services and config
[8] Single    Process one specific channel
[9] Recent    Process videos from last 30 days only
[0] Exit
```

### Command Line (alternative)

```
python -m src.main                                    # full pipeline
python -m src.main --skip-nvidia                      # ollama only
python -m src.main --skip-nvidia --skip-sheets        # local test
python -m src.main --channels "Raj Shamani"           # single channel
python -m src.main --since 2024-06-01                 # recent only
python -m src.main --max-videos 10 --skip-nvidia      # quick sample
```

## Project Structure

```
.
|-- config/
|   |-- channels.yaml        Channel registry (handles, IDs, filters)
|   |-- settings.yaml        Model config, batch size, delays
|   |-- taxonomy.yaml        Categories, user interest profile, thresholds
|
|-- data/
|   |-- raw/                 Backup of fetched metadata (JSON)
|   |-- transcripts/         Saved transcript files per channel
|   |-- processed/           Output artifacts
|
|-- src/
|   |-- main.py              Pipeline orchestrator (13-step flow)
|   |-- youtube.py           YouTube API collector with shorts filtering
|   |-- transcript.py        Transcript fetcher, saves to files not sheets
|   |-- ollama_client.py     Local LLM for classification
|   |-- nvidia_client.py     Cloud LLM for deep analysis
|   |-- processing_router.py Smart routing: Ollama all, NVIDIA selective
|   |-- sheets.py            Google Sheets push (3 sheets)
|   |-- models.py            Data classes matching sheet columns
|
|-- manage_channels.py       CLI to add/remove/list channels
|-- resolve_channels.py      Auto-resolve channel IDs from handles
|-- pipeline.ps1             Terminal control panel (PowerShell)
|-- pipeline.bat             Launcher for pipeline.ps1
|-- requirements.txt         Pinned dependencies
|-- .gitignore
|-- README.md
```

## Google Sheets Output

Three sheets are created automatically:

**EPISODES** contains one row per video with columns:
FO_ID, Guest, Title, YouTube_URL, Date, Duration, Description, Transcript (file path), Primary_Category, Subcategory, Topics, Summary, Key_Insights, Relevance, Tags, Ollama_Status, NVIDIA_Status, Last_Updated

**CATEGORIES** holds the controlled taxonomy (14 fixed categories). Prevents the model from inventing hundreds of slight variations.

**PROFILE** stores your interest scores (1 to 5 per category). The pipeline uses this to calculate a relevance score for each episode. High relevance episodes get routed to NVIDIA for deep analysis. Low relevance ones get classified by Ollama only.

Transcripts are stored as local files, not inside the spreadsheet. The sheet only holds a reference path. This keeps it fast even with thousands of rows.

## Configuration

### config/channels.yaml

```yaml
channels:
  - name: "Raj Shamani"
    channel_handle: "@rajshamani"
    channel_id: "UCbMGBIayK26L4VaKbwYXSew"
    enabled: true
    fo_prefix: "RS"
    max_videos: 0          # 0 means all
    since_date: ""         # empty means all time
    filter_shorts: true
    min_duration_minutes: 15
```

### config/taxonomy.yaml

```yaml
categories:
  - "AI & Technology"
  - "Finance & Investing"
  - "Business & Entrepreneurship"
  ...

profile:
  "AI & Technology": 5
  "Finance & Investing": 5
  "Entertainment": 1

nvidia_threshold: 4.0
```

Episodes scoring below nvidia_threshold get Ollama classification only. Episodes above it get full NVIDIA deep analysis.

### config/settings.yaml

Controls which Ollama model to use, NVIDIA model selection, batch sizes, delays between API calls, transcript language preferences.

## Adding a Channel

Option A (CLI):
```
python manage_channels.py add --name "New Channel" --handle "@handle" --prefix "NC"
python resolve_channels.py
```

Option B (edit config/channels.yaml directly)

## Tech Stack

| Layer | Tool |
|-------|------|
| Video discovery | YouTube Data API v3 |
| Transcripts | youtube-transcript-api |
| Local classification | Ollama |
| Deep analysis | NVIDIA API (OpenAI-compatible) |
| Storage and UI | Google Sheets |
| Config | YAML + dotenv |
| Terminal UI | Rich |
| Retry logic | Tenacity |

## Name Suggestions

Pick one for the repo:

- `podscope`
- `castmind`
- `podcast-cortex`
- `episcan`
- `podpipeline`
- `pod-intel`
- `yt-podcast-brain`

## License

Private project. Not licensed for redistribution.
