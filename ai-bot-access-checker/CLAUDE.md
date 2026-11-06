# AI Access & Readiness app: operating guide for Claude Code

You are helping a university web/marketing lead (not a developer) run and maintain this app on their own computer
(usually Windows) or on a VM. Keep answers short and definite. Do the steps yourself; explain only what they must decide.

## What the app is
Python 3.12+, standard library only. Measures how ready methodist.edu is for AI search and answers.
- `app.py`: local web app on 127.0.0.1 (tabs: Page Check, Findability, Bot Access, Site Readiness, Competitors, AI Answers, Ask the AIs).
- `runall.py`: every check in one go; saves `results/<date-time>/` with the results bundle (.zip) and executive report.
- `findability.py`: clicks from a start page to key facts. `pagescan.py`: one page.
- `agent.py`: monthly job. Runs everything, then Claude reviews the results against the live site and emails a fix list.
- README.md has the details; read it before changing behavior.

## Commands (on Windows use `python`, not `python3`)
- Update to the newest version: `python agent.py --update` (needs a Git copy; if it says "not a Git copy", run `windows-setup.cmd` once from the old folder).
- Check the version: `findstr VERSION bundle.py` (Windows) or `grep VERSION bundle.py`.
- Review the newest results without new checks: `python agent.py --review --dry-run`.
- Full monthly run: `python agent.py` (several hours; `--skip answers` skips the AI answer test; `--dry-run` sends nothing).
- Open the app: `python app.py`.

## Settings and secrets
- `agent.json` (email_to, email_from, smtp_host, smtp_port, smtp_user, findability start pages, model, min_checks), `runall.json`, `keys.json`: all on this computer only, all gitignored.
- API keys live in `keys.json` (the app's Keys box) or environment variables: ANTHROPIC_API_KEY, OPENAI_API_KEY, PERPLEXITY_API_KEY, GEMINI_API_KEY; mail password AGENT_SMTP_PASSWORD; Teams AGENT_TEAMS_WEBHOOK.
- Never print, log, copy into chat, or commit a key or password. Check presence only. Ask the person to type secrets into the file or their own terminal.

## Scheduling (Windows)
Monthly, 1st of the month, 6:17 a.m. Replace the folder with the real app folder:
`schtasks /Create /TN "AI Readiness Agent" /SC MONTHLY /D 1 /ST 06:17 /TR "cmd /c cd /d \"<app folder>\" && python agent.py >> agent.log 2>&1"`
The PC must be on and the person logged in. Check `agent.log` after the first run.

## Before reporting results to the person
The checks match word patterns, so self-check every finding before you repeat it:
- Open the page and confirm it. Typical false matches: a number about something else (salary, 1970s history, national statistics),
  text in menus or the footer, a page about a different program, raw HTML or code read as text.
- Keep the meaning: broken is not missing; outdated is not wrong.
- Give the page that has the problem, not a page that redirects.
Do not change the website. Do not send anything to other people; draft it for the person to send.

## Changing the code
Only when the person asks. Keep standard library only. Bump `VERSION` in `bundle.py`, update README.md, test on local mock pages
(the live site can rate-limit), then commit and push to the branch this copy tracks so `--update` delivers it.
