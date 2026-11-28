# ADR 0020: Document storage and upload safety

- **Status:** Accepted
- **Date:** 2026-11-28
- **Settles:** ADR 0002 (object storage target) for customer files.

## Decisions
- **S3 API is the storage target.** Customer files go to an S3-compatible bucket (RustFS locally; AWS S3 or any compatible
  store in production). Callers use a four-method interface (`put`, `get`, `delete`, `exists`), so Azure Blob can be added
  later without touching them. Endpoint, bucket and keys are environment settings; production refuses the development keys.
- **We encrypt every file ourselves, before it leaves the process.** AES-256-GCM with a fresh random key per object. The
  object's storage key is bound in as associated data, so a ciphertext copied under another key will not open, and any
  change to it is detected. The per-object key is wrapped by the platform master key ring (the same ring and rotation as
  admin secrets, KMS-backed in production) and lives in the database row, never beside the data. The bucket's own
  server-side encryption is switched on in production as a second layer; our layer does not depend on it.
- **Upload is the raw file as the request body**, not a multipart form or a pre-signed URL. The API reads it in chunks and
  stops at the organisation's size limit, so an oversized or endless body is refused without being buffered (a multipart parser
  would write the whole body to disk first). This differs from the plan's "pre-signed URL" wording in 3.17: our own encryption
  means the bytes must pass through us anyway. Pre-signed uploads can be added for very large files with a re-encrypt step.
- **A file is held until it has been checked.** Status `UPLOADED` -> `SCANNING` -> `CLEAN`, `REJECTED` or `FAILED`. The one
  function that reads a customer file for normal use refuses anything that is not `CLEAN`; a second one exists only for the scan
  task. Download, audit, remediation and AI use all go through the first.
- **Two layers of checks.** In the API, before anything is stored: file name reduced to a safe display name (never used in a
  storage key), the real kind decided from the bytes and required to agree with the extension, size limit, and for ZIP-based
  files (Word, PowerPoint, EPUB) a measured, capped decompression (entry count, total size, per-item expansion ratio, unsafe
  paths, nested programs and archives, password-protected items). In the documents worker, after storing: the virus scan, then
  a parser-level inspection (password protection, page count, scripts and launch actions in PDFs, macros in Office files, XML
  entity declarations). Nothing is executed or rendered.
- **It fails closed.** If the scanner or the store is down, the task retries with back-off and the file stays unreadable. After
  the admin-set number of attempts it becomes `FAILED`, which is our fault: nothing is charged, the customer is told so, and an
  administrator can send it back through every check once the problem is fixed. A scanner reply that is not a clear "OK" or
  "FOUND" counts as unavailable, never as clean. The scan can be switched off only outside production, and the setting is
  recorded on the document when it was.
- **Hostile files do not stay.** For a virus, zip bomb, unsafe archive, script or macro, or XML entity attack, the bytes are erased
  at once and only the reason is kept. Other refusals (password-protected, too many pages, damaged) keep the bytes for a short,
  admin-set support window.
- **Retention is an admin setting**, at global, plan or organisation scope, applied when the file arrives (changing it affects new
  files). An hourly sweep erases expired files; a customer or administrator can erase one at once. Erasing deletes the bytes and
  the keys and leaves a tombstone row (no name, no keys) for quota history and audit.
- **Everything tunable is a setting, not code**: `documents.uploads` (file types, size per type, pages, upload rate, files kept;
  global, plan, organisation), `documents.safety` (scan policy, encrypted and active content, zip limits; global only, high risk),
  `documents.retention`, and the `documents` feature flag. `/admin` -> Documents shows scanner and store health, the pipeline, why
  files were refused, and files that failed on our side (retry), and can run the retention sweep.

## Known limits (honest list)
- The scan task and the PDF parser run in the shared documents worker, which has network access to the store and the scanner. The
  plan's "short-lived containers with no network" is a production hardening step: run the docs worker in its own network segment,
  as the web worker must be. Until then the parser is the exposed surface.
- Only one region is supported; the region/data-policy slice of Phase 3 is still to do, as is zero-retention for AI providers.
- The HTTP server still receives the body before our cap stops it; put a request-size limit on the reverse proxy in production.
- ClamAV catches known malware only, and only what it can see: checked against a real daemon, the standard EICAR test file is
  found on its own and inside a .docx (ClamAV unpacks archives), but NOT when it sits inside something ClamAV parses as a PDF.
  So the scan is one layer, next to the structural checks, not proof a file is safe. Signatures update daily in the container.
- The ClamAV image is `clamav/clamav-debian` because the plain `clamav/clamav` image has no Apple Silicon build.
- Orphaned objects (stored, then the database commit failed, then the cleanup also failed) are logged but not yet swept.
