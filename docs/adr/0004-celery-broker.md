# ADR 0004: Celery on Redis to start

- **Status:** Accepted (PROJECT_PLAN open decision 6)
- **Date:** 2026-11-26

## Decision
Redis as broker, with `acks_late`, `task_reject_on_worker_lost`, `prefetch_multiplier=1` and a `visibility_timeout`
above the longest job. Queues (`web`, `docs`, `media`, `mobile`, `ai`) exist from day one so images can split later.
Tasks carry `org_id` and open a `tenant_session`.

## Revisit
When video/media jobs land (Phase 4): move long jobs to RabbitMQ if Redis redelivery or memory becomes a problem.
