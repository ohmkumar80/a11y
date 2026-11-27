# a11y: Omni-Channel AI Accessibility Platform

A multi-tenant accessibility-as-a-service platform. It audits websites, documents, media and mobile apps against WCAG and national laws, explains each issue in plain language, proposes fixes a person can review, and produces compliance reports (including a drafted VPAT / ACR).

**Our own product must meet WCAG 2.2 AA, and the build enforces it.** An accessibility vendor with an inaccessible product has no credibility, so accessibility checks block merges from the first commit.

## Status

Planning is complete and published here. Application code is in active development and is not published yet.

| Phase | Scope | State |
|---|---|---|
| 0. Foundations | Monorepo, Docker stack, CI accessibility gates, accessible component library, auth, tenant isolation | Built (manual screen-reader smoke test still to do) |
| 1a. Sellable core | Web scanner, rule registry, reports and VPAT drafts, public API skeleton, Razorpay Payment Links, admin MFA | In progress (SaaS core, settings, admin screens, AI providers incl. enterprise own-key, rule registry, the web scanner with its workspace screens, and accessible reports (PDF, Word, CSV, VPAT with sign-off) built; email templates, billing and the public API to do) |
| 1b. Breadth and hardening | Full notification catalogue, webhooks, canaries, sampled AI validation, our own ACR | Planned |
| 2. Deep web audit and monetisation | Authenticated scans, vision audit, monitoring, self-serve billing, SSO/SCIM, CI/CD and Jira/GitHub integrations | Planned |
| 3. Documents and eBooks | PDF, DOCX, PPTX, EPUB remediation and the human review console | Planned |
| 4. Audio and video | Captions, transcripts, audio description | Planned |
| 5. Mobile | Android accessibility audits | Planned |

The full breakdown, with item-by-item status for Phase 1, is in the plan.

## What it does

- **Scan** websites with several engines at once (axe-core, IBM Equal Access, HTML_CodeSniffer), deduplicated into one list of findings with a confidence score.
- **Explain and fix.** Every rule has a stored plain-language explanation and fix examples. AI is used only where a fix depends on the customer's own code, and every AI output is verified (our own scanner re-checks each proposed patch) before it is shown.
- **Report** for the law that applies: WCAG 2.0/2.1/2.2, ADA, Section 508, EU EAA / EN 301 549, Australia DDA and India GIGW 3.0. Switching the standard recalculates scores from the same scan. Reports are accessible PDFs, DOCX and CSV. VPATs are drafts that a person signs off, because automated testing cannot prove full conformance.
- **Remediate documents and media** (later phases): PDF, DOCX, PPTX, EPUB, captions and audio description, with a human-review queue for complex files.
- **Integrate.** A versioned public API (`/v1`, OpenAPI/Swagger), API keys, webhooks, a CLI and CI integrations, and Jira, GitHub, Slack and SSO/SCIM for enterprise customers.
- **Configure everything from the admin panel:** AI providers and models (OpenAI, Azure OpenAI, Claude, Bedrock, Gemini, DeepSeek, any OpenAI-compatible endpoint), plans, quotas, coupons, trials, email templates and more. Settings are typed, scoped, versioned, audited and reversible.

## Documentation

| Document | What it covers |
|---|---|
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | Recommendations, accessibility commitments, technical design, phased plan, open decisions and risks |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System blueprint diagram |
| [docs/MASTER_BUILD_PROMPT.md](docs/MASTER_BUILD_PROMPT.md) | The original product specification |

Architecture decision records live in `docs/adr/` in the development tree.

## Tech stack

Next.js (App Router, TypeScript) with React Aria Components and Tailwind; FastAPI, SQLAlchemy (async) and Alembic; PostgreSQL 16 with Row-Level Security; Redis and Celery; S3-compatible object storage; Playwright and the scan engines; open-source document, media and speech tooling. Payments through Razorpay. See the plan for the licensing review and the reasoning behind each choice.

## Running the code (development tree)

These commands apply to the development tree, which contains the application code. They need Docker, and for work outside Docker, Node 22+, pnpm and Python 3.12.

