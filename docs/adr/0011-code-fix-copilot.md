# ADR 0011: Code-fix copilot

- **Status:** Accepted
- **Date:** 2026-11-27

## Decisions
- **A fix is shown only if our own scanner agrees.** Every candidate, from a recipe or a model, must pass static checks
  (V1) and the **re-scan oracle**: the three engines run on the element alone, the targeted rule must be gone, and no
  new failing rule may appear. A model's own opinion that its fix works is never used. A fix that fails is not stored
  as code: the table constraint `ck_fix_only_if_ready` refuses `fixed_html` on any row that is not `READY`.
- **The ladder (3.13), as built:** rung 1 cache (same rule and element already fixed in this organisation: no job, no
  tokens), rung 2 deterministic recipes (`fixes/recipes.py`: meta refresh, viewport zoom, form label, marquee/blink,
  page language, invalid ARIA role), rung 3 the `code_fix` model route with one repair attempt that carries the failed
  checks back into the prompt. Then `NEEDS_REVIEW` with a plain reason. **Not built yet:** tiers (`AIModel.tier`) and
  escalation to a stronger model, the V2 LLM validator, the human queue.
- **Recipes never invent content.** There is deliberately no recipe for `image-alt` (what an image shows is a human
  decision). Where a recipe must assume (the page language is set to English) the assumption is stated next to the fix.
  The oracle also showed that a recipe for "decorative image without alt" could never fire, since no engine flags it,
  so it was removed rather than shipped.
- **Only the element's own tag is known.** The scanner stores an element's opening tag (and its empty end tag), never its
  children, which keeps page text out of our database. A fix is therefore an attribute-level patch, optionally with a
  short sibling such as a `<label>`. Problems that cannot be reproduced on the tag alone (colour contrast inherited from
  a parent, a label elsewhere in the page) are reported as not checkable, instead of guessed at.
- **Model output is untrusted.** The prompt marks page content as data; the static checks reject scripts, event handlers,
  iframes, objects, `javascript:`/`data:` URLs, new web addresses and changes to `href`, `src`, `id`, `name`, `type`,
  `value` and `data-*`; text written for screen readers must not be empty, a file name, "image of …", generic, or
  over 125 characters.
- **Data use is stated before the click, and configurable.** Setting `ai.code_fix` (global, plan or organisation):
  `enabled`, `per_minute`, `use_ai` (off = recipes only). Only the opening tag is sent to a provider. The gateway's
  existing rules still apply: data-policy eligibility, enterprise own-key, budgets and per-call metering.
- **Runs on the browser worker** (queue `web`, task `web.suggest_fix`) because the oracle needs Chromium. Idempotent: a
  finished suggestion is never recomputed. A platform fault becomes `FAILED` with a retry, never a half-result.

## Consequences
- Fix quality is bounded by what one tag reveals. Capturing a bounded, redacted inner snippet would allow content
  fixes (headings, tables, list structure) and is a later decision because it changes what we store.
- Escalation tiers and the V2 validator need `AIModel.tier` and the validation-policy setting from 3.13.

## Update (2026-11-28): escalation and the independent reviewer
- **Escalation.** Two more AI tasks, `code_fix_escalate` and `code_fix_validate`, are routed like every other task in
  `/admin` (a model per task, with fallbacks). When the light model's two attempts fail, one attempt goes to
  `code_fix_escalate` with the failed checks in the prompt (rung `standard`). Models now carry a `tier` (Light, Standard,
  Premium; informational for now, used by the cost views and shadow mode later). If the light route is not configured the
  stronger route alone can serve the request.
- **Independent review (V2).** After the checks and the re-scan oracle pass, a second model reads the before and after and
  answers `pass` or `fail` with reasons. Policy (`ai.code_fix.validation`): `off`; `sample` (a share, default 10%, a quality
  measure that never blocks); or `always`, which fails closed: with `always`, a fix the reviewer rejects, cannot run, or answers
  unreadably is not shown (reason `validator_unavailable`). A rejection sends the reviewer's reasons into the repair attempt.
  Recipes are deterministic and are not reviewed. The reviewer's verdict appears in "What we checked".
- **Not built:** forcing the reviewer onto a different provider than the author (an admin chooses the routes), the human review
  queue, and shadow-mode promotion.
