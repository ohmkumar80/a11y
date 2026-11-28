# A queue is backing up

## What it means
Jobs are waiting in Redis faster than workers take them (more than 100 waiting in `system`, `web` or `docs`).

## Check
1. Which queue: `web` = scans and fixes, `docs` = reports, `system` = email, webhooks, sweepers.
2. Is that worker running and healthy? `docker compose ps` and `docker compose logs --tail 50 <service>`.
3. A genuine burst (many customers scanning) drains by itself: watch the depth fall over 10 minutes.

## Fix
1. Worker not running or crashing: restart it (`web-worker`, `docs-worker` or `worker`).
2. Sustained load: scale that worker (`docker compose up -d --scale web-worker=2`). Never scale `beat` above 1.

## Escalate
Depth still rising after a restart and one extra worker.
