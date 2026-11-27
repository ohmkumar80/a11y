# ADR 0003: LLM providers and customer-data policy

- **Status:** Partly decided; the gateway and configuration model are implemented, see ADR 0006. PROJECT_PLAN 3.11.2 (commit f15c591) makes providers, models and routing admin-configured data behind an `LLMGateway`; still open: which two providers go live at launch and the customer-data policy below.
- **Date:** 2026-11-26

## Recommendation
(See PROJECT_PLAN 3.11.2 for the data model; the gateway and settings framework are the remaining Phase 0 work.)

- A provider-agnostic `LLMGateway` with per-task routing, per-tenant budgets and caching (built in Phase 1 with the
  Code-Fix Copilot; nothing in Phase 0 calls an LLM).
- Zero-data-retention or enterprise agreements before any customer content is sent.
- Per-tenant opt-out that falls back to deterministic output.
- AI output is always a suggestion with human approval (PROJECT_PLAN 3.7).

## Open questions
- Which providers do we sign agreements with first?
- Do public-sector customers need regional endpoints at launch?
