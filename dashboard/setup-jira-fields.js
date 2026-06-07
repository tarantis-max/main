#!/usr/bin/env node
/**
 * MU VPMO Dashboard — Jira custom field setup
 * --------------------------------------------
 * Run once to create the six VPMO custom fields in your Jira instance and
 * record their IDs in vpmo-fields.json (auto-loaded by server.js).
 *
 * Usage (any platform):
 *   export JIRA_BASE_URL="https://methodist.atlassian.net"
 *   export JIRA_EMAIL="jgreene@methodist.edu"
 *   export JIRA_TOKEN="<your Atlassian API token>"
 *   node dashboard/setup-jira-fields.js
 *
 * Windows (from the dashboard folder):
 *   $env:JIRA_BASE_URL="https://methodist.atlassian.net"
 *   $env:JIRA_EMAIL="jgreene@methodist.edu"
 *   $env:JIRA_TOKEN="<token>"
 *   node setup-jira-fields.js
 *
 * The script is safe to re-run — it skips fields that already exist.
 * On success it writes dashboard/vpmo-fields.json; restart server.js to apply.
 */
"use strict";

const fs   = require("fs");
const path = require("path");

const CONFIG = {
  baseUrl: (process.env.JIRA_BASE_URL || "https://methodist.atlassian.net").replace(/\/$/, ""),
  email:   process.env.JIRA_EMAIL  || "",
  token:   process.env.JIRA_TOKEN  || "",
};

function auth() {
  return "Basic " + Buffer.from(`${CONFIG.email}:${CONFIG.token}`).toString("base64");
}

async function jira(method, endpoint, body) {
  const r = await fetch(`${CONFIG.baseUrl}/rest/api/3${endpoint}`, {
    method,
    headers: {
      Authorization: auth(),
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`Jira ${r.status} ${method} ${endpoint}:\n  ${text.slice(0, 400)}`);
  return text ? JSON.parse(text) : null;
}

/* ---- Field definitions --------------------------------------------------- */
// These match the spreadsheet columns that have no proper Jira equivalent.
// Risk uses a select so the three values stay consistent; the rest use text/number
// so the dashboard can write any value without hitting "option not found" errors.
const WANTED = [
  {
    key:          "risk",
    name:         "VPMO Risk Status",
    description:  "Red/Amber/Green project health indicator (Green | Yellow | Red)",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:select",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
    fieldType:    "select",
    options:      ["Green", "Yellow", "Red"],
  },
  {
    key:          "portfolio",
    name:         "VPMO Portfolio",
    description:  "Program portfolio (e.g. Colleague SaaS, Infrastructure, Security & Compliance)",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    fieldType:    "text",
  },
  {
    key:          "compliance",
    name:         "VPMO Compliance Driver",
    description:  "Regulatory/compliance driver (FERPA, GLBA, HIPAA, PCI — semicolon-separated)",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    fieldType:    "text",
  },
  {
    key:          "sponsor",
    name:         "VPMO Business Sponsor",
    description:  "Business sponsor name for the project",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    fieldType:    "text",
  },
  {
    key:          "projectId",
    name:         "VPMO Project ID",
    description:  "Unique program plan identifier (e.g. P-001)",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    fieldType:    "text",
  },
  {
    key:          "pctComplete",
    name:         "VPMO % Complete",
    description:  "Manual percentage complete (0–100). Used when sub-task rollup is not available.",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:float",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:exactnumber",
    fieldType:    "number",
  },
];

/* ---- Helpers ------------------------------------------------------------- */
async function ensureField(spec, byName) {
  const existing = byName[spec.name.toLowerCase()];
  if (existing) {
    console.log(`  ✓  [exists]   ${spec.name.padEnd(30)}  →  ${existing.id}`);
    return { id: existing.id, fieldType: spec.fieldType };
  }

  process.stdout.write(`  +  [creating] ${spec.name.padEnd(30)}  …  `);
  const created = await jira("POST", "/field", {
    name: spec.name,
    description: spec.description || "",
    type: spec.type,
    searcherKey: spec.searcherKey,
  });
  const fieldId = created.id;
  console.log(fieldId);

  if (spec.options && spec.options.length) {
    // Fetch the auto-created default context so we can add options to it
    const ctxResp = await jira("GET", `/field/${fieldId}/context`);
    const ctxId   = ctxResp.values && ctxResp.values[0] && ctxResp.values[0].id;
    if (ctxId) {
      await jira("POST", `/field/${fieldId}/context/${ctxId}/option`, {
        options: spec.options.map(v => ({ value: v })),
      });
      console.log(`       options: ${spec.options.join(", ")}`);
    } else {
      console.warn(`       warning: no context found, options not added — add them manually`);
    }
  }

  return { id: fieldId, fieldType: spec.fieldType };
}

/* ---- Main ---------------------------------------------------------------- */
async function main() {
  if (!CONFIG.email || !CONFIG.token) {
    console.error("\n  Error: set JIRA_EMAIL and JIRA_TOKEN before running this script.\n");
    process.exit(1);
  }

  console.log(`\n  MU VPMO — Jira custom field setup`);
  console.log(`  Instance: ${CONFIG.baseUrl}\n`);

  const allFields = await jira("GET", "/field");
  const byName    = {};
  for (const f of allFields) byName[f.name.toLowerCase()] = f;

  const ids       = {};    // key → customfield_XXXXX
  const fieldTypes = {};   // key → "select"|"text"|"number"

  for (const spec of WANTED) {
    const { id, fieldType } = await ensureField(spec, byName);
    ids[spec.key]        = id;
    fieldTypes[spec.key] = fieldType;
  }

  // Write vpmo-fields.json (server.js loads this at startup)
  const outPath = path.join(__dirname, "vpmo-fields.json");
  fs.writeFileSync(outPath, JSON.stringify({ ids, fieldTypes }, null, 2) + "\n");

  console.log(`\n  Wrote ${outPath}`);
  console.log("  Restart server.js to pick up the new fields.\n");

  console.log("  Field summary:");
  const pad = Math.max(...Object.keys(ids).map(k => k.length));
  for (const [k, id] of Object.entries(ids)) {
    console.log(`    ${k.padEnd(pad)}  ${id}  (${fieldTypes[k]})`);
  }
  console.log();
}

main().catch(e => { console.error("\n  Error:", e.message); process.exit(1); });
