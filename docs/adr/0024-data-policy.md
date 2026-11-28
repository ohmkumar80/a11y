# ADR 0024: Per-organisation data policy

- **Status:** Accepted
- **Date:** 2026-11-29

## Decisions
- **Three layers, strictest wins.** (1) The platform decides which storage **regions** exist (`data.regions`) and the retention
  ceiling (`documents.retention`). (2) The platform decides, per plan or organisation, which **controls** an organisation may
  use (`data.controls`: choose a region, enable AI on documents, shorten retention, block human review, and the shortest
  retention allowed). (3) The organisation's administrator sets its own **policy** inside those limits (`data.policy`, edited on
  `/org/data-policy`). One function, `data_policy.effective()`, combines them, and everything that stores, keeps, shows to a person
  or sends to an AI provider a customer's file asks it. A choice the plan does not allow (or no longer allows after a downgrade)
  is ignored, never honoured loosely, and the page says why. Saving a choice the plan does not allow is refused with the reason.
- **Retention.** An organisation may keep files for a shorter time than the plan, never longer. A shorter choice also applies to
  files already stored (their expiry moves earlier, never later), and the hourly sweep deletes them. Lengthening later does not
  bring an already-shortened file back.
- **Regions: a file never leaves the one it was written to.** Each document records its region. Reads, deletes, scrubs and the fixed
  copy made from it all use that file's own region. An unknown region is an error (`StorageError`), never a silent fall back to
  another place. A region can be switched off for new files but is kept in the list while it holds files; removing it entirely is
  reported prominently in `/admin` (files cannot be read until it is added back) instead of being hidden. Regions share the platform's
  storage credentials, with an optional bucket, endpoint and provider region each.
- **Human review can be forbidden.** If the organisation switches it off (where its plan allows), requests are refused with a plain
  message and a link to the policy.
- **AI on documents is off unless the organisation turns it on, and fails closed.** A request that carries a customer's file
  (`data_class="customer_document"`, and always for the document-specific `doc_layout` task, whatever the caller says) is sent only to
  a provider that satisfies the policy: the organisation has AI on and its plan allows it; the provider promises zero retention
  (unless the organisation relaxed that); and the provider processes in one of the organisation's allowed regions (if it named any).
  If no provider qualifies, nothing is sent and the reasons are listed. A request with no organisation is refused. This holds for
  platform providers and for an organisation's own (BYOK) providers alike, using each provider's declared data policy.
- **Deletion on request.** An administrator can erase every document in every region at once, with confirmation. Everything is
  audit-logged: each policy change (what is now in force and how many files expired sooner) and each mass deletion.
- **Everything the platform decides is a setting**, versioned and audited like the rest, at global, plan or organisation scope. The
  admin Documents tab shows files per region, per-region storage health, and any region that is no longer configured.

## Not built yet (honest list)
- No customer feature sends a document to an AI provider yet, so the AI rules are enforced and tested at the gateway, but nothing
  exercises them end to end. Whoever adds the first one must use the gateway (they have no other way to reach a model) and must not
  weaken `data_class` handling.
- Reviewers see customer files from wherever they work. There is no reviewer-region rule yet, so an organisation that needs a file
  to stay in one region should switch human review off until there is.
- A provider's region list is whatever an administrator typed (`processing_regions`); we do not verify it against the provider.
- Backups and logs are not region-aware; this ADR covers the files and their derived data in object storage and the database.
- Moving existing files between regions is not supported (files stay where they were written).
- An organisation cannot yet export its documents in bulk before deleting them.
