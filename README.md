# Pod-Intel — Podcast Intelligence Pipeline

Automated system that pulls videos from YouTube channels, extracts transcripts, classifies content using AI (Google Gemini or local Ollama), runs deep analysis on high-value episodes via NVIDIA API, and pushes structured results to Google Sheets.

Built for podcast-heavy channels. Filters out shorts and clips automatically. Processes hundreds of episodes without manual intervention.

## How It Works

```
YouTube Channels (multiple)
        |
        v
  Uploads Playlist Scanner
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
Gemini       NVIDIA API
(cloud,fast) (cloud, selective)
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

Gemini classifies every episode fast (~3-5 sec each). NVIDIA only gets called for episodes that score above your relevance threshold. You do not burn API credits on low-value content.

Alternatively, you can use Ollama (local, free) for classification if you prefer no internet dependency.

## Requirements

- Python 3.10+
- Google Gemini API key (free tier: 15 requests/min)
- YouTube Data API v3 key (free: 10,000 units/day)
- NVIDIA API key (https://build.nvidia.com)
- Google Cloud OAuth Client ID (Desktop app) for Sheets access
- Optional: Ollama installed locally for offline classification

## Setup

```
git clone <repo-url>
cd pod-intel
.\pipeline.bat
```

Select option 1 (Setup). The script will:

1. Create a virtual environment (.venv) automatically
2. Check your Python version
3. Install all packages from requirements.txt
4. Ask you to paste each API key (skippable, fills in later)
5. Resolve YouTube channel IDs from handles
6. Verify API keys are set

The .env file is created automatically during setup. No manual file copying needed.

For Google Sheets, download an OAuth Client ID JSON from Google Cloud Console:
- Go to APIs & Services > Credentials > Create OAuth Client ID > Desktop app
- Save the downloaded file as `config/credentials.json`
- On first pipeline run with Sheets, your browser opens for Google login (one-time)

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
--- SETUP ---
[1] Setup     Install packages, configure keys
[2] Resolve   Fetch channel IDs from YouTube handles
[3] Health    Check all services and config

--- RUN ---
[4] Test      Dry run (3 videos, no Sheets)
[5] Fast      Ollama local (free, no internet)
[6] Full      Gemini + NVIDIA + Sheets (fast)

--- TARGETED ---
[7] Single    Process one specific channel
[8] Recent    Last 30 days only

--- INFO ---
[9] Channels  List configured channels
[0] Exit
```

### Command Line (alternative)

```
python -m src.main                                         # full pipeline (Gemini + NVIDIA)
python -m src.main --classifier ollama --skip-nvidia       # Ollama only (local, free)
python -m src.main --skip-nvidia                           # Gemini classify, no deep analysis
python -m src.main --skip-nvidia --skip-sheets             # local test, no external writes
python -m src.main --channels "Raj Shamani"                # single channel
python -m src.main --since 2024-06-01                      # recent only
python -m src.main --max-videos 10 --skip-nvidia           # quick sample
```

## Project Structure

```
.
|-- config/
|   |-- channels.yaml        Channel registry (handles, IDs, filters)
|   |-- settings.yaml        Model config, rate limits, delays
|   |-- taxonomy.yaml        Categories, user interest profile, thresholds
|
|-- data/
|   |-- raw/                 Backup of fetched metadata (JSON)
|   |-- transcripts/         Saved transcript files per channel
|   |-- processed/           CSV backup + timing benchmarks
|
|-- src/
|   |-- main.py              Pipeline orchestrator with rich animations
|   |-- youtube.py           YouTube uploads playlist scanner with filtering
|   |-- transcript.py        Transcript fetcher (youtube-transcript-api v1.x)
|   |-- gemini_client.py     Google Gemini for fast cloud classification
|   |-- ollama_client.py     Local Ollama for offline classification
|   |-- nvidia_client.py     NVIDIA API for deep analysis (selective)
|   |-- processing_router.py Smart routing: classify all, deep-analyze important
|   |-- sheets.py            Google Sheets push via OAuth (3 sheets)
|   |-- models.py            Data classes matching sheet columns
|
|-- manage_channels.py       CLI to add/remove/list channels
|-- resolve_channels.py      Auto-resolve channel IDs from handles
|-- pipeline.ps1             Terminal control panel (PowerShell)
|-- pipeline.bat             Launcher for pipeline.ps1
|-- requirements.txt         Dependencies
|-- .gitignore
|-- README.md
```

## Google Sheets Output

Three sheets are created automatically:

**EPISODES** — one row per video:
FO_ID, Guest, Title, YouTube_URL, Date, Duration, Description, Transcript, Primary_Category, Subcategory, Topics, Summary, Key_Insights, Relevance, Tags, Ollama_Status, NVIDIA_Status, Last_Updated

**CATEGORIES** — controlled taxonomy (14 fixed categories). Prevents the model from inventing variations.

**PROFILE** — your interest scores (1-5 per category). The pipeline uses this to calculate relevance. High relevance episodes get routed to NVIDIA for deep analysis.

Transcripts are stored as local files, not in the spreadsheet. The sheet holds a reference path only.

**Local CSV Backup** — every pipeline run automatically saves results to `data/processed/episodes.csv`. This ensures no data is lost even if Google Sheets auth fails or network drops mid-run.

## Configuration

### config/channels.yaml

```yaml
channels:
  - name: "Raj Shamani"
    channel_handle: "@rajshamani"
    channel_id: "UCzwCEE_PchiBULMnAJqhGVg"
    enabled: true
    fo_prefix: "FO"
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

nvidia_threshold: 3.0
```

Episodes scoring below nvidia_threshold get classification only. Episodes above it get full NVIDIA deep analysis.

### config/settings.yaml

Controls which Gemini/Ollama model to use, NVIDIA model, rate limits, batch sizes, delays, transcript language preferences.

## Adding a Channel

Option A (CLI):
```
python manage_channels.py add --name "New Channel" --handle "@handle" --prefix "NC"
python resolve_channels.py
```

Option B (edit config/channels.yaml directly)

## Free Tier Limits

| Service | Free Quota | Pipeline Usage |
|---------|-----------|----------------|
| YouTube Data API | 10,000 units/day | ~20 units per 500 videos |
| Google Gemini | 15 requests/min | Built-in rate limiter |
| NVIDIA API | Varies | Only high-relevance episodes |
| Google Sheets | No limit | 3 sheets, append-only |

Everything runs within free tier for normal use (5 channels, hundreds of episodes).

## Tech Stack

| Layer | Tool |
|-------|------|
| Video discovery | YouTube Data API v3 (uploads playlist) |
| Transcripts | youtube-transcript-api v1.x |
| Cloud classification | Google Gemini (gemini-3.6-flash) |
| Local classification | Ollama (optional, any model) |
| Deep analysis | NVIDIA API (OpenAI-compatible) |
| Storage and UI | Google Sheets (OAuth) |
| Config | YAML + dotenv |
| Terminal UI | Rich (progress bars, spinners, panels) |
| Retry logic | Tenacity |

## Performance

With Gemini + NVIDIA (full pipeline):
- Classification: ~3-5 sec/episode
- Deep analysis: ~40 sec/episode
- 15 episodes: ~12 min
- 100 episodes: ~1.5 hours

With Ollama (local, free):
- Classification: ~40 sec/episode (depends on hardware)
- 15 episodes: ~10 min (no NVIDIA)
- 100 episodes: ~1 hour (classification only)

## License

Private project. Not licensed for redistribution.
