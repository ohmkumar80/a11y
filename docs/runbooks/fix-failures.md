# Code-fix suggestions failing

## What it means
Suggestions ended `FAILED` in the last 24 hours. (A suggestion that could not be validated is `NEEDS_REVIEW`, which is normal and
not listed here.) `FAILED` means our job crashed.

## Check
1. The **Browser and scan engines** canary (the check uses the same browser). If failing, follow `canary-web-scan`.
2. `docker compose logs --tail 100 web-worker` for the `fix ... failed` line.
3. If every suggestion needs review with "no AI model is available", the AI routes are not configured: **Admin → AI**.

## Fix
1. `docker compose restart web-worker`.
2. Customers can press **Try again** in the Workbench.

## Escalate
Repeated failures after a restart.
