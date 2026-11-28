# Reports failing

## What it means
Reports ended `FAILED` in the last 24 hours. The usual cause is the accessibility gate refusing a file (we never deliver a file
that fails PDF/UA or the Word and CSV checks), or the PDF/UA checker being unavailable.

## Check
1. The **Accessible PDF generation and the PDF/UA check** canary on this page. If it is failing, follow `canary-docs-pdf`.
2. `docker compose logs --tail 100 docs-worker`: look for `failed its gate` (a template or data problem) or `validator unavailable`.

## Fix
1. Gate failures on one customer's report: it is a template/data bug. Do not weaken the gate. Escalate with the report id.
2. Checker unavailable: `docker compose restart docs-worker`, then ask the customer to create the report again.

## Escalate
Any gate failure on a standard template, or the canary failing.
