#!/usr/bin/env node
/**
 * MU VPMO Dashboard — Jira custom field setup
 * --------------------------------------------
 * Two modes, both write dashboard/vpmo-fields.json (auto-loaded by server.js):
 *
 * 1) CREATE (company-managed projects):
 *      node setup-jira-fields.js
 *    Creates the VPMO fields as global custom fields. Note: global fields
 *    CANNOT be used by team-managed ("simplified") projects like ITPM.
 *
 * 2) MAP (team-managed projects — recommended for ITPM):
 *      node setup-jira-fields.js --map ITPM
 *    Team-managed projects only use fields created inside the project
 *    (Project settings → Issue types → drag a field onto each type — see
 *    the field list this script prints). The API can't create those, but
 *    this mode DISCOVERS them by name and maps their IDs so the dashboard
 *    reads/writes the real fields instead of falling back to labels.
 *
 * Env (both modes):
 *   export JIRA_BASE_URL="https://methodist.atlassian.net"
 *   export JIRA_EMAIL="jgreene@methodist.edu"
 *   export JIRA_TOKEN="<your Atlassian API token>"
 *
 * Safe to re-run — create mode skips existing fields, map mode just
 * refreshes the mapping. Restart server.js afterwards to apply.
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
  // ---- Change-request specific fields ------------------------------------
  {
    key:          "crType",
    name:         "VPMO CR Type",
    description:  "ITIL change type (Standard / Normal / Emergency)",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:select",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
    fieldType:    "select",
    options:      ["Standard", "Normal", "Emergency"],
  },
  {
    key:          "crImpact",
    name:         "VPMO CR Impact",
    description:  "Expected impact if the change is implemented (Low / Medium / High)",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:select",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher",
    fieldType:    "select",
    options:      ["Low", "Medium", "High"],
  },
  {
    key:          "crAffectedSystems",
    name:         "VPMO Affected Systems",
    description:  "Systems, services, or environments affected by this change",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    fieldType:    "text",
  },
  {
    key:          "crRollbackPlan",
    name:         "VPMO Rollback Plan",
    description:  "Steps to revert the change if something goes wrong",
    type:         "com.atlassian.jira.plugin.system.customfieldtypes:textfield",
    searcherKey:  "com.atlassian.jira.plugin.system.customfieldtypes:textsearcher",
    fieldType:    "text",
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

/* ---- Map mode: discover a project's real fields by name ------------------ */
// Accepted field names per VPMO key (matched case-insensitively). The first
// name is what we suggest you create in Project settings → Issue types.
const NAME_CANDIDATES = {
  risk:              ["Risk", "VPMO Risk Status", "Risk Status", "Risk Level"],
  portfolio:         ["Portfolio", "VPMO Portfolio"],
  compliance:        ["Compliance Driver", "VPMO Compliance Driver", "Compliance"],
  sponsor:           ["Business Sponsor", "VPMO Business Sponsor", "Sponsor"],
  projectId:         ["Project ID", "VPMO Project ID"],
  pctComplete:       ["% Complete", "VPMO % Complete", "Percent Complete"],
  crType:            ["Change Type", "VPMO CR Type", "CR Type"],
  crImpact:          ["CR Impact", "VPMO CR Impact"],
  crAffectedSystems: ["Affected Systems", "VPMO Affected Systems"],
  crRollbackPlan:    ["Rollback Plan", "VPMO Rollback Plan"],
};
// What to create in the project UI when a key has no match
const UI_FIELD_HINT = {
  risk:              "Dropdown — options: Green, Yellow, Red",
  portfolio:         "Short text",
  compliance:        "Short text",
  sponsor:           "Short text",
  projectId:         "Short text",
  pctComplete:       "Number",
  crType:            "Dropdown — options: Standard, Normal, Emergency",
  crImpact:          "Dropdown — options: Low, Medium, High",
  crAffectedSystems: "Short text",
  crRollbackPlan:    "Paragraph or short text",
};

