# Alma Patron Load — Colleague Data Connect Pipelines

Banner-to-Alma is what the Ellucian "Alma Integration Guide" (June 2026) documents — its
delivered `Ellucian-Alma-*` pipelines query Banner tables (SPRIDEN, GOREMAL, SGBSTDN, ...)
through Insights and cannot run against our Colleague tenant. These two custom pipelines
re-implement that integration against the Colleague/ODS tables already used by the other
pipelines in this repo, while keeping the Alma-side contract from the guide unchanged
(user XML layout, field mappings, zipped delivery, daily schedule).

## Pipelines

| File | Population | User group |
|---|---|---|
| `MU_Alma_Student_Demographics_Extract_v1_0_0.pipeline.json` | Students with a `STUDENT.TERMS` record for the target term | `UStu` / `GStu` from the active program's academic level (`graduateLevelCodes` parameter, default `GR`) |
| `MU_Alma_Faculty_Demographics_Extract_v1_0_0.pipeline.json` | Faculty with a `COURSE.SEC.FACULTY` assignment in the target term | Fixed, from `userGroupCode`/`userGroupDesc` parameters (default `Faculty`) |

Both resolve the target term automatically (earliest FA/SP/SU term whose end date has not
passed) unless `targetTerm` is set, and both compute `expiry_date`/`purge_date` as
term end date + `expiryGraceDays` (default 30), per the guide.

## Flow

```
extractData (Colleague SQL)
  → Build User XML (per-record <user> element, XML-escaped)
  → reducer → Assemble XML Document (<users> doc + dated file names)
  → s3sink (stage report_*.xml in staging bucket)
  → ZipFile (Alma only ingests zipped XML; max 4 GB/zip)
  → S3Accessor (read zip back, binary)
  → sftpPut (drop report_*.zip in the Alma-watched directory)
```

The S3 staging bucket is required because zipping in Data Connect (`ZipFile` segment)
operates on staged files, and Ex Libris requires the SIS load files to be zipped XML
placed on the S/FTP location watched by the integration profile.

## Alma-side setup (Library Systems Manager)

1. In Alma: Configuration → General → External Systems → Integration Profiles → add a
   **Student Information Systems** profile (or one per population) in **Synchronize** mode.
2. Define the S/FTP connection and watch directory; it must match `almaSftpPath`
   (`/alma/student/` and `/alma/faculty/` by default).
3. Confirm the user groups sent by the pipelines (`UStu`, `GStu`, `Faculty`) exist in
   Alma's user group code table, and that id_type `01` is the external identifier type
   expected by the profile.
4. After Alma processes a file it renames it `*.zip.old` on the server.

## Data mapping (kept from the guide)

`record_type`=PUBLIC, `primary_id`=Colleague ID, names from PERSON (middle initial only),
`pin_number` empty, `preferred_language`=en, birth/expiry/purge dates with `Z` suffix,
one External `user_identifier` (id_type 01) carrying the SSO ID, one preferred home
address (country defaults to USA), one preferred personal email (falls back to
`defaultEmail` — Alma requires an email). Records and elements with no data are omitted
rather than sent empty.

## Validate before first run (Banner→Colleague adaptation assumptions)

Tables/columns proven by the existing Carnegie/eRezLife pipelines are reused as-is
(`ods_students`, `ods_student_terms`, `ods_student_programs`, `ods_person`,
`ods_person_address_info`, `ods_address`, `people_email`, `ods_terms`). The following are
standard Colleague structures but are **not yet proven in our Insights tenant** — check
they exist (add via custom data set if missing) or adjust:

- `dbo.acad_programs.acpg_acad_level` (student UG/GR split)
- `dbo.course_sec_faculty` (`csf_faculty`, `csf_course_section`) and
  `dbo.course_sections` (`sec_term`) (faculty population)
- `dbo.ods_terms.term_end_date` (expiry calculation)

Known deltas from the Banner baseline, to revisit if the library wants them:

- **Phone**: omitted. The Banner extract pulls SPRTELE but its student baseline ships
  `0000000000` anyway; wire a Colleague phone source here if the library needs real numbers.
- **user_title** (name prefix): sent empty; map `ods_person` prefix column if available.
- **External ID**: uses the Colleague ID (same convention as the eRezLife feed's
  `external_auth_id`). If Alma authenticates against a different SSO attribute
  (e.g. AD username), swap the `external_id` column in the extract query.
- **Deceased/exclusion filters**: the Banner query excludes deceased persons
  (SPBPERS_DEAD_IND); add the equivalent ODS person filter once the column is confirmed.

## Operations

Import each `*.pipeline.json` in Experience → Data Connect, set the persistent
parameters (staging S3 credentials, Alma SFTP credentials), run once with a small
`targetTerm`, verify the zip lands and Alma's import job report looks right, then
schedule daily per the guide. Failure behavior matches the guide: empty population,
SQL errors, or SFTP failures fail the job — review the run log, fix parameters, rerun.
