# ITS Change Advisor - launch guide

An AI agent that runs in the Claude Console (Anthropic Managed Agents) and
reviews ITS change requests before CAB. On each run it finds changes in
**Review, Planning, or Authorize**, checks them for completeness, risk,
history, and scheduling conflicts, and posts an **internal** advisory note.
It never approves, edits, or transitions anything.

Total setup time: about an hour, most of it in steps 1 and 7.

## What's in this folder

| File | What it is |
|---|---|
| `agents/its-change-advisor.md` | The agent: model, tools, and its instructions (the text below the `---` block) |
| `environments/its-change-advisor.yaml` | Its sandbox: can reach `methodist.atlassian.net` and nothing else |
| `vaults/its-jira.yaml` | The vault that holds the Jira credential (the credential itself is never in the repo) |
| `deployments/its-change-advisor-hourly.md` | The schedule: hourly, 8am-5pm Eastern, weekdays |
| `make-jira-auth.ps1` | Encodes the Jira credential on your PC and copies it to the clipboard |

## 0. Before you start

- An Anthropic Console organization (platform.claude.com) with Managed Agents
  available, and a workspace you're a Developer or Admin in.
- Confirm that using the Claude API/Console with ITS change data is covered
  under MU Policy 100.15 (AI Governance). If it isn't yet, open an AI
  Governance review through the IT Help Desk. The agent only needs change
  metadata, and its instructions forbid handling Restricted data, but the
  change text is sent to Anthropic.

## 1. Create the Jira service account

In Atlassian admin, create a user named **ITS Change Advisor**
(for example `its-change-advisor@methodist.edu`):

- **Give it a JSM agent license on ITS.** Only agents can post *internal*
  comments, and the advisor's notes must stay hidden from requesters.
- **Grant the least access your ITS permission scheme allows for that:**
  browse the project and add comments. If your scheme's agent role also
  grants Edit or Transition, the agent's instructions are the only thing
  stopping those, so tighten the role if you can.
- **Do not** add it to any approver group, CAB group, or the Approvers field.
  That keeps Jira itself from letting it approve a change, whatever happens.

Then sign in as that account and create an API token at
id.atlassian.com → Security → API tokens.

## 2. Encode the credential

On your PC, from this folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\make-jira-auth.ps1
```

Enter the service account's email and API token. The script copies the
encoded value to your clipboard; nothing is saved.

## 3. Create the environment (Console)

Console → **Managed Agents → Environments → Create**:

- Name: `its-change-advisor`
- Type: Cloud
- Networking: **Limited**, allowed host `methodist.atlassian.net`,
  package managers **off**, MCP servers **off**

## 4. Create the vault and credential (Console)

Console → **Managed Agents → Vaults → Create** → name `ITS Jira (Change Advisor)`.
Then **Add credential**:

- Type: **Environment variable**
- Name: `JIRA_BASIC_AUTH` (exactly this)
- Value: paste from step 2
- Allowed hosts: `methodist.atlassian.net`
- Injection: header only (the Console default)

## 5. Create the agent (Console)

Console → **Managed Agents → Agents → Create**:

- Name: `ITS Change Advisor`
- Model: Claude Opus 5.5, effort **High**
- System prompt: paste everything in `agents/its-change-advisor.md` **below**
  the closing `---` line
- Tools: agent toolset on, **web search off, web fetch off**

## 6. Test it on one change

Console → **Sessions → New session** with the agent, the environment, and the
vault. Send:

> Review only ITS-7902 and post your note. Do not review any other change.

Watch it in the session viewer. Then open
https://methodist.atlassian.net/browse/ITS-7902 and check that:

- the note is there and marked **Internal**, not visible to the requester
- it starts with `[ITS Change Advisor - advisory, not a CAB decision]`
- what it says about missing plans and risk is right

Repeat with ITS-7833. If anything is off, edit the system prompt (the agent
gets a new version) and test again. The session viewer also shows each run's
token cost.

## 7. Fill in the real blackout dates

The agent's instructions include a **provisional** list of blackout windows
(add/drop, registration, aid disbursement, finals, commencement, fiscal
year-end). Replace it with this year's actual dates from the academic and
financial aid calendars, then update the agent.

## 8. Turn on the schedule

Console → **Managed Agents → Deployments → Create**:

- Agent, environment, and vault from above
- Schedule: `0 8-17 * * 1-5`, time zone `America/New_York`
  (every hour, 8am-5pm, weekdays)
- Starting message: the text at the bottom of
  `deployments/its-change-advisor-hourly.md`

Use **Run now** once to confirm a scheduled run works. Each run skips changes
that nobody has touched since the advisor's last note, so most runs are quick.

## Alternative: command line instead of the Console (macOS / Linux / WSL)

With the `ant` CLI (1.34.0+) signed in to the same workspace:

```sh
cd change-advisor
ant apply --dry-run -v agents/its-change-advisor.md environments/its-change-advisor.yaml vaults/its-jira.yaml
ant apply agents/its-change-advisor.md environments/its-change-advisor.yaml vaults/its-jira.yaml
```

Then add the `JIRA_BASIC_AUTH` credential to the vault in the Console
(step 4), run the test (step 6), put the vault ID from `claude-lock.json`
into the deployment file in place of `vlt_REPLACE_ME`, and apply it:

```sh
ant apply deployments/its-change-advisor-hourly.md
```

Commit `claude-lock.json` so later `ant apply` runs update these resources
instead of creating duplicates.

## Day-to-day

- **Pause it:** Console → Deployments → Pause.
- **Change its behavior:** edit the system prompt and save (new version).
- **Audit:** every run's transcript, Jira calls, and cost are in Console →
  Managed Agents → Sessions.
- **After 2-4 weeks:** compare its readiness and risk calls with CAB's actual
  decisions. If they hold up, move on to phase 2 (auto-route Standard
  changes, assign approvers).
