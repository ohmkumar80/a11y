# Database or Redis is down

## What it means
The readiness check cannot reach Postgres or Redis. The site shows errors and no job runs.

## Check
1. `docker compose ps postgres redis` and `docker compose logs --tail 50 postgres redis`.
2. Disk space on the host (a full disk stops Postgres).

## Fix
1. `docker compose up -d postgres redis`. Wait until `docker compose ps` shows them healthy.
2. Then restart the API and workers: `docker compose restart api worker web-worker docs-worker beat`.
3. Do not delete the Postgres volume.

## Escalate
Postgres does not start, or reports corruption: stop and escalate immediately. Do not retry destructive repairs.
