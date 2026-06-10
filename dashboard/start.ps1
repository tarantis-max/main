# ============================================================
#  MU VPMO Dashboard - launcher (Windows)
#  Stores the Jira API token encrypted with Windows DPAPI:
#  only your Windows user account on this PC can decrypt it.
# ============================================================
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

# --- non-sensitive defaults (edit if needed) ---
$env:JIRA_BASE_URL = 'https://methodist.atlassian.net'
$env:JIRA_EMAIL    = 'jgreene@methodist.edu'
$env:JIRA_PROJECT  = 'ITPM'
$port              = 8787
$env:PORT          = "$port"

# --- check Node ---
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Host ''
  Write-Host '  [!] Node.js is not installed or not on your PATH.' -ForegroundColor Yellow
  Write-Host '      Get the LTS installer from https://nodejs.org , then run this again.'
  Read-Host '  Press Enter to exit' | Out-Null
  exit 1
}

$tokenFile = Join-Path $PSScriptRoot 'jira-token.dat'
$token = $null

# --- try to load + decrypt a saved token ---
if (Test-Path $tokenFile) {
  try {
    $secure = (Get-Content $tokenFile -Raw).Trim() | ConvertTo-SecureString   # DPAPI, current user
    $token  = [System.Net.NetworkCredential]::new('', $secure).Password
    Write-Host '  Loaded saved token (decrypted for your Windows account).' -ForegroundColor DarkGray
  } catch {
    Write-Host '  [!] Could not decrypt saved token (different user or PC?). Please re-enter it.' -ForegroundColor Yellow
    $token = $null
  }
}

# --- otherwise prompt, then offer to save encrypted ---
if (-not $token) {
  Write-Host ''
  Write-Host '  Enter your Atlassian API token.'
  Write-Host '  Create one at https://id.atlassian.com/manage-profile/security/api-tokens'
  Write-Host ''
  $secure = Read-Host '  API token' -AsSecureString
  $token  = [System.Net.NetworkCredential]::new('', $secure).Password
  if ($token) {
    $save = Read-Host "  Save it (encrypted) so you don't have to paste it next time? (y/n)"
    if ($save -eq 'y') {
      $secure | ConvertFrom-SecureString | Set-Content -Path $tokenFile -Encoding Ascii
      Write-Host '  Saved DPAPI-encrypted to jira-token.dat (only your account on this PC can read it).' -ForegroundColor DarkGray
    }
  }
}

if ($token) {
  $env:JIRA_TOKEN = $token
} else {
  Write-Host '  [!] No token - "Load from Jira" will not work, but the dashboard opens with built-in data.' -ForegroundColor Yellow
}

# --- build the React front end (app/) on first run -------------------
# server.js serves app/dist when it exists; otherwise it falls back to the
# legacy single-file dashboard, so a failed/skipped build is never fatal.
$appDir  = Join-Path (Split-Path $PSScriptRoot -Parent) 'app'
$distIdx = Join-Path $appDir 'dist\index.html'
if ((Test-Path (Join-Path $appDir 'package.json')) -and -not (Test-Path $distIdx)) {
  if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host '  Building the web app (first run only, takes a minute)...' -ForegroundColor DarkGray
    Push-Location $appDir
    try {
      npm install --no-audit --no-fund | Out-Null
      npm run build | Out-Null
      Write-Host '  Web app built.' -ForegroundColor DarkGray
    } catch {
      Write-Host '  [!] Web app build failed - falling back to the legacy dashboard.' -ForegroundColor Yellow
    }
    Pop-Location
  } else {
    Write-Host '  [!] npm not found - serving the legacy dashboard. Install Node LTS to get the full app.' -ForegroundColor Yellow
  }
}

Write-Host ''
Write-Host "  Starting dashboard at http://localhost:$port"
Write-Host '  (Close this window or press Ctrl+C to stop.)'
Write-Host ''

# open the browser shortly after the server boots
Start-Process powershell -WindowStyle Hidden -ArgumentList @(
  '-NoProfile','-Command',"Start-Sleep -Seconds 2; Start-Process 'http://localhost:$port'"
) | Out-Null

# run the server (blocks until closed)
node server.js

Write-Host ''
Write-Host '  Server stopped.'
Read-Host '  Press Enter to exit' | Out-Null
