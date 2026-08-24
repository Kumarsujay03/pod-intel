# YouTube Knowledge Pipeline
# Terminal control panel. Run: .\pipeline.ps1 or .\pipeline.bat

$ErrorActionPreference = "Continue"
$projectRoot = $PSScriptRoot
Set-Location $projectRoot

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
            Label = "Path to Google service account JSON file"
            Link = "https://console.cloud.google.com/iam-admin/serviceaccounts"
            Default = "config/service_account.json"
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
    $py = python --version 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Ok "$py" }
    else { Write-Fail "Python not found. Install Python 3.10+"; return }

    Write-Step "2/5" "Installing packages"
    $reqFile = Join-Path $projectRoot "requirements.txt"
    $pkgs = Get-Content $reqFile | Where-Object { $_ -and ($_ -notmatch "^#") }
    $total = $pkgs.Count
    $i = 0

    foreach ($pkg in $pkgs) {
        $i++
        $name = ($pkg -split "==|>=|<=|~=")[0].Trim()
        if (-not $name) { continue }
        $pct = [math]::Round(($i / $total) * 100)
        Write-Host "`r  [$i/$total] $pct%  $name                    " -NoNewline -ForegroundColor DarkGray
        python -m pip install "$pkg" --quiet 2>&1 | Out-Null
    }
    Write-Host ""
    Write-Ok "$total packages installed"

    Write-Step "3/5" "Configuring environment"
    Ensure-Env

    Write-Step "4/5" "Resolving channel IDs"
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path $envPath) {
        $content = Get-Content $envPath -Raw
        if ($content -match "YOUTUBE_API_KEY=.{10,}") {
            python resolve_channels.py
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
    $oll = ollama list 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Ollama is running"
        $oll | ForEach-Object { Write-Host "       $_" -ForegroundColor DarkGray }
    }
    else {
        Write-Fail "Ollama not reachable. Start it: ollama serve"
    }

    Write-Host ""
    Write-Host "  Setup complete." -ForegroundColor Green
    Write-Host ""
}

function Run-Full {
    Write-Header "Full Pipeline"
    Ensure-Env
    python -m src.main
}

function Run-Fast {
    Write-Header "Ollama Only"
    Ensure-Env
    python -m src.main --skip-nvidia
}

function Run-Test {
    Write-Header "Test Run (3 videos, no Sheets)"
    Ensure-Env
    python -m src.main --skip-nvidia --skip-sheets --max-videos 3
}

function Run-Resolve {
    Write-Header "Resolve Channel IDs"
    Ensure-Env
    python resolve_channels.py
}

function Run-Channels {
    Write-Header "Channels"
    python manage_channels.py list
}

function Run-Health {
    Write-Header "Health Check"

    Write-Step "1" "Ollama"
    $oll = ollama list 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Ok "Running" }
    else { Write-Fail "Not running" }

    Write-Step "2" "Python packages"
    $check = python -c "import ollama, gspread, yaml, openai, loguru; print('ok')" 2>&1
    if ("$check".Trim() -eq "ok") { Write-Ok "All installed" }
    else { Write-Fail "Missing: $check" }

    Write-Step "3" "Environment"
    $envPath = Join-Path $projectRoot ".env"
    if (Test-Path $envPath) {
        $c = Get-Content $envPath -Raw
        if ($c -match "YOUTUBE_API_KEY=.{10,}") { Write-Ok "YOUTUBE_API_KEY" } else { Write-Info "YOUTUBE_API_KEY not set" }
        if ($c -match "NVIDIA_API_KEY=.{10,}") { Write-Ok "NVIDIA_API_KEY" } else { Write-Info "NVIDIA_API_KEY not set" }
        if ($c -match "GOOGLE_SHEETS_SPREADSHEET_ID=.{10,}") { Write-Ok "GOOGLE_SHEETS" } else { Write-Info "GOOGLE_SHEETS not set" }
    }
    else {
        Write-Fail ".env missing. Run setup first."
    }

    Write-Step "4" "Channel IDs"
    $yc = Get-Content "config\channels.yaml" -Raw
    $empty = ([regex]::Matches($yc, 'channel_id: ""')).Count
    if ($empty -gt 0) { Write-Info "$empty channels need IDs (run option 5)" }
    else { Write-Ok "All channel IDs configured" }
}

function Run-Single {
    Write-Header "Single Channel"
    python manage_channels.py list
    Write-Host ""
    $name = Read-Host "  Channel name"
    if ($name) {
        Ensure-Env
        python -m src.main --channels "$name" --skip-nvidia
    }
}

function Run-Recent {
    Write-Header "Recent Videos (Last 30 Days)"
    Ensure-Env
    $since = (Get-Date).AddDays(-30).ToString("yyyy-MM-dd")
    Write-Host "  Since: $since" -ForegroundColor DarkGray
    python -m src.main --since $since --skip-nvidia
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
