# YouTube Knowledge Pipeline
# Terminal control panel. Run: .\pipeline.ps1 or .\pipeline.bat

$ErrorActionPreference = "Continue"
$projectRoot = $PSScriptRoot
Set-Location $projectRoot

# ─── Virtual Environment ──────────────────────────────────────────────
# Auto-creates .venv on first run. All subsequent runs use it.
function Ensure-Venv {
    $venvPath = Join-Path $projectRoot ".venv"
    $activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

    if (-not (Test-Path $venvPath)) {
        Write-Host ""
        $frames = @("⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏")
        for ($i = 0; $i -lt 10; $i++) {
            Write-Host "`r  $($frames[$i]) Creating virtual environment..." -NoNewline -ForegroundColor Cyan
            Start-Sleep -Milliseconds 100
        }
        python -m venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "`r  [FAIL] Could not create virtual environment.       " -ForegroundColor Red
            Write-Host "  Make sure Python 3.10+ is installed." -ForegroundColor Red
            exit 1
        }
        Write-Host "`r  [OK] Virtual environment created (.venv)            " -ForegroundColor Green
    }

    # Activate if not already active
    if (-not $env:VIRTUAL_ENV) {
        & $activateScript
    }
}

Ensure-Venv
# ──────────────────────────────────────────────────────────────────────

# Explicit path to venv Python — guarantees we always use the right one
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

# ──────────────────────────────────────────────────────────────────────

function Write-Header {
    param([string]$text)
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║  $($text.PadRight(48))║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step {
    param([string]$num, [string]$text)
    Write-Host "  [$num] $text" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$text)
    Write-Host "  [OK] $text" -ForegroundColor Green
}

function Write-Fail {
    param([string]$text)
    Write-Host "  [FAIL] $text" -ForegroundColor Red
}

function Write-Info {
    param([string]$text)
    Write-Host "  [INFO] $text" -ForegroundColor DarkYellow
}

function Ensure-Env {
    $envPath = Join-Path $projectRoot ".env"

    $keys = @(
        @{
            Name = "YOUTUBE_API_KEY"
            Label = "YouTube Data API v3 Key"
            Link = "https://console.cloud.google.com/apis/credentials"
            Default = ""
        },
        @{
            Name = "GEMINI_API_KEY"
            Label = "Google Gemini API Key"
            Link = "https://aistudio.google.com/apikey"
            Default = ""
        },
        @{
            Name = "NVIDIA_API_KEY"
            Label = "NVIDIA API Key"
            Link = "https://build.nvidia.com/"
            Default = ""
        },
        @{
            Name = "GOOGLE_SHEETS_CREDENTIALS_PATH"
            Label = "Path to OAuth Client ID JSON (Desktop app)"
            Link = "https://console.cloud.google.com/apis/credentials > Create OAuth Client ID > Desktop"
            Default = "config/credentials.json"
        },
        @{
            Name = "GOOGLE_SHEETS_SPREADSHEET_ID"
            Label = "Spreadsheet ID from your Google Sheet URL"
            Link = "URL format: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/"
            Default = ""
        }
    )

    # Read existing values
    $existing = @{}
    if (Test-Path $envPath) {
        foreach ($line in (Get-Content $envPath)) {
            if ($line -match "^([A-Z_]+)=(.*)$") {
                $k = $matches[1].Trim()
                $v = $matches[2].Trim()
                if ($v -and -not ($v -like "your_*")) {
                    $existing[$k] = $v
                }
            }
        }
    }

    # Find missing keys
    $missing = @()
    foreach ($item in $keys) {
        if (-not $existing.ContainsKey($item.Name)) {
            $missing += $item
        }
    }

    if ($missing.Count -eq 0) {
        Write-Ok ".env is configured (all keys present)"
        return
    }

    Write-Host ""
    Write-Host "  $($missing.Count) key(s) missing from .env" -ForegroundColor Yellow
    Write-Host "  Enter values below. Press Enter to skip or accept default." -ForegroundColor DarkGray
    Write-Host ""

    foreach ($item in $missing) {
        Write-Host "  $($item.Label)" -ForegroundColor White
        Write-Host "  $($item.Link)" -ForegroundColor DarkGray
        if ($item.Default) {
            Write-Host "  Default: $($item.Default)" -ForegroundColor DarkGray
        }
        $input_val = Read-Host "  $($item.Name)"

        if ([string]::IsNullOrWhiteSpace($input_val)) {
            if ($item.Default) {
                $existing[$item.Name] = $item.Default
                Write-Host "  -> using default" -ForegroundColor DarkGray
            }
            else {
                Write-Info "Skipped. Set it later in .env"
                $existing[$item.Name] = ""
            }
        }
        else {
            $existing[$item.Name] = $input_val
            Write-Ok "$($item.Name) saved"
        }
        Write-Host ""
    }

    # Write .env
    $lines = @()
    $lines += "# Auto-generated environment file"
    $lines += "# Edit this file directly or re-run setup to update values"
    $lines += ""
    foreach ($item in $keys) {
        $val = ""
        if ($existing.ContainsKey($item.Name)) { $val = $existing[$item.Name] }
        $lines += "$($item.Name)=$val"
    }

    Set-Content -Path $envPath -Value ($lines -join "`n") -Encoding UTF8 -NoNewline
    Write-Ok ".env file saved"
}

