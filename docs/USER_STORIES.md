# User stories and status

This is [PROJECT_PLAN.md](PROJECT_PLAN.md) rewritten as user stories. Each row is one story. The plan stays the source of truth for scope and design. This file is the tracker for what is done.

**Last updated:** 2026-11-28. Status comes from the repository (branch `phase-1`, not yet merged) and the test runs recorded in the plan.

## How to read this

| Status | Meaning |
|---|---|
| **Done** | Built, tested and visible in the running app. A "draft" note means a human specialist must still review the content. |
| **Partly** | Some of the story works. The Notes column says what is missing. |
| **Not started** | Due in the current stage, but no work yet. |
| **Deferred** | Needs the owner's input or a person outside the code (a specialist, an accountant, an account). Agreed on 2026-11-28 to move to the final phase. |
| **Later** | Belongs to Phase 2 to 5 and is not due yet. |

**Personas.** *Visitor* (someone on the public site), *Member* (a person in a customer organisation), *Org admin* (the company admin of a customer), *Enterprise admin* (an org admin on the Enterprise plan), *Developer* (someone integrating through the API), *Platform admin* (our Super Admin), *Billing admin*, *Content editor / Reviewer / Publisher*, *Support agent*, *Accessibility lead* (our own owner of accessibility), *Ops owner*, *Business owner*.

**Stages.** 0 = Foundations, 1a = sellable to design partners, 1b = breadth and hardening, 2 to 5 = later phases.

**Definition of done for every UI story** (plan section 2.7): keyboard operable, correct names and roles, no axe violations in light and dark, works at 200% zoom and 320px, drag actions have a single-pointer alternative, targets at least 24 by 24px, live updates announced sensibly, checked with a screen reader.

---

## Summary

| Status | Stories |
|---|---|
| Done | 83 |
| Partly | 9 |
| Not started | 21 |
| Deferred | 27 |
| Later | 52 |
| **Total** | **192** |

| Epic | Done | Partly | Not started | Deferred | Later |
|---|---|---|---|---|---|
| E1. Our own product is accessible (plan section 2) | 5 | 4 | 1 | 2 | 3 |
| E2. Generated files are accessible (plan section 2.5) | 3 | 0 | 0 | 0 | 1 |
| E3. Foundations (Phase 0) | 8 | 0 | 2 | 0 | 0 |
| E4. Accounts, organisations, trial and seats | 7 | 0 | 2 | 0 | 0 |
| E5. Plans, quotas, coupons and pricing (plan 3.5 and 3.19) | 5 | 0 | 0 | 3 | 3 |
| E6. Admin-configurable platform (plan 3.11) | 8 | 1 | 1 | 2 | 3 |
| E7. AI gateway, tiering and validation (plan 3.7, 3.11.2, 3.13) | 5 | 1 | 3 | 1 | 0 |
| E8. Web scanner (plan 3.2, 3.6) | 11 | 0 | 1 | 0 | 0 |
| E9. Standards and rules (plan 3.8) | 3 | 0 | 0 | 1 | 0 |
| E10. Findings, Fix Workbench and code fixes (plan 3.13) | 5 | 0 | 4 | 0 | 0 |
| E11. Reports and VPAT (plan 3.14) | 4 | 0 | 1 | 1 | 0 |
| E12. Notifications and templates (plan 3.14) | 4 | 0 | 3 | 0 | 1 |
| E13. Public API and webhooks (plan 3.17) | 6 | 0 | 1 | 0 | 5 |
| E14. Reliability and operations (plan 3.15) | 3 | 2 | 1 | 0 | 2 |
| E15. Billing with Razorpay (plan 3.16) | 0 | 0 | 0 | 6 | 3 |
| E16. Security and trust (plan 3.6, 3.18) | 2 | 0 | 1 | 6 | 1 |
| E17. Knowledge base and Content Agent (plan 3.20) | 0 | 0 | 0 | 0 | 6 |
| E18. Phase 2: deep web audit and monetisation | 0 | 0 | 0 | 0 | 7 |
| E19. Phase 3: documents and eBooks | 0 | 0 | 0 | 0 | 5 |
| E20. Phase 4: audio and video | 0 | 0 | 0 | 0 | 5 |
| E21. Phase 5: mobile, refunds and support | 0 | 0 | 0 | 0 | 7 |
| E22. Decisions the plan needs (plan section 5) | 4 | 1 | 0 | 5 | 0 |

