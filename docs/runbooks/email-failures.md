# Email not being delivered

## What it means
Emails are `FAILED` (gave up after 4 attempts) or `QUEUED` for over an hour. Delivery means "handed to the mail server".

## Check
1. The **Mail server connection** canary on this page, and the recent emails list in **Admin → Emails** (the error shows the
   cause, for example `ConnectionError` or an authentication failure).
2. Mail settings: **Admin → Settings → notify.provider** (or the SMTP_* environment values) and use **Send a test to me**.
3. Is the system worker running? `docker compose logs --tail 50 worker`.

## Fix
1. Wrong host, port or password: correct `notify.provider`, publish, then **Send a test to me**.
2. Worker down: `docker compose restart worker`. Queued emails send on their own.
3. Emails already marked `FAILED` are not re-sent automatically (customers may have taken another route). Decide case by case.

## Escalate
The provider rejects mail for a reason you cannot fix (blocked sender domain, rate limit).
