# Scans failing for platform reasons

## What it means
Scans ended `FAILED` in the last 24 hours with an error code that is **our** fault (not a bad address, a blocked site or a
timeout on the customer's page). Customers were not charged for these. Typical codes: `system_error`, `worker_lost`,
`engines_failed`, `queue_unavailable`.

## Check
1. Look at the codes and counts in the incident. `engines_failed` points at the browser or engine bundles; `worker_lost` at a
   worker that died; `queue_unavailable` at Redis or the broker.
2. Check the **Browser and scan engines** canary on this page. If it is failing, follow `canary-web-scan`.
3. `docker compose logs --tail 100 web-worker` for stack traces.

## Fix
1. If the canary fails or the worker crashes repeatedly: `docker compose restart web-worker`.
2. If the codes are `queue_unavailable`: check Redis (`docker compose ps redis`) and follow `queue-backlog`.
3. Tell affected customers nothing needs doing: failed scans returned their credit and can be started again.

## Escalate
More than 10 platform failures in an hour, or any after a restart.