```sh
make up        # builds and starts everything; migrations and demo seed data run automatically
```

| Service | Default URL | Port setting in `.env` |
|---|---|---|
| Web app | http://localhost:3000 | `WEB_PORT` |
| API docs (Swagger UI) | http://localhost:8000/docs | `API_PORT` |
| Mailpit (all outgoing email) | http://localhost:8025 | |
| S3-compatible storage | http://localhost:9000 (console :9001) | `S3_PORT`, `S3_CONSOLE_PORT` |

**Port already in use?** If another app on your machine uses one of these ports, set a different one in `.env` (for example `API_PORT=8010`) and run `make up` again; then use that port in the URL. To check which app answers on a port, open `/openapi.json` there and look at `info.title`: ours is `a11y API`.

Demo login: `admin@demo.example.com` / `demo-passphrase-123` (administrator) or `member@demo.example.com` (standard user). Demo coupon: `DEMO20`.

**AI providers:** in `/admin` → AI, use *Quick add* for DeepSeek, Azure OpenAI or OpenAI (key is write-only, then *Test connection*).
Enterprise organisation admins can use their own keys at `/org/ai`. `make reset` wipes all data volumes. Ports can be changed in `.env` (`WEB_PORT`, `API_PORT`, and so on).

```sh
docker compose up -d postgres redis mailpit   # infrastructure only
make venv && make engines                     # Python env + Chromium, and the pinned scan-engine bundles
make migrate && make seed                     # schema, demo data
make test-api                                 # tenant-isolation and auth tests
pnpm install
pnpm --filter @a11y/ui storybook              # component workbench with the accessibility panel
pnpm --filter @a11y/ui test                   # vitest + vitest-axe + keyboard tests
make a11y-tokens                              # design-token contrast gate
pnpm --filter @a11y/web dev                   # web app (set API_INTERNAL_URL if the API is elsewhere)
pnpm --filter @a11y/web e2e                   # axe on every route, role and colour scheme
```

**Platform admin (Super Admin).** Create a platform operator with `python -m a11y_api.admin_cli you@example.com` (prompts for a password), sign in through `POST /auth/login`, then use the `/admin/*` endpoints and screens. Settings are declared in `libs/core/a11y_core/config/definitions.py`; the design is in the plan (section 3.11) and ADR 0006.

### Repository layout

```text
apps/web         Next.js App Router: all dashboards and auth
apps/api         FastAPI + Alembic (RLS migrations)
libs/core        Models, tenant-scoped DB sessions, settings, rule registry, AI gateway, billing, SSRF guard
workers/web_audit  Browser scanner: three engines in one page, egress proxy, scan job runner
workers/documents  Accessible reports: PDF/UA (WeasyPrint + veraPDF gate), DOCX, CSV, VPAT; report templates
packages/ui      React Aria component library, design tokens, Storybook
packages/engine-bundles  Pinned, hash-checked axe / IBM / HTMLCS browser bundles
rules/           WCAG criteria, standards mappings, canonical cross-engine rules (SME-reviewed data)
fixtures/        Known-good and known-bad pages for scanner tests
infra/           Dockerfiles, Postgres role bootstrap
docs/            Specification, architecture, plan, ADRs
```

## Accessibility gates

All of these block a merge in CI:

- `eslint-plugin-jsx-a11y` (strict) and TypeScript strict mode
- Design-token contrast, light and dark
- `vitest-axe` and keyboard tests for every component
- Storybook build with the accessibility addon
- Playwright and axe on every route, role and colour scheme (the test matrix fails if a new page is not listed)
- 320px reflow, skip link, route announcement, focus and consistent-help checks

Allow-list entries need an issue link and an expiry date (`apps/web/e2e/axe-allowlist.json`). Every release also gets a manual pass with NVDA and VoiceOver; see section 2.6 of the plan.

## Tenant isolation

Postgres Row-Level Security with three roles (owner, app, admin). Any table with an `organization_id` must have forced RLS and a policy, or the isolation test suite fails. The reasoning is in the plan (section 3.4) and ADR 0005.

## Licence

A licence has not been chosen yet. Until one is added, all rights are reserved.
