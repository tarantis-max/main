# MU Student Vehicle Permit — Authorize.net Payment

All-Ellucian implementation: **Experience** (extension page + card) +
**EIP / Intelligent Processes** (form, workflow, tasks, email) +
**Data Connect serverless APIs** (Authorize.net calls).
No self-hosted middleware. Card data is entered only on Authorize.net's
hosted page (PCI SAQ-A).

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full flow,
trust boundaries, and go-live checklist.

## Repo contents

| Path | What it is |
|---|---|
| `MU_ParkingPermit_GetPaymentToken_v1_0_0.serverless.json` | Data Connect serverless API — mints the Accept Hosted one-time token; fee is resolved server-side |
| `MU_ParkingPermit_VerifyPayment_v1_0_0.serverless.json` | Data Connect serverless API — authoritative payment confirmation via Authorize.net |
| `extension/` | Experience extension — teaser card + full payment page |
| `docs/ARCHITECTURE.md` | Architecture, sequence diagram, EIP workflow config notes |
| `docs/MU_ParkingPermit_PaymentArchitecture.docx` | Architecture document (Word) |

## Quick start

1. Publish both serverless pipeline files in Data Connect; note their API names.
2. In Experience Setup > Permissions, grant the student role **Execute** on both pipelines.
3. Build and upload the Experience extension (see `extension/README.md`).
4. Set the `tokenPipeline` and `verifyPipeline` card configuration values to the API names from step 1.
5. Fill in the real fee schedule in the `GetPaymentToken` pipeline's **Build Token Request** segment.
6. Update the deep-link URLs in the EIP form confirmation message and email action (replace `<tenant>` and `<account>`).