function Show-Menu {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "  ║       YouTube Knowledge Pipeline                ║" -ForegroundColor Cyan
    Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  ┌─ SETUP ────────────────────────────────────────┐" -ForegroundColor DarkGray
    Write-Host "  │  [1] Setup     Install packages, configure keys│" -ForegroundColor White
    Write-Host "  │  [2] Resolve   Fetch channel IDs from handles  │" -ForegroundColor White
    Write-Host "  │  [3] Health    Check all services and config    │" -ForegroundColor White
    Write-Host "  ├─ RUN ──────────────────────────────────────────┤" -ForegroundColor DarkGray
    Write-Host "  │  [4] Test      Dry run (3 videos, no Sheets)   │" -ForegroundColor White
    Write-Host "  │  [5] Fast      Ollama local (free, no internet)│" -ForegroundColor White
    Write-Host "  │  [6] Full      Gemini + NVIDIA + Sheets (fast) │" -ForegroundColor White
    Write-Host "  ├─ TARGETED ─────────────────────────────────────┤" -ForegroundColor DarkGray
    Write-Host "  │  [7] Single    Process one specific channel    │" -ForegroundColor White
    Write-Host "  │  [8] Recent    Last 30 days only               │" -ForegroundColor White
    Write-Host "  ├─ INFO ─────────────────────────────────────────┤" -ForegroundColor DarkGray
    Write-Host "  │  [9] Channels  List configured channels        │" -ForegroundColor White
    Write-Host "  │  [0] Exit                                      │" -ForegroundColor DarkGray
    Write-Host "  └────────────────────────────────────────────────┘" -ForegroundColor DarkGray
    Write-Host ""
}

function Run-Setup {
    Write-Header "Setup"

    Write-Step "1/5" "Checking Python"
    $py = & $venvPython --version 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Ok "$py" }
    else { Write-Fail "Python not found. Install Python 3.10+"; return }

    Write-Step "2/5" "Installing packages (into .venv)"
    $reqFile = Join-Path $projectRoot "requirements.txt"
    $pkgs = (Get-Content $reqFile | Where-Object { $_ -and ($_ -notmatch "^#") })
    $total = $pkgs.Count
    $frames = @("⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏")
    $frameIdx = 0

    # Show animated spinner during install
    $job = Start-Job -ScriptBlock {
        param($python, $req)
        & $python -m pip install -r $req --quiet 2>&1
    } -ArgumentList $venvPython, $reqFile

    while ($job.State -eq "Running") {
        $frame = $frames[$frameIdx % $frames.Count]
        Write-Host "`r  $frame Installing $total packages...          " -NoNewline -ForegroundColor Cyan
        $frameIdx++
        Start-Sleep -Milliseconds 120
    }

    $result = Receive-Job $job
    Remove-Job $job
    Write-Host "`r                                                      " -NoNewline
    Write-Host "`r" -NoNewline

    if ($job.State -ne "Failed") {
        Write-Ok "$total packages installed"
    } else {
        Write-Fail "Some packages failed. Run: .venv\Scripts\pip install -r requirements.txt"
    }

    Write-Step "3/5" "Configuring environment"
    Ensure-Env

    Write-Step "4/5" "Resolving channel IDs"
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path $envPath) {
        $content = Get-Content $envPath -Raw
        if ($content -match "YOUTUBE_API_KEY=.{10,}") {
            & $venvPython resolve_channels.py
            if ($LASTEXITCODE -eq 0) { Write-Ok "Channels resolved" }
            else { Write-Info "Some channels could not be resolved" }
        }
        else {
            Write-Info "Skipped. YOUTUBE_API_KEY not configured yet."
        }
    }
    else {
        Write-Info "Skipped. No .env file."
    }

    Write-Step "5/5" "Checking APIs"
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path $envPath) {
        $c = Get-Content $envPath -Raw
        if ($c -match "GEMINI_API_KEY=.{10,}") { Write-Ok "Gemini API key set" }
        else { Write-Info "GEMINI_API_KEY not set yet" }
        if ($c -match "NVIDIA_API_KEY=.{10,}") { Write-Ok "NVIDIA API key set" }
        else { Write-Info "NVIDIA_API_KEY not set yet" }
    }

    Write-Host ""
    Write-Host "  Setup complete." -ForegroundColor Green
    Write-Host ""
}

