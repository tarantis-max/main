# Legacy Form Intake — myMU/Jenzabar Captures & Source PDFs

18 unique documents received June 10, 2026 (22 uploads, 4 exact duplicates removed).
Machine-readable index: [`uploads_manifest.csv`](uploads_manifest.csv).

**Headline finding: 14 of the 18 are print-to-PDF captures of live myMU (Jenzabar) portal e-forms — not documents.**
They are fill-and-submit forms with dropdowns, prefilled submitter data, repeating rows, uploads, and payment hand-offs.
Posting these captures to SharePoint would publish non-functional screenshots (dead SUBMIT buttons). Per the tracker's own
hosting rule — *"fill-and-submit forms → Etrieve/Softdocs or Ellucian Forms/EIP, not a PDF"* — their "SharePoint (PDF)"
tag is the default placeholder, not a destination. **Recommended disposition: treat as e-form rebuild references.**
Only 4 uploads are true SharePoint documents (Gift Card Authorization, Prize Purchase, P-Card Training deck, Vehicle Rentals guide).

## Flags requiring functional-owner decisions

1. **FAFSA Simplification likely obsoletes three Financial Aid forms before rebuild:**
   - *Family Size/Number in College 2023-2024* (P1) — "number in college" no longer affects the SAI as of 2024-25; family size now derives from FTI.
   - *Child Support Paid* (P2) — child support **paid** is no longer collected; child support **received** moved to assets.
   - *VA Non-educational Benefit* (P3) — captures "benefits received in 2021"; untaxed-benefit questions were removed/restructured.
   Confirm with Financial Aid whether these are still required for 2026-27 verification before anyone builds them. Potentially three P1–P3 builds avoided.
2. **Security — Request for Independent Status** displays a static shared password (`kz9928ucsz`) for the Secure Document Upload link in the form body. Whatever platform it lands on, that pattern shouldn't be carried forward (and the current password should be rotated if the capture circulates).
3. **Payment-integrated forms:** Replacement ID Card ($10 fee → Payments portlet) and the Vehicle Registration family (Cash/Check vs Credit/Debit variants) hand off to payment after submit. Ellucian Forms has no payment step — these need either Etrieve with payment, or a Forms→payment-link pattern. Decide before building.
4. **Vehicle Registration sprawl:** the tracker carries 10+ rows (Summer / Full Year / Half Year × Cash/Check / Credit/Debit × Undergraduate / MU Online, plus Faculty/Staff EIP build and a Student Etrieve build already in progress). The legacy forms are field-identical (plate, state, make, model, year, color, owner, policy agreement). One form with term/duration + payment-method choices replaces all of them — coordinate so the Etrieve student build and the EIP faculty/staff build don't fork the field set.
5. **OTD mirrors DPT:** the OTD Students yr1/yr1-3 forms (locker, anatomy policies, photo/video release, handbook ack, background-check release, informed consent, fieldwork ack) are the same patterns as the DPT Wave 3 cluster. Build the templates once, deploy to both programs. Note the DPT rows are tagged Ellucian Forms/EIP while the matching OTD rows are tagged SharePoint (PDF) — they should land on the same platform.

## Field references by document

### Academic Honor Code Violation — Faculty tab · tracker: TBD
Respondent: faculty. Fields: Year* (dropdown), Term* (dropdown), Date Submitted (auto), Course* (dropdown — faculty's sections),
Student Name* (dropdown — roster of selected course), Nature of Violation* (long text), How addressed* (long text),
How communicated* (long text), up to 3 file uploads. Cascading course→student dropdowns need a faculty-sections data source.

### Financial Aid E-Forms (all prefill Submitter Name/ID/Email; student signature + auto date)
- **Child Support Paid** (P2 — see flag 1): year dropdown, payer name*, repeating rows (child name / yearly amount / age) with "Add Child".
- **Family Size/Number in College 2023-2024** (P1 — see flag 1): Dependent/Independent branch* with different household instructions; repeating household-member rows (full name / age / relationship dropdown / describe / college / half-time Y-N) with "Add Household Member"; parent + student signatures.
- **Outside Scholarship Submission** (P1): award name*, award year* (dropdown), amount*, Fall/Spring/Summer splits*, donor org*, issuing org, donor contact*/phone*/address*, paid-to-MU* Y/N, renewable* Y/N (+ how many years 1-4), per-semester amounts, change-by-year note, documentation upload*, certification + signature. One form per award.
- **Request for Independent Status** (P4 — see flag 2): name*, ID (prefill), address*, phone*, email (prefill), dependency-override policy text, signature*. Supporting docs via secure upload link.
- **VA Non-educational Benefit** (P3 — see flag 1): Dependent/Independent branch, multi-page (NEXT), reports benefits received in 2021.

### Public Safety / ID & Parking (myMU "MU ID Card & Parking Pass" tab)
- **Replacement ID Card** (P1): student ID/name/email (prefill), review page, $10 fee → Payments portlet (flag 3).
- **MU ID Card Photo Submission** (P2): photo upload* with policy text; identical form placed on two portal tabs (Forms & Documentation + ID Card & Parking Pass).
- **Summer Vehicle Registration — Cash/Check & Credit/Debit** (P1 family — flag 4): prefilled student block; License Plate #* (max 10), Plate State* (dropdown), Make* (25), Model* (25), Year* (integer), Color(s)* (60), Owner First* (15) / Last* (30), rules-agreement* Y/N linking parking map/regulations.

### Advising (DPT Advisors / OTD Advisors tabs — identical layout, P4/TBD)
Advisor (prefill), Date*, Advisee* (dropdown — advisor's advisees), Advisee Email (auto from selection), Meeting Location* (dropdown),
Purpose*, Summary of Discussion*, Action Plan, Student Comments, "student verbally agreed" checkbox*, faculty e-signature* + date*.
Needs an advisor→advisees data source. One template serves DPT and OTD.

### OTD Students cluster (P4/TBD — flag 5; all: policy text + typed e-signature* + auto date)
- Anatomy Lab Locker Policies (yr1) — $20 lock replacement policy ack
- Anatomy Laboratory Policies and Procedures (yr1) — long policy ack (key cards, cadaver regs, hazmat, attire)
- Photo and Video Release (yr1) — media release ack
- Student Handbook Acknowledgement (yr1)
- Criminal Background Check & Health Record Release (yr1-3) — releases listed onboarding docs to fieldwork sites; prefilled academic year/ID/name/expected grad
- Informed Consent — Clinical Education/Fieldwork (yr1-3) — COVID-era consent text (likely needs content refresh by owner)
- Student Fieldwork Handbook Acknowledgement (yr1-3) — dual signature (handbook + AOTA Code of Ethics)

### True SharePoint documents (Lane 3 — ready to migrate)
| Upload | Tracker row | Suggested SharePoint name | Notes |
|---|---|---|---|
| gift_card_10apr24.pdf | Gift Card Authorization Form | MU-Gift-Card-Authorization.pdf | Fill/print form; pairs with Gift Card Log (not yet received) |
| prize_purchase_form_12apr24.pdf | Prize Purchase Form - 404 | MU-Prize-Purchase-Form.pdf | Fill/print form with recipient signature log |
| pcard_training_13nov24.pdf | P-Card - Training | MU-PCard-Training.pdf | Slide deck — Resources Hub reference doc, not a form |
| vehicle_rental_info30mar26.pdf | Vehicle Request and Rental Information | MU-Vehicle-Rental-Guide.pdf | Rev 03.30.26 reference doc — Resources Hub |

Source PDFs are retained in the session uploads only — they contain a test user's ID/contact details, so the extracts above
are committed instead of the binaries.
