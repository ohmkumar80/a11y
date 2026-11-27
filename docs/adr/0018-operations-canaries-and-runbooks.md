# ADR 0018: Operations overview, canaries and runbooks

- **Status:** Accepted
- **Date:** 2026-11-28

## Decisions
- **Canaries** prove the parts customers depend on still work, on a schedule, before a customer finds out. Each runs in the
  worker that owns the capability and writes its result to Redis (`canary:<name>`, kept 6 hours):
  `web_scan` (a headless browser loads a planted bad snippet, all three engines find it, a fixed version is clean; no network, no
  credits, nothing stored; every 15 minutes), `docs_pdf` (a sample report becomes an accessible PDF that passes the PDF/UA check;
  every 30 minutes) and `email_smtp` (a connection and login to the mail server, sending nothing; every 15 minutes). A result
  older than 2.5 intervals is shown as *not reporting*, a missing one as *has not reported yet*: silence is never "fine".
  Schedules are declared in the core library because the scheduler process loads only core; the `web.*` and `docs.*` task names
  are routed to their own queues.
- **A read-only operations page** (`/admin` → Operations, `GET /admin/ops`): database and Redis health, queue depths, the
  canaries, a 24-hour summary, and INCIDENTS computed from live data: stuck scans (beyond the sweeper's own thresholds, so it
  flags a dead sweeper), scans that failed for platform reasons (customer faults such as a bad address are excluded), failed
  reports, failed and long-waiting email, abandoned webhook deliveries and switched-off endpoints, failed code-fix jobs,
  credits left reserved after their scan ended, queue backlogs, failing or silent canaries and a core service being down.
  Severity is a word (Critical, Warning, For information), worst first. It changes nothing and every read is audit-logged.
- **Runbooks** are plain Markdown in `docs/runbooks/`, one per incident type, each with *What it means, Check, Fix, Escalate*;
  the page opens the right one beside each incident. Each runbook names its own limits ("do not edit rows by hand", "never scale
  beat above 1"). The API serves a runbook only by a plain file name from that folder; tests prove every incident the page can
  raise points at a runbook that exists and that names cannot escape the folder.

## Not built yet
- Paging or alerting (the page is pull, not push), automatic remediation, SLO dashboards, and a customer-facing status page.
- Canaries for the AI providers (they have their own *Test connection*) and for outbound webhooks.