function Run-Full {
    Write-Header "Full Pipeline (Gemini + NVIDIA + Sheets)"
    Ensure-Env
    & $venvPython -m src.main --classifier gemini
}

function Run-Fast {
    Write-Header "Ollama Local (free, no internet)"
    Ensure-Env
    & $venvPython -m src.main --classifier ollama --skip-nvidia
}

function Run-Test {
    Write-Header "Test Run (3 videos, no Sheets)"
    Ensure-Env
    & $venvPython -m src.main --skip-sheets --max-videos 3
}

function Run-Resolve {
    Write-Header "Resolve Channel IDs"
    Ensure-Env
    & $venvPython resolve_channels.py
}

function Run-Channels {
    Write-Header "Channels"
    & $venvPython manage_channels.py list
}

function Run-Health {
    Write-Header "Health Check"

    Write-Step "1" "Gemini API"
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path $envPath) {
        $c = Get-Content $envPath -Raw
        if ($c -match "GEMINI_API_KEY=.{10,}") { Write-Ok "Gemini API key configured" }
        else { Write-Fail "GEMINI_API_KEY not set. Get it from https://aistudio.google.com/apikey" }
    }

    Write-Step "2" "Python packages"
    $check = & $venvPython -c "import gspread, yaml, openai, loguru, google.genai; print('ok')" 2>&1
    if ("$check".Trim() -eq "ok") { Write-Ok "All installed" }
    else { Write-Fail "Missing: $check" }

    Write-Step "3" "Environment"
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path $envPath) {
        $c = Get-Content $envPath -Raw
        if ($c -match "YOUTUBE_API_KEY=.{10,}") { Write-Ok "YOUTUBE_API_KEY" } else { Write-Info "YOUTUBE_API_KEY not set" }
        if ($c -match "GEMINI_API_KEY=.{10,}") { Write-Ok "GEMINI_API_KEY" } else { Write-Info "GEMINI_API_KEY not set" }
        if ($c -match "NVIDIA_API_KEY=.{10,}") { Write-Ok "NVIDIA_API_KEY" } else { Write-Info "NVIDIA_API_KEY not set" }
        if ($c -match "GOOGLE_SHEETS_SPREADSHEET_ID=.{10,}") { Write-Ok "GOOGLE_SHEETS_SPREADSHEET_ID" } else { Write-Info "GOOGLE_SHEETS_SPREADSHEET_ID not set" }
    }
    else {
        Write-Fail ".env missing. Run setup first."
    }

    Write-Step "4" "Google Sheets OAuth"
    $credFile = Join-Path $projectRoot "config\credentials.json"
    if (Test-Path $credFile) { Write-Ok "credentials.json found" }
    else { Write-Fail "config\credentials.json missing. Download from Google Cloud Console." }

    $tokenFile = Join-Path $projectRoot "config\authorized_user.json"
    if (Test-Path $tokenFile) { Write-Ok "OAuth token cached (logged in)" }
    else { Write-Info "Not logged in yet. First pipeline run will open browser." }

    Write-Step "5" "Channel IDs"
    $yc = Get-Content "config\channels.yaml" -Raw
    $empty = ([regex]::Matches($yc, 'channel_id: ""')).Count
    if ($empty -gt 0) { Write-Info "$empty channels need IDs (run option 2)" }
    else { Write-Ok "All channel IDs configured" }
}

function Run-Single {
    Write-Header "Single Channel"
    & $venvPython manage_channels.py list
    Write-Host ""
    $name = Read-Host "  Channel name"
    if ($name) {
        Ensure-Env
        & $venvPython -m src.main --channels "$name" --skip-nvidia
    }
}

function Run-Recent {
    Write-Header "Recent Videos (Last 30 Days)"
    Ensure-Env
    $since = (Get-Date).AddDays(-30).ToString("yyyy-MM-dd")
    Write-Host "  Since: $since" -ForegroundColor DarkGray
    & $venvPython -m src.main --since $since --skip-nvidia
}

# Main loop
while ($true) {
    Show-Menu
    $choice = Read-Host "  Select"

    switch ($choice) {
        "1" { Run-Setup }
        "2" { Run-Resolve }
        "3" { Run-Health }
        "4" { Run-Test }
        "5" { Run-Fast }
        "6" { Run-Full }
        "7" { Run-Single }
        "8" { Run-Recent }
        "9" { Run-Channels }
        "0" { Write-Host ""; Write-Host "  Done." -ForegroundColor Green; exit }
        default { Write-Host "  Invalid." -ForegroundColor Red }
    }

    Write-Host ""
    Write-Host "  Press any key..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
