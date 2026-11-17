---
# Apply this file only after the first manual test run looks right (LAUNCH.md, step 6).
# Replace vlt_REPLACE_ME with the vault ID from claude-lock.json first.
name: ITS Change Advisor - weekday hourly
agent: ../agents/its-change-advisor.md
environment_id: ../environments/its-change-advisor.yaml
vault_ids:
  - vlt_REPLACE_ME
schedule:
  type: cron
  expression: "0 8-17 * * 1-5"
  timezone: America/New_York
---

Review the ITS change requests that are waiting for review or authorization, following your instructions, and post your advisory notes.
