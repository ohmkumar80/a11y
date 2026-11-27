# Webhook deliveries failing

## What it means
Webhook deliveries were abandoned in the last 24 hours (the customer's server did not accept them after 6 tries), or an endpoint
was switched off because it kept failing. The customer's administrators have been emailed about switched-off endpoints.

## Check
1. This is almost always the customer's receiver. The customer can see each delivery and its error under **Organisation →
   Webhooks → Deliveries**.
2. If many different customers fail at once, the problem is ours: check outbound network access from the `worker` and the
   `webhooks.retry_due` sweeper in the `beat` logs.

## Fix
1. One customer: nothing to fix on our side. They correct their receiver, turn the webhook back on and retry deliveries.
2. Many customers: `docker compose restart worker beat`.

## Escalate
Failures across customers that a restart does not clear.
