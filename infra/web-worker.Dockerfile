# Browser worker for the `web` queue (PROJECT_PLAN 3.9): Python + Playwright Chromium + the pinned
# engine bundles. Kept separate from the API image: it is memory-heavy and runs untrusted pages.
#
# The Playwright base image tag MUST match the playwright version pinned in workers/web_audit.
FROM node:22-slim AS bundles
WORKDIR /b
COPY packages/engine-bundles/package.json ./package.json
COPY packages/engine-bundles/scripts ./scripts
# Exact versions are pinned in package.json; build.mjs records a SHA-256 per bundle in versions.json.
RUN npm install --omit=dev --no-audit --no-fund && node scripts/build.mjs

FROM mcr.microsoft.com/playwright/python:v1.65.2-noble
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 A11Y_RULES_DIR=/app/rules ENGINE_BUNDLES_DIR=/app/engine-bundles
WORKDIR /app
COPY libs/core libs/core
COPY workers/web_audit workers/web_audit
COPY rules rules
COPY --from=bundles /b/dist /app/engine-bundles
RUN pip install ./libs/core ./workers/web_audit
USER pwuser
CMD ["celery", "-A", "a11y_core.celery_app", "worker", "-Q", "web", "--concurrency=2", "--loglevel=INFO"]
