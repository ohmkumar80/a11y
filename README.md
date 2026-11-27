# a11y: Omni-Channel AI Accessibility Platform

Multi-tenant accessibility audit SaaS. Our own product must meet **WCAG 2.2 AA**; the build enforces it.

- Product spec: [docs/MASTER_BUILD_PROMPT.md](docs/MASTER_BUILD_PROMPT.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Plan and accessibility commitments: [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md)**
- Decisions: [docs/adr/](docs/adr/)

## Quick start

Requires Docker, and (for development outside Docker) Node 22+, pnpm, Python 3.12.

```sh
make up        # builds and starts everything; migrations + demo seed data run automatically
```

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Mailpit (all outgoing email) | http://localhost:8025 |
| Scheduler (`beat`) | hourly trial expiry; run exactly one |
| S3-compatible storage (RustFS) | http://localhost:9000, console :9001 |

Demo login: `admin@demo.example.com` / `demo-passphrase-123` (admin) or `member@demo.example.com` (standard user).
`make reset` wipes all data volumes.

## Develop

```sh
docker compose up -d postgres redis mailpit   # infra only
make venv && make migrate && make seed        # Python env, schema, demo data
make test-api                                 # RLS isolation + auth tests
pnpm install
pnpm --filter @a11y/ui storybook              # component workbench with the a11y panel
pnpm --filter @a11y/ui test                   # vitest + vitest-axe + keyboard tests
make a11y-tokens                              # design-token contrast gate
pnpm --filter @a11y/web dev                   # web app (set API_INTERNAL_URL if API is elsewhere)
pnpm --filter @a11y/web e2e                   # axe on every route x role x colour scheme
```

## Platform admin (Super Admin)

```sh
python -m a11y_api.admin_cli you@example.com    # prompts for a password; creates a platform operator (no tenant)
```

Sign in via `POST /auth/login`, then use `/admin/*` (see `/docs`). Settings, plans, entitlements, coupons,
tenant directory and manual plan assignment are all API-first today; the admin UI is next. Settings are declared in
`libs/core/a11y_core/config/definitions.py` and described in [ADR 0006](docs/adr/0006-settings-framework-and-ai-config.md).
Demo coupon: `DEMO20`.

## Layout

```
apps/web         Next.js App Router, all dashboards + auth
apps/api         FastAPI + Alembic (RLS migrations)
libs/core        Models, tenant-scoped DB sessions, settings, Celery wiring
packages/ui      React Aria component library, design tokens, Storybook
infra/           Dockerfiles, Postgres role bootstrap
docs/            Spec, architecture, plan, ADRs
```

## Accessibility gates (all blocking in CI)

eslint-plugin-jsx-a11y strict · TypeScript strict · token contrast (light + dark) · vitest-axe + keyboard tests per component ·
Storybook build · Playwright + axe on every route, role and colour scheme (the matrix fails if a new page is not listed) · 320px reflow ·
skip link, route announcement, focus and consistent-help checks. Allow-list entries need an issue link and an expiry date
(`apps/web/e2e/axe-allowlist.json`).

Manual (every release, not automated): NVDA + VoiceOver smoke test; see PROJECT_PLAN section 2.6.

## Tenant isolation

Postgres RLS with three roles (owner / app / admin). Any table with `organization_id` must have forced RLS and a policy or the
isolation suite fails. See [ADR 0005](docs/adr/0005-tenant-isolation.md).
