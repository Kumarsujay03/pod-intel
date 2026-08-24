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
        Write-Host "  Creating virtual environment (.venv)..." -ForegroundColor Cyan
        python -m venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  [FAIL] Could not create virtual environment." -ForegroundColor Red
            Write-Host "  Make sure Python 3.10+ is installed." -ForegroundColor Red
            exit 1
        }
        Write-Host "  [OK] Virtual environment created" -ForegroundColor Green
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

# ─── Ollama Auto-Start & Model Selection ──────────────────────────────
# Ranked preference: best models first. Picks the best one already installed.
$ollamaModelPreference = @(
    "llama3.1",
    "llama3",
    "mistral",
    "gemma2",
    "phi3",
    "qwen2",
    "llama2",
    "deepseek-coder"
)

function Ensure-Ollama {
    # Check if Ollama is reachable
    $running = $false
    try {
        $resp = ollama list 2>&1
        if ($LASTEXITCODE -eq 0) { $running = $true }
    } catch {}

    if (-not $running) {
        Write-Host "  [INFO] Ollama not running. Starting in background..." -ForegroundColor DarkYellow
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
        # Wait a few seconds for it to come up
        Start-Sleep -Seconds 3

        # Verify it started
        try {
            $resp = ollama list 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  [OK] Ollama started successfully" -ForegroundColor Green
            } else {
                Write-Host "  [FAIL] Could not start Ollama. Install from https://ollama.com" -ForegroundColor Red
                return
            }
        } catch {
            Write-Host "  [FAIL] Could not start Ollama. Install from https://ollama.com" -ForegroundColor Red
            return
        }
    }

    # Get installed models
    $modelOutput = ollama list 2>&1
    $installedModels = @()
    foreach ($line in ($modelOutput -split "`n")) {
        if ($line -match "^\s*(\S+:\S+)") {
            $name = $matches[1].Trim()
            if ($name -and $name -ne "NAME") {
                $installedModels += $name
            }
        }
    }

    if ($installedModels.Count -eq 0) {
        Write-Host "  [INFO] No models installed. Pulling llama3..." -ForegroundColor DarkYellow
        ollama pull llama3
        $installedModels += "llama3:latest"
    }

    # Pick the best available model from preference list
    # Match by base name (before the colon)
    $bestModel = ""
    foreach ($preferred in $ollamaModelPreference) {
        foreach ($installed in $installedModels) {
            $baseName = ($installed -split ":")[0]
            if ($baseName -eq $preferred) {
                $bestModel = $installed
                break
            }
        }
        if ($bestModel) { break }
    }

    # Fallback: use whatever is installed first
    if (-not $bestModel) {
        $bestModel = $installedModels[0]
    }

    # Update settings.yaml with the best model
    $settingsFile = Join-Path $projectRoot "config\settings.yaml"
    if (Test-Path $settingsFile) {
        $content = Get-Content $settingsFile -Raw
        # Match the model under the ollama section specifically (first model: line)
        if ($content -match '(?m)^ollama:[\s\S]*?^\s+model:\s*"([^"]*)"') {
            $currentModel = $matches[1]
            if ($currentModel -ne $bestModel) {
                # Replace only the first model: occurrence (ollama section)
                $content = $content -replace '(?m)(^ollama:[\s\S]*?^\s+model:\s*)"[^"]*"', "`$1`"$bestModel`""
                Set-Content -Path $settingsFile -Value $content -Encoding UTF8 -NoNewline
                Write-Host "  [OK] Using model: $bestModel (updated from $currentModel)" -ForegroundColor Green
            } else {
                Write-Host "  [OK] Ollama ready | Model: $bestModel" -ForegroundColor Green
            }
        }
    } else {
        Write-Host "  [OK] Ollama ready | Model: $bestModel" -ForegroundColor Green
    }
}

Ensure-Ollama
# ──────────────────────────────────────────────────────────────────────

function Write-Header {
    param([string]$text)
    Write-Host ""
    Write-Host "----------------------------------------------------" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "----------------------------------------------------" -ForegroundColor Cyan
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
        },
        @{
            Name = "OLLAMA_BASE_URL"
            Label = "Ollama server URL"
            Link = "Default works if Ollama runs locally"
            Default = "http://localhost:11434"
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
    Write-Header "YouTube Knowledge Pipeline"
    Write-Host "  --- SETUP ---" -ForegroundColor DarkGray
    Write-Host "  [1] Setup     Install packages, configure keys, check Ollama"
    Write-Host "  [2] Resolve   Fetch channel IDs from YouTube handles"
    Write-Host "  [3] Health    Check all services and config"
    Write-Host ""
    Write-Host "  --- RUN ---" -ForegroundColor DarkGray
    Write-Host "  [4] Test      Process 3 videos, no Sheets push (dry run)"
    Write-Host "  [5] Fast      Run Ollama only (skip NVIDIA, free and local)"
    Write-Host "  [6] Full      Run full pipeline (Ollama + NVIDIA + Sheets)"
    Write-Host ""
    Write-Host "  --- TARGETED ---" -ForegroundColor DarkGray
    Write-Host "  [7] Single    Process one specific channel"
    Write-Host "  [8] Recent    Process videos from last 30 days only"
    Write-Host ""
    Write-Host "  --- INFO ---" -ForegroundColor DarkGray
    Write-Host "  [9] Channels  List configured channels"
    Write-Host "  [0] Exit"
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
    & $venvPython -m pip install -r $reqFile --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $count = (Get-Content $reqFile | Where-Object { $_ -and ($_ -notmatch "^#") }).Count
        Write-Ok "$count packages installed"
    } else {
        Write-Fail "Some packages failed to install. Run manually: .venv\Scripts\pip install -r requirements.txt"
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

    Write-Step "5/5" "Checking Ollama"
    Ensure-Ollama

    Write-Host ""
    Write-Host "  Setup complete." -ForegroundColor Green
    Write-Host ""
}

function Run-Full {
    Write-Header "Full Pipeline"
    Ensure-Env
    & $venvPython -m src.main
}

function Run-Fast {
    Write-Header "Ollama Only"
    Ensure-Env
    & $venvPython -m src.main --skip-nvidia
}

function Run-Test {
    Write-Header "Test Run (3 videos, no Sheets)"
    Ensure-Env
    & $venvPython -m src.main --skip-nvidia --skip-sheets --max-videos 3
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

    Write-Step "1" "Ollama"
    Ensure-Ollama

    Write-Step "2" "Python packages"
    $check = & $venvPython -c "import ollama, gspread, yaml, openai, loguru; print('ok')" 2>&1
    if ("$check".Trim() -eq "ok") { Write-Ok "All installed" }
    else { Write-Fail "Missing: $check" }

    Write-Step "3" "Environment"
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path $envPath) {
        $c = Get-Content $envPath -Raw
        if ($c -match "YOUTUBE_API_KEY=.{10,}") { Write-Ok "YOUTUBE_API_KEY" } else { Write-Info "YOUTUBE_API_KEY not set" }
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
