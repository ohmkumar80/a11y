# Project Plan: Omni-Channel AI Accessibility Platform

**Status:** Draft v1 · 2026-11-26
**Inputs:** [MASTER_BUILD_PROMPT.md](MASTER_BUILD_PROMPT.md) (product spec) · [ARCHITECTURE.md](ARCHITECTURE.md) (blueprint)

This plan sets out the build order and the changes recommended to the spec. It also commits us to making our own product accessible: an accessibility vendor whose app fails WCAG will not win enterprise or government deals.

---

## 1. Key recommendations

1. **Our own product meets WCAG 2.2 AA, and the build enforces it.** Accessibility checks block merges from the first commit. We publish an Accessibility Statement and our own ACR (VPAT) before the first paid customer. See [section 2](#2-our-own-product-must-be-accessible).
2. **Every file we generate must also be accessible.** PDF reports must be tagged and pass PDF/UA, and VPAT DOCX files need real headings and table headers. An inaccessible audit report would hurt our credibility.
3. **Keep Phase 1 small enough to sell.** It covers the multi-tenant core and a web scanner that reports and exports results. The Vision-LLM auditor, screen reader capture and focus-trap agent move to Phase 2.
4. **Run all three scan engines inside one Playwright page.** Inject axe-core, IBM `ace.js` and HTML_CodeSniffer bundles into the same page instead of starting pa11y's own Puppeteer browser. That means one page load, one DOM state, half the memory, and results that are easier to deduplicate.
5. **Replace PyMuPDF.** It is AGPL-3.0, which creates source-disclosure obligations for a network service. Use `pypdfium2` (Apache/BSD) or `pdfplumber` (MIT) instead, or buy a commercial PyMuPDF licence. See the [licensing review](#31-licensing-review-zero-licence-stack).
6. **Fix the screen reader assumption.** Guidepup drives real **NVDA (Windows) and VoiceOver (macOS)** only; it does not support Orca, and none of these run in a headless Linux worker. Use `@guidepup/virtual-screen-reader` server-side and offer real-screen-reader runs later on dedicated Windows and macOS hosts.
7. **Never claim compliance from automation alone.** Automated engines cover only part of WCAG. VPATs we generate are *drafts*: criteria that automation cannot test default to "Not Evaluated", and a human signs off before export. The FTC's 2025 $1M order against accessiBe over AI "compliance" claims is the precedent to avoid.
8. **Design for scanning untrusted content.** Arbitrary URLs bring SSRF risk, uploaded files can be zip bombs or malicious PDFs, and APKs can be malware. Workers run sandboxed with network egress controls. See [section 3.6](#36-security-of-scanning-untrusted-content).

---

## 2. Our own product must be accessible

### 2.1 Commitment

- **Target:** WCAG 2.2 Level AA across every screen, email and generated file, for all three dashboards, marketing site, auth, checkout and reports.
- **Also covered:** EN 301 549 (for EU buyers) and Section 508 (for US public-sector buyers). Both are met if WCAG 2.2 AA is met for web content, plus documentation and support requirements.
- **Ownership:** an Accessibility Lead (can be part-time at first) holds release sign-off. Accessibility is part of Definition of Done, not a later QA phase.

### 2.2 Foundation choices

| Area | Decision | Why |
|---|---|---|
| Component library | **React Aria Components** as the only primitive layer | Tested across screen readers, has strong keyboard and focus management and built-in i18n. Mixing Radix and React Aria gives two different focus and keyboard models, so pick one. |
| Styling | Tailwind with **design tokens whose contrast is checked in CI** | Text ≥ 4.5:1, large text ≥ 3:1, UI components and focus indicators ≥ 3:1 (SC 1.4.3, 1.4.11). Checked for both light and dark themes. |
| Focus | Global `:focus-visible` ring token (≥ 2px, ≥ 3:1 against adjacent colours); `scroll-padding-top` set to sticky header height | SC 2.4.7 and 2.4.11 (Focus Not Obscured), because sticky headers commonly hide the focused element. |
| Layout | Landmarks (`header`/`nav`/`main`/`aside`), one `h1` per page, skip link, unique `<title>` per route, route-change announcement | Next.js App Router client-side navigation does not move focus or announce new pages by default. |
| Motion and modes | Respect `prefers-reduced-motion`, support `forced-colors` (Windows High Contrast), work at 200%/400% zoom and 320px width | SC 1.4.4, 1.4.10, 1.4.12, 2.3.3 (good practice). |
| Language | `lang` on `<html>` and on any foreign-language fragments | SC 3.1.1/3.1.2. Needed once Indian-language UI is added. |

### 2.3 WCAG 2.2 criteria that directly affect our features

| SC (WCAG 2.2) | Where it applies to us | Required approach |
|---|---|---|
| 2.4.11 Focus Not Obscured (Min) | Sticky headers, cookie banner, toasts, split-pane workbench | Scroll padding; toasts must never cover focused content; no sticky overlays over the main area |
| 2.5.7 Dragging Movements | **Reading-order editor** (docs), **video caption/AD timeline**, resizable split panes, Kanban-style HITL queue | Every drag must have a single-pointer alternative: move up/down buttons, numeric time inputs, a keyboard-operable splitter (APG Window Splitter pattern) |
| 2.5.8 Target Size (Min) | Icon buttons in tables, timeline handles, chart legends | All targets ≥ 24×24 CSS px (we aim for 44×44 on primary actions) |
| 3.2.6 Consistent Help | Help/contact entry point | Same help location on every page across all three dashboards |
| 3.3.7 Redundant Entry | Checkout, multi-step new-scan wizard, invite flow | Never ask for the same info twice in a flow; prefill from earlier steps |
| 3.3.8 Accessible Authentication (Min) | Login, signup, MFA, password reset | No puzzle CAPTCHAs or cognitive tests; allow paste and password managers (`autocomplete` attributes); support passkeys and magic links; use invisible bot protection |

### 2.4 Accessible patterns for complex UI

- **Charts (Recharts/Tremor):** every chart has a visible "View as table" toggle with the same data. Colour is never the only signal (use patterns and direct labels), and each chart has a text summary ("Issues fell 32% since last scan"). Turn on Recharts' keyboard accessibility layer.
- **Live scan progress (WebSocket/SSE):** one `aria-live="polite"` region, throttled to milestone updates (start, 25/50/75%, done, failed) so screen readers are not flooded. Completion moves no focus, but the message links to the results.
- **Seat counter and quota meters:** `role="meter"` (or `progressbar` for jobs) with `aria-valuetext` such as "7 of 10 seats used". Warning states use text and an icon as well as colour.
- **Interactive Fix Workbench:** each pane is a labelled `region`. The issue list is a keyboard-navigable grid or listbox, and selecting an issue updates the screenshot highlight *and* a text description of the element (selector, role, name), so blind users don't depend on the screenshot. Code fixes go in `<pre><code>` with a labelled copy button that announces "Copied".
- **Screenshot inspector:** highlighted regions have text equivalents, and zoom and pan work by keyboard.
- **Video workbench:** accessible media player (keyboard controls, captions on by default in the editor, no autoplay). Captions are edited as a list of text rows with time fields; the waveform is an optional visual aid, not the only way to edit.
- **Data tables (tenants, findings, coupons):** real `<table>` with `<th scope>`, sortable headers announce sort state (`aria-sort`), filters are labelled, and pagination is used instead of infinite scroll.
- **Forms (signup, checkout, coupon):** visible labels, inline errors tied with `aria-describedby`, an error summary on submit that receives focus, no time limits (or adjustable ones, SC 2.2.1).
- **Modals (New Scan):** React Aria `Dialog` with a focus trap, `Esc` to close, and focus returned to the trigger.
- **Toasts:** never the only place important information appears. They persist until dismissed when actionable, and live in a polite live region.
- **Emails (invites, trial expiry, scan done):** semantic HTML, real text (not images), sufficient contrast, plain-text alternative.
- **White-label:** tenant brand colours are validated for contrast when saved. Inaccessible combinations are rejected with a suggestion, so a customer's theme cannot make our UI fail.

### 2.5 Generated files must be accessible

| Output | Requirement | Gate |
|---|---|---|
| Audit report PDF | Tagged PDF/UA-1: title, language, headings, table headers, alt text on charts, logical reading order | veraPDF must pass before download is enabled |
| VPAT/ACR DOCX | Built-in Heading styles, table header rows repeat, alt text on logos | Automated DOCX check in CI on golden samples |
| CSV | UTF-8 with BOM, header row, no merged meaning | Schema test |
| Remediated customer files | Re-validated (veraPDF / Ace / EPUBCheck) before delivery | Worker refuses to mark job complete on failure |

### 2.6 Testing and quality gates

**Every pull request (blocking):**
- `eslint-plugin-jsx-a11y` (strict) and TypeScript strict mode.
- Storybook + `@storybook/addon-a11y` on every component and state (hover, error, disabled, loading).
- Component tests with `vitest-axe`, plus keyboard interaction tests (Tab order, Esc, arrow keys) with Testing Library.
- Playwright end-to-end run on **every route and role** with `@axe-core/playwright`. Zero violations, and an allow-list entry needs an issue link and an expiry date.
- Contrast check on design tokens (light, dark, and the forced-colors snapshot).

**Nightly:**
- **Dogfooding:** our own scanner runs against staging, and any finding fails the nightly build.
- `@guidepup/virtual-screen-reader` scripts for the critical flows (signup → first scan → read results → export). We snapshot the spoken output and diff it between runs.
- 200%/400% zoom and 320px reflow visual regression snapshots.

**Every release (manual, documented checklist):**

| Screen reader | Browser | Platform |
|---|---|---|
| NVDA | Firefox, Chrome | Windows |
| JAWS | Chrome | Windows |
| VoiceOver | Safari | macOS, iOS |
| TalkBack | Chrome | Android |

Also each release: keyboard-only pass, Windows High Contrast, voice control (Voice Access / Dragon) on the main flows.

**Every quarter:** paid usability sessions with disabled users (blind, low vision, motor, cognitive). Our HITL SME network in Chennai, Salem and Madurai is a natural partner for this.

### 2.7 Definition of Done (accessibility part)

A UI story is done only when all of these are true:
- [ ] Fully operable by keyboard; focus order is logical and focus is always visible and not obscured.
- [ ] Every control has an accessible name, role and state; verified in the accessibility tree.
- [ ] No axe violations in Storybook or end-to-end tests.
- [ ] Works at 200% zoom and 320px width without horizontal scrolling or lost content.
- [ ] Any drag interaction has a single-pointer alternative; targets are ≥ 24×24px.
- [ ] Dynamic updates are announced appropriately (and not over-announced).
- [ ] Checked with at least one screen reader by the developer (NVDA or VoiceOver).

### 2.8 Public commitments (before first paid customer)

- **Accessibility Statement** page: conformance target, known issues, feedback contact, response time.
- **Our own ACR** (VPAT 2.5 INT edition, which covers WCAG, 508 and EN 301 549 together), produced by a human audit and refreshed each major release.
- Accessible feedback channel (email + form) with a committed response time.

---

## 3. Technical recommendations (changes to the spec)

### 3.1 Licensing review (zero-licence stack)

We run as a hosted service, so GPL components are fine when used server-side and not distributed. **AGPL is the exception**: network use triggers source-disclosure obligations.

| Component | Licence | Action |
|---|---|---|
| axe-core | MPL-2.0 | ✅ Use |
| IBM Equal Access (`accessibility-checker-engine`) | Apache-2.0 | ✅ Use (inject the engine bundle directly) |
| HTML_CodeSniffer | BSD-3 | ✅ Inject directly; pa11y (LGPL-3.0) is not needed |
| veraPDF | GPLv3+ / MPL-2.0 dual | ✅ Use under MPL-2.0 |
| pikepdf | MPL-2.0 | ✅ Use |
| **PyMuPDF** | **AGPL-3.0** / commercial | ⚠️ **Replace** with `pypdfium2` / `pdfplumber`, or buy a licence |
| python-docx, python-pptx | MIT | ✅ Use |
| EPUBCheck | BSD-3 | ✅ Use |
| Ace by DAISY | MIT | ✅ Use |
| faster-whisper | MIT | ✅ Use (no speaker labelling, see 3.7) |
| Piper TTS | Maintained fork is GPL-3.0; **voice licences vary per voice** | ⚠️ Fine server-side; check each voice's dataset licence. Kokoro-82M (Apache-2.0) is the cleaner default |
| FFmpeg | LGPL/GPL depending on build | ✅ Server-side only |
| Appium, Google ATF | Apache-2.0 | ✅ Use |
| `@guidepup/virtual-screen-reader` | MIT | ✅ Use |

"Zero licence" does not mean zero cost: LLM API spend, GPU time for Whisper, and emulator hosts are the main variable costs and need per-tenant metering (see 3.5).

### 3.2 Web scan engine

- **Single page, three engines:** Python Playwright opens the page once, waits for network idle and DOM stability, then injects pinned bundles of axe-core, IBM `ace.js` and HTML_CodeSniffer and runs them one after another on the same DOM.
- **Normalisation:** each engine's rule ID maps to a `CanonicalRule` through a versioned mapping file. Findings are deduplicated on `(canonical_rule, normalised_selector, element_fingerprint)`. Agreement between engines becomes a **confidence score**, shown in the UI.
- **Crawl:** sitemap plus same-origin link crawl with a page limit, robots.txt respected (with owner override after domain verification), politeness delay.
- **Template fingerprinting:** hash the DOM structure skeleton so findings repeated on 500 product pages group into one root cause, which cuts noise and LLM cost.
- **Engine versions are pinned and recorded on every scan** so results can be reproduced and compared over time.
- **Benchmark before launch:** measure recall and precision against known fixture suites (W3C WAI "BAD" demo, GOV.UK accessibility-tool-audit test pages) and keep that suite in CI.

### 3.3 Screen reader and keyboard analysis

- **Phase 2 (server-side):** `@guidepup/virtual-screen-reader` produces a spoken-output transcript from the live DOM in Playwright, along with the Chromium accessibility tree snapshot.
- **Keyboard and focus agent:** *deterministic first*. Playwright presses Tab/Shift+Tab/arrow keys and records focus order, visibility, traps and focus jumps compared with visual position. The LLM only interprets anomalies; it does not drive the traversal. This makes runs cheaper, reproducible and testable.
- **Later (premium):** real NVDA and VoiceOver capture via Guidepup on dedicated Windows and macOS runner hosts.

### 3.4 Multi-tenancy and Row-Level Security

- Every tenant table has `organization_id` and an RLS policy `USING (organization_id = current_setting('app.org_id')::uuid)`.
- Each request or job opens a transaction and runs `SET LOCAL app.org_id = …`. `SET LOCAL` keeps this safe with connection pooling (PgBouncer transaction mode).
- The application database role is **not** the table owner and has no `BYPASSRLS`. Super Admin uses a separate role with `BYPASSRLS` and **every cross-tenant read is written to the audit log**.
- Celery tasks carry `org_id` and set it in the same way. Workers never query without it.
- CI includes an **isolation test suite** that tries cross-tenant reads and writes through every repository function.

### 3.5 Quotas, coupons and billing

- **Quota reservations, not just counters:** add a `UsageReservation` table (`RESERVED → COMMITTED | RELEASED`) keyed by job ID (idempotent). The reserve step is a single conditional `UPDATE … SET used = used + n WHERE used + n <= quota RETURNING`, so it stays atomic under concurrency. A failure caused by the system releases the reservation; a failure caused by the user (bad URL, corrupt file) commits it. Separate `UsageLedger` rows per period, including for annual plans that reset monthly.
- **AI cost metering:** record tokens and cost per LLM call against org and job. This feeds the Super Admin FinOps view and a per-tenant spend cap.
- **Coupons:** add a `CouponRedemption` table (unique `(coupon_id, organization_id)`) and increment `current_redemptions` with a conditional update, so two simultaneous checkouts can't exceed `max_redemptions`.
- **Payments are missing from the spec.** INR pricing needs a payment gateway with GST-compliant invoices (18% GST, GSTIN capture for B2B). Recommendation: Phase 1 uses Super Admin–assigned plans and manual invoices (enough for early B2B deals); Phase 2 integrates a gateway with subscriptions and webhooks.
- **Trial expiry:** run the Celery beat job hourly. The guard also checks `trial_ends_at` on each request, so a missed cron run can never extend a trial.

### 3.6 Security of scanning untrusted content

- **SSRF:** resolve and validate the target IP *at connect time*, block private, loopback, link-local and cloud-metadata ranges (`169.254.169.254`, `fd00::/8`, etc.), re-check after redirects and against DNS rebinding. Crawlers run in a network segment that cannot reach internal services.
- **Authenticated scans:** `storageState.json` holds live customer session cookies. Encrypt it with envelope encryption (KMS), keep it for the scan only, delete it after, never log it, and show the customer a clear warning about what they are uploading.
- **Uploads:** size and page limits, MIME sniffing, zip-bomb limits for EPUB, DOCX and PPTX (they are ZIPs), malware scan (ClamAV), and processing in short-lived containers with no network.
- **APKs:** run in disposable emulators on an isolated network.
- **Domain verification** (DNS TXT or meta tag) before large crawls or authenticated scans, so the platform cannot be used to hammer third-party sites.
- **Data protection:** customer documents and screenshots may contain personal data, so we need a DPDP Act (India) / GDPR data processing agreement, retention policies per plan, and deletion on request.

### 3.7 AI gateway

- One internal `LLMGateway` interface with provider adapters (start with the providers in the spec; keep it provider-agnostic). Per-task model routing, per-tenant budgets, retries and fallback, and a response cache keyed by template fingerprint.
- **Customer data to third-party LLMs:** use zero-data-retention or enterprise agreements, let tenants opt out (falling back to deterministic-only output), and support regional endpoints for public-sector customers.
- **Human in the loop by default:** AI code fixes are suggestions with a diff and are never applied automatically. AI alt text and AD scripts need approval before they go into a delivered file.
- **Evaluation harness:** a golden set of issues with expected fixes and alt text, scored in CI whenever prompts or models change.
- **Speaker labels:** faster-whisper does not do diarization. Add WhisperX or pyannote in Phase 4, and check model licence and terms.

### 3.8 Compliance mapping accuracy

The rule registry is **legal content**, so it needs SME review and versioning:
- `US_ADA_TITLE_II` → WCAG 2.1 AA (DOJ 2024 rule; state and local government). **Add `US_ADA_TITLE_III`** (private businesses, which will be most of our customers). It has no regulatory technical standard; WCAG 2.1 AA is the de facto benchmark used in settlements.
- `US_SECTION_508` → WCAG 2.0 AA plus Chapters 3, 5, 6 ✅.
- `EU_EAA_EN_301_549` → EN 301 549 v3.2.1 (aligned with WCAG 2.1 AA), Clauses 9/10/11 ✅.
- `AU_DDA_AS_EN_301_549` → AS EN 301 549 is based on an earlier EN 301 549 edition. Mapping it to WCAG 2.2 AA is a *recommended target*, not a legal requirement, and the UI must label it that way.
- `IN_RPWD_GIGW_3` → GIGW 3.0 + IS 17802 ✅.
- Every mapping row stores source citation, version and `reviewed_by` / `reviewed_at`. Compliance scores show "Automated coverage: X of Y criteria tested" so a score is never presented as full conformance.

### 3.9 Worker topology

Different workers need very different runtimes, so build **separate images and Celery queues** instead of one large worker:

| Queue | Image contents | Notes |
|---|---|---|
| `web` | Python + Playwright Chromium + engine bundles + Node (for the virtual screen reader) | Memory-heavy; limit concurrency per container |
| `docs` | Python + JRE (veraPDF, EPUBCheck) + Node (Ace) | CPU |
| `media` | Python + FFmpeg + faster-whisper | GPU optional, large disk |
| `mobile` | Appium + Android emulator | Needs **KVM**: bare-metal or nested-virt hosts, not standard serverless containers |
| `ai` | Lightweight Python | I/O-bound LLM calls, high concurrency |

Celery on Redis: use `acks_late`, idempotent task IDs, and set `visibility_timeout` above the longest job (video), or move long media jobs to RabbitMQ.

### 3.10 Proposed repository layout

```text
apps/
  web/                 Next.js (App Router, TS) – all three dashboards + marketing
  api/                 FastAPI service + Alembic migrations
libs/
  core/                Shared Python: models, RLS session, guardrails, storage, LLM gateway
workers/
  web_audit/           Playwright + injected engines
  documents/           PDF / DOCX / PPTX / EPUB
  media/               FFmpeg + Whisper + TTS
  mobile/              Appium + emulator (Phase 5)
packages/
  ui/                  Accessible component library (React Aria) + design tokens + Storybook
  engine-bundles/      Pinned axe-core / IBM / HTMLCS browser bundles
rules/                 Versioned rule registry + standard mappings (YAML, SME-reviewed)
fixtures/              Known-bad test sites/files for scanner benchmarks
infra/                 docker-compose, Dockerfiles, deployment
docs/                  Architecture, plan, ADRs, accessibility statement
```

---

## 4. Phased build plan

Each phase ends with exit criteria, not dates, because timelines depend on team size. Accessibility gates from section 2.6 apply from Phase 0 onward.

### Phase 0: Foundations

**Scope**
- Monorepo layout (3.10), `docker-compose.yml` (Postgres 16, Redis, MinIO, API, workers, web), `.env.example`, Makefile.
- CI pipeline: lint, type checks, unit tests, Alembic migration check, **all PR accessibility gates**, container builds, secret scanning.
- `packages/ui`: design tokens (contrast-validated), React Aria base components (Button, Link, TextField, Select, Dialog, Table, Tabs, Toast, Meter, ProgressBar), Storybook with the a11y addon.
- App shell: landmarks, skip link, route announcer, focus management, consistent help entry, error pages.
- Accessible auth: signup, login, email verification, password reset, invite acceptance (SC 3.3.8). Short-lived JWT access tokens plus refresh tokens in `httpOnly` cookies.
- Postgres RLS framework plus the isolation test suite.
- ADRs for: component library, cloud target, LLM providers, broker.

**Exit criteria**
- `docker compose up` brings up the full stack with seed data in one command.
- Zero axe violations on every shell route. Keyboard and screen reader smoke test passed (NVDA + VoiceOver).
- Cross-tenant isolation tests are green.

### Phase 1: MVP, sellable web accessibility audits

**Scope**
- **SaaS core:** Plans, Organizations, Users and roles, Seat Limit Guard with upgrade prompt, Trial engine (14 days → `LOCKED_READ_ONLY`), Coupons + Redemptions, Usage Ledger + Reservations, audit logs.
- **Rule registry:** WCAG 2.0/2.1/2.2 (A/AA, plus 2.2 AAA as informational), Section 508, ADA Title II + III, EN 301 549 Clause 9, GIGW 3.0, AU target. Switching standards recalculates scores and filters on existing scan data.
- **Web scanner:** single URL + bounded crawl, three engines in one page, normalisation, deduplication, confidence score, template clustering, full-page + element screenshots, pinned engine versions.
- **AI Code-Fix Copilot:** one suggested HTML/ARIA/React patch per clustered root cause, with explanation and the WCAG SC it addresses. Copy-only.
- **Reports:** in-app results, CSV, **accessible PDF (veraPDF-gated)**, DOCX; **VPAT 2.5 draft** (WCAG / 508 / EU / INT editions) with "Not Evaluated" defaults and required human sign-off before export.
- **Dashboards (first version):**
  - `/workspace`: New Scan dialog (URL + standards), live progress, findings list with filters, web Fix Workbench (issue list ↔ screenshot ↔ code fix), report export.
  - `/org`: team and invites with live "X of Y seats used", quota meters, plan details, coupon entry, branding (logo only).
  - `/admin`: tenant directory, plan and coupon CRUD, manual plan assignment, trial funnel counts.
- **Security:** SSRF protections, domain verification, rate limits.
- **Platform accessibility:** Accessibility Statement published; first human audit of our own UI.

**Exit criteria**
- Scanner benchmark (fixture suite) recall/precision recorded and above the agreed baseline.
- Quota and coupon concurrency tests pass (no overspend under parallel requests).
- Every exported PDF passes veraPDF; DOCX golden tests pass.
- Our own ACR drafted from a human audit; zero open Critical/Serious accessibility issues in our UI.
- 3–5 design partners actively scanning.

### Phase 2: Deep web audit and monetisation

**Scope**
- Authenticated scans (encrypted `storageState`, recorded login scripts).
- Deterministic keyboard and focus-trap agent, with LLM interpretation of anomalies.
- Virtual screen reader transcript in the workbench (spoken log next to the issue).
- Vision-LLM auditor: text in images, contrast over gradients and images, alt text quality, missing focus indicators.
- Scheduled monitoring, scan-to-scan regression diff, email digests (accessible HTML emails).
- Payment gateway: subscriptions, GST invoices, webhooks, `PAST_DUE` handling, self-serve upgrade checkout (SC 3.3.7-compliant).
- Super Admin: MRR/ARR, trial conversion, AI FinOps (token cost per tenant), budget caps.
- White-label: contrast-validated brand colours, custom report branding.
- Enterprise SSO (SAML/OIDC); optional here, required before large enterprise deals.

**Exit criteria**
- Self-serve trial → paid conversion works end to end without staff involvement.
- AI features pass the evaluation harness; per-tenant AI cost visible and capped.
- Release screen-reader matrix (section 2.6) passed.

### Phase 3: Documents and eBooks

**Scope** (in order of customer demand)
1. **PDF:** veraPDF audit → layout analysis (Vision-LLM + `pypdfium2`/`pdfplumber`) → tag tree, title, language, alt text via `pikepdf` → re-validate. A large share of Matterhorn Protocol checkpoints need human judgment, so complex files are routed to HITL.
2. **DOCX:** heading semantics, table header rows, alt text, document language.
3. **PPTX:** reading order, slide titles, alt text.
4. **EPUB3:** EPUBCheck + Ace, accessibility metadata in `package.opf`, landmarks, alt text, MathML.
- **HITL SME console:** queue, assignment, side-by-side review, approve/edit/reject, SLA tracking. Fully keyboard-operable, with no drag-only actions (SC 2.5.7).
- Document workbench: side-by-side preview, editable alt text, **reading-order editor with move up/down buttons** (not drag-only), "Download Remediated File".

**Exit criteria**
- Remediated files pass their validators, and SME review confirms reading order on a sample set.
- HITL turnaround SLA measured.

### Phase 4: Audio and video

**Scope**
- FFmpeg extraction → faster-whisper with word timestamps → diarization (WhisperX/pyannote) → `.vtt`, `.srt`, `.txt`, `.docx` transcripts.
- Caption editor: row-based text editing with time inputs; waveform as an optional aid; keyboard shortcuts documented and remappable (SC 2.1.4).
- Audio Description: keyframes during pauses → LLM-drafted AD script → human approval → TTS (Kokoro/Piper) → mux AD track + captions into an accessible MP4. Extended AD when pauses are too short.
- Indian-language captions (Whisper multilingual): a differentiator for the domestic market.

**Exit criteria**
- Caption accuracy (WER) measured on a reference set for each supported language.
- Player and editor pass the release screen-reader matrix.

### Phase 5: Mobile

**Scope**
- Android: APK upload → sandboxed emulator (KVM host) → Appium UiAutomator2 + Google ATF → TalkBack-order traversal, node info, screenshots → Kotlin / Jetpack Compose / React Native fixes.
- iOS (XCUITest + VoiceOver on on-demand macOS hosts) and real NVDA/VoiceOver capture for web: backlog, prioritised by customer demand.

**Exit criteria**
- Benchmark against a known-bad sample APK set; sandbox escape and network-isolation tests pass.

---

## 5. Open decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | UI primitive library | React Aria Components only (no Radix mixing) |
| 2 | Production cloud | Pick **one** for v1 (S3 or Azure Blob); keep the storage abstraction for later |
| 3 | Payment gateway and timing | Manual invoicing in Phase 1; gateway with INR + GST subscriptions in Phase 2 |
| 4 | LLM providers and data policy | Provider-agnostic gateway; zero-retention agreements; per-tenant opt-out |
| 5 | Real screen reader capture | Virtual screen reader in Phase 2; real NVDA/VoiceOver hosts as a premium backlog item |
| 6 | Celery broker | Redis to start (tuned `visibility_timeout`); revisit RabbitMQ when media jobs land |
| 7 | Rule-mapping and VPAT sign-off | Named accessibility SME (IAAP CPACC/WAS) owns mappings and VPAT approvals |
| 8 | PDF library replacing PyMuPDF | `pypdfium2` + `pdfplumber` unless we buy a commercial licence |

## 6. Top risks

| Risk | Mitigation |
|---|---|
| Overclaiming compliance (legal/regulatory exposure) | "Automated coverage X/Y" scoring, "Not Evaluated" defaults, human-signed VPATs, careful marketing copy |
| Our own UI has accessibility defects | CI gates from Phase 0, release AT matrix, disabled-user testing, public statement and feedback loop |
| Scope too broad, delaying revenue | Phase 1 kept to the web audit MVP; later phases driven by design-partner demand |
| LLM cost grows with crawl size | Template clustering, response cache, per-tenant budgets, deterministic checks before AI |
| Hostile inputs (SSRF, malicious files, APKs) | Sandboxed workers, egress controls, domain verification, malware scanning |
| Engine and rule drift over time | Pinned engine versions per scan, versioned rule registry, benchmark suite in CI |
