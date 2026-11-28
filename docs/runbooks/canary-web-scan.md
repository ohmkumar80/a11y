# Canary failing: browser and scan engines

## What it means
The headless browser could not load the test snippet, or the engines no longer find the planted problem. Real scans will fail too.

## Check
1. The canary detail on this page says which check failed.
2. `docker compose logs --tail 100 web-worker`: look for Chromium launch errors (out of memory, missing libraries) or engine bundle
   errors (hash mismatch).
3. Did the image or the engine versions just change? Compare with `docs/benchmark.md` and the pinned versions in
   `packages/engine-bundles`.

## Fix
1. Restart: `docker compose restart web-worker`.
2. After an image change, rebuild: `docker compose build web-worker && docker compose up -d web-worker`.

## Escalate
Still failing after a rebuild, or the detail mentions the engines (not the browser).
