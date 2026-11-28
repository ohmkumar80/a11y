# Canary failing: accessible PDF generation

## What it means
A sample report no longer becomes a PDF that passes the PDF/UA check. Customers' PDF reports will be refused too (we never
deliver a file that fails the check).

## Check
1. The canary detail shows the rules that failed, or that the checker could not run.
2. `docker compose logs --tail 100 docs-worker`: Java and veraPDF errors, or WeasyPrint errors.
3. Did a template, WeasyPrint or veraPDF version just change?

## Fix
1. Restart: `docker compose restart docs-worker`.
2. If a template change caused it, revert that change (templates are versioned) and rebuild.

## Escalate
Rule failures after a revert, or the checker will not start.
