# Project Plan: Omni-Channel AI Accessibility Platform

**Status:** Draft v4 · 2026-11-27. v2 added model tiering and validation, templates-first reporting and notifications, the self-healing Ops Agent and Razorpay billing (3.13 to 3.16). v3 added the Phase 1 staging (1a and 1b) around work already built, the public API and enterprise integrations (3.17), and positioning, unit economics and trust (3.18). v4 adds subscription, discount and coupon management (3.19), the accessibility knowledge base with AI-assisted article authoring (3.20), and refunds and support tickets in the admin area (3.21). All v4 additions are additive and do not change Phase 1 work in progress.
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
9. **Use configuration, not code, for anything commercial or AI-related.** AI providers and models, task routing, plans, quotas, trials, coupons, payment and email providers, scan engines, compliance mappings and feature flags are all managed from the Super Admin panel. Every setting is typed, scoped (global → plan → organization), versioned, audited and can be rolled back, and changes apply without a redeploy. See [section 3.11](#311-admin-configurable-platform).
10. **Match the model to the job, and add a validation layer.** Routine work (labelling, simple alt text, common-pattern fixes, triage) runs on light, cheap models or on no model at all, and a premium model validates what matters. Output is produced, then checked by deterministic tests (our own scan engines re-run on every proposed patch), then optionally by a stronger model. Unvalidated output is never delivered. Tiers and policies are admin settings. See [section 3.13](#313-model-tiering-and-the-validation-layer).
11. **Templates first, tokens last.** Every report and every notification email is a permanent, versioned template that admins can edit, and every rule has a stored explanation and fix in a content library. AI fills only named dynamic slots, each with a deterministic fallback. See [section 3.14](#314-templates-reports-and-notifications-templates-first).
12. **Build a monitor-and-heal agent on top of ordinary resilience.** Retries, checkpoints, dead-letter queues and watchdogs handle most failures without any AI. An Ops Agent then diagnoses unfamiliar failures and acts only through an allow-listed, audited, rate-limited action catalogue, starting in suggest-only mode. See [section 3.15](#315-reliability-and-self-healing-monitor-and-heal-agent).
13. **Payments run on Razorpay.** Webhooks are the source of truth, we issue GST-compliant accessible invoices, and a nightly reconciliation catches drift. See [section 3.16](#316-billing-with-razorpay).
14. **Stage Phase 1 instead of rebuilding it.** What is already built stays as it is. The remaining Phase 1 work is split into 1a (sellable to design partners) and 1b (breadth and hardening), with an item-by-item status table. Admin MFA moves into 1a, because the admin panel already controls keys, prices and billing. See [Phase 1](#phase-1-mvp-sellable-web-accessibility-audits).
15. **Make the product integrable with a versioned public API and Swagger/OpenAPI docs.** A `/v1` API with API keys, scopes, webhooks, rate limits, generated SDKs and a CLI, added next to the existing internal routes, which are not renamed. See [section 3.17](#317-public-api-and-enterprise-integrations).
16. **Settle the market wedge and the unit economics before scaling the build.** Web scanning is a commodity. The plan needs a defined wedge, a cost-per-unit model that sets plan quotas, and the legal, security and ownership items that enterprise buyers ask for. See [section 3.18](#318-positioning-unit-economics-and-trust).
17. **Manage plans, discounts and coupons as versioned data, with one pricing function.** Plan versions with grandfathering, per-customer overrides, add-ons, automatic promotions and coupon campaigns, all feeding a single `price_quote` function that checkout, Payment Links, invoices and the pricing page share. See [section 3.19](#319-subscription-pricing-and-promotions-management).
18. **Publish accessibility articles, drafted by AI and published by people.** A knowledge base at `/learn`, with a Content Agent that plans, drafts, validates (our own scanner checks every code sample) and refreshes articles, and never publishes without a named human reviewer. See [section 3.20](#320-accessibility-knowledge-base-article-management-and-ai-authoring).
19. **Keep refunds and support in the admin area, small and auditable.** A policy-driven refund workflow with approvals and credit notes, and a lightweight built-in ticket system with SLA timers, both on the existing template, notification and audit systems. See [section 3.21](#321-refunds-and-support-tickets-admin-area).

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
- **Payments are missing from the spec.** INR pricing needs a payment gateway and GST-compliant invoices. The gateway is **Razorpay**; design, flows and the pre-build spike are in [3.16](#316-billing-with-razorpay). Phase 1 uses Super Admin–assigned plans paid through Razorpay Payment Links; Phase 2 adds self-serve subscriptions.
- **Trial expiry:** run the Celery beat job hourly. The guard also checks `trial_ends_at` on each request, so a missed cron run can never extend a trial.

### 3.6 Security of scanning untrusted content

- **SSRF:** resolve and validate the target IP *at connect time*, block private, loopback, link-local and cloud-metadata ranges (`169.254.169.254`, `fd00::/8`, etc.), re-check after redirects and against DNS rebinding. Crawlers run in a network segment that cannot reach internal services.
- **Authenticated scans:** `storageState.json` holds live customer session cookies. Encrypt it with envelope encryption (KMS), keep it for the scan only, delete it after, never log it, and show the customer a clear warning about what they are uploading.
- **Uploads:** size and page limits, MIME sniffing, zip-bomb limits for EPUB, DOCX and PPTX (they are ZIPs), malware scan (ClamAV), and processing in short-lived containers with no network.
- **APKs:** run in disposable emulators on an isolated network.
- **Domain verification** (DNS TXT or meta tag) before large crawls or authenticated scans, so the platform cannot be used to hammer third-party sites.
- **Data protection:** customer documents and screenshots may contain personal data, so we need a DPDP Act (India) / GDPR data processing agreement, retention policies per plan, and deletion on request.

### 3.7 AI gateway

- One internal `LLMGateway` interface with provider adapters. Providers, models and per-task routing are **admin-configured data, not code** (see [3.11.2](#3112-ai-provider-and-model-management)). The gateway also handles per-tenant budgets, retries and fallback, and a response cache keyed by template fingerprint.
- **Model tiers and validation:** routine tasks run on light models or on none, premium models act as validators, and unvalidated output is never delivered. See [3.13](#313-model-tiering-and-the-validation-layer).
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
| `notify` | Lightweight Python | Email and in-app notifications; isolated so a mail-provider outage cannot block scans (3.14) |
| `billing` | Lightweight Python | Razorpay webhooks, reconciliation, invoice generation (3.16) |
| `ops` | Lightweight Python | Ops Agent and runbook executor, with its own least-privilege credentials (3.15) |
| `integrations` | Lightweight Python | Outbound webhooks and Jira, GitHub and Slack sync, aware of each provider's rate limits (3.17) |
| `content` | Lightweight Python | Content Agent: article planning, drafting, validation, refresh and link checks. Its code-sample check calls the scanner through the `web` queue (3.20) |

Celery on Redis: use `acks_late`, idempotent task IDs, and set `visibility_timeout` above the longest job (video), or move long media jobs to RabbitMQ.

### 3.11 Admin-configurable platform

**Principle:** if a business, commercial or AI decision might change after launch, it is a setting managed in `/admin`, not a constant in code or an environment variable. New features add their settings to the same framework, so the admin panel grows with the product without one-off screens.

#### 3.11.1 Settings framework (built in Phase 0)

| Concern | Design |
|---|---|
| **Typed registry** | Every setting is declared once in code: `key`, type (Pydantic model), default, validation, allowed scopes, sensitivity, owner role. The admin UI **generates its forms from this registry**, so a new setting appears without UI work, and the generated forms follow our accessible form patterns (section 2.4). |
| **Scope hierarchy** | `global → plan → organization` (→ user where relevant). The UI shows the **effective value and where it came from** (for example "Inherited from GROWTH plan"). |
| **Secrets** | API keys and credentials are stored with envelope encryption (KMS / Key Vault), or as a reference to a secrets manager. They are **write-only** in the UI (shown as `••••abcd`), have rotation dates, and are never returned by the API or logged. |
| **Versioning and audit** | Every change is a new version with who, when, why (required comment) and a diff. One-click rollback to any earlier version. |
| **Safe rollout** | Draft → validate → publish. "Test connection" for providers. AI routing and prompt changes must pass the evaluation harness before activation. Optional staged rollout by percentage of tenants. |
| **Live reload** | Effective config is cached in Redis and invalidated through pub/sub. API and workers pick up changes within seconds without a redeploy. Each job records the config version it ran with, for reproducibility. |
| **Guardrails** | Validation stops unsafe states: the last enabled model for a task cannot be disabled, budgets cannot be negative, a quota cannot drop below current usage without confirmation, and white-label colours are contrast-checked. |
| **Granular admin roles** | Super Admin access is split into `PLATFORM_OWNER`, `BILLING_ADMIN`, `AI_OPS`, `COMPLIANCE_SME`, `SUPPORT` (read-only). High-risk changes (pricing, rule mappings, provider credentials) can require **two-person approval**. |
| **Not admin-configurable** | Database URLs, master encryption keys, RLS policies and network/sandbox settings stay in environment variables and infrastructure-as-code. The admin panel must never be able to weaken tenant isolation or security. |

#### 3.11.2 AI provider and model management

The provider list is open-ended. Adding a provider means adding a row in the admin panel, and, for a brand-new API style, one adapter class.

| Provider type | Examples | Notes |
|---|---|---|
| `openai` | OpenAI | |
| `azure_openai` | Azure OpenAI | Deployment name + API version + region |
| `anthropic` | Claude (Anthropic API) | |
| `bedrock` | AWS Bedrock (Claude, Llama, Mistral, etc.) | IAM role or keys + region |
| `vertex` / `gemini` | Google Gemini | |
| `deepseek` | DeepSeek API | Hosted API processes data in China. Flag it so government or regulated tenants can exclude it; open weights can be self-hosted instead |
| `mistral`, `groq`, etc. | Other hosted APIs | |
| `openai_compatible` | vLLM, Ollama, OpenRouter, self-hosted open-weight models | Any endpoint that speaks the OpenAI API; good for on-premises or data-residency deals |

Recommended implementation: our own `LLMGateway` interface over **LiteLLM** (MIT, 100+ providers), with the dependency pinned and hash-locked, or thin native adapters where we need provider-specific features. The rest of the codebase never imports a provider SDK directly.

**Data model**

```text
AIProvider      id, type, display_name, base_url, region, credential_ref (secret),
                data_policy {zero_retention, processing_regions[], gov_approved},
                is_enabled, health_status, last_checked_at
AIModel         id, provider_id, model_name, tier (LIGHT|STANDARD|PREMIUM),   -- see 3.13
                capabilities {text, vision, json, tools},
                context_window, input_cost_per_1m, output_cost_per_1m, is_enabled
AITask          key: code_fix | vision_audit | alt_text | mathml | ad_script |
                     vpat_narrative | focus_anomaly | doc_layout | ...
AITaskRoute     task_key, scope (global|plan|org), scope_id,
                primary_model_id, fallback_model_ids[], params {temperature, max_tokens, timeout},
                prompt_template_version_id, is_active
PromptTemplate  task_key, version, body, eval_score, status (draft|active|retired)
OrgAICredential org_id, provider_id, credential_ref   -- Enterprise "bring your own key"
AIUsage         org_id, job_id, task_key, model_id, tokens_in/out, cost, latency, status
```

**Admin screens (`/admin/ai`)**
- **Providers:** add or edit, enter credentials once (write-only), "Test connection", enable/disable switch, health status.
- **Models:** catalogue per provider with capabilities and prices (prices drive FinOps cost reports).
- **Task routing:** for each AI task, set the tier ladder (which tier produces, which validates, when to escalate; see [3.13](#313-model-tiering-and-the-validation-layer)) and, within each tier, a primary model and an ordered fallback chain. The router only offers models with the required capability (for example vision for `vision_audit`). Overrides are possible per plan or per organization.
- **Prompts:** versioned templates per task, with evaluation score shown; activation is blocked if the score falls below the threshold.
- **Budgets and limits:** token and cost caps per tenant and per plan, rate limits per provider, alert thresholds.
- **Data policy:** organizations can restrict processing regions or require zero-retention providers. The router then automatically leaves out providers that don't qualify, and if none qualify, the AI step is skipped and the run falls back to deterministic-only output, never silently ignoring the restriction.
- **FinOps:** cost per tenant, task, model and provider; error and fallback rates; latency.

#### 3.11.3 Other configurable areas

| Area | What admins control | Phase |
|---|---|---|
| **Plans and entitlements** | Plans, prices (INR + other currencies), billing cycles. Quotas and features go in an `PlanEntitlement(plan_id, feature_key, limit)` table instead of fixed `quota_*` columns, so new quotas or features need no schema migration | 1 |
| **Trials** | Length, trial plan, grace period, behaviour after expiry, reminder schedule | 1 |
| **Coupons** | Type, value, validity, max redemptions, plan applicability, stacking rules, first-purchase-only | 1 |
| **Compliance registry** | Standards, rule ↔ clause mappings, versions; SME review workflow before publish | 1 |
| **Scan engines** | Enable/disable each engine, pinned version, crawl page limits, timeouts and concurrency per plan | 1 |
| **Email and notifications** | Provider (SMTP / SES / other), sender identity, templates, and which event sends what to whom and when (3.14) | 1 |
| **Feature flags** | Global, per plan, per tenant, percentage rollout, kill switches | 1 |
| **Payment gateway and tax** | Razorpay account (mode, keys, webhook secret), plan sync, GST settings, invoice series, dunning and grace periods (3.16) | 1 (payment links), 2 (subscriptions) |
| **Auth and security policy** | SSO providers per tenant, MFA enforcement, session length, password policy, IP allow-lists | 1 (admin MFA), 2 (the rest) |
| **White-label defaults** | Allowed customisations per plan, report branding | 2 |
| **Data retention** | Retention period per plan and asset type, deletion schedules | 2 |
| **HITL** | SME teams, skills, routing rules, SLAs, escalation | 3 |
| **Media** | STT models, supported languages, TTS engines and voices, AD style guide | 4 |
| **Mobile** | Device and emulator profiles, Android API levels | 5 |
| **Legal content** | Terms, privacy policy, Accessibility Statement, versions shown to users | 1 |
| **Report templates and rule content** | Report layouts, rule explanations and fix examples, with review workflow and versioning (3.14) | 1 |
| **AI tiers and validation** | Tier per model, tier ladder per task, validation mode and sample rate, escalation limits (3.13) | 1 |
| **Ops Agent** | Autonomy level per action, runbooks, canaries, escalation contacts, token budgets (3.15) | 2 |
| **Public API and integrations** | API access and rate limits per plan, key lifetime, webhook limits, docs visibility, enabled integrations and their OAuth app credentials (3.17) | 1 |
| **Plan versions, promotions and coupon rules** | Plan versions and grandfathering, entitlement overrides, add-ons and top-ups, automatic promotions, coupon eligibility, stacking and caps, campaigns, pricing-page content (3.19) | 1a (quote), 1b, 2 |
| **Knowledge base and Content Agent** | Content types and templates, source pack, style guide and banned phrases, task routes, review periods, weekly cap, autonomy per type (3.20) | 2 |
| **Refunds and support** | Refund policy and thresholds, ticket categories, priorities, SLA targets, canned replies, retention, AI help on or off (3.21) | 5 (basic refund in 2) |

### 3.12 Proposed repository layout

```text
apps/
  web/                 Next.js (App Router, TS) – all three dashboards + marketing
  api/                 FastAPI service + Alembic migrations
libs/
  core/                Shared Python: models, RLS session, guardrails, storage, LLM gateway, payment providers, template renderer
workers/
  web_audit/           Playwright + injected engines
  documents/           PDF / DOCX / PPTX / EPUB
  media/               FFmpeg + Whisper + TTS
  mobile/              Appium + emulator (Phase 5)
  notify/              Email and in-app notification delivery (3.14)
  billing/             Razorpay webhooks, reconciliation, invoices (3.16)
  ops_agent/           Monitor-and-heal agent and runbook executor (3.15)
packages/
  ui/                  Accessible component library (React Aria) + design tokens + Storybook
  engine-bundles/      Pinned axe-core / IBM / HTMLCS browser bundles
rules/                 Versioned rule registry + standard mappings (YAML, SME-reviewed)
  content/             Rule content library: plain-language explanation and fixes per rule (3.14)
templates/             Default report and notification templates, shared accessible blocks (3.14)
runbooks/              Self-healing runbooks (YAML) and their fault-injection tests (3.15)
fixtures/              Known-bad test sites/files for scanner benchmarks
infra/                 docker-compose, Dockerfiles, deployment
cli/                   `a11y` command-line tool and CI wrappers (GitHub Action, GitLab CI) (3.17)
sdks/                  Generated API client libraries (3.17)
docs/                  Architecture, plan, ADRs, accessibility statement; api/ holds the published OpenAPI spec and changelog
```

### 3.13 Model tiering and the validation layer

**Principle:** spend premium-model tokens only where a wrong answer is costly or hard to detect. Routine work runs on cheap models or on no model at all, and a stronger model checks the output that matters.

**Resolution ladder.** Every AI task tries the cheapest rung first and stops at the first rung that produces a validated result:

| Rung | What | Tokens |
|---|---|---|
| 1 | Content library or cache hit (rule library text, response cache keyed by template fingerprint) | 0 |
| 2 | Deterministic recipe: a DOM or AST patch for a known pattern (add `lang`, associate a `<label>`, mark a decorative image `alt=""`, add table header scope) | 0 |
| 3 | `LIGHT` model | Low |
| 4 | `STANDARD` model (escalation) | Medium |
| 5 | `PREMIUM` model (escalation, or the validator) | High |
| 6 | Human review (HITL queue) | None, but slow and costly |

**Tiers.** Tier is an attribute of each model in the admin panel (`AIModel.tier`), so which concrete models sit in which tier is a setting, not code.

| Tier | Typical models (examples only; admins decide) | Used for |
|---|---|---|
| `LIGHT` | Small, fast, cheap: Haiku-, Flash- and mini-class models, DeepSeek, self-hosted open-weight models | Normalising and labelling findings, naming root-cause clusters, simple alt text, patches for common patterns, caption clean-up, language detection, incident triage |
| `STANDARD` | Mid-size general models | Component-level code patches, vision audit of screenshots, document layout analysis, audio-description drafts, diagram alt text |
| `PREMIUM` | Top reasoning and frontier models | **Validation**, STEM and MathML, complex charts, VPAT conformance reasoning, resolving disagreement between engines, diagnosing novel incidents |

**Validation layer: produce, then verify.** Three validators, cheapest first:

1. **V1, deterministic (always on, no tokens).** Schema and JSON validity; the patch applies cleanly; the **re-scan oracle**: apply the patch to an isolated copy of the DOM fragment, re-run the scan engines, and require that the targeted violation is gone and no new one appears; the cited WCAG criterion exists in the registry; alt-text rules (length, no "image of", not a filename, correct language); every number in a generated narrative matches the data; veraPDF, EPUBCheck and Ace re-validation for files; MathML parses and renders. Our own scan engines act as the oracle, which is a structural advantage over general-purpose AI tools.
2. **V2, LLM validator (`PREMIUM`, policy-driven).** Reviews the producer's output against the evidence (screenshot, DOM, rule) and returns pass or fail with reasons in a strict schema. It prefers a **different model family** from the producer, to avoid correlated mistakes. Mode per task: `always`, `sample` (a percentage), `on_low_confidence` or `never`.
3. **V3, human.** The HITL queue takes anything left after escalation and all high-risk categories. An SME also audits a small sample of validator "passes", so we can measure the validator's own precision.

**Escalation.** Per task: `max_attempts`, `escalate_on` (validation failure, unparsable output, timeout, low confidence), `max_cost_per_item` and `max_cost_per_job`. On a validation failure there is one repair attempt on the same tier with the validator's feedback in the prompt, then escalation by one tier. When the ladder is exhausted the item becomes `needs_review`: **unvalidated output is never delivered**. Model self-reported confidence is not trusted alone; confidence comes from validator results, agreement between scan engines, and agreement with the deterministic recipe.

**Defaults by task** (all editable in admin):

| Task | Producer | Validation |
|---|---|---|
| Finding normalisation, cluster names | Light | V1 |
| Code fix, known pattern | Recipe, then Light | V1 re-scan oracle |
| Code fix, component-level | Standard | V1 + V2 sampled |
| Alt text, simple images | Light | V1 + V2 sampled, user approval |
| Alt text, charts and diagrams | Standard | V1 + V2 always, user approval |
| Vision audit findings | Standard | V2 on serious and critical findings; shown as "AI-detected, please confirm" |
| STEM and MathML | Premium | V1 + V2 always + SME |
| Audio description script | Standard | V2 always + user approval |
| VPAT remarks and conformance level | Standard draft | V2 always + human sign-off |
| Incident triage (3.15) | Light | V1 + policy engine |
| Novel incident diagnosis (3.15) | Premium | Policy engine + human approval |

**Cost controls.** Prompt caching for long static prefixes (rule text, instructions) where the provider supports it. Batch or async APIs at a discount for non-interactive work (scheduled monitoring, bulk alt text). Structured output with `max_tokens` caps. DOM snippets and computed context instead of whole pages. Downscaled images for vision. One fix per template fingerprint, not per page. Per-job and per-tenant budgets with a hard stop.

**Evidence-driven tuning.** Each task has a golden set scored per model. To move a task to a cheaper model, an admin runs it in **shadow mode** on real items; the console shows the quality delta and the cost delta against the current route, and promotion is blocked below the evaluation threshold. Tracked: cost per accepted fix, first-pass acceptance by tier, escalation rate, validator rejection rate, validator precision (from V3 audits), and tokens avoided by rungs 1 and 2.

**Data model additions to 3.11.2:** `AIModel.tier`; `AITaskRoute` becomes per stage (`produce` or `validate`) with an ordered chain of tiers, each holding models; `ValidationPolicy(task_key, mode, sample_rate, validator_tier, require_different_provider)`; `EscalationPolicy`; `AIUsage` gains `stage`, `attempt`, `escalated_from` and `validator_verdict`. New admin screens: tier per model, ladder editor per task, validation policy editor, and a cost-versus-quality dashboard.

### 3.14 Templates, reports and notifications (templates first)

**Principle:** static content costs zero tokens. Every report and every notification is a permanent, versioned template. AI fills only named dynamic slots, each with a deterministic fallback, and its output is cached by input hash.

**Reports with permanent templates**

| Report | Formats | Optional AI slot (admin toggle per plan) |
|---|---|---|
| Full audit report | PDF (PDF/UA), DOCX, CSV, JSON | Executive summary paragraph |
| One-page executive summary | PDF | None; generated from data |
| VPAT 2.5 / ACR (WCAG, 508, EU, INT editions) | DOCX, PDF | "Remarks and explanations" on partial and failing rows |
| Document remediation report (before and after validator results) | PDF, DOCX | None |
| Media report (captions, audio description) | PDF | None |
| Mobile report | PDF | None |
| Scan-to-scan regression report | PDF, email digest | None |
| Usage and quota statement | PDF, CSV | None |
| GST tax invoice, credit note, receipt | PDF/UA | None |
| Super Admin reports (MRR/ARR, AI FinOps, trial funnel) | CSV, PDF | None |

**Notification event catalogue.** Every event maps to a template, channels, recipients and timing, all editable in admin:

- **Account:** verify email, welcome, invite, invite reminder, password reset, new-device sign-in, MFA change, data export ready, account deletion.
- **Trial:** started, ending (days configurable, for example 7 / 3 / 1), expired and locked, converted.
- **Usage:** quota at 80% and 100%, seat limit reached, plan changed, coupon applied.
- **Scans and files:** complete, failed (with a credit-refund notice), regression detected, scheduled digest, remediated file ready, review assigned, review completed.
- **Billing:** payment link, payment succeeded with invoice, payment failed with retry date, final notice, subscription cancelled, renewal reminder, refund processed.
- **Operations (to admins):** provider outage and fallback active, incident opened and resolved, budget threshold reached, agent action awaiting approval.

Channels: email and an in-app notification centre in Phase 1; outbound webhooks (3.17) in Phase 1b; Slack or Teams alerts in Phase 2.

**How the template system works**

| Concern | Design |
|---|---|
| **Registry** | Each template is declared in code: `key`, channels, variable schema (Pydantic), sample data, default content, category (`transactional`, `product`, `marketing`) and `requires_approval`. |
| **Versions** | `TemplateVersion(key, locale, channel, subject, body, scope, status, author, comment, a11y_check)`. One published version per key, locale, channel and scope (global, or organization for white-label). A generated report records the `template_version_id` it used. |
| **Rendering** | Sandboxed Jinja2 with autoescape and whitelisted variables only. Saving fails on an unknown variable or a syntax error. Plurals and dates go through ICU-style helpers, with a locale fallback chain (for example `ta` → `en`). |
| **Shared blocks** | Header, heading, paragraph, button, table and legal footer are built and accessibility-tested once, then reused by every email and report, so a brand change is made in one place. |
| **Editor (`/admin/templates`)** | Subject, preheader and body as source, with a variable picker, side-by-side preview (desktop, mobile, dark mode, plain text), "send test to me", diff, rollback and publish. Billing and legal templates need two-person approval. **No WYSIWYG widget** unless it passes our own audit: most fail, and a source editor with live preview is easier to make accessible. |
| **Save-time checks (blocking)** | Required variables present; renders with sample data; our own scanner on the rendered HTML (heading order, link text, contrast, alt text, `lang`, text size, reflow); no broken links; unsubscribe and legal footer where the category requires them; size limit. |
| **CI** | A golden-render test for every template and locale, using sample data. |
| **Fallback** | If a published template fails at send time, the last known-good version is used and an incident is raised (3.15). |
| **Delivery** | `notify` queue; an idempotency key per event and recipient; email provider from the registry (3.11.3) with failover; retries with backoff; bounce and complaint handling into a suppression list; per-user preferences (transactional mail cannot be switched off); digests; rate limits; an SPF, DKIM and DMARC checklist for the sender domain; no open-tracking pixels by default, for privacy. |
| **Log** | `NotificationLog(event, template_version, recipient, status, provider_message_id, variables_hash)` for support and audit, with a retention limit. |

**Rule content library (the biggest token saver).** For every `CanonicalRule` we keep, once: a plain-language title and summary, why it matters, who is affected, how to fix it (steps), before-and-after code for each stack (HTML, React, Angular, Jetpack Compose, SwiftUI), WCAG and legal clause links, the test method, and severity guidance. It is authored in `rules/content/*.yaml` (LLM-assisted drafting at authoring time, SME review, versioning, localisable) and edited through the compliance registry's review workflow. At scan time findings are filled by lookup. AI is called only for **context-specific patches** where the generic example does not fit, following the ladder in 3.13.

**Report assembly.** A report is `template + data snapshot`, rendered deterministically:
- Jinja2 → HTML → Chromium print to **tagged PDF** (document title, language, headings, table header cells, bookmarks) → veraPDF gate, with `pikepdf` repairs where tags are incomplete. Whether Chromium's tagged output reaches PDF/UA-1 without repairs is a Phase 0 spike.
- DOCX through python-docx or docxtpl with real Heading styles and table header rows. CSV from code.
- Charts are rendered server-side as SVG with `<title>` and `<desc>` and an adjacent data table.
- The snapshot is stored, so any report can be re-downloaded or re-rendered later at no token cost. A template change affects new reports only, unless the user regenerates.
- **Narrative paragraphs** default to deterministic text built from the data ("142 issues across 38 pages; 12 are critical; the most common is..."). An AI narrative is an optional toggle per report type and plan, produced by the light tier, cached by input hash, and checked by V1 (every number in the text must match the data).

**Rule of thumb:** zero tokens for emails, report structure, rule explanations and invoices. Tokens go only to per-customer context: code patches, alt text, vision findings and optional narrative slots. FinOps reports "tokens avoided" next to "tokens spent".

### 3.15 Reliability and self-healing (monitor-and-heal agent)

**Scope:** any step in the platform that fails unexpectedly and unattended: scans, remediation jobs, AI calls, queues, webhooks, email, scheduled jobs.

**Principles:** (1) heal deterministically first, because it is cheap, predictable and testable; (2) the agent diagnoses, and acts only through an allow-listed catalogue of bounded actions; (3) every action is reversible, rate-limited and audited; (4) the healer must not depend on what it heals.

**Layers**

| Layer | What | AI? |
|---|---|---|
| 0. Resilient by design | Built into every job (below) | No |
| 1. Detection | Watchdogs, SLO alerts, synthetic canaries, reconciliation | No |
| 2. Runbooks | Versioned, tested remediation steps for known failure signatures | No |
| 3. Ops Agent | Triage, diagnosis of unknown failures, proposes or runs catalogue actions | Yes, bounded |
| 4. Humans | Approvals, and anything outside the catalogue | n/a |

**Where things break, and what happens automatically**

| Area | Typical failures | Automatic response |
|---|---|---|
| Web scans | Browser crash, hang or out-of-memory; target blocks us (403, 429, WAF); crawl traps; redirect loops; TLS errors | Kill and retry in a fresh browser; resume from the crawl checkpoint; per-domain back-off; page and depth caps; blocked pages recorded with a reason; partial results delivered |
| AI providers | Outage, 429, invalid JSON, expired or revoked key, deprecated model, runaway cost | Circuit breaker, then the fallback chain (3.11.2); repair-retry on invalid output; key-expiry alerts; per-job and per-tenant budget stop |
| Queue and workers | Lost or stuck tasks, poison messages, redelivery loops, backlog | Heartbeats and a stuck-job sweeper; retry cap, then the dead-letter queue; quarantine; scale workers within limits |
| Documents | Encrypted or corrupt files, JVM out-of-memory, validator still failing after remediation | Classify as user fault or system fault (3.5); route to review; never deliver an unvalidated file |
| Media | FFmpeg or GPU out-of-memory, transcription loops | Chunked processing with resume; duration limits |
| Mobile | Emulator will not boot, ADB offline, Appium session dies | Recycle the emulator; retry on another host |
| Billing | Missed, duplicate or out-of-order webhooks; credits stuck in `RESERVED`; missed trial job | Idempotent handlers; nightly reconciliation; reservation sweeper; request-time trial check |
| Email | Provider down, bounces, template render error | Provider failover; retry; last known-good template |
| Platform | DB connection exhaustion, slow queries, full disk, certificate expiry | Alerts and a runbook (the agent suggests but does not act) |

**Layer 0: in every job.** An explicit state machine (`QUEUED → RUNNING → SUCCEEDED | FAILED | NEEDS_REVIEW | CANCELLED`, plus `RETRYING`); a heartbeat; idempotency keys; checkpoints; timeouts and resource limits; a retry policy by error class (transient, user fault, system fault, poison); a dead-letter queue; circuit breakers per provider, engine and target domain; bulkheads (per-queue concurrency); graceful degradation (a scan whose AI step is down still completes with deterministic findings, flagged "AI step skipped"); and release of the credit reservation on a system fault (3.5).

**Layer 1: detection.** Stuck-job sweeper; queue age and depth; error-rate and latency SLOs per queue, provider, engine and domain; **synthetic canaries** (scan a known fixture page, send a tiny prompt to each provider, send a test email, check the Razorpay webhook heartbeat); cost-anomaly detection; billing reconciliation; orphaned-reservation sweeper. Each detection opens an `Incident` with a fingerprint, so repeats are grouped, not duplicated.

**Layer 2: runbooks.** `runbooks/*.yaml` holds the trigger signature, diagnostics to collect, ordered steps from the action catalogue, a verification check, rollback, maximum attempts and escalation. Runbooks are versioned and **tested with fault injection** in CI and in periodic game days. Most incidents end here, with no tokens spent.

**Layer 3: Ops Agent.** Event-driven: it starts when an incident opens and does not poll continuously, which saves tokens. Flow: triage → diagnose → plan → act through the policy engine → verify → report and learn.

*Action catalogue and default autonomy (all editable in `/admin/ops`):*

| Class | Examples | Default |
|---|---|---|
| A: safe and reversible | Retry a job; resume from a checkpoint; release an orphaned reservation; recycle a worker, browser or emulator; close a circuit breaker after the canary passes | Auto, with notification |
| B: bounded configuration | Switch an AI route to its fallback (auto-reverts when the primary is healthy); lower crawl concurrency; pause or resume a queue; scale workers within limits; disable a failing engine for N hours | Auto only for runbooks with a proven record, otherwise approval |
| C: customer-affecting | Fail a job with a reason and refund credits; cancel a tenant's jobs | Approval |
| D: forbidden | Change prices, plans or quotas; read or write secrets; touch RLS or security settings; read customer content; delete data; deploy code | The agent has no tool for these |

Autonomy levels, set per action and per environment: **Observe → Suggest → Approve-to-run → Auto-with-notify**. Everything ships at Suggest. An action is promoted to Auto only after a configurable number of supervised successes, and the console shows that evidence.

*Safeguards:*
- A deterministic **policy engine** authorises every action. The agent outputs structured proposals only, and tool arguments are validated against schemas.
- **Untrusted input:** logs, URLs, page content and uploaded files are data, never instructions. Customer content and secrets are redacted before anything reaches a model; the agent works from error signatures, stack frames, metrics and ids.
- Rate limits and blast-radius caps (for example no more than N jobs per hour, one route switch per provider per hour). Loop guard: after N attempts on one fingerprint, hand over to a human. Temporary changes expire or auto-revert. A global kill switch.
- Token budgets per incident and per day: `LIGHT` tier for triage and `PREMIUM` for novel diagnosis (3.13). If every AI provider is down, the agent falls back to runbook-only mode.
- It runs as its own `ops` service and queue, with least-privilege credentials and a read-only database role. **Watching the watcher:** a simple external uptime and dead-man's-switch check covers the agent and the core.

*Learning loop:* a fix the agent finds for a new failure becomes a draft runbook, and a human approves it before it joins the library. Each incident gets a templated post-incident summary (3.14) and a drafted backlog item for the permanent fix.

**Ops console (`/admin/ops`):** incident list and timeline with the agent's reasoning and evidence, pending approvals (fully keyboard-operable), runbook library, autonomy matrix, canary status, heal rate, mean time to recovery, and the agent's own token cost.

**Customer-visible behaviour:** job pages say "Retrying automatically (attempt 2 of 3)"; users are told only if the outcome changes; credits are refunded automatically on system faults; a public status page fed by the canaries arrives in Phase 2.

**Observability baseline (Phase 0):** structured JSON logs carrying `trace_id`, `job_id` and `org_id`; OpenTelemetry traces; Prometheus metrics; Grafana dashboards; Loki for logs; an open-source error tracker (GlitchTip or similar); Alertmanager routing to email and Slack. One ADR picks the stack.

### 3.16 Billing with Razorpay

**Decision:** Razorpay is the payment gateway (INR). It sits behind a `PaymentProvider` interface with a fake provider for tests, so the admin gateway registry (3.11.3) still holds and another gateway can be added later.

**Which Razorpay product for which case**

| Case | Razorpay product | Notes |
|---|---|---|
| Self-serve monthly plans | Subscriptions (auto-debit by card, UPI AutoPay or e-mandate) | Webhooks drive state |
| Annual plans, and anything above e-mandate limits | Orders + Checkout, or Payment Links, with renewal reminders (or a yearly subscription if limits allow) | Decide in the spike. RBI rules require per-charge customer authentication for recurring debits above a per-transaction limit (₹15,000 when last checked; verify the current figure) |
| Enterprise and invoice-based | Payment Link on a GST invoice, or bank transfer to a virtual account (NEFT, RTGS, UPI) | Reconcile TDS deductions on bank transfers |
| First design partners (Phase 1) | Super Admin assigns the plan and creates a Payment Link; the `payment_link.paid` webhook activates it | Same webhook pipeline as later phases |
| Refunds | Refund API plus a credit note | Admin-initiated, reason required |

**Self-serve flow**
1. On `/org/billing` the admin picks plan, cycle and coupon. The server calculates the price (our coupon engine is the source of truth; amounts are integers in paise) and shows a GST preview.
2. The server creates a local `CheckoutSession` (with an idempotency key) and the Razorpay subscription or order. Razorpay Plans are created lazily and mapped through `RazorpayPlanMap(plan, cycle, amount) → razorpay_plan_id`.
3. The browser opens Razorpay Checkout with the public `key_id` and ids only. The success callback is a hint: the server verifies its HMAC signature, but **entitlements change only after the webhook**.
4. **Webhook receiver:** verify `X-Razorpay-Signature` (HMAC-SHA256 of the raw body with the webhook secret), de-duplicate by event id in `WebhookEvent` (unique key), store the raw payload, enqueue on the `billing` queue and return 200 quickly. Handlers are idempotent and tolerate out-of-order delivery by re-fetching authoritative state from the Razorpay API when in doubt.
5. The handler updates `Subscription`, `Payment` and `Invoice`, sets `subscription_status` and entitlements, confirms the coupon redemption (only on payment success), and sends the invoice and notifications from templates (3.14).
6. A nightly reconciliation compares Razorpay payments and subscriptions with ours. Mismatches open an incident (3.15).

**Status mapping.** Razorpay subscription states (`created`, `authenticated`, `active`, `pending`, `halted`, `cancelled`, `completed`, `expired`, `paused`) map to our `TRIALING / ACTIVE / PAST_DUE / LOCKED_READ_ONLY` plus a `cancel_at_period_end` flag. A failing charge (`pending`) shows a warning and keeps access. `halted` becomes `PAST_DUE`, then `LOCKED_READ_ONLY` after an admin-configurable grace period. `cancelled` keeps access to the end of the paid period. Cancelling never deletes data. Dunning messages come from templates.

**Plan changes.** Upgrades take effect immediately, with the prorated difference charged as a one-off payment. Downgrades take effect at the next cycle. Entitlements change with the plan. Razorpay's own change semantics are verified in the spike.

**Coupons.** Razorpay only ever sees the final amount; Razorpay Offers (managed in its dashboard) are not used. Version 1 supports a percentage or fixed discount for the first cycle, the first N cycles, or the lifetime of the subscription. A redemption is confirmed only on payment success, and an abandoned checkout releases it.

**GST and invoicing (India).** A billing profile holds legal name, address, state and an optional GSTIN (format and checksum validation). We issue the tax invoice ourselves, because a gateway receipt is not a GST invoice: a gap-free sequential series per financial year; CGST + SGST or IGST by place of supply; GST rate and SAC code as admin settings, confirmed with a chartered accountant; credit notes for refunds; e-invoicing (IRN) if our turnover crosses the threshold; statutory retention. **Invoices are accessible PDF/UA** from the template system.

**Data model.** `PaymentGatewayAccount` (mode test or live, key id, secret references), `BillingProfile`, `Subscription`, `Payment`, `Invoice`, `CreditNote`, `Refund`, `WebhookEvent`, `CheckoutSession`, `RazorpayPlanMap`, `DunningAttempt`. All are tenant-scoped under RLS except the gateway configuration.

**Admin screens**
- `/admin/billing`: gateway setup (mode, keys, webhook secret, test connection, webhook health), Razorpay plan sync with drift detection, subscriptions, payments, failed payments and dunning, refunds, invoices (re-send, re-download), reconciliation report, and GST settings (legal entity, GSTIN, state, SAC, rate, invoice series, bank details).
- `/org/billing`: current plan and next charge date, plan change, coupon, GSTIN and billing address, payment-method update, invoice history, cancel.

**Security.** Card data never touches our servers; hosted Checkout keeps PCI scope minimal. The key secret and webhook secret live in the secrets store, write-only. Test and live modes are separate, with a visible "TEST MODE" banner. The webhook endpoint is signature-only and rate-limited. Stored payloads are minimised and retention-limited. Every admin billing action is audited; refunds above a threshold and price changes need two-person approval.

**Accessibility of paying.** Razorpay Checkout is third-party UI that we do not control. We test it with keyboard, NVDA and VoiceOver in the spike and report the result in our Accessibility Statement. An accessible fallback is always available: a hosted Payment Link, bank transfer against an invoice, or support-assisted payment. Our own billing screens (plan picker, GSTIN form, invoice list) meet section 2 in full.

**Testing.** A `PaymentProvider` fake for unit tests; contract tests on recorded sandbox payloads; signed-webhook replay tests (duplicate, out-of-order, late, forged); coupon concurrency tests; reconciliation tests. Automating the Checkout iframe is flaky, so Checkout itself stays on the release checklist.

**Spike before building** (validate against current Razorpay docs and the sandbox):
1. Subscription lifecycle, statuses and webhook event order.
2. Plan-change and proration behaviour.
3. E-mandate limits, and the right approach for annual and high-value plans.
4. Updating the payment method on an existing subscription.
5. First-cycle and N-cycle discounts.
6. Webhook retry window and event ids.
7. International cards and multi-currency enablement.
8. Virtual accounts for bank transfers.
9. Checkout accessibility.
10. GST invoicing duties and e-invoicing applicability, with a chartered accountant.
11. Account activation and KYC lead time: start early, it can take days to weeks.

### 3.17 Public API and enterprise integrations

**Principle:** anything a customer can do in the UI can also be done through a documented, versioned API, and the product pushes events out to the tools enterprises already use. The Swagger/OpenAPI document is generated from the code, so it cannot drift from the product.

**Two API surfaces (nothing already built is renamed)**

| Surface | Paths | For | Contract |
|---|---|---|---|
| Internal app API (exists today) | `/auth`, `/org`, `/admin/...` | Our own web app | None. It may change at any time and stays out of the public docs. Interactive docs for it are switched off in production |
| Public API (new) | `/v1/...` | Customers, integrators, our CLI and SDKs, and the web app for new features | Versioned and stable. Its own OpenAPI document, with Swagger UI at `/v1/docs`, ReDoc at `/v1/redoc` and the schema at `/v1/openapi.json` |

**How it fits the current code.** The public API is a separate FastAPI sub-application mounted at `/v1`, so it has its own OpenAPI document and no internal route needs renaming. New capabilities (scans, findings, reports) are written **once**, as service-layer functions exposed under `/v1`, and the web app calls them with the user's session. Existing organisation, user and subscription functions get thin `/v1` wrappers only where enterprises need them. Both surfaces pass through the same tenant isolation (RLS), seat guard, trial lock and quota reservation, so an API call can never bypass a limit.

**Authentication and authorisation**
- **API keys (Phase 1a):** created by a Company Admin, shown once, stored only as a hash. Format `a11y_live_<random>_<checksum>`: the prefix and checksum let secret scanners (including GitHub's) recognise leaked keys. Each key has a name, scopes, an optional expiry and IP allow-list, a last-used time, and can be rotated with an overlap period or revoked.
- **OAuth 2.0 client credentials (Phase 2)** for server-to-server integrations; the authorisation-code flow later for marketplace apps.
- **Session tokens:** `/v1` also accepts the web app's normal access token, so the UI and integrations share one code path.
- **Scopes** follow least privilege (`scans:read`, `scans:write`, `reports:read`, and so on). A key can never perform Super Admin actions and cannot manage other keys.
- **Service accounts:** a key acts as an `API_CLIENT` principal inside its organisation. It does not use a user seat (admin setting).

**API catalogue**

| Area | Operations (all under `/v1`) | Scope | Phase |
|---|---|---|---|
| Scans | `POST /scans` (URL, standards, crawl limits, auth-state id), `GET /scans`, `GET /scans/{id}`, `POST /scans/{id}/cancel`, `POST /scans/{id}/rescan`, `GET /scans/{id}/events` (server-sent events) | `scans:read`, `scans:write` | 1a |
| Findings | `GET /scans/{id}/findings` (filter by standard, severity, rule, status), `GET /findings/{id}`, `PATCH /findings/{id}` (status, assignee, comment), `GET /scans/{id}/diff/{other_id}` | `findings:read`, `findings:write` | 1a (read), 2 (triage, diff) |
| Standards and rules | `GET /standards`, `GET /rules`, `GET /rules/{id}` (explanation, fix examples, clause citations) | `catalog:read` | 1a |
| Reports | `POST /reports` (scan, standard, type, format), `GET /reports/{id}`, `GET /reports/{id}/download`, `POST /reports/{id}/sign-off` | `reports:read`, `reports:write` | 1a |
| Uploads | `POST /uploads` (returns a pre-signed URL), `POST /uploads/{id}/complete`; used for `storageState` files, documents, media and APKs | `uploads:write` | 1a (auth state), 3 to 5 |
| Organisation | `GET /org`, `GET /org/usage`, `GET /org/subscription`, `GET /org/invoices`, `GET /org/users`, `POST /org/invites` and `DELETE /org/users/{id}` (the seat guard applies and returns the upgrade prompt on a full plan) | `org:read`, `users:write` | 1a (read), 1b (write) |
| API keys | `GET/POST /org/api-keys`, `POST /org/api-keys/{id}/rotate`, `DELETE /org/api-keys/{id}` | Company Admin session only | 1a |
| Webhooks | `GET/POST/PATCH/DELETE /webhooks`, `GET /webhooks/{id}/deliveries`, `POST /webhooks/{id}/test`, `POST /deliveries/{id}/redeliver` | `webhooks:manage` | 1b |
| Audit log | `GET /audit-events` (pulled by a SIEM) | `audit:read` | 1b |
| Monitors | `POST /monitors` (scheduled recurring scans), `GET /monitors`, `PATCH /monitors/{id}`, `DELETE /monitors/{id}` | `monitors:write` | 2 |
| Integrations | `GET/POST/DELETE /integrations` (Jira, GitHub, Slack), `POST /findings/{id}/export` (create an issue) | `integrations:manage` | 2 |
| Identity | SCIM 2.0 at `/scim/v2` (Users, Groups) | SCIM token | 2 |
| Documents | `POST /documents`, `GET /documents/{id}`, `GET /documents/{id}/download`, `GET /documents/{id}/review` | `documents:read`, `documents:write` | 3 |
| Media | `POST /media`, `GET /media/{id}`, `GET /media/{id}/captions` (`.vtt`, `.srt`), `/transcript`, `/audio-description` | `media:read`, `media:write` | 4 |
| Mobile | `POST /mobile/scans`, `GET /mobile/scans/{id}` | `mobile:read`, `mobile:write` | 5 |

**Conventions (all endpoints)**
- Resource-oriented JSON, RFC 3339 UTC timestamps, UUID ids, cursor pagination (`limit`, `cursor`), and documented filter and sort parameters.
- Work that takes time returns `202 Accepted` with a job resource and a `Location` header. Clients poll, stream events (SSE) or receive a webhook.
- An `Idempotency-Key` header on every `POST` that creates work or spends quota. It maps onto the existing idempotent reservation by job id, so a retried request never charges twice.
- Errors use RFC 9457 `application/problem+json` with a stable `type`, a machine-readable `code` and, where relevant, the structured upgrade prompt (seat limit, quota, locked trial) that the app already returns.
- Rate limits per key and per organisation (token bucket in Redis), with `429`, `Retry-After` and rate-limit headers. Limits come from plan entitlements and can be overridden per organisation in admin.
- `X-Request-Id` on every response and in the audit log; optimistic concurrency with `ETag` and `If-Match` on `PATCH`.
- **Versioning:** `/v1` accepts additive changes only (new fields, endpoints and optional parameters). A breaking change means `/v2`. Endpoints marked `beta` may change. A deprecated endpoint gets `Deprecation` and `Sunset` headers and stays for at least 12 months.

**Swagger / OpenAPI and the developer portal**
- FastAPI generates OpenAPI 3.1 from the code. Every operation must have an `operationId`, a tag, a summary and description, the required scopes, request and response examples, and every error response modelled. CI fails when any are missing.
- **CI quality gates:** Spectral (lint rules), oasdiff (breaking-change detection against the last release), Schemathesis (contract and fuzz tests against a running API) and a check that the generated SDKs still compile.
- CI commits the published spec to `docs/api/openapi-v1.json`, with a changelog, so every API change is visible in review.
- **Accessible reference:** Swagger UI and ReDoc are third-party tools with known accessibility gaps (we verify with our own scanner and a screen reader). We keep them for their "try it" convenience **and** publish our own semantic-HTML API reference generated from the same OpenAPI file. The Accessibility Statement lists the status of each.
- **Developer portal at `/developers`:** getting started, authentication, quickstarts (curl, Python, JavaScript), webhook guide, error and rate-limit reference, changelog, Postman collection export, and a sandbox target site so integrators can test without scanning real sites. Docs visibility (public or signed-in) is an admin setting.
- **SDKs and CLI:** Python and TypeScript SDKs generated with openapi-generator (Phase 2), other languages on demand. The `a11y` CLI wraps the SDK, for example `a11y scan <url> --fail-on serious --baseline file`, and works from any CI system.

**Outbound webhooks (Phase 1b)**
- Events: `scan.completed`, `scan.failed`, `report.ready`, `regression.detected`, `document.remediated`, `review.completed`, `quota.threshold_reached`, `subscription.changed`, `user.invited`. Payloads are thin (ids and a summary), and the receiver fetches details through the API.
- Each delivery carries a signed header (HMAC-SHA256 over timestamp and body, with a replay window), an event id for de-duplication and the API version. Retries use exponential back-off over 24 hours. An endpoint auto-disables after repeated failures, with a notification. Admins see a delivery log with manual redelivery and secret rotation.
- Webhook URLs go through the same SSRF checks as scan targets (3.6). Delivery runs on the `integrations` queue.

**Enterprise integrations**

| Need | What we build | Phase |
|---|---|---|
| Single sign-on and provisioning | SAML 2.0 and OIDC SSO; SCIM 2.0 user and group provisioning; MFA enforcement | 2 |
| Issue tracking | Jira Cloud and Data Center, and GitHub Issues: create an issue from a finding and sync its status. Issue title and body come from admin-editable templates (3.14). GitLab and Azure DevOps on demand | 2 |
| CI/CD gates | `a11y` CLI, GitHub Action, GitLab CI template, Azure Pipelines and Jenkins through the CLI; fail the build on new violations against a baseline | 2 |
| Team chat | Slack and Microsoft Teams: scan summaries and regression alerts | 2 |
| Security and compliance tooling | Audit-log pull endpoint, then streaming to a SIEM (Splunk, Datadog, Elastic) over HTTPS | 1b (pull), 3 (streaming) |
| IT service management | ServiceNow and similar through webhooks and the API; a native app on demand | 3 or later |
| No-code automation | Zapier, Make and Power Automate connectors built on webhooks and the API | 3 or later, on demand |
| Data export | Scheduled CSV or JSON export to the customer's own S3 or Azure Blob storage | 3 |

**Integration framework.** Each connection is an `Integration(org_id, type, config, secret_ref, scopes, status)`. Platform-level OAuth app credentials (for Jira, GitHub and Slack) are write-only admin settings (3.11.1). Per-organisation tokens are encrypted and refreshed automatically. Outbound calls respect each provider's rate limits and run on the `integrations` queue. Connection health feeds the incident system (3.15), so an expired Jira token raises a notification instead of failing silently.

**Admin configuration (3.11).** Per plan and per organisation: API access on or off, requests per minute and per month, maximum keys, maximum webhooks, key lifetime, allowed integrations, docs visibility, and a CORS origin allow-list (off by default, because the public API is server-to-server).

**Security.** Keys are hashed at rest and never logged. Every API call is written to the audit log with organisation, key and action. Burst and anomaly alerts feed `/admin/ops`. Request size limits apply, uploads go only through pre-signed URLs with malware scanning (3.6), IP allow-lists are supported, and each organisation has a kill switch for API access. mTLS for Enterprise is an option for later.

**Exit criteria (Phase 1a):** the OpenAPI document is published and passes the lint and breaking-change gates; API-key authentication and scopes are enforced and tested; a sample integration script runs scan, findings and report using only the API in CI; rate-limit, idempotency and tenant-isolation tests pass for `/v1`.

### 3.18 Positioning, unit economics and trust

**Market wedge.** Web scanning alone is a commodity: the best engines (axe-core, IBM Equal Access) are free, and established vendors (for example Deque, Level Access, Siteimprove and Pope Tech) already sell monitoring. The places where we can be different are already in this plan: remediation instead of detection only, document and PDF remediation, multi-law reporting with a drafted VPAT, Indian-market fit (INR pricing, GIGW, regional languages) and trained human review. Actions:
- Keep a short competitor comparison in `docs/market/` (features, price, weaknesses).
- Interview 5 to 10 target customers before 1a closes, and write down the primary customer type and the one problem we solve first.
- **Order check:** after design-partner feedback on 1a, decide whether Phase 3 (documents) should run before parts of Phase 2. The phases are independent enough to swap.

**Unit economics.** Plan quotas count different things (URLs, document pages, video minutes), and each costs something different. Before final pricing:
- Build a cost model per unit: URL scan (pages, CPU seconds, storage, tokens by tier), document page, alt text, video minute (GPU transcription, audio-description tokens, speech synthesis, storage), mobile scan (emulator host time) and human-review minute. Add payment fees, email and support.
- Meter the inputs: extend `UsageLedger` and `AIUsage` with worker-seconds, GPU-seconds and storage, so FinOps can show **margin per tenant** and not only AI cost.
- Set quotas and prices from the model, with a target gross margin per plan, and review them quarterly. **The plan limits seeded in migration 0003 are launch placeholders** and should be replaced once the model exists.
- Human review is a paid add-on, priced per page or minute with turnaround tiers, and backed by a capacity plan for the SME teams.

**Legal and trust**
- Terms of service with liability limits and plain wording that automated results are not legal advice or a guarantee of compliance; a privacy policy; a data processing agreement with a sub-processor list (AI providers, Razorpay, email, hosting); DPDP Act and GDPR handling.
- **Hosting region:** a single region (India) at launch, stated in the DPA. Regional deployments come only when a customer needs them.
- **Security assurance:** an independent penetration test before the first paying customer; a vulnerability disclosure policy (`security.txt`); backup and recovery targets (RPO and RTO) that are written down and tested; a SOC 2 or ISO 27001 roadmap started when the enterprise pipeline asks for it.
- Consider professional-liability (errors and omissions) insurance before enterprise contracts.

**Brand.** "a11y" is a common shorthand for accessibility, so it is hard to trademark, to search for and to get a domain for. Keep `a11y` as the code and repository name, and choose a distinctive product name and domain, with a trademark check, before the public launch.

**Named owners.** The plan assumes people in these roles. Each needs a name before the phase that depends on it.

| Role | Responsible for | Needed by |
|---|---|---|
| Accessibility lead (IAAP-certified) | Sign-off on our own ACR, VPAT approvals, release screen-reader checks | 1a |
| Rule-mapping SME | Standards mappings and the rule content library | 1a |
| Security owner | Penetration test, key management, admin MFA policy, incident response | 1a |
| Chartered accountant | GST rate, SAC code, e-invoicing, invoice retention | Before the first invoice |
| Privacy contact | DPA, data requests, retention | Before the first customer |
| Ops owner and on-call | Approvals for Ops Agent actions, incident response | 1b |
| Content owner and editor | Editorial calendar, style guide, final approval of every published article (3.20). The accessibility lead is the reviewer for law and compliance articles | 2 |
| Pricing owner | Plan prices, discount policy, grandfathering decisions (3.19) | Before the first paid customer |

### 3.19 Subscription, pricing and promotions management

**What exists.** The SaaS core already has `Plan`, `PlanEntitlement` (a row per feature, so new quotas need no migration), `PlanPrice` (per plan, currency and cycle, in minor units), `Coupon` with a concurrency-safe redemption counter, `CouponRedemption`, trials, seat limits, and admin screens for plans and coupons. Nothing below replaces them. Every item is additive: new tables and new columns with defaults, so Phase 1 work in progress is not disturbed.

**What is missing.** Plans are edited in place, so a price or quota change would silently change every subscriber. A coupon is global and has one shape. There is no single function that turns "organisation, plan, cycle, coupon" into a price, so checkout, Payment Links, invoices and previews could disagree. There are no add-ons, no per-customer overrides and no campaign tooling.

**One pricing function.** `price_quote(org, plan_version, cycle, add_ons, coupons, billing_profile, at)` is a pure function that returns list price, each discount line, taxable value, GST split and total, all as integer minor units. Checkout, Payment Links (3.16), invoices, the pricing page, the admin preview and the tests all call it, so there is one source of truth. Property tests: never negative, never above list price, deterministic, the rounding rule is documented, and stacking never exceeds the configured cap. Razorpay only ever sees the final amount (3.16).

**Plan management**

| Capability | Design |
|---|---|
| **Plan versions** | A published plan version is immutable. Editing a price or entitlement creates a new draft version. Existing subscribers stay on their version (grandfathering) until an admin moves them. A price change needs two-person approval (3.16) and shows an impact preview first: subscribers affected, MRR change and who gets notified. |
| **Moving subscribers** | Scheduled for the next renewal, never mid-cycle unless the customer agrees. The notice email comes from a template (3.14). A downgrade is blocked while the organisation exceeds the new limits (for example more seats), with a message saying what to remove. Data is never deleted by a downgrade. |
| **Price book** | Prices per currency and cycle, with a tax-inclusive or tax-exclusive flag and an annual-discount setting. INR first; other currencies only when Razorpay international payments are enabled (3.16 spike item 7). |
| **Visibility** | `public` (on the pricing page), `hidden` (assigned by an admin or by link) and `legacy` (existing subscribers only). The public pricing page is generated from published versions, so it cannot disagree with billing. It uses a real comparison table with header cells. |
| **Custom enterprise terms** | `OrgEntitlementOverride(org, feature_key, limit, reason, expires_at, approved_by)` overrides a plan limit for one organisation, with an expiry and an audit entry. The entitlement resolver reads plan version, then add-ons, then overrides. |
| **Add-ons and top-ups** | Extra seats, extra quota packs (URLs, document pages, alt texts, video minutes), human-review credits and white-label. Recurring or one-off. Prepaid credit packs expire after an admin-set period. Add-ons add to plan limits through the same entitlement resolver. |
| **Subscription operations** (`/admin/subscriptions`) | Per organisation: change plan, extend trial, grant a credit or a complimentary period (reason required, approval above a threshold), pause, cancel, reactivate, view the entitlement breakdown and every change. |
| **Metrics** | MRR and ARR, average revenue per account, trial conversion, churn, expansion, plan mix and margin per tenant (3.18). CSV export. |

**Discounts and coupons.** Several kinds exist, and they differ in how they are found, who may use them and how they stack.

| Kind | How it applies | Notes |
|---|---|---|
| **Coupon code** (built) | The customer enters it | Extended below |
| **Automatic promotion** | Applies without a code when its rules match, inside a date window | Annual prepay discount, launch offer, seat or volume tiers |
| **Eligibility discount** | An admin verifies eligibility, then applies it | Non-profit, education, government. Evidence is stored, and re-verification is yearly |
| **Partner or referral code** | Attributes the customer to a partner or referrer | Revenue and discount reporting only. Commission payouts are out of scope |
| **Goodwill or win-back credit** | An admin grants a one-off credit, or a targeted code goes to lapsed accounts | Reason required, approval above a threshold |

**Coupon rules (extend the existing table).**
- **Eligibility:** plans and cycles, first purchase only, minimum organisation age, email-domain allow-list (for example a university domain), country, minimum and maximum order value.
- **Duration:** first cycle, first N cycles, a fixed number of months, or the life of the subscription (the same choices as 3.16).
- **Stacking:** an admin setting with `exclusive`, `best_of` or `stack`, plus a cap on the total discount, so an automatic promotion and a code cannot add up to a free product.
- **Limits:** global and per-organisation redemption limits (built), plus an optional per-user limit.
- **Campaigns:** a campaign groups codes. Bulk generation produces N unique single-use codes from an unambiguous character set, with expiry and a CSV export.
- **Abuse controls:** rate-limit code attempts, return the same error for an unknown and an expired code so codes cannot be enumerated, one trial per organisation domain, and a per-coupon kill switch. Redemption is confirmed only on payment success, and an abandoned checkout releases it (3.16).
- **Invoice presentation:** list price, discount lines and tax are shown separately, and the GST base is the discounted value. Confirm the treatment with the chartered accountant (open decision 12).
- **Analytics:** redemptions, discount given, revenue influenced, conversion by code or campaign, and unused or expired codes.

**Accessibility of buying.** The coupon field keeps its value after an error (SC 3.3.7), uses no cognitive test (SC 3.3.8) and announces the result through a live region. A price change after choosing a plan or cycle is announced too. No countdown timers or fake-urgency banners: a time limit must be extendable (SC 2.2.1), and artificial urgency is a poor fit for an accessibility vendor.

**Settings (3.11.3):** stacking policy and discount cap, coupon attempt limits, grandfathering default, approval thresholds, top-up expiry, visibility defaults and the pricing-page content.

**Stages.** `price_quote` and the Payment Link flow arrive in **1a** with Razorpay, because Payment Links need a quote. Plan versions with grandfathering, entitlement overrides, bulk coupon campaigns and stacking rules arrive in **1b**. Automatic promotions, add-ons and top-ups, eligibility discounts, partner attribution, analytics and the generated pricing page arrive in **Phase 2**, together with self-serve checkout.

### 3.20 Accessibility knowledge base: article management and AI authoring

**Why.** Three jobs: attract search traffic from people looking for accessibility help, give customers a "learn more" page behind every rule explanation, and show real expertise. This is long-form editorial content. It is not the rule content library (3.14), which is structured per-rule data used at scan time. The two are linked: an article cites rules and the rule page links to its articles.

**Content types:** how-to guides (for example "Label form fields in React"), WCAG criterion explainers, law and standard explainers (EAA, ADA Title II, GIGW 3.0, RPwD), checklists, product and release notes, case studies and glossary entries. Tags: WCAG criterion, standard, rule, audience (developer, designer, content author, compliance), stack and locale.

**Data model.** `Article(slug, type, status, locale, translation_group, title, summary, author, reviewer, ai_assisted, review_due_at, published_at)`, immutable `ArticleVersion(body, change_note, validation_report, created_by)`, `ArticleSource` (the source pack, with licence and last-checked date), `ArticleBrief`, `ArticleSeries`, `ArticleRedirect` and `ArticleAsset`. Bodies are restricted Markdown with typed blocks (callout, code sample, comparison table, figure), so we control the HTML and can check it. No arbitrary HTML.

**Workflow.** `Idea → Brief → Drafting → Validation → In review → Approved → Scheduled → Published → Review due → Archived`. Every transition is audited. Roles are Content editor, Accessibility reviewer and Publisher (they use the granular admin roles in 1b), and the author cannot publish their own article. Law and compliance articles always need the accessibility reviewer.

**Publishing and our own accessibility.**
- Public `/learn` with static or incremental rendering, search (Postgres full text first, with no new infrastructure), RSS, sitemap and structured data.
- Rule detail pages and the Fix Workbench show "Learn more" links by rule reference.
- An accessibility vendor's own articles must be accessible. Publishing is blocked unless our own scanner passes on the rendered page. Other gates: alt text on every image, a valid heading outline, descriptive link text, `lang` on text in another language, table header cells, keyboard-focusable scrollable code blocks, captions or transcripts for any media, and a reading-level target. Technical writing aims for plain language (the AI-assisted style guide enforces it).
- Articles are `noindex` until approved.

**Management screen (`/admin/content`).** Article list with filters, a source editor with live preview (no WYSIWYG widget, the same rule as decision 13), a brief editor, a review queue with a diff between the AI draft and the edited text, a validation panel, a calendar, and a **content gaps** view: criteria and rules with no article, search terms with no result, and the most common finding types across scans (aggregated across several tenants and anonymised, with no customer data). Performance uses privacy-friendly analytics with no third-party trackers by default.

**Automated authoring (the Content Agent).** It is a pipeline on the AI gateway (3.13) with its own task keys: `content.plan`, `content.draft`, `content.validate`, `content.translate` and `content.refresh`. It reuses the principles of templates first, validate before delivery, and tokens only where they add value.

1. **Plan (`LIGHT` or `STANDARD`).** From the content gaps, the topic backlog and the editorial themes set in admin, it proposes briefs: audience, angle, target criteria and laws, outline, sources and length. A similarity check against existing titles prevents duplicates.
2. **Ground.** The drafter may use only the **source pack**: our rule content library, the WCAG text and Understanding documents, official legal texts, and admin-approved URLs. Each source records its licence and when it was last checked. Sources are paraphrased and cited, and long quotation is avoided. The licence terms of each source (W3C documents have their own) are confirmed in an ADR before the pack is built. Fetching a page at generation time goes through the same SSRF-guarded fetcher as the scanner (3.6).
3. **Draft (`STANDARD`).** A fixed structure per article type (for example what the criterion says, who is affected, how to test, how to fix, common mistakes, further reading), as with report templates: the structure is permanent and the model fills slots. Code samples come from the rule content library first, which costs no tokens, and the model writes only the connecting prose. Every factual statement carries a source reference.
4. **Validate, cheapest first.**
   - **V1, deterministic, no tokens:** schema; every cited criterion exists in the registry with the right name and level; every legal statement points to a source and matches the stored clause text; **every code sample is run through our scanner, so a "before" sample must trigger the rule the article names and an "after" sample must pass**; links resolve; the accessibility gates above; reading level; a lint for overclaiming ("guarantees compliance", "fully compliant", anything that reads as legal advice), the same discipline as recommendation 7; near-duplicate and copied-passage detection against the source pack and existing articles; every date and "as of" statement is explicit.
   - **V2 (`PREMIUM`, a different model family from the drafter):** claim-by-claim check against the cited sources, marking each claim supported, unsupported or contradicted, and flagging legal statements. Always on for law and compliance articles, sampled for others.
   - **V3, human:** an editor approves every article. The default is that **nothing is published without a named human reviewer**.
5. **Review and publish.** The editor sees the draft, the sources next to each claim and the validation results, then edits and approves. Publishing is scheduled and passes the accessibility gate.
6. **Maintain.** Each article has a `review_due_at` (shorter for law). A change to a WCAG or standard mapping, to a rule's content, or a legal update marked by an admin flags the affected articles as "needs review". The agent then proposes a refreshed draft as a diff (Suggest mode). A monthly job checks links.
7. **Translate (`LIGHT`, reviewed).** Drafts for Tamil, Hindi and others, linked through `translation_group`. V1 checks that code blocks, numbers and links are unchanged. A reviewer for that language approves before publishing. This supports the Indian-market wedge (3.18).

**Autonomy and quality policy (same ladder as the Ops Agent, 3.15).** At launch the Content Agent is **draft-only**: AI drafts, a human publishes. Auto-publish is never available for law, compliance, pricing or claims about our own product. It may be considered later for low-risk types (for example glossary entries built from the rule library), only after a track record (a set number of consecutive drafts accepted with no material edits, and a measured validator precision), per type, off by default, with a kill switch and a sampled human audit. We recommend keeping human publishing for everything in version 1.
- **Disclosure:** pages say "Drafted with AI assistance and reviewed by [name]". The named human is accountable.
- **No scaled thin content:** a weekly publishing cap (admin setting), every article must offer something original (code samples verified by our scanner, our own data, an expert contribution), and unreviewed drafts are `noindex`. Search engines act against mass-produced low-value pages, so volume is not a goal.
- **Style guide as a setting:** voice, plain language, inclusive and consistent disability language, a banned-phrase list and prompt versions, all versioned, with evaluation-gated activation (Phase 2 configuration, round 2).
- **Privacy:** no customer scan data, URLs or findings appear in an article or in a prompt. Gap analytics use only aggregates across several tenants.
- **Cost:** `max_cost_per_item` and a monthly content budget, metered in `AIUsage` per task key, with cost per published article on the FinOps view.

**Notifications (3.14), to editors:** brief ready, draft awaiting review, validation failed, review due, translation ready.

**Settings (3.11.3):** content types and templates, source pack, style guide and banned phrases, task routes and tiers, review periods, weekly cap, autonomy per type, analytics on or off, and the `/learn` page content.

**Stage.** Phase 2. The CMS, public `/learn` and the first articles come before the agent: the agent needs 20 or so human-written, reviewed articles as style examples and as the golden set for evaluation. Two tasks can start earlier, without disturbing Phase 1: the owner writes a handful of launch articles in a Markdown repository folder, and the 1b rule content library already carries the explanation and fix text that the agent will reuse.

### 3.21 Refunds and support tickets (admin area)

Two admin-area functions that every paid product needs. Both are deliberately small. They sit in the existing admin and organisation areas, use the template, notification and audit systems already planned, and do not add a separate helpdesk product.

**Where they sit in the plan.** The basic admin-initiated refund with a credit note stays in Phase 2 with self-serve billing (3.16), because the first live payments need it. The policy-driven refund workflow, customer refund requests, dispute handling and the support ticket system described here are added to **Phase 5, the last phase**, as requested. If design partners need tickets earlier, the section can move up without changes, because it depends only on pieces built in Phases 1 and 2.

**Refund mechanism** (extends the Razorpay design in 3.16)

| Step | Design |
|---|---|
| **Policy (settings)** | Refund window in days, eligible reasons, full or partial, pro-rata for the unused part of an annual plan, non-refundable items (consumed AI or human-review credits), trial rules, and approval thresholds. Terms of service carry the matching wording (3.18). |
| **Request** | From `/org/billing` ("Request a refund" with a reason), from a support ticket, or started by an admin. |
| **Eligibility** | A pure function, like `price_quote` (3.19): refundable amount = amount paid minus the value of what was used, capped at the captured amount, summing all earlier refunds. It shows its working to the admin. |
| **Approval** | Two-person approval above the configured amount (3.16). Reason is mandatory on approve and reject. |
| **Execution** | Razorpay Refund API, idempotent (our refund id is the key). The status changes only on the `refund.processed` or `refund.failed` webhook, never on the API response alone. Refund speed and timing depend on Razorpay and the customer's bank, and we state that to the customer. |
| **Paper trail** | A GST credit note (accessible PDF/UA) is issued from the template system. Entitlements change according to policy: cancel at period end, or immediately. The coupon redemption is handled per policy. Templates send the notices. Everything is audited. |
| **Failure path** | A failed refund opens an admin task and an incident. The fallback is a bank transfer recorded with its reference. |

States: `Requested → Under review → Approved | Rejected → Processing → Refunded | Failed`.

Other cases covered: payments made through Payment Links or bank transfer (the transfer is refunded by a manual transfer with TDS considered), partial refunds, a refund larger than what was captured (blocked), and **disputes and chargebacks** (the Razorpay dispute events open a ticket and an incident, evidence can be attached, and the deadline is tracked). The nightly reconciliation (3.16) includes refunds, credit notes and disputes. A report shows refunds by reason and by plan, and a repeated refund-then-new-trial pattern is flagged.

**Admin screens:** `/admin/billing/refunds` (queue, detail with payment, usage and policy calculation, approve or reject, status, export) and the customer's request form and history in `/org/billing`. Needs a Billing admin role (granular roles, 1b).

**Support tickets (small, built in)**

*Customer side* (`/org/support`, with a consistent "Help" link on every screen, SC 3.2.6):
- Create a ticket with a category (billing and refunds, scan problem, report or file problem, account and access, **accessibility barrier in our product**, other), subject and description. Context is attached only with the customer's consent: organisation, plan, and the chosen scan or report.
- Attachments with type and size limits, and malware scanning (3.6).
- A ticket list, a conversation thread, reply, close and reopen, and a one-click satisfaction rating after resolution.
- The "accessibility barrier" category is a feedback channel that honours the commitment in section 2.8: higher default priority and a published response target.

*Admin side* (`/admin/support`):
- A queue with filters (status, priority, category, assignee, organisation), assignment, tags, search, merge for duplicates, CSV export.
- Statuses `New, Open, Waiting on customer, Waiting on us, Resolved, Closed`. Private internal notes that are never visible to the customer.
- Canned replies, which are templates (3.14), editable in admin and versioned.
- **SLA timers per plan** (first response and resolution targets are settings), warnings before a breach and an alert on breach through the `notify` queue.
- Links from a ticket to the organisation, scan, report, payment and refund, so an admin sees context without asking the customer. No "log in as the customer" feature, and no passwords ever.

*Optional AI help* (admin toggle, off by default, tiered under 3.13): a light model suggests category, priority, language and duplicates; a draft reply built from the rule library and the knowledge base (3.20) for the agent to edit. It is **never sent automatically**, and V1 checks block secrets and personal data in drafts.

*Not in scope:* live chat, phone, social channels and inbound email parsing in version 1. If volume grows, tickets sync to an external helpdesk through the integrations in 3.17.

**Data model.** `RefundRequest` (linked to the existing `Refund` and `CreditNote`), `RefundPolicy` (settings), `SupportTicket`, `SupportMessage` (with a `visibility` of public or internal), `SupportAttachment`, `TicketEvent`, `SupportSlaPolicy`. All are tenant-scoped under RLS, so customers see only their own organisation's tickets. The isolation suite covers them, with a test that internal notes never leave the admin API. Retention is a setting.

**Notification events (3.14):** to customers: refund requested, approved, rejected, processed, failed; ticket received, replied, resolved. To admins: new ticket, SLA warning and breach, refund awaiting approval, dispute opened.

**Accessibility.** Both areas meet section 2: the thread is a structured list with headings, a new reply is announced without moving focus, the page does not refresh itself under the user, attachments work by keyboard, and every status is conveyed by text as well as colour.

**Settings (3.11.3):** refund policy and thresholds, ticket categories, priorities and SLA targets, canned replies, satisfaction survey on or off, retention, AI help on or off.

---

## 4. Phased build plan

Each phase ends with exit criteria, not dates, because timelines depend on team size. Accessibility gates from section 2.6 apply from Phase 0 onward.

**Build order (decided 2026-11-28): Phase 0, Phase 1, Phase 3, Phase 2, Phase 4, Phase 5.** Documents and eBooks (Phase 3) now come before the deep web audit and monetisation work (Phase 2), because documents are the stronger wedge (3.18) and the document tooling is already partly in place. The phase numbers are kept so existing references still work. Four items move forward from Phase 2 and the web backlog into Phase 3; they are listed under Phase 3.

### Phase 0: Foundations

**Scope**
- Monorepo layout (3.12), `docker-compose.yml` (Postgres 16, Redis, MinIO, API, workers, web), `.env.example`, Makefile.
- CI pipeline: lint, type checks, unit tests, Alembic migration check, **all PR accessibility gates**, container builds, secret scanning.
- `packages/ui`: design tokens (contrast-validated), React Aria base components (Button, Link, TextField, Select, Dialog, Table, Tabs, Toast, Meter, ProgressBar), Storybook with the a11y addon.
- App shell: landmarks, skip link, route announcer, focus management, consistent help entry, error pages.
- Accessible auth: signup, login, email verification, password reset, invite acceptance (SC 3.3.8). Short-lived JWT access tokens plus refresh tokens in `httpOnly` cookies.
- Postgres RLS framework plus the isolation test suite.
- **Settings framework (3.11.1):** typed registry, scope resolution, encrypted write-only secrets, versioning + audit + rollback, Redis cache with live invalidation, schema-generated admin forms.
- `LLMGateway` interface with provider adapters and a fake provider for tests, with hooks for tiers, escalation and validation (3.13).
- **Template system (3.14):** registry, versioned storage, sandboxed renderer and shared accessible email blocks; move the existing auth emails onto it. Spike: does Chromium's tagged PDF reach PDF/UA-1?
- **Reliability baseline (3.15):** job state machine with heartbeat, error classes, retry policy and dead-letter queue; structured logs with trace ids; OpenTelemetry, Prometheus and Grafana wired into docker-compose.
- `PaymentProvider` interface, fake provider and billing data model (3.16). Start Razorpay account activation and KYC now, because it has a lead time.
- ADRs for: component library, cloud target, LLM providers, broker, observability stack, template engine.

**Exit criteria**
- `docker compose up` brings up the full stack with seed data in one command.
- Zero axe violations on every shell route. Keyboard and screen reader smoke test passed (NVDA + VoiceOver).
- Cross-tenant isolation tests are green.
- Every auth email renders from a published template and passes the template accessibility check.

### Phase 1: MVP, sellable web accessibility audits

**Staging (added 2026-11-27).** Phase 1 is already in development, so this staging does not change anything that is built. It only assigns the remaining work to two stages, so design partners can start sooner. The scope and exit criteria below remain the full list; this table says in which stage each item lands. Status comes from the repository and was last updated on 2026-11-28; the summary under the table says where Phase 1 stands.

- **1a, sellable to design partners:** scan a site, understand the findings, export a report, be billed.
- **1b, breadth and hardening:** what makes it cheaper to run and easier to operate, but is not needed on day one.

| Item | Stage | Status |
|---|---|---|
| Settings framework, `/admin/settings`, schema-generated admin forms (3.11.1) | 1a | Built |
| SaaS core: plans and entitlements, trial, seat guard, quota reservations, coupons; admin screens for organisations, plans and coupons | 1a | Built |
| `LLMGateway`: routing, fallback, budgets, metering | 1a | Built. Adapters: DeepSeek, Azure OpenAI, OpenAI, OpenAI-compatible, Anthropic (Claude, Messages API) and fake; enterprise own-key (BYOK) built. Five real providers, so fallback works across vendors. Bedrock not started (needs AWS request signing and an account to test against) |
| Rule registry and switching standards | 1a | Built (87 criteria, 12 standards, 42 canonical rules; mappings still `draft` until SME review) |
| Web scanner: Playwright, three engines, normalisation, screenshots | 1a | Built, including page screenshots ([ADR 0012](adr/0012-screenshots-and-fix-workbench.md)). Benchmark baseline recorded and gated in CI: [docs/benchmark.md](benchmark.md) (own fixtures 60 of 60 planted defects, 0 false failures; independent GOV.UK suite 54 of the 92 failures that at least one of 13 other tools reported, 59%) |
| SSRF protection, domain verification, rate limits | 1a | Built (egress proxy, domain verification, per-org rate and concurrency limits) |
| Code-fix copilot: library text, recipes, V1 re-scan check (3.13) | 1a | Built ([ADR 0011](adr/0011-code-fix-copilot.md)): cache, 6 deterministic recipes, the light model with one repair, a stronger model tried once (`code_fix_escalate`), and an independent reviewer (`code_fix_validate`, policy off/sample/always, fails closed when required); every fix must pass static checks and the re-scan oracle or it is never shown; admin setting `ai.code_fix`; "Suggest a fix" in the finding dialog and the Workbench. Not yet: human review queue, shadow-mode promotion, content-level fixes (the scanner stores only the element's tag) |
| Reports: in-app, CSV, accessible PDF, DOCX, VPAT draft with sign-off | 1a | Built: audit PDF (veraPDF-gated), DOCX (structure-checked), CSV, and the VPAT (WCAG tables) with draft defaults, editing, sign-off and export ([ADR 0008](adr/0008-pdf-ua-generation.md), [ADR 0009](adr/0009-reports-and-vpat.md)). Not yet: the 508/EU/INT chapters, per-element screenshots |
| Template engine, report layouts and about 10 essential email events (verify, invite, reset, trial ending and expired, scan complete and failed, quota full, payment) | 1a | Built ([ADR 0013](adr/0013-notifications-and-reservation-sweeper.md)): report templates, plus 9 email events (4 account, trial ending and ended, scan finished and failed, scan limit reached) with fixed accessible layout, admin-editable wording (versioned, guarded), logged idempotent delivery with retries, and the `/admin` Emails editor with preview and test send. Payment emails come with Razorpay. Not yet: per-user opt-out, email provider setting, bounce handling |
| Content library for the 50 or so most common rules; engine help text for the rest | 1a | Built: a guide for every one of the 43 canonical rules in `rules/content/*.yaml`, each example run through the real engines (9 rules no engine can judge by default are marked for human checking); served at `/rules/{id}/guidance` and shown in the finding dialog and the Fix Workbench. Draft until an accessibility SME reviews it. Not yet: code examples beyond HTML and React |
| Admin MFA for every admin role, and session refresh | 1a | Built: MFA admin-configurable (dev default off, refused in production) and rotating Super Admin sessions ([ADR 0010](adr/0010-admin-two-step-verification.md)) |
| Public API: `/v1` skeleton, API keys and scopes, OpenAPI published (3.17) | 1a | Built ([ADR 0014](adr/0014-public-api.md)): 10 endpoints (scans, findings, summary, reports, audit log), hashed scoped keys with a key-management page at `/org/api`, per-key rate limits, idempotency keys, plan entitlement `api_access`, published OpenAPI at `/v1/openapi.json`. Outbound webhooks arrived with 1b (below). Not yet: SDK |
| Workspace screens: new scan, findings list, Fix Workbench | 1a | Built: new scan, scans list, results and findings, and the Fix Workbench (problem list, screenshot with the element outlined, guidance, checked code fix; [ADR 0012](adr/0012-screenshots-and-fix-workbench.md)). Not yet: mark as fixed or ignore, single-page re-scan |
| Razorpay: webhook receiver, Payment Links, GST invoice engine, essential `/admin/billing` | 1a | Not started |
| Reliability layer 0 for the scan pipeline; stuck-job and reservation sweepers (3.15) | 1a | Built: state machine, heartbeat, idempotent redelivery, stuck-scan sweeper, credit rules, and the orphaned-reservation sweeper ([ADR 0013](adr/0013-notifications-and-reservation-sweeper.md)) |
| Remaining notification events, in-app notification centre | 1b | Built ([ADR 0017](adr/0017-notification-centre.md)): in-app items for every email event (same editable wording), unread count in the header, list with mark read, per-person opt-out of scan emails, feature flag. Not yet: digests, per-event preferences, push |
| Content library for all rules | 1b | Built (covered by the row above: every canonical rule has a guide and a test enforces it) |
| Outbound webhooks and the audit-log endpoint (3.17) | 1b | Built ([ADR 0015](adr/0015-outbound-webhooks.md)): signed, retried, SSRF-checked webhooks for scan and report events with `/org/webhooks` and a section in the API reference; audit log readable at `GET /v1/audit-log` |
| Accessible API reference page and the full API quality gates (3.17) | 1b | Built: `/developers` renders the published OpenAPI with our own accessible components (axe in both themes, keyboard, 320px); contract tests cover every operation (summary, scope, documented errors, unique ids) and fail if the saved copy drifts from the real description. Not yet: runnable examples, changelog |
| Canaries, first runbooks, read-only `/admin/ops` | 1b | Built ([ADR 0018](adr/0018-operations-canaries-and-runbooks.md)): three scheduled canaries (browser and engines, PDF/UA, mail server), a read-only Operations tab with health, queues and computed incidents, and 12 runbooks. Not yet: paging, status page |
| Sampled premium validation (V2) and shadow-mode promotion (3.13) | 1b | V2 built (sampled or always, see the code-fix row). Shadow-mode promotion and the cost-versus-quality dashboard not started |
| Remaining admin settings (email provider, legal pages, scan engines, feature flags), granular admin roles, two-person approval | 1b | Email provider, legal pages (mechanism only: no legal text is shipped) and feature flags built ([ADR 0016](adr/0016-admin-settings-email-provider-and-flags.md)); scan engines built earlier. Not yet: granular admin roles, two-person approval |
| `price_quote`: one pure pricing function (plan, cycle, coupon, tax) shared by checkout, Payment Links, invoices and previews (3.19) | 1a | Not started. Plans, prices and coupons exist, but there is no single quote function yet. Built together with the Razorpay Payment Link flow |
| Plan versions with grandfathering, per-organisation entitlement overrides, coupon campaigns (bulk codes) and stacking rules (3.19) | 1b | Overrides and campaigns built ([ADR 0019](adr/0019-entitlement-overrides-campaigns-and-fix-credits.md)): per-organisation exceptions with a reason and end date (honoured by quotas, seats, API and own-AI), batches of unique codes with campaign reporting and a kill switch. Not yet: plan versions with grandfathering and stacking rules (they come with the price-quote work for Razorpay) |
| Our own ACR from a human audit, Accessibility Statement, manual NVDA and VoiceOver pass | 1b | Not started |

**Completion status (2026-11-28).** All of Phase 1 so far is on `main`: it was pushed on `phase-1` and merged through pull request #1, which was also the first time CI ran on GitHub. The secret scan flagged six public placeholders (four fake test keys and the public development master key that production refuses); `.gitleaks.toml` allows exactly those values and keeps every default rule. The other CI jobs had not finished when this was written, so check the Actions tab before relying on them. The interface was also restyled the same day (palette, landing page, card layout), with the same accessibility gates. Verified locally on a clean scratch database: 674 API tests (1 skipped), 208 browser tests including the axe checks in light and dark, and clean lint and type checks. A live run on the Docker stack covered a real API key, a real scan, a PDF/UA report, the scan email, an in-app notification, and the Fix Workbench.

| Stage | Rows | Built | Partly built | Not started |
|---|---|---|---|---|
| 1a | 16 | 14 | 0 | 2: Razorpay, and `price_quote` |
| 1b | 9 | 5 | 3 | 1: our own ACR, Accessibility Statement and manual screen reader pass |

- **Open in 1a:** Razorpay (webhook receiver, Payment Links, GST invoices, essential `/admin/billing`, read-only `/org/billing`) and `price_quote`. This is the only blocker for onboarding design partners. It is deferred to the end and will be built and tested together with the owner, starting with test mode.
- **Partly built in 1b:** shadow-mode promotion (the second-model review is done); granular admin roles and two-person approval (which role may do what is an owner decision); plan versions with grandfathering and coupon stacking rules (they come with `price_quote`). Entitlement overrides and bulk coupon campaigns are done.
- **Built but still draft, waiting for an accessibility specialist:** the standards mappings, all 43 rule guides, and the review of the GOV.UK benchmark, which was AI-assisted.
- **Deferred to the final phase by the owner (2026-11-28):** Razorpay; granular admin roles and two-person approval; Bedrock; plan versions and stacking rules; the 508, EU and international VPAT chapters; our own ACR, Accessibility Statement and manual NVDA and VoiceOver pass; the specialist sign-off; the legal page text.
- **Small gaps, no decision needed:** digests and per-event email preferences, paging and a status page, shadow-mode promotion and the cost-versus-quality dashboard, mark-as-fixed and single-page re-scan in the Workbench, runnable API examples and a changelog, a screenshot retention setting, bounce handling.
- **Before production:** real `A11Y_MASTER_KEYS` and `JWT_SECRET`; run the web worker on a network with no route to internal services; never set `SCAN_DEV_ALLOW_HOSTS`, and never leave MFA on its dev default of off.
- **Exit criteria still unmet:** our own ACR with zero open Critical or Serious issues on our screens, the Razorpay webhook tests, and 3 to 5 design partners actively scanning. The measured share of fixes made without a model call and the cost per accepted fix are not yet reported.

**Stage gates.** Design partners onboard when **1a** exits: the scanner benchmark is recorded; the quota and coupon concurrency tests pass; exported PDFs pass veraPDF; switching the code-fix provider needs no redeploy and falls back automatically (two real adapters); a worker killed mid-scan resumes or fails with a reason and leaves no credits reserved; a Razorpay Payment Link activates a plan through the webhook, including the duplicate, out-of-order and forged-signature tests; admin MFA is enforced for every admin role; the `/v1` exit criteria in 3.17 pass; and no Critical or Serious accessibility issue is open on any screen shipped so far. **1b** closes when the remaining exit criteria below pass, 3 to 5 design partners are actively scanning, and our own ACR is done before the first paid customer.

**Scope**
- **SaaS core:** Plans, Organizations, Users and roles, Seat Limit Guard with upgrade prompt, Trial engine (14 days → `LOCKED_READ_ONLY`), Coupons + Redemptions, Usage Ledger + Reservations, audit logs.
- **Rule registry:** WCAG 2.0/2.1/2.2 (A/AA, plus 2.2 AAA as informational), Section 508, ADA Title II + III, EN 301 549 Clause 9, GIGW 3.0, AU target. Switching standards recalculates scores and filters on existing scan data.
- **Web scanner:** single URL + bounded crawl, three engines in one page, normalisation, deduplication, confidence score, template clustering, full-page + element screenshots, pinned engine versions.
- **AI Code-Fix Copilot:** one suggested HTML/ARIA/React patch per clustered root cause, with explanation and the WCAG SC it addresses. Copy-only. It follows the resolution ladder (3.13): library text, then deterministic recipes, then a light model, then escalation. Every fix passes the V1 re-scan check, and sampled fixes also pass premium-model validation (V2).
- **Reports:** in-app results, CSV, **accessible PDF (veraPDF-gated)**, DOCX; **VPAT 2.5 draft** (WCAG / 508 / EU / INT editions) with "Not Evaluated" defaults and required human sign-off before export.
- **Templates and content (3.14):** permanent templates for every report and for every notification in the event catalogue; admin template editor with preview and test send; rule content library covering every rule the scanner can emit; deterministic narrative text by default.
- **Dashboards (first version):**
  - `/workspace`: New Scan dialog (URL + standards), live progress, findings list with filters, web Fix Workbench (issue list ↔ screenshot ↔ code fix), report export.
  - `/org`: team and invites with live "X of Y seats used", quota meters, plan details, coupon entry, branding (logo only).
  - `/admin`: tenant directory, manual plan assignment, trial funnel counts, plus the configuration screens: **plans and entitlements, trials, coupons, AI providers / models / tiers / task routing / validation policies / budgets, scan engines, compliance registry, report and email templates, notification events, feature flags, legal content, billing** (3.11, 3.13, 3.14, 3.16), with audit history and rollback.
- **AI providers at launch:** at least two live adapters behind the gateway, so fallback works from day one. All provider types in 3.11.2 can be added as rows without code changes. Each task has a tier ladder and a validation policy; the validator runs on a different provider from the producer where two are available.
- **Reliability, layers 0 to 2 (3.15)** for the web scan pipeline: retries by error class, checkpoints, dead-letter queue, stuck-job and orphaned-reservation sweepers, provider circuit breakers and failover, synthetic canaries, first deterministic runbooks, and a read-only incident list in `/admin/ops`.
- **Billing foundation (3.16):** Razorpay test-mode spike, webhook receiver with signature check and de-duplication, Payment Link flow for design partners, GST invoice engine (accessible PDF/UA), essential `/admin/billing` screens, read-only `/org/billing` (plan and invoices).
- **Security:** SSRF protections, domain verification, rate limits.
- **Platform accessibility:** Accessibility Statement published; first human audit of our own UI.

**Exit criteria**
- Scanner benchmark (fixture suite) recall/precision recorded and above the agreed baseline.
- Quota and coupon concurrency tests pass (no overspend under parallel requests).
- Every exported PDF passes veraPDF; DOCX golden tests pass.
- Our own ACR drafted from a human audit; zero open Critical/Serious accessibility issues in our UI.
- Switching the code-fix task to a different provider in `/admin` takes effect on the next job with no redeploy, and an outage of one provider falls back automatically.
- Killing a worker mid-scan ends in an automatic resume, or a failure with a reason within the target time, and no credits stay reserved. With the primary AI provider disabled, the canary detects it and the route fails over without staff action.
- The share of findings explained and fixed without any model call (library plus recipes) is measured and reported, along with cost per accepted fix.
- Every event in the notification catalogue has a published template that passes the template accessibility check.
- A Razorpay Payment Link payment activates a plan through the webhook, and the duplicate, out-of-order and forged-signature webhook tests pass.
- 3–5 design partners actively scanning.

### Phase 2: Deep web audit and monetisation

*Runs after Phase 3 (build order above). Its exit criteria are unchanged. Per-organisation data policy moves forward into Phase 3; SSO and SCIM move forward again if a large enterprise deal needs them first.*

**Scope**
- Authenticated scans (encrypted `storageState`, recorded login scripts).
- Deterministic keyboard and focus-trap agent, with LLM interpretation of anomalies.
- Virtual screen reader transcript in the workbench (spoken log next to the issue).
- Vision-LLM auditor: text in images, contrast over gradients and images, alt text quality, missing focus indicators.
- Scheduled monitoring, scan-to-scan regression diff, email digests (accessible HTML emails).
- **Razorpay self-serve billing (3.16):** subscriptions for monthly plans, orders or yearly subscriptions for annual plans as decided in the spike, plan changes, coupons mapped to final amounts, dunning, refunds and credit notes, nightly reconciliation, `PAST_DUE` and lock handling, and an upgrade checkout that meets SC 3.3.7 with accessible fallback payment paths.
- **Ops Agent (3.15):** start it once real production incidents exist, because runbooks are written from real failures (layers 0 to 2 ship earlier, in Phase 1). Suggest and Approve-to-run modes, action catalogue with policy engine, approvals in `/admin/ops`, billing-reconciliation incidents, public status page; proven runbooks promoted to Auto.
- **AI tiering, round 2 (3.13):** sampled premium validation, shadow-mode promotion of cheaper models, cost-versus-quality dashboard.
- **Notifications, round 2 (3.14):** Slack or Teams alerts, per-user preferences and digests, Indian-language template variants (for example Tamil and Hindi). Outbound webhooks arrive earlier, in 1b (3.17).
- **Subscription and promotions, round 2 (3.19):** automatic promotions, add-ons and top-ups, eligibility discounts (non-profit, education, government), partner and referral attribution, coupon analytics, and the pricing page generated from published plan versions.
- **Accessibility knowledge base (3.20):** article data model and workflow, `/admin/content` editor and review queue, public `/learn` with search, RSS and sitemap, "Learn more" links from rule pages, and the accessibility publishing gate. About 20 human-written, reviewed articles first. Then the Content Agent in **draft-only** mode: plan, ground, draft, validate (V1 code-sample check with our scanner, V2 fact check), refresh when a standard or rule changes, and reviewed translations.
- Super Admin: MRR/ARR, trial conversion, AI FinOps (token cost per tenant), budget caps.
- Configuration, round 2: payment gateway registry, tax settings, bring-your-own AI key for Enterprise, per-org data policy (regions, zero retention), prompt versioning with evaluation-gated activation, staged rollouts, two-person approval for high-risk changes.
- White-label: contrast-validated brand colours, custom report branding.
- **Enterprise integrations (3.17):** OAuth 2.0 client credentials, Python and TypeScript SDKs, the `a11y` CLI with a GitHub Action and a GitLab CI template, Jira and GitHub issue sync, Slack and Teams, SSO (SAML/OIDC) with SCIM 2.0 provisioning, and the finding-lifecycle and monitor endpoints. SSO and SCIM are required before large enterprise deals.

**Exit criteria**
- Self-serve trial → paid conversion works end to end without staff involvement.
- AI features pass the evaluation harness; per-tenant AI cost visible and capped.
- Release screen-reader matrix (section 2.6) passed.
- A self-serve payment through Razorpay works end to end in live mode, and the nightly reconciliation shows no unexplained differences over a full billing cycle.
- In Suggest mode the Ops Agent makes correct proposals for injected faults (provider outage, stuck queue, orphaned reservations), and every action and proposal is in the audit log.
- A sample customer pipeline fails a build on a new violation through the CLI or GitHub Action, and a finding can be sent to Jira from the UI and through the API.
- Plan versioning: a price change on a published plan leaves existing subscribers on their version until moved, and `price_quote` property tests pass (never negative, never above list, stacking cap respected).
- At least 20 reviewed articles are live and every one passes our own scanner at publish. The Content Agent's V1 checks catch planted defects in test drafts (a wrong criterion number, a code sample that does not trigger its rule, an overclaiming phrase, a copied passage). The accepted-draft rate, edit effort and cost per published article are reported. No article is published without a named reviewer.

### Phase 3: Documents and eBooks

*Decision (2026-11-28): this phase now runs before Phase 2. Confirm with the 5 to 10 prospect interviews in open decision 14 before committing the whole phase.*

**Moved forward into this phase**
- **Upload safety (3.6):** malware scanning, size and zip-bomb limits, encrypted storage and a retention limit for customer files. This is the first story, because nothing else may accept an upload without it.
- **Per-organisation data policy** (from Phase 2 configuration): regions, retention, and zero-retention use of AI providers for customer files.
- **Granular admin roles** (from the 1b backlog): the review console needs a reviewer role that sees only review work.
- **Unit cost of human review:** extend the unit-cost model (3.18) so each plan's document quota covers the people-time that complex files need.

**Order of work.** Sell sooner by building in this order:
1. **PDF audit only:** upload, veraPDF check, findings report and a document workbench that shows the problems.
2. **PDF remediation** with human review for the hard cases, then re-validation.
3. **DOCX and PPTX.**
4. **EPUB3**, unless a buyer asks for it earlier.

Sell "audit plus guided fix" first. Automatic remediation of a PDF is much harder than scanning a web page, and a large share of the Matterhorn checkpoints need a person.


**Scope** (in order of customer demand)
1. **PDF:** veraPDF audit → layout analysis (Vision-LLM + `pypdfium2`/`pdfplumber`) → tag tree, title, language, alt text via `pikepdf` → re-validate. A large share of Matterhorn Protocol checkpoints need human judgment, so complex files are routed to HITL.
2. **DOCX:** heading semantics, table header rows, alt text, document language.
3. **PPTX:** reading order, slide titles, alt text.
4. **EPUB3:** EPUBCheck + Ace, accessibility metadata in `package.opf`, landmarks, alt text, MathML.
- **HITL SME console:** queue, assignment, side-by-side review, approve/edit/reject, SLA tracking. Fully keyboard-operable, with no drag-only actions (SC 2.5.7).
- Document workbench: side-by-side preview, editable alt text, **reading-order editor with move up/down buttons** (not drag-only), "Download Remediated File".
- Document validators (veraPDF, EPUBCheck, Ace) are V1 checks in the validation layer (3.13). Add document runbooks (3.15) and the remediation report template (3.14).
- Public API: the `/v1/documents` endpoints and the document pages of the uploads flow (3.17).

**Exit criteria**
- Remediated files pass their validators, and SME review confirms reading order on a sample set.
- HITL turnaround SLA measured.
- Upload safety tests pass: a malicious PDF, a zip bomb and an oversized file are all refused, and no customer file leaves the allowed region or is kept past its retention limit.
- Human review cost per document is measured, and the plan quotas cover it.

**Status (2026-11-28, in progress on branch `phase-3`).** Slice 1 of the build order, upload safety (including the customer upload screen), is built; the PDF audit (slice 2) is built apart from page previews and an audit report file. Everything an administrator might want to tune is a setting (`documents.uploads`, `documents.safety`, `documents.retention`, the `documents` feature flag), editable in `/admin` at global, plan or organisation scope, plus a read-and-act Documents tab.

| Story | Slice | Status |
|---|---|---|
| Storage layer: S3 API behind a small interface, per-file envelope encryption bound to the object key ([ADR 0020](adr/0020-document-storage-and-upload-safety.md)) | 1 | Built and tested against the real local store |
| Upload safety: kind decided from the bytes, size and page limits, zip-bomb and unsafe-path checks, password and active-content policy, ClamAV scan that fails closed, hostile files erased at once | 1 | Built. Tested with a fake scanner and against a real ClamAV (EICAR in a .docx is refused and erased; the ADR lists what ClamAV does not catch) |
| Retention, deletion on request, tombstones, hourly sweep, stuck-upload re-queue | 1 | Built |
| Admin Documents module: scanner and store health, pipeline counts, refusal reasons, retry files that failed on our side, run the sweep | 1 | Built (API + `/admin` tab, axe in both colour schemes) |
| Customer upload screen and document list (`/workspace/documents`): limits and retention explained up front, plain-word statuses, download, delete with confirmation, refreshes while a file is checked | 1 | Built (axe in both colour schemes; Tab and Enter path tested) |
| PDF audit: veraPDF PDF/UA-1 check with plain-language findings, three direct checks (scanned pages, bookmarks, facts), `document_pages_monthly` page quota with reserve and settle, results page, `/v1/documents` ([ADR 0021](adr/0021-pdf-audit.md)) | 2 | Built and tested against real veraPDF. Not yet: page previews with marked problem areas, an audit report file, a webhook event, AI layout analysis |
| Per-organisation data policy (regions, zero-retention AI use), granular reviewer role, human-review unit cost | 2 to 3 | Not started |
| Guided fix for tagged PDFs: title and language, alternative text per figure, heading levels; fixed copy built from the original, re-checked and gated ([ADR 0022](adr/0022-guided-pdf-fix.md)) | 3 | Built and tested against real veraPDF (page-quota charged on success, given back on failure or refusal by the gate). Not yet: page previews, reading-order and table-header editors, tagging of untagged files, `/v1` fix endpoints |
| Human review: reviewer role, review queue and consent, side-by-side review, SLA tracking, human-review unit cost | 3 | Not started. Reuses the guided-fix engine |
| DOCX and PPTX, EPUB3 | 4 to 5 | Not started |

**Open items found while building slice 1.** (1) The shared `Table` component renders a keyboard grid, so a keyboard user cannot reach a button inside a table cell with the Tab key (focus stops on the row and then leaves the table). This predates Phase 3 and affects, for example, the Runbook buttons in Operations; the new Documents tab avoids it by using a list. The component needs a decision (native table semantics for data tables, or keep the grid and add arrow-key help). (2) The document scan runs in the shared documents worker; the plan's "no network" sandbox is still to do (ADR 0020, known limits).

### Phase 4: Audio and video

**Scope**
- FFmpeg extraction → faster-whisper with word timestamps → diarization (WhisperX/pyannote) → `.vtt`, `.srt`, `.txt`, `.docx` transcripts.
- Caption editor: row-based text editing with time inputs; waveform as an optional aid; keyboard shortcuts documented and remappable (SC 2.1.4).
- Audio Description: keyframes during pauses → LLM-drafted AD script → human approval → TTS (Kokoro/Piper) → mux AD track + captions into an accessible MP4. Extended AD when pauses are too short.
- Indian-language captions (Whisper multilingual): a differentiator for the domestic market.
- Light-tier caption clean-up; premium validation of audio-description scripts (3.13). Add media runbooks (chunk and resume) and the media report template (3.14, 3.15).
- Public API: the `/v1/media` endpoints, including caption and transcript downloads (3.17).

**Exit criteria**
- Caption accuracy (WER) measured on a reference set for each supported language.
- Player and editor pass the release screen-reader matrix.

### Phase 5: Mobile

**Scope**
- Android: APK upload → sandboxed emulator (KVM host) → Appium UiAutomator2 + Google ATF → TalkBack-order traversal, node info, screenshots → Kotlin / Jetpack Compose / React Native fixes.
- iOS (XCUITest + VoiceOver on on-demand macOS hosts) and real NVDA/VoiceOver capture for web: backlog, prioritised by customer demand.
- Mobile runbooks (emulator recycle, host failover) and the mobile report template (3.15, 3.14).
- Public API: the `/v1/mobile` endpoints (3.17).
- **Refunds in the admin area (3.21):** refund policy settings, customer refund requests from `/org/billing`, the eligibility calculation, approval with two-person approval above a threshold, execution through Razorpay confirmed by webhook, GST credit notes, failure path, dispute and chargeback handling, and `/admin/billing/refunds`. (The basic admin-initiated refund from Phase 2 stays and is folded into this workflow.)
- **Support tickets in the admin area (3.21):** `/org/support` and `/admin/support` with categories, assignment, internal notes, canned replies from templates, SLA timers per plan, notifications, satisfaction rating, and an "accessibility barrier" channel. Optional AI triage and draft replies, off by default and never auto-sent.

**Exit criteria**
- Benchmark against a known-bad sample APK set; sandbox escape and network-isolation tests pass.
- A refund goes from request through approval to a confirmed Razorpay refund and a credit note, including the failure, partial, over-refund and dispute cases. Reconciliation includes refunds, and every step is in the audit log.
- Tickets can be created, answered and resolved end to end by keyboard and screen reader. Tenant-isolation tests prove that customers see only their own tickets and never see internal notes. SLA warnings and breaches notify the assigned admin.

---

## 5. Open decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | UI primitive library | React Aria Components only (no Radix mixing) |
| 2 | Production cloud | Pick **one** for v1 (S3 or Azure Blob); keep the storage abstraction for later |
| 3 | Payment gateway and timing | **Razorpay** (3.16). Payment Links with manual plan activation in Phase 1; subscriptions in Phase 2. Start account activation and KYC now |
| 4 | LLM providers and data policy | Admin-configurable providers (3.11.2). Pick 2 for launch; zero-retention agreements; per-tenant region and provider restrictions |
| 5 | Real screen reader capture | Virtual screen reader in Phase 2; real NVDA/VoiceOver hosts as a premium backlog item |
| 6 | Celery broker | Redis to start (tuned `visibility_timeout`); revisit RabbitMQ when media jobs land |
| 7 | Rule-mapping and VPAT sign-off | Named accessibility SME (IAAP CPACC/WAS) owns mappings and VPAT approvals |
| 8 | PDF library replacing PyMuPDF | `pypdfium2` + `pdfplumber` unless we buy a commercial licence |
| 9 | Concrete models per tier | Assign models to `LIGHT`, `STANDARD` and `PREMIUM` per provider. Use a premium model from a different provider than the producer as the default validator |
| 10 | Observability stack | OpenTelemetry + Prometheus + Grafana + Loki + GlitchTip (or equivalent), chosen in a Phase 0 ADR |
| 11 | Ops Agent autonomy and ownership | Every action starts at Suggest and is promoted only with a supervised track record. Name a human owner for approvals and on-call |
| 12 | GST and e-invoicing | A chartered accountant confirms rate, SAC code, e-invoicing applicability and invoice retention before the first invoice |
| 13 | Template editor | Source editor with live preview; no WYSIWYG widget unless it passes our own audit |
| 14 | Market wedge and first customer type | Lead with remediation, documents, multi-law reports and Indian-market fit, not scanning alone. Interview 5 to 10 prospects before 1a closes (3.18) |
| 15 | Public API contract | `/v1` as a sub-application next to the internal routes; API keys first, OAuth client credentials in Phase 2; additive-only changes within a version; 12-month deprecation window (3.17) |
| 16 | Hosting region and security assurance | India region at launch; penetration test before the first paying customer; SOC 2 or ISO 27001 when the pipeline requires it (3.18) |
| 17 | Product brand | A distinctive name and domain with a trademark check before public launch; keep `a11y` as the code and repository name |
| 18 | Named owners | Accessibility lead, rule-mapping SME, security owner, chartered accountant, privacy contact, ops owner (3.18), content owner and pricing owner (3.19, 3.20) |
| 19 | Plan change policy | Published plan versions are immutable; existing subscribers are grandfathered and moved only at renewal with notice (3.19). Confirm with the pricing owner |
| 20 | Discount stacking | One coupon plus automatic promotions under a total discount cap, `best_of` by default (3.19) |
| 21 | AI-authored articles | Draft-only at launch; a named human reviewer publishes every article; no auto-publish for law, compliance, pricing or product claims; AI assistance disclosed on the page (3.20) |
| 22 | Source licences for the article source pack | Confirm the licence terms of each source (W3C documents, legal texts) in an ADR before building the pack; paraphrase and cite (3.20) |
| 23 | Refund policy | Window, pro-rata rules, non-refundable items and approval thresholds are set by the business and reviewed by the chartered accountant and legal advisor, then stored as settings (3.21) |
| 24 | Support scope and timing | A small built-in ticket system in Phase 5 as requested; move earlier if design partners need it; sync to an external helpdesk if volume grows (3.21) |
| 25 | Build order | Phase 3 (documents and eBooks) runs before Phase 2 (decided 2026-11-28). Revisit after design-partner feedback and the prospect interviews (decision 14) |

## 6. Top risks

| Risk | Mitigation |
|---|---|
| Overclaiming compliance (legal/regulatory exposure) | "Automated coverage X/Y" scoring, "Not Evaluated" defaults, human-signed VPATs, careful marketing copy |
| Our own UI has accessibility defects | CI gates from Phase 0, release AT matrix, disabled-user testing, public statement and feedback loop |
| PDF remediation is much harder than auditing, and cost more than the plan quotas allow | Sell audit plus guided fix first, route complex files to human review, measure review cost per document, set quotas from that cost (Phase 3) |
| Scope too broad, delaying revenue | Phase 1 kept to the web audit MVP and split into 1a and 1b; later phases driven by design-partner demand |
| LLM cost grows with crawl size | Template clustering, response cache, per-tenant budgets, deterministic checks before AI, model tiering and the resolution ladder (3.13), rule content library (3.14) |
| Hostile inputs (SSRF, malicious files, APKs) | Sandboxed workers, egress controls, domain verification, malware scanning |
| Admin misconfiguration breaks production (bad key, wrong price, disabled model) | Typed validation, test connection, draft/publish, evaluation gates, two-person approval, versioned rollback, audit log |
| Cheaper models degrade quality unnoticed | Validation layer, shadow-mode promotion behind an evaluation gate, escalation caps, validator precision audits, cost-versus-quality dashboard |
| The self-healing agent causes harm or loops | Allow-listed actions, deterministic policy engine, rate limits, auto-revert, Suggest-first autonomy, kill switch, no access to secrets or customer content |
| Payment state drifts from Razorpay (missed or duplicate webhooks) | Signature check, event-id de-duplication, idempotent handlers, nightly reconciliation, incident on mismatch |
| GST or e-invoicing mistakes | Chartered accountant sign-off, admin-configurable tax settings, gap-free invoice series, credit notes |
| Razorpay Checkout is not fully accessible (we do not control it) | Test it in the spike, publish the result, offer accessible fallback payment paths |
| Template edits break emails or reports | Save-time render and accessibility checks, two-person approval for billing and legal templates, last known-good fallback, version rollback |
| An undifferentiated product (commodity scanning) | Defined wedge, competitor comparison, customer interviews, order check after 1a (3.18) |
| Plan prices lose money on heavy plans (video, AI, human review) | Unit-cost model, per-unit metering, quotas set from the model, margin-per-tenant view, human review sold as an add-on |
| Admin account takeover | Admin MFA in 1a, two-person approval for high-risk changes, audit log, short sessions |
| Public API breaks integrators | `/v1` versioning, breaking-change gate in CI, `Deprecation` and `Sunset` headers, SDK contract tests |
| API key leaks | Hashed storage, recognisable key format for secret scanners, scopes, IP allow-lists, rotation, anomaly alerts |
| Liability from customers relying on our reports | Terms with liability limits, "not a guarantee" wording, human-signed VPATs, insurance review |
| Engine and rule drift over time | Pinned engine versions per scan, versioned rule registry, benchmark suite in CI |
| A price or plan edit changes existing subscribers' bills | Immutable plan versions, grandfathering, impact preview, two-person approval, notice before any move (3.19) |
| Discounts stack into near-free plans, or codes are guessed | Total discount cap, stacking policy, attempt rate limits with uniform errors, per-coupon kill switch, coupon analytics (3.19) |
| AI-written articles contain wrong accessibility or legal statements | Source-grounded drafting, V1 checks (our scanner runs every code sample), V2 claim check, mandatory named human reviewer, SME for law, overclaim lint, review dates (3.20) |
| Search penalties or lost trust from mass-produced AI content | Draft-only, weekly cap, original verified examples, `noindex` until reviewed, AI disclosure (3.20) |
| Our own articles are inaccessible | The publish gate runs our scanner on the rendered page and blocks on failure (3.20) |
| Refund errors or fraud (over-refund, refund-then-retrial) | One eligibility function, capped at captured amount, two-person approval, webhook-confirmed status, credit notes, reconciliation, abuse flags (3.21) |
| Support data leaks between tenants, or internal notes reach customers | RLS on all ticket tables, `visibility` column with tests, isolation suite coverage, attachment scanning, retention limit (3.21) |
