# Stuck scans

## What it means
A scan has been `RUNNING` with no heartbeat for over 10 minutes, or `QUEUED` for over 45 minutes. The stuck-scan sweeper
(`scans.sweep_stuck`, every 2 minutes) fails such scans at 5 and 30 minutes and returns the credit, so seeing one here means the
sweeper itself is not running, or the scan table is changing faster than it can keep up.

## Check
1. Is `beat` running? `docker compose ps beat` and `docker compose logs --tail 50 beat` (look for `scans.sweep_stuck`).
2. Is the system `worker` consuming the `system` queue? `docker compose logs --tail 50 worker`.
3. Is the queue backed up? See the queue depths on this page.

## Fix
1. Restart the scheduler: `docker compose restart beat`. There must be exactly one `beat`.
2. Restart the system worker: `docker compose restart worker`.
3. Wait 5 minutes and refresh this page. The sweeper fails the scans and returns credits by itself.

## Escalate
If it is still listed after 15 minutes, or beat and worker are healthy but nothing is swept, stop and escalate to engineering.
