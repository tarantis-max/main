# MU — Softdocs → Ellucian DataConnect relay (Azure Function)

A tiny serverless relay that sits between **Softdocs Etrieve** and an
**Ellucian DataConnect HTTP-triggered pipeline** and fixes the one thing
Etrieve's HTTP step can't: the `Content-Type` header.

```
Softdocs Etrieve Flow ──POST──▶ Azure Function ──POST──▶ DataConnect pipeline
     (text/plain or                 relay                (requires application/json)
      form-encoded)
```

What the relay does on every call:

1. **Rewrites `Content-Type`** to `OVERRIDE_CONTENT_TYPE` (default
   `application/json`) — the body bytes are forwarded untouched.
2. **Handles Ethos auth**: exchanges your DataConnect application's API key
   for a JWT at `https://integrate.elluciancloud.com/auth` and attaches it as
   `Authorization: Bearer <jwt>`, caching the token until just before expiry.
   Softdocs never sees the Ethos key; the Ethos key never leaves Azure.
3. Forwards the method and query string (minus the Azure `code` key), and
   returns the pipeline's status and body to Softdocs unchanged.

## Files

```
azure-relay/
  host.json                      Functions host config
  package.json                   Node 20, @azure/functions v4
  src/functions/relay.js         the relay (single file)
  local.settings.sample.json     local-dev settings template
  test/relay.test.js             offline tests (node test/relay.test.js)
```

## Deploy (one-time, ~10 minutes)

**1. Create the Function App** (portal: Create resource → Function App):
- Hosting: **Consumption** (serverless — pennies/month for this traffic)
- Runtime stack: **Node.js 20**, OS: Windows or Linux (either works)
- Name it e.g. `mu-softdocs-relay`

**2. Add application settings** (Function App → Settings → Environment
variables):

| Setting | Value |
|---|---|
| `TARGET_URL` | `https://integrate.elluciancloud.com/api/<pipeline-api-name>` — the API name shown on the pipeline's HTTP trigger in DataConnect |
| `ETHOS_API_KEY` | API key of the Ethos **application** the pipeline is published under (Ethos Integration → Applications) |
| `OVERRIDE_CONTENT_TYPE` | `application/json` (default; set only to change it) |
| `EXTRA_HEADERS` | optional JSON, e.g. `{"Accept":"application/json"}` |
| `FORWARD_HEADERS` | optional comma-separated inbound headers to pass through |

For production hygiene, store `ETHOS_API_KEY` as a Key Vault reference
(`@Microsoft.KeyVault(SecretUri=...)`) instead of a plain setting.

**3. Publish the code.** From this folder, either:

```bash
# Azure Functions Core Tools
func azure functionapp publish mu-softdocs-relay

# or zip deploy with the Azure CLI
zip -r relay.zip host.json package.json src
az functionapp deployment source config-zip -g <resource-group> -n mu-softdocs-relay --src relay.zip
```

(VS Code's Azure Functions extension → "Deploy to Function App…" also works.)

**4. Get the function URL + key**: Function App → Functions → `relay` →
*Get function URL*. It looks like:

```
https://mu-softdocs-relay.azurewebsites.net/api/relay?code=<function-key>
```

## Point Softdocs at it

In Etrieve Flow, configure the HTTP/integration step to POST to the function
URL above (the `code=` key is the shared secret — treat it like a password).
Whatever Content-Type Etrieve declares, the pipeline receives
`application/json`. Query parameters are passed through, so
`...&studentId=123` reaches the pipeline as `?studentId=123`.

## Test it

```bash
# offline unit tests (no Azure, no network)
node test/relay.test.js

# end-to-end once deployed — note the "wrong" content type on purpose:
curl -X POST "https://mu-softdocs-relay.azurewebsites.net/api/relay?code=<key>" \
     -H "Content-Type: text/plain" \
     -d '{"documentId": 42}'
```

A `200`/`202` back means DataConnect accepted the payload. The function's
**Monitor** tab (Application Insights) logs every call as
`Content-Type: text/plain → application/json` plus the upstream status, which
makes mismatches easy to spot.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `401` from the relay itself | Missing/wrong `code=` function key on the Softdocs side |
| `502 Ethos auth failed (401)` | `ETHOS_API_KEY` wrong, or the application isn't subscribed to the pipeline's API |
| `404` from upstream | `TARGET_URL` pipeline API name doesn't match the HTTP trigger's api name |
| `415`/`400` from upstream | Pipeline expects a different type — set `OVERRIDE_CONTENT_TYPE` to match |
