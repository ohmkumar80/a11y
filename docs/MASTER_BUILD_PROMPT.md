# Master Build Prompt: Omni-Channel AI Accessibility (A11y) SaaS Platform

> Original product specification, kept verbatim as the source of truth for scope.
> The recommended execution order, changes and accessibility commitments are in [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Role & Context
You are a Principal Full-Stack & AI Systems Architect. Build a production-grade, multi-tenant **Accessibility-as-a-Service (A11y) SaaS Platform** using a zero-license open-source stack. The platform must itself strictly conform to **WCAG 2.2 Level AA** (using accessible UI primitives like Radix UI / React Aria).

## Tech Stack
- **Frontend:** Next.js (App Router, TypeScript), Tailwind CSS, Radix UI / React Aria, Recharts/Tremor.
- **Backend:** Python 3.11+, FastAPI, SQLAlchemy (Async), Alembic, Pydantic v2.
- **Database & Queue:** PostgreSQL 16 (with Row-Level Security for tenant isolation), Redis, Celery workers.
- **Storage:** S3-compatible object storage (MinIO locally / AWS S3 / Azure Blob in prod).
- **Web & Screen Reader Engines:** Playwright, `axe-core`, `pa11y` (`HTML_CodeSniffer`), `accessibility-checker` (IBM Equal Access), `@guidepup/guidepup` (NVDA/Orca spoken phrase capture).
- **Document & ePub Engines:** `veraPDF` (PDF/UA validation), `pikepdf` + `pymupdf` (PDF tag tree & metadata manipulation), `python-pptx`, `python-docx`, `EPUBCheck`, `@daisy/ace` (Ace by DAISY).
- **Media Engines:** `FFmpeg`, `faster-whisper` (STT + timestamps), `piper-tts` (Audio Description synthesis).
- **Mobile Engine (Phase 3/4):** Appium (`UiAutomator2` + Google Accessibility Test Framework for Android `.apk` + TalkBack tree inspection).
- **AI Layer:** Configurable Multi-LLM Gateway (Azure OpenAI / OpenAI / Gemini Vision) for visual auditing, code-patch generation, alt-text/STEM MathML synthesis, audio description scripting, and VPAT narrative generation.

---

## Module 1: Multi-Tenant SaaS Core, Trials, Seat Limits & Discounts
Implement the commercial and governance foundation first:

1. **Database Schema (`models/saas_core.py`):**
   - `SubscriptionPlan`: `id`, `name` (`TRIAL`, `STARTER`, `GROWTH`, `ENTERPRISE`), `price_monthly_inr`, `price_annual_inr`, `max_users` (int, `-1` for unlimited), `quota_urls_monthly`, `quota_doc_pages_monthly`, `quota_alt_text_monthly`, `quota_video_mins_monthly`, `quota_mobile_scans_monthly`, `allowed_standards` (JSONB), `white_label_enabled` (bool).
   - `Organization`: `id`, `name`, `slug`, `domain`, `plan_id` (FK), `subscription_status` (`TRIALING`, `ACTIVE`, `PAST_DUE`, `LOCKED_READ_ONLY`), `trial_ends_at`, `billing_cycle` (`MONTHLY`, `ANNUAL`), `applied_coupon_id` (FK, nullable), `custom_logo_url`.
   - `DiscountCoupon`: `id`, `code` (unique uppercase), `discount_type` (`PERCENTAGE`, `FIXED_INR`), `discount_value`, `valid_from`, `valid_until`, `max_redemptions`, `current_redemptions`, `applicable_plan_ids` (JSONB), `is_active`.
   - `User`: `id`, `organization_id` (FK, nullable for Super Admin), `email`, `hashed_password`, `role` (`SUPER_ADMIN`, `COMPANY_ADMIN`, `STANDARD_USER`), `is_active`.
   - `UsageLedger`: `id`, `organization_id`, `billing_period_start`, `urls_used`, `doc_pages_used`, `alt_text_used`, `video_mins_used`, `mobile_scans_used`.

2. **Enforcement Middleware (`core/guardrails.py`):**
   - **Seat Limit Guard:** Block user invitations/activations when `active_users_count >= plan.max_users` and return a structured upgrade prompt.
   - **Trial Expiration Cron:** Automatically transition expired trials to `LOCKED_READ_ONLY` (users can view past reports but cannot trigger new scans/remediations until upgrading).
   - **Quota Reservation Guard:** Atomically check and reserve credits in `UsageLedger` before enqueuing any Celery scan/remediation job; refund credits if a worker fails due to system error.

---

## Module 2: Canonical Compliance Rule Registry (Multi-Law Selector)
Build a jurisdiction-aware rule engine (`models/compliance.py` & `services/rule_mapper.py`):
- Seed `ComplianceStandard` records for:
  - `WCAG_2_0_AA`, `WCAG_2_1_AA`, `WCAG_2_2_AA`, `WCAG_2_2_AAA`
  - `US_ADA_TITLE_II` (maps to WCAG 2.1 AA + public digital assets)
  - `US_SECTION_508` (maps to WCAG 2.0 AA + Chapters 3, 5, 6)
  - `EU_EAA_EN_301_549` (maps to EN 301 549 Clauses 9 Web, 10 Non-Web Docs, 11 Software)
  - `AU_DDA_AS_EN_301_549` (maps to WCAG 2.2 AA + Australian AS EN 301 549)
  - `IN_RPWD_GIGW_3` (maps to WCAG 2.1 AA + IS 17802)
  - `EPUB_A11Y_1_1` & `PDF_UA_ISO_14289`
- Seed `CanonicalRule` and `StandardRuleMapping` tables linking internal check IDs to exact legal clause citations so a single scan dynamically recalculates compliance scores and filters issues when the user switches laws in the UI.

---

## Module 3: Progressive AI Audit & File Remediation Workers (Celery)
Implement modular workers in `workers/`:

1. **Web URL & Screen Reader Worker (`workers/web_audit_worker.py`):**
   - Launches headless Playwright (supporting optional user-uploaded `storageState.json` cookies/localStorage for authenticated portals).
   - Runs **3-Engine Ensemble** (`axe-core` + `pa11y` + `IBM accessibility-checker`), normalizes outputs into `CanonicalRule` IDs, and deduplicates overlapping selectors.
   - Captures Accessibility Tree (`AXTree`), runs Guidepup virtual/screen-reader navigation script to record spoken announcements, and executes an AI keyboard Tab/focus-trap traversal check.
   - Captures full-page + element bounding-box screenshots and passes them to the **Vision-LLM Auditor** to detect text-in-images, gradient contrast failures, and low-quality alt-text.
   - Calls the **AI Code-Fix Copilot** to generate copy-paste HTML/ARIA/React patch snippets for each clustered root-cause issue.

2. **Document & eBook Remediation Worker (`workers/doc_remediation_worker.py`):**
   - **PDF (`PDF/UA`):** Runs `veraPDF` baseline audit $\rightarrow$ uses Vision-LLM layout analysis + `pikepdf` to inject missing title, language (`en-US`), reading-order struct tree (`H1`–`H6`, `P`, `L`, `Table`), and AI-generated alt-text $\rightarrow$ re-validates with `veraPDF` $\rightarrow$ saves `remediated_<filename>.pdf` to object storage.
   - **PPTX (`.pptx`):** Uses `python-pptx` + Vision-LLM to reorder slide shape XML z-order into logical screen-reader sequence, populate missing slide titles, and inject shape/chart alt-text $\rightarrow$ outputs `remediated_<filename>.pptx`.
   - **DOCX (`.docx`):** Uses `python-docx` + LLM to convert visual bold/sized headers into semantic `Heading 1/2/3`, mark table header rows, and inject image alt-text $\rightarrow$ outputs `remediated_<filename>.docx`.
   - **EPUB3 (`.epub`):** Unzips EPUB, runs `EPUBCheck` + `Ace by DAISY`, injects `schema:accessMode`, `accessibilityFeature`, and `accessibilitySummary` into `package.opf`, adds ARIA landmarks and AI alt-text/MathML, repackages, re-validates, and outputs `remediated_<filename>.epub`.
   - Includes a `needs_sme_review` flag to route complex STEM/multi-column files to a Human-in-the-Loop (HITL) review queue.

3. **Audio & Video Accessibility Worker (`workers/media_worker.py`):**
   - Extracts audio via `FFmpeg` $\rightarrow$ runs `faster-whisper` with word-level timestamps and speaker labels $\rightarrow$ exports `.vtt` (WebVTT), `.srt`, and full `.docx`/`.txt` transcript.
   - Extracts keyframes during dialogue pauses $\rightarrow$ Vision-LLM drafts concise **Audio Description (AD)** narration $\rightarrow$ synthesizes AD audio via `piper-tts` $\rightarrow$ muxes secondary AD audio track + VTT captions into an accessible `.mp4` master.

4. **Android Mobile App Worker (`workers/mobile_android_worker.py`):**
   - Accepts `.apk` upload, launches headless Android emulator + Appium (`UiAutomator2`) + Google Accessibility Test Framework, traverses screens in TalkBack focus order, captures `AccessibilityNodeInfo` speech logs + screenshots, and generates Kotlin / Jetpack Compose / React Native fixes.

---

## Module 4: Three Role-Based Dashboards & Reports
Build clean, WCAG 2.2 AA-compliant Next.js interfaces:

1. **Super Admin Dashboard (`/admin`):**
   - Tenant directory, trial conversion metrics, MRR/ARR overview, AI token cost telemetry per tenant, CRUD manager for `SubscriptionPlan` & `DiscountCoupon`, and HITL Specialist Escalation Queue.
2. **Company Admin Dashboard (`/org`):**
   - Team management with live seat counter (`X of Y seats used`) and hard limit enforcement, usage quota progress bars, plan upgrade + coupon redemption checkout flow, and white-label settings.
3. **User Workspace (`/workspace`):**
   - **New Scan / Remediation Modal:** Choose Asset Type (`Website URL`, `Document PDF/PPTX/DOCX/EPUB`, `Video/Audio`, `Android APK`) + Multi-select Target Standards (`WCAG 2.2 AA`, `ADA`, `Section 508`, `EU EAA`, `Australia DDA`).
   - **Interactive Fix Workbench:**
     - *Web/Mobile:* Split-screen visual screenshot inspector + spoken screen-reader log + copy-paste AI code fix.
     - *Documents/Alt-Text:* Side-by-side preview + editable AI alt-text/reading-order approval + **"Download Remediated File"** button.
     - *Video:* Synced waveform + editable `.vtt` caption & Audio Description timeline + bulk export (`.vtt`, `.srt`, `.mp4`).
   - **1-Click VPAT 2.5 / ACR & Audit Report Generator:** Exports jurisdiction-matched DOCX, PDF, and CSV reports.

---

## Execution Instructions
1. Start by generating the complete project directory structure, `docker-compose.yml` (PostgreSQL, Redis, MinIO, FastAPI, Celery worker, Next.js), and database migrations (`alembic`).
2. Build **Phase 1** (Multi-Tenant Auth, Seat Limits, Trials, Coupons, Canonical Rule Registry, and the 3-Engine Web URL Scanner + AI Code Fixer + VPAT Exporter) completely with working unit/integration tests before scaffolding the Document, Media, and Android workers.
3. Output setup commands, `.env.example`, and an architectural README upon completion.