**What the numbers say.** The large Phase 1 features that need no outside input are built. The stories still open for Phase 1 are Razorpay billing and `price_quote`, the items that need a person (a specialist, an accountant, counsel, a human audit, the owner's decisions), and a list of small gaps (organisation logo, removing a team member, mark-as-fixed in the Workbench, a dead-letter queue, tracing and metrics, and similar). Phases 2 to 5 have not started, by design.

**Not yet verified.** These statuses come from the repository and test runs on a local branch. CI has never run on GitHub, and no manual screen reader pass has been done.

---

## E1. Our own product is accessible (plan section 2)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-001 | Member using a screen reader | every screen to meet WCAG 2.2 AA | I can use the product without help | 0 | Done | Axe runs on every route in light and dark in CI. Manual NVDA and VoiceOver pass is still outstanding (US-009) |
| US-002 | Developer on our team | accessibility checks to block a merge | accessibility never regresses | 0 | Done | Lint, Storybook axe, component tests with keyboard checks, e2e axe, contrast check on tokens (`.github/workflows/ci.yml`). CI has not yet run on GitHub |
| US-003 | Keyboard user | a skip link, landmarks, one h1, a unique page title per route, and a route-change announcement | I always know where I am | 0 | Done | A unique-title test covers every route including `?id=` pages |
| US-004 | Low-vision user | sufficient contrast, visible focus, reflow at 320px, reduced motion, forced colours | the UI works for my settings | 0 | Partly | Contrast, focus and reflow are gated. Forced-colours snapshot is not a gate yet |
| US-005 | Member | charts to have a table view, text summary and non-colour cues | I can read the data | 1a | Partly | Quota meters have text values. Charts are not built yet, so the chart rule is untested |
| US-006 | Member | live scan progress that does not flood my screen reader | I can follow a scan calmly | 1a | Done | One polite live region with milestone updates |
| US-007 | Member | forms with labels, inline errors, an error summary and no redundant entry | I can finish them (SC 3.3.7, 3.3.8) | 0 | Done | Shared `Form` component; no CAPTCHA |
| US-008 | Member | the same help link on every page | I can always find help (SC 3.2.6) | 0 | Partly | A `/help` page exists. Confirm the link on every dashboard |
| US-009 | Accessibility lead | a manual release pass with NVDA, JAWS, VoiceOver and TalkBack, plus a keyboard, high-contrast and voice-control pass | automated checks are not our only evidence | 1b | Deferred | Needs a person. Part of the final-phase list |
| US-010 | Accessibility lead | paid usability sessions with disabled users each quarter | we learn what automation misses | 2 | Later | |
| US-011 | Nightly build | our own scanner and a virtual screen reader to run against staging | we dogfood the product | 2 | Later | Needs a staging environment |
| US-012 | Visitor | an Accessibility Statement with our target, known issues and a feedback contact | I know how we stand | 1b | Partly | `/accessibility` page exists. Needs a refresh once the human audit is done |
| US-013 | Business owner | our own ACR (VPAT 2.5 INT) from a human audit | we can show enterprise buyers our own conformance | 1b | Deferred | Needs a human audit |
| US-014 | Visitor | an accessible feedback channel with a committed response time | I can report a barrier | 1b | Not started | The support-ticket "accessibility barrier" category (US-265) is the planned channel |
| US-015 | Org admin | brand colours checked for contrast when saved | a customer theme cannot break our UI | 2 | Later | |

## E2. Generated files are accessible (plan section 2.5)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-020 | Member | the audit PDF to be tagged PDF/UA-1 and pass veraPDF before I can download it | I can share it with anyone | 1a | Done | WeasyPrint plus veraPDF gate (ADR 0008) |
| US-021 | Member | the VPAT DOCX to use real headings, repeating table headers and alt text | it is usable in a screen reader | 1a | Done | Structure check in CI on golden samples |
| US-022 | Member | a CSV export with UTF-8, BOM and a header row | it opens correctly in spreadsheets | 1a | Done | Schema test |
| US-023 | Member | remediated customer files to be re-validated before delivery | I never get a broken file | 3 | Later | |

## E3. Foundations (Phase 0)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-030 | Developer on our team | a monorepo, one-command `docker compose up`, `.env.example` and a Makefile | I can run the whole stack | 0 | Done | |
| US-031 | Developer on our team | a CI pipeline with lint, types, tests, migration check, accessibility gates, container builds and secret scanning | quality is enforced | 0 | Done | `ci.yml` exists. It has never run on GitHub because nothing is pushed yet |
| US-032 | Developer on our team | a UI package with tokens, React Aria components and Storybook | screens share one accessible base | 0 | Done | Button, Link, TextField, Select, Dialog, Table, Tabs, Toast, Meter, Card and more |
| US-033 | Member | an app shell with landmarks, skip link, route announcer and error pages | navigation works for everyone | 0 | Done | |
| US-034 | Visitor | to sign up, verify my email, log in, reset my password and accept an invite | I can get started | 0 | Done | Short-lived access tokens, refresh cookie |
| US-035 | Developer on our team | row-level security and an isolation test suite | one customer never sees another's data | 0 | Done | ADR 0005 |
| US-036 | Developer on our team | structured logs with trace ids, OpenTelemetry, Prometheus and Grafana in compose | we can observe the system | 0 | Not started | No tracing or metrics stack is wired in yet |
| US-037 | Developer on our team | a `PaymentProvider` interface and a fake provider | billing code is testable | 0 | Not started | Comes with the Razorpay work (US-190) |
| US-038 | Developer on our team | ADRs for the main architecture choices | decisions are recorded | 0 | Done | ADRs 0001 to 0019 |
| US-039 | Developer on our team | a template system with versioned storage and a sandboxed renderer | emails and reports are editable and safe | 0 | Done | Notification templates built (ADR 0013); report templates in code |

## E4. Accounts, organisations, trial and seats

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-050 | Visitor | to start a 14-day trial for my company | I can try it | 1a | Done | |
| US-051 | Org admin | to invite people and see "X of Y seats used" | I manage my team | 1a | Done | Seat guard is race-safe |
| US-052 | Org admin | an upgrade prompt when seats or quota run out | I know what to do next | 1a | Done | Structured error the UI renders |
| US-053 | Org admin | a read-only locked state when the trial ends | my data is kept but I cannot scan | 1a | Done | `LOCKED_READ_ONLY` |
| US-054 | Org admin | to see my plan, quota meters and coupon | I know my limits | 1a | Done | `/org` |
| US-055 | Org admin | to upload my company logo | reports carry our brand | 1a | Not started | Plan lists "branding (logo only)" under `/org` |
| US-056 | Org admin | to remove a team member | people who leave lose access | 1b | Not started | Listed with the org endpoints in plan 3.17 |
| US-057 | Platform admin | a tenant directory with manual plan assignment and trial funnel counts | I can support customers | 1a | Done | `/admin` Organisations |
| US-058 | Platform admin | to give one organisation an exception to its plan, with a reason and an end date | I can make a special deal without a new plan | 1b | Done | Overrides (ADR 0019); audited |

## E5. Plans, quotas, coupons and pricing (plan 3.5 and 3.19)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-060 | Platform admin | to manage plans and entitlements in the admin | I change commercial terms without a deploy | 1a | Done | Launch limits are placeholders |
| US-061 | Platform admin | quota reservations that cannot overspend under parallel requests | a plan limit is a real limit | 1a | Done | Concurrency tests pass |
| US-062 | Platform admin | coupons with terms and redemption limits | I can run promotions | 1a | Done | |
| US-063 | Platform admin | bulk coupon batches with a campaign report and a kill switch | I can run a campaign | 1b | Done | ADR 0019 |
| US-064 | Org admin | credits for AI code fixes that are only used when a fix is accepted | I pay only for useful fixes | 1b | Done | `ai_code_fixes_monthly` meter; recipes, cache and failures are free |
| US-065 | Platform admin | one pure `price_quote` function used by checkout, Payment Links, invoices and previews | prices are never inconsistent | 1a | Deferred | Built together with Razorpay |
| US-066 | Platform admin | plan versions that never change after publishing, with grandfathering and notice before a move | a price edit never changes an existing bill | 1b | Deferred | Comes with `price_quote` |
| US-067 | Platform admin | a total discount cap and a stacking policy | discounts cannot reach near-free | 1b | Deferred | Comes with `price_quote` |
| US-068 | Platform admin | automatic promotions, add-ons and top-ups | I can sell more flexibly | 2 | Later | |
| US-069 | Business owner | eligibility discounts (non-profit, education, government) and partner or referral attribution | I can serve these segments | 2 | Later | |
| US-070 | Business owner | coupon analytics and a pricing page generated from published plans | marketing and billing always match | 2 | Later | |

## E6. Admin-configurable platform (plan 3.11)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-080 | Platform admin | typed settings with global, plan and organisation scopes, versions, audit and rollback | I can change behaviour safely without a redeploy | 0 | Done | ADR 0006 |
| US-081 | Platform admin | secrets that are write-only and encrypted | keys are never shown again | 0 | Done | |
| US-082 | Platform admin | forms generated from each setting's schema | every setting has an accessible editor | 0 | Done | |
| US-083 | Platform admin | draft, publish and "high risk" guards on dangerous settings | a bad edit cannot break production | 0 | Done | |
| US-084 | Platform admin | to set the two-step verification policy per admin group | I can turn it off in development and require it in production | 1a | Done | ADR 0010. Off is refused in production |
| US-085 | Platform admin | to choose the email provider and test the connection | I can switch mail servers without a deploy | 1b | Done | ADR 0016; password encrypted |
| US-086 | Platform admin | feature flags per plan or organisation | I can roll features out gradually | 1b | Done | ADR 0016 |
| US-087 | Platform admin | to set legal page content and see public pages with footer links | legal text lives in settings | 1b | Partly | Mechanism done. No legal text is shipped on purpose; the owner or counsel writes it |
| US-088 | Platform admin | scan engine settings, including screenshot options | I tune scanning without code | 1a | Done | |
| US-089 | Platform admin | granular admin roles | each admin gets only the access they need | 1b | Deferred | Needs the owner to decide who may do what |
| US-090 | Platform admin | two-person approval for high-risk changes | one person cannot make a damaging change alone | 1b | Deferred | Same decision as US-089 |
| US-091 | Platform admin | an editor and preview for report templates | I can edit report wording | 1a | Not started | Plan lists an admin template editor. Email wording is editable (US-132) |
| US-092 | Platform admin | a payment gateway registry and tax settings | I can change payment setup in the admin | 2 | Later | |
| US-093 | Platform admin | prompt versioning with evaluation-gated activation and staged rollouts | prompt changes are safe | 2 | Later | |
| US-094 | Platform admin | per-organisation data policy (regions, zero retention) | enterprise data rules are honoured | 2 | Later | |

## E7. AI gateway, tiering and validation (plan 3.7, 3.11.2, 3.13)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-100 | Platform admin | to add AI providers and models as data and route each task | providers are swappable | 1a | Done | DeepSeek, Azure OpenAI, OpenAI, OpenAI-compatible, Anthropic and a fake provider |
| US-101 | Platform admin | automatic fallback to another provider when one fails | an outage does not stop work | 1a | Done | Works across vendors |
| US-102 | Platform admin | "Test connection" and quick-add for a provider | I do not save a broken key | 1a | Done | |
| US-103 | Platform admin | per-task budgets and metering | AI cost is capped and visible | 1a | Partly | Metering and budgets exist; model prices start at 0 and need setting. Per-tenant cost view is Phase 2 |
| US-104 | Enterprise admin | to use my own AI provider key | my data stays under my own contract | 1a | Done | `/org/ai`, SSRF-guarded |
| US-105 | Platform admin | an AWS Bedrock adapter | we can use Bedrock models | 1a | Deferred | Needs AWS request signing and an account to test against |
| US-106 | Platform admin | a cheap model first, a stronger model only when needed, and an independent reviewer | quality is high and cost is low | 1a | Done | Ladder with escalation and reviewer (ADR 0011) |
| US-107 | Platform admin | shadow-mode promotion of cheaper models and a cost-versus-quality dashboard | I move to cheaper models safely | 1b | Not started | |
| US-108 | Platform admin | a human review queue for fixes the AI could not validate | nothing unchecked reaches a customer | 1b | Not started | Those fixes are held as "needs review" today |
| US-109 | Business owner | the share of findings fixed without a model call, and cost per accepted fix, reported | I can prove the unit economics | 1a | Not started | Exit criterion; metrics exist per fix but no report |

## E8. Web scanner (plan 3.2, 3.6)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-110 | Member | to scan a URL, or crawl a bounded site | I see accessibility problems | 1a | Done | Respects robots.txt |
| US-111 | Member | three engines to run in one page and their results merged with a confidence score | I get fewer false alarms | 1a | Done | axe, IBM Equal Access, HTML_CodeSniffer |
| US-112 | Member | similar findings grouped by template | I fix a root cause once | 1a | Done | Clusters |
| US-113 | Member | a full-page screenshot with the problem element outlined | I can see the problem | 1a | Done | ADR 0012 |
| US-114 | Org admin | to prove I own a domain before scanning it deeply | scanning is authorised | 1a | Done | Domain verification |
| US-115 | Platform admin | scans to be unable to reach internal addresses | scanning untrusted URLs is safe | 1a | Done | Egress proxy, SSRF checks (ADR 0007). Production needs a separate network for the web worker |
| US-116 | Platform admin | per-organisation rate and concurrency limits | one customer cannot starve others | 1a | Done | |
| US-117 | Platform admin | a recorded scanner benchmark gated in CI | recall and precision are known | 1a | Done | `docs/benchmark.md`. The independent GOV.UK review was AI-assisted and needs a specialist's re-check |
| US-118 | Platform admin | custom checks for the known gaps in the benchmark | detection improves | 1b | Not started | About 35 known gaps |
| US-119 | Platform admin | a worker killed mid-scan to resume or fail with a reason and leave no credits reserved | scans are reliable | 1a | Done | State machine, heartbeat, sweepers |
| US-120 | Platform admin | orphaned reservations released automatically | credits are not stuck | 1a | Done | Sweeper every 10 minutes |
| US-121 | Platform admin | pinned engine versions recorded per scan | results are reproducible | 1a | Done | |

## E9. Standards and rules (plan 3.8)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-125 | Member | to switch the standard (WCAG 2.0, 2.1, 2.2, Section 508, EN 301 549, GIGW, ADA and others) and see scores recalculated | I report against the law that applies to me | 1a | Done | 87 criteria, 12 standards, 42 canonical rules |
| US-126 | Accessibility lead | mappings to be signed off by a named specialist | we never overstate compliance | 1a | Deferred | All mappings are `draft` until a specialist signs off |
| US-127 | Member | an explanation, a fix and examples for every rule | I know what to do | 1a | Done | 43 guides, each example run through the real engines. Draft until reviewed. 9 rules are marked for human checking |
| US-128 | Member | an honest "automated coverage X of Y" score | I am not told I comply when I may not | 1a | Done | "Not Evaluated" defaults |

## E10. Findings, Fix Workbench and code fixes (plan 3.13)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-135 | Member | a list of scans and a findings view with filters | I can review results | 1a | Done | |
| US-136 | Member | the Fix Workbench: problem list, screenshot with the element outlined, guidance and a checked code fix | I can fix problems one by one | 1a | Done | `/workspace/scan/workbench` |
| US-137 | Member | a code fix that has been re-scanned and passes before I see it | I never get a fix that makes it worse | 1a | Done | Static checks plus the re-scan oracle |
| US-138 | Member | fixes from fixed recipes for common problems, free of charge | common fixes are instant | 1a | Done | 6 recipes. No image-alt recipe by design |
| US-139 | Member | fixes for React and other stacks | I get code in my framework | 1b | Not started | Fixes are HTML attribute-level today |
| US-140 | Member | fixes to page content, not only attributes | more problems can be fixed | 1b | Not started | The scanner stores only the opening tag |
| US-141 | Member | to mark a problem fixed or ignored and re-scan one page | I track progress | 1a | Not started | Listed as not yet in the plan |
| US-142 | Member | a text description of the selected element next to the screenshot | I do not depend on the picture | 1a | Done | |
| US-143 | Platform admin | a screenshot retention policy | storage does not grow forever | 1b | Not started | |

## E11. Reports and VPAT (plan 3.14)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-145 | Member | in-app results, CSV, PDF and DOCX exports | I can share results | 1a | Done | |
| US-146 | Member | a VPAT draft with "Not Evaluated" defaults that never proposes "Supports" | the draft is honest | 1a | Done | WCAG tables |
| US-147 | Org admin | to edit the VPAT and sign it off before export | a human stands behind it | 1a | Done | Export only after sign-off |
| US-148 | Member | VPAT chapters for Section 508, EU and international | I can answer any buyer | 1a | Deferred | Needs the authoritative source text |
| US-149 | Member | per-element screenshots in reports | the report shows the problem | 1a | Not started | |
| US-150 | Platform admin | report layouts as permanent templates | reports stay consistent | 1a | Done | |

## E12. Notifications and templates (plan 3.14)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-130 | Member | emails for verify, invite, reset, trial ending and ended, scan finished and failed, and scan limit reached | I know what is happening | 1a | Done | ADR 0013; accessible fixed layout |
| US-131 | Member | an in-app notification list with an unread count and mark-as-read | I do not rely on email | 1b | Done | ADR 0017 |
| US-132 | Platform admin | to edit email wording with a preview, a test send and a delivery log | I tune messages without a deploy | 1a | Done | Guards stop unknown placeholders and generic link text |
| US-133 | Member | to opt out of scan emails | I control my inbox | 1b | Done | |
| US-134 | Member | per-event preferences and digests | I choose exactly what I get | 1b | Not started | Digests are listed in Phase 2 |
| US-151 | Member | payment emails (receipt, failed payment, plan changed) | I know about billing events | 1a | Not started | Comes with Razorpay |
| US-152 | Platform admin | bounce handling | bad addresses are marked | 1b | Not started | |
| US-153 | Org admin | Slack or Teams alerts and Indian-language email variants | I get alerts where I work | 2 | Later | |

## E13. Public API and webhooks (plan 3.17)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-160 | Developer | scoped API keys I can create and revoke | my systems can call the API safely | 1a | Done | Stored hashed; `/org/api` |
| US-161 | Developer | a versioned `/v1` API for scans, findings, summary, reports and the audit log | I can integrate | 1a | Done | 10 endpoints (ADR 0014) |
| US-162 | Developer | idempotency keys and rate limits | retries are safe | 1a | Done | |
| US-163 | Developer | an accessible API reference with a published OpenAPI file | I can learn the API | 1b | Done | `/developers`. Runnable examples and a changelog are missing |
| US-164 | Developer | signed, retried webhooks for scan and report events | I hear about results without polling | 1b | Done | ADR 0015; checked against internal addresses on every delivery |
| US-165 | Developer | an audit-log endpoint | our security team can pull it | 1b | Done | `GET /v1/audit-log` |
| US-166 | Developer | Python and TypeScript SDKs and an `a11y` CLI | I integrate faster | 2 | Later | |
| US-167 | Developer | OAuth 2.0 client credentials | I use standard machine auth | 2 | Later | |
| US-168 | Developer | a GitHub Action and GitLab template that fail a build on new violations | accessibility is part of CI | 2 | Later | |
| US-169 | Org admin | Jira and GitHub issue sync, Slack and Teams | findings flow into our tools | 2 | Later | |
| US-170 | Enterprise admin | SSO (SAML or OIDC) and SCIM provisioning | I manage users centrally | 2 | Later | Needed before large enterprise deals |
| US-171 | Developer | org read and write endpoints, webhook management and finding-lifecycle endpoints through the API | I can manage everything programmatically | 1b | Not started | Webhooks are managed in the UI only today |

## E14. Reliability and operations (plan 3.15)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-175 | Ops owner | scheduled canaries for the browser, PDF and mail server | I find outages before customers do | 1b | Done | ADR 0018 |
| US-176 | Ops owner | a read-only operations page with health, queues and incidents | I see the state of the system | 1b | Done | `/admin` Operations tab |
| US-177 | Ops owner | runbooks for the common failures | anyone can respond | 1b | Done | 12 runbooks |
| US-178 | Ops owner | paging and a public status page | the right person is told and customers are informed | 1b | Not started | |
| US-179 | Ops owner | retries by error class and a dead-letter queue | failures are handled and visible | 0 | Partly | Retries and sweepers exist. No dead-letter queue yet |
| US-180 | Ops owner | provider circuit breakers | a failing provider is skipped quickly | 1a | Partly | Fallback exists; confirm breaker behaviour |
| US-181 | Ops owner | an Ops Agent that suggests and, with approval, runs allow-listed actions | incidents are handled faster | 2 | Later | Starts once real incidents exist |
| US-182 | Ops owner | billing reconciliation incidents | payment drift is caught | 2 | Later | |

## E15. Billing with Razorpay (plan 3.16)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-190 | Developer on our team | a Razorpay test-mode spike that also tests its checkout accessibility | we know it works for everyone | 1a | Deferred | To do together with the owner; account activation (KYC) has a long lead time |
| US-191 | Business owner | a webhook receiver that checks the signature and ignores duplicates and out-of-order events | payment state is correct | 1a | Deferred | Exit criterion with forged-signature tests |
| US-192 | Billing admin | to send a Payment Link that activates a plan through the webhook | a design partner can pay | 1a | Deferred | |
| US-193 | Business owner | GST-compliant invoices as accessible PDF/UA with a gap-free series | we meet tax rules | 1a | Deferred | A chartered accountant confirms rate, SAC code and e-invoicing first |
| US-194 | Billing admin | essential `/admin/billing` screens | I can see and handle payments | 1a | Deferred | |
| US-195 | Org admin | a read-only `/org/billing` with plan and invoices | I can see what I paid | 1a | Deferred | |
| US-196 | Org admin | self-serve subscriptions, plan changes, dunning and an accessible upgrade checkout | I can pay without staff | 2 | Later | |
| US-197 | Billing admin | nightly reconciliation, `PAST_DUE` and lock handling | state never drifts | 2 | Later | |
| US-198 | Billing admin | refunds and credit notes (admin-initiated) | I can return money properly | 2 | Later | |

## E16. Security and trust (plan 3.6, 3.18)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-200 | Platform admin | admin sessions that refresh safely and detect replay | a stolen cookie is not enough | 1a | Done | Rotating httpOnly cookie |
| US-201 | Platform admin | two-step verification for every admin role | admin takeover is hard | 1a | Done | TOTP and recovery codes. WebAuthn is not built |
| US-202 | Platform admin | a security owner and a penetration test before the first paying customer | we meet buyer expectations | 1b | Deferred | Needs people and a vendor |
| US-203 | Business owner | a privacy contact, data-processing terms, subprocessor list and retention policy | enterprise buyers can approve us | 1b | Deferred | Needs the owner and counsel |
| US-204 | Business owner | customers to accept terms at sign-up | we are protected and they are informed | 1b | Deferred | Needs legal text |
| US-205 | Platform admin | production secrets set and the web worker network isolated | production is safe | 1b | Deferred | Part of the production checklist in the plan |
| US-206 | Business owner | SOC 2 or ISO 27001 readiness | large buyers can sign | 3 | Later | Only when a deal requires it |
| US-207 | Business owner | a defined market wedge, a competitor comparison and 5 to 10 prospect interviews | we are not just another scanner | 1a | Deferred | Needs the owner. An exit item for 1a |
| US-208 | Business owner | a unit-cost model that sets plan quotas | plans do not lose money | 1a | Not started | |
| US-209 | Business owner | a product name, domain and trademark check | we can launch publicly | 1b | Deferred | Needs the owner |

## E17. Knowledge base and Content Agent (plan 3.20)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-215 | Content editor | to write and manage articles with a workflow and audit trail | content is controlled | 2 | Later | `/admin/content` |
| US-216 | Reviewer | a review queue and an accessibility publishing gate that scans the rendered page | no inaccessible article goes live | 2 | Later | |
| US-217 | Visitor | a public `/learn` with search, RSS and sitemap | I can learn accessibility | 2 | Later | |
| US-218 | Member | "Learn more" links from rule pages | I go deeper from a finding | 2 | Later | |
| US-219 | Content editor | a Content Agent that plans and drafts articles, checks code samples with our scanner, and refreshes articles | I write faster, with human approval | 2 | Later | Draft-only; a named human publishes |
| US-220 | Content editor | about 20 reviewed launch articles | the agent has good examples | 2 | Later | Written by people first |

## E18. Phase 2: deep web audit and monetisation

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-230 | Member | authenticated scans with encrypted login state | I can scan pages behind login | 2 | Later | |
| US-231 | Member | a keyboard and focus-trap check with an explanation of what it found | I find keyboard problems | 2 | Later | |
| US-232 | Member | a virtual screen reader transcript in the workbench | I hear what a user would hear | 2 | Later | |
| US-233 | Member | a vision check for text in images, contrast over images and alt text quality | I find what code checks miss | 2 | Later | |
| US-234 | Member | scheduled monitoring, a scan-to-scan difference and digests | I see progress over time | 2 | Later | |
| US-235 | Platform admin | MRR and ARR, trial conversion, AI cost per tenant and budget caps | I run the business on data | 2 | Later | |
| US-236 | Org admin | white-label reports with contrast-validated brand colours | reports carry our brand | 2 | Later | |

## E19. Phase 3: documents and eBooks

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-240 | Member | to upload a PDF and get it audited and remediated, then re-validated | my documents are accessible | 3 | Later | veraPDF, layout analysis, tags |
| US-241 | Member | the same for DOCX, PPTX and EPUB3 | all my document types are covered | 3 | Later | |
| US-242 | SME reviewer | a review console with a queue, assignment, side-by-side review and SLA tracking | people check what AI cannot | 3 | Later | No drag-only actions |
| US-243 | Member | a document workbench with editable alt text and a reading-order editor with move up and down buttons | I can correct the result | 3 | Later | |
| US-244 | Developer | `/v1/documents` endpoints | I can automate document checks | 3 | Later | |

## E20. Phase 4: audio and video

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-250 | Member | transcripts and captions from my audio and video in VTT, SRT, TXT and DOCX | my media is accessible | 4 | Later | |
| US-251 | Member | a caption editor with text rows and time inputs and remappable shortcuts | I can fix captions | 4 | Later | |
| US-252 | Member | audio description with human approval and an accessible MP4 | blind users can follow the video | 4 | Later | |
| US-253 | Member | Indian-language captions | I serve the domestic market | 4 | Later | |
| US-254 | Developer | `/v1/media` endpoints | I can automate media checks | 4 | Later | |

## E21. Phase 5: mobile, refunds and support

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-260 | Member | to upload an Android APK and get an accessibility audit and fix suggestions | my app is checked | 5 | Later | Sandboxed emulator |
| US-261 | Member | iOS and real screen reader capture | I get real-device evidence | 5 | Later | Backlog by demand |
| US-262 | Developer | `/v1/mobile` endpoints | I can automate mobile checks | 5 | Later | |
| US-263 | Org admin | to request a refund from `/org/billing` with a reason | I can get money back under the policy | 5 | Later | |
| US-264 | Billing admin | a refund queue with the eligibility calculation, approval and a confirmed Razorpay refund and credit note | refunds are correct and auditable | 5 | Later | `/admin/billing/refunds` |
| US-265 | Org admin | to create support tickets with attachments, reply, close, reopen and rate | I get help | 5 | Later | `/org/support` |
| US-266 | Support agent | to assign, answer and resolve tickets with SLA timers, internal notes and canned replies | support is organised | 5 | Later | `/admin/support` |

## E22. Decisions the plan needs (plan section 5)

| ID | As a | I want | So that | Stage | Status | Notes |
|---|---|---|---|---|---|---|
| US-280 | Business owner | the UI library chosen | the UI is consistent | 0 | Done | React Aria Components (ADR 0001) |
| US-281 | Business owner | one production cloud chosen | we can deploy | 0 | Done | ADR 0002 |
| US-282 | Business owner | the AI providers and data policy chosen | we know where data goes | 0 | Done | ADR 0003. Zero-retention agreements are not confirmed |
| US-283 | Business owner | the task broker chosen | jobs are reliable | 0 | Done | Redis (ADR 0004) |
| US-284 | Business owner | a named accessibility specialist (IAAP CPACC or WAS) to own mappings and VPAT approvals | claims are defensible | 1a | Deferred | Needs a person |
| US-285 | Business owner | a chartered accountant to confirm GST rate, SAC code, e-invoicing and retention | invoices are valid | 1a | Deferred | Needs a person |
| US-286 | Business owner | the refund policy, support scope and plan change policy confirmed | policy is clear before we build | 1b | Deferred | |
| US-287 | Business owner | named owners for accessibility, security, accounting, privacy, operations, content and pricing | someone is responsible for each area | 1b | Deferred | |
| US-288 | Business owner | concrete models assigned to the light, standard and premium tiers | the cost ladder works as designed | 1a | Partly | Routes are set for the providers the owner has configured |
| US-289 | Business owner | hosting in an India region and an observability stack chosen | we meet data and operations needs | 1b | Deferred | |