function fieldTypeFromSchema(schema) {
  const custom = (schema && schema.custom) || "";
  if (/:(select|radiobuttons|jwm-category)$/.test(custom)) return "select";
  if ((schema && schema.type) === "number" || /:float$/.test(custom)) return "number";
  return "text";
}

// Union of every field available on any of the project's issue types,
// via the create-meta API (works for team- and company-managed projects).
async function projectFields(projectKey) {
  const typesResp = await jira("GET", `/issue/createmeta/${encodeURIComponent(projectKey)}/issuetypes?maxResults=200`);
  const types = typesResp.issueTypes || typesResp.values || [];
  if (!types.length) throw new Error(`No issue types found for project "${projectKey}" — check the key and your permissions.`);
  const byId = {};
  for (const t of types) {
    let startAt = 0;
    for (;;) {
      const page = await jira("GET", `/issue/createmeta/${encodeURIComponent(projectKey)}/issuetypes/${t.id}?startAt=${startAt}&maxResults=200`);
      const fields = page.fields || page.values || [];
      for (const f of fields) byId[f.fieldId || f.key] = f;
      if (fields.length < 200) break;
      startAt += fields.length;
    }
  }
  return Object.values(byId);
}

async function mapMode(projectKey) {
  console.log(`\n  MU VPMO — map existing fields in project ${projectKey}`);
  console.log(`  Instance: ${CONFIG.baseUrl}\n`);

  const fields = await projectFields(projectKey);
  const customs = fields.filter(f => /^customfield_/.test(f.fieldId || f.key || ""));
  console.log(`  Found ${customs.length} custom field(s) available on ${projectKey}.\n`);

  const ids = {}, fieldTypes = {}, missing = [];
  for (const [key, names] of Object.entries(NAME_CANDIDATES)) {
    const hit = names.map(n => n.toLowerCase())
      .map(n => customs.find(f => (f.name || "").toLowerCase() === n))
      .find(Boolean);
    if (hit) {
      ids[key] = hit.fieldId || hit.key;
      fieldTypes[key] = fieldTypeFromSchema(hit.schema);
      console.log(`  ✓  ${key.padEnd(18)} → "${hit.name}"  (${ids[key]}, ${fieldTypes[key]})`);
    } else {
      missing.push(key);
    }
  }

  if (!Object.keys(ids).length) {
    console.log(`  No matching fields found — nothing written.\n`);
  } else {
    const outPath = path.join(__dirname, "vpmo-fields.json");
    fs.writeFileSync(outPath, JSON.stringify({ ids, fieldTypes }, null, 2) + "\n");
    console.log(`\n  Wrote ${outPath} — restart server.js to apply.`);
    console.log(`  The dashboard will now read/write these real fields (labels remain a fallback).`);
  }

  if (missing.length) {
    console.log(`\n  Not found (still stored as labels): ${missing.join(", ")}`);
    console.log(`  To use real fields for these, open Jira → ${projectKey} → Project settings`);
    console.log(`  → Issue types, add the field to EACH issue type, then re-run this command:\n`);
    for (const k of missing) console.log(`    • "${NAME_CANDIDATES[k][0]}"  —  ${UI_FIELD_HINT[k]}`);
    console.log();
  }
}

/* ---- Main ---------------------------------------------------------------- */
async function main() {
  if (!CONFIG.email || !CONFIG.token) {
    console.error("\n  Error: set JIRA_EMAIL and JIRA_TOKEN before running this script.\n");
    process.exit(1);
  }

  const mapIdx = process.argv.indexOf("--map");
  if (mapIdx !== -1) {
    const projectKey = process.argv[mapIdx + 1];
    if (!projectKey) { console.error("\n  Error: --map needs a project key, e.g.  --map ITPM\n"); process.exit(1); }
    return mapMode(projectKey.toUpperCase());
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
  console.log("  NOTE: global fields don't apply to team-managed projects (like ITPM).");
  console.log("  For those, create the fields in Project settings → Issue types, then run:");
  console.log("    node setup-jira-fields.js --map ITPM");
  console.log();
}

main().catch(e => { console.error("\n  Error:", e.message); process.exit(1); });
