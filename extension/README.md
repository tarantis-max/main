# MU Parking Permit Payment — Experience Extension Card

A custom Experience card that lets a student pay their vehicle permit fee on
Authorize.net's hosted payment page, backed by the two Data Connect serverless
APIs in the repo root:

| Pipeline | Called when |
|---|---|
| `MU_ParkingPermit_GetPaymentToken` | Student clicks **Pay with card** — returns the Accept Hosted form token + URL |
| `MU_ParkingPermit_VerifyPayment` | Card polls (and on **Verify payment**) — confirms approved + captured with Authorize.net |

The card never sees Authorize.net credentials and never handles card data
(PCI SAQ-A). Both pipelines use **User token** auth (`authType: "oauth"`), so
`authenticatedEthosFetch` handles authentication transparently.

## Important: merge into the official template

This folder contains the extension-specific files only (`extension.js`,
`src/cards/ParkingPermitPayment.jsx`, `package.json`). Generate a base project
with Ellucian's extension template/SDK for your SDK version (which supplies the
webpack config, `.env` handling, and upload tooling), then drop these files in.
Pin the dependency versions to whatever your template ships with — the versions
here are placeholders.

## Setup checklist

1. Publish both serverless pipelines; note their API names.
2. In Experience Setup > Permissions, grant the student role **Execute** on
   both pipelines (User-token pipelines push their permissions to Experience
   automatically).
3. Upload the extension, enable the card, and set the two card configuration
   values (token + verify pipeline API names).
4. The card collects the Registration ID as a text field in this scaffold.
   For production, pre-fill it from the workflow deep link, or derive the
   registration server-side from `context['user.id']` (the Ethos person GUID
   the User token injects) so students can't pay against someone else's
   registration.

## Flow

1. Student picks a permit type, enters their registration ID, clicks
   **Pay with card** → card calls the token pipeline → POSTs the one-time
   token to Authorize.net in a new tab (redirect mode; A.net shows the receipt).
2. Card polls the verify pipeline (~2 min) and flips to a confirmation view
   when the payment is approved + captured; a **Verify payment** button covers
   late confirmations.
3. The EIP workflow advances using the same verify pipeline as its authority —
   never the browser's claim.
