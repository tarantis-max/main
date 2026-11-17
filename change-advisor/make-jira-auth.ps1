# ============================================================
#  ITS Change Advisor - encode the Jira credential for the vault
#  Prompts for the service account's email and API token, builds
#  the value Jira expects for Basic auth (base64 of email:token),
#  and copies it to the clipboard. Nothing is written to disk.
# ============================================================
$ErrorActionPreference = 'Stop'

$email = Read-Host '  Service account email (e.g. its-change-advisor@methodist.edu)'
$secure = Read-Host '  API token for that account' -AsSecureString
$token = [System.Net.NetworkCredential]::new('', $secure).Password
if (-not $email -or -not $token) { Write-Host '  Email and token are both required.' -ForegroundColor Yellow; exit 1 }

$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${email}:${token}"))
Set-Clipboard -Value $encoded
$token = $null; $encoded = $null

Write-Host ''
Write-Host '  Copied to clipboard. Paste it as the value of the JIRA_BASIC_AUTH' -ForegroundColor Green
Write-Host '  credential in the Claude Console vault (LAUNCH.md, step 4),'
Write-Host '  then copy something else to clear the clipboard.'
