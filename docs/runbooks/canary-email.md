# Canary failing: mail server connection

## What it means
The mail server did not accept a connection or login. Nothing is sent by this check, but real emails will fail and queue up.

## Check
1. The canary detail says the error. Compare with **Admin → Settings → notify.provider** (or the SMTP_* environment values).
2. Is the provider up (their status page), and is the network allowed to reach its port?

## Fix
1. Wrong credentials or host: correct `notify.provider`, then **Admin → Emails → Send a test to me**.
2. Provider outage: nothing to do on our side; queued emails send once it is back (they retry 4 times over several hours; after
   that they are marked failed).

## Escalate
The provider's account is suspended or the sender domain is blocked.
