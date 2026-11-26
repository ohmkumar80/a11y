# Application Blueprint

High-level architecture for the accessibility compliance platform (WCAG 2.2 AA).

```text
====================================================================================================
                                    CLIENT & ADMIN INTERFACES (WCAG 2.2 AA)
   [User Dashboard]                 [Company Admin Dashboard]              [Super Admin Dashboard]
   • URL/App/Doc/Video Scans        • Team Seats & Limit Guardrails        • Tenant & Trial Funnel
   • Interactive Fix Workbench      • Quota Meters & Plan Billing          • Promo / Coupon Engine
   • VPAT 2.5 / ACR Exports         • Discount / Coupon Redemption         • AI FinOps & Pod Routing
====================================================================================================
                                               │ HTTPS / REST + WebSockets (JWT + Tenant RLS)
                                               ▼
====================================================================================================
                         API GATEWAY & COMMERCIAL GOVERNANCE CORE (FastAPI)
   ┌───────────────────────────┐   ┌──────────────────────────┐   ┌────────────────────────────┐
   │ Multi-Tenant RBAC & Seats │   │ Subscription, Trial &    │   │ Canonical Compliance Rule  │
   │ • Org Isolation (RLS)     │   │   Quota Guardrails       │   │   Registry                 │
   │ • Hard User Seat Caps     │   │ • 14-Day Trial Engine    │   │ • WCAG 2.0 / 2.1 / 2.2     │
   │ • Audit Logs              │   │ • Coupon/Discount Engine │   │ • ADA, Sec 508, EAA, AU DDA│
   └───────────────────────────┘   └──────────────────────────┘   └────────────────────────────┘
                                               │
                                               ▼ Enqueues Async Jobs (Redis + Celery)
====================================================================================================
                     DISTRIBUTED ASYNC WORKER FLEET (ZERO-LICENSE OPEN-SOURCE STACK)
 ┌─────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────────────┐
 │ 1. WEB & SCREEN READER  │  │ 2. DOCUMENT & EBOOK      │  │ 3. MEDIA & MOBILE WORKERS        │
 │    WORKERS              │  │    REMEDIATION WORKERS   │  │                                  │
 │ • Playwright Crawler    │  │ • PDF: veraPDF + pikepdf │  │ • Video/Audio: FFmpeg + Faster-  │
 │   (Auth/Login State)    │  │   (Auto-tag & PDF/UA out)│  │   Whisper (STT -> .vtt/.srt) +   │
 │ • Multi-Engine Ensemble:│  │ • EPUB: EPUBCheck + Ace  │  │   Piper/Kokoro TTS (Audio Desc.) │
 │   axe-core + Pa11y +    │  │   by DAISY (OPF/ARIA fix)│  │ • Android: Appium + Google ATF   │
 │   IBM equal-access      │  │ • PPTX/DOCX: python-pptx │  │   + TalkBack Tree & Speech Log   │
 │ • Guidepup (NVDA/Orca)  │  │   / docx XML Rebuilder   │  │ • iOS (Phase 4): XCUITest +      │
 │   Spoken Speech Capture │  │ • Remediated File Export │  │   VoiceOver (On-Demand Mac Host) │
 └───────────┬─────────────┘  └────────────┬─────────────┘  └────────────────┬─────────────────┘
             └─────────────────────────────┼─────────────────────────────────┘
                                           ▼
====================================================================================================
                        AI COGNITIVE & REMEDIATION GATEWAY (Multi-LLM Router)
   • Vision-LLM Visual Auditor (detects contrast over gradients, text-in-image, broken focus rings)
   • Autonomous Keyboard & Focus-Trap Agent (Tab/Arrow traversal vs. visual DOM layout)
   • AI Code-Patch Copilot (HTML/ARIA/React, Jetpack Compose/Kotlin, SwiftUI fixes)
   • AI Alt-Text, Chart & STEM MathML Generator + HITL SME Approval Queue (Chennai/Salem/Madurai)
   • VPAT 2.5 / ACR Synthesizer (maps findings to WCAG, 508, EN 301 549, ADA, AU DDA templates)
====================================================================================================
                                               │
                                               ▼
====================================================================================================
                                   PERSISTENCE & OBJECT STORAGE LAYER
   [PostgreSQL + Row-Level Security]        [Redis (Broker / Cache)]        [S3 / Azure Blob]
   • Orgs, Plans, Coupons, Quotas           • Job Queues & Rate Limits      • Raw & Remediated PDFs,
   • Canonical Rules & Law Mappings         • Template Crawl Fingerprints     PPTX, EPUB3, VTT, MP4,
   • Unified Findings & VPAT Snapshots                                        Screenshots & VPAT DOCX
====================================================================================================
```

## Layers at a glance

| Layer | Responsibility | Key tech |
|---|---|---|
| Client & Admin Interfaces | User, Company Admin and Super Admin dashboards | REST + WebSockets, JWT |
| API Gateway & Governance Core | Multi-tenant RBAC, seat caps, trials, coupons, canonical compliance rule registry | FastAPI, Redis + Celery |
| Async Worker Fleet | Web/screen reader scans, document remediation, media and mobile workers | Playwright, axe-core, Pa11y, IBM equal-access, Guidepup, veraPDF, pikepdf, EPUBCheck, Ace, FFmpeg, Faster-Whisper, Piper/Kokoro, Appium |
| AI Cognitive & Remediation Gateway | Vision audits, focus-trap agent, code patches, alt-text/MathML, VPAT/ACR synthesis | Multi-LLM router, HITL SME approval queue |
| Persistence & Object Storage | Relational data with tenant isolation, queues/cache, file storage | PostgreSQL (RLS), Redis, S3 / Azure Blob |

## Notes

- iOS (XCUITest + VoiceOver on an on-demand Mac host) is scheduled for Phase 4.
- Tenant isolation is enforced through JWT claims plus PostgreSQL Row-Level Security.
- Compliance targets: WCAG 2.0/2.1/2.2, ADA, Section 508, EAA / EN 301 549, AU DDA.
