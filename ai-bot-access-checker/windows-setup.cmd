@echo off
setlocal
rem One-time setup for Windows. Makes an updatable copy of the AI Readiness app (a Git copy) and moves your
rem keys, settings and results into it. Run it from your current app folder: the one with keys.json and results.
rem After this, "python agent.py --update" gets new versions. Nothing is uploaded; your keys stay on this computer.

set "OLD=%~dp0"
set "NEW=%USERPROFILE%\AI_Ready_app"
set "REPO=https://github.com/tarantis-max/main"
set "BRANCH=claude/kind-maxwell-1gtch5"

where git >nul 2>nul
if errorlevel 1 (
  echo Installing Git...
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
  set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
)
where git >nul 2>nul
if errorlevel 1 (
  echo Git could not be installed. Install it from git-scm.com, then run this again.
  exit /b 1
)

if exist "%NEW%\.git" (
  echo Updating the copy in %NEW%
  git -C "%NEW%" pull -q --ff-only
) else (
  echo Downloading the app to %NEW% - a GitHub sign-in window may open.
  git clone -q -b %BRANCH% %REPO% "%NEW%"
  if errorlevel 1 (
    echo The download failed. Sign in to GitHub with an account that can see %REPO%, then run this again.
    exit /b 1
  )
)

set "APP=%NEW%\ai-bot-access-checker"
for %%F in (keys.json agent.json runall.json ask-history.jsonl) do (
  if exist "%OLD%%%F" if not exist "%APP%\%%F" (
    copy /y "%OLD%%%F" "%APP%\" >nul
    echo Copied %%F
  )
)
if exist "%OLD%results" (
  robocopy "%OLD%results" "%APP%\results" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
  echo Copied the results folder
)

echo.
echo Done. The app is now in: %APP%
echo   cd /d "%APP%"
echo   python agent.py --update      gets the newest version
echo   python app.py                 opens the app
echo   python agent.py --review --dry-run
echo Your old folder is unchanged. Delete it once the new one works.
echo If you scheduled the monthly run, recreate it with the new folder.
endlocal
