# Runbooks

One page per kind of incident shown in **Admin → Operations**. Each says what it means, how to check, how to fix and when to
stop and escalate. They assume the services of `docker-compose.yml` (api, worker, web-worker, docs-worker, beat, postgres, redis,
mailpit); on a cloud deployment use the equivalent restart and log commands. They are deliberately plain: do the steps in order,
write down what you saw, and stop at "Escalate" rather than improvising.

General rules: never edit rows in the database by hand to "unstick" something (every job is idempotent and the sweepers
settle credits correctly); never paste customer data into a ticket; note the time you started and the time it recovered.
