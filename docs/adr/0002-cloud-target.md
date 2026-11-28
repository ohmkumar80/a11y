# ADR 0002: Cloud and object-storage target

- **Status:** Partly accepted (2026-11-28). The owner chose the **S3 API** for customer files; see ADR 0020. The choice of
  cloud for hosting is still open (PROJECT_PLAN open decision 2).
- **Date:** 2026-11-26

## Context
The spec allows S3 or Azure Blob. Supporting both for v1 doubles testing for no customer benefit.

## Recommendation
Pick **one** for v1. Local development uses MinIO (S3 API), so S3 is the zero-cost default; choose Azure Blob only if
the first customers or credits require it. Keep object access behind a small storage interface.

## Open questions
- Which cloud do we have credits or customer pressure for?
- Region for India data residency (DPDP Act)?
