# Credits left reserved

## What it means
A scan credit is still `RESERVED` more than 2 hours after its scan ended or vanished. The sweeper (`scans.sweep_reservations`,
every 10 minutes) settles these by the normal rules, so seeing them means it is not running.

## Check
1. `docker compose logs --tail 50 beat` for `scans.sweep_reservations`.
2. `docker compose logs --tail 50 worker` for the task running.

## Fix
1. `docker compose restart beat worker`. The next run settles the credits. Settling is safe to repeat.
2. Do not edit usage rows by hand.

## Escalate
Still listed after 30 minutes.
