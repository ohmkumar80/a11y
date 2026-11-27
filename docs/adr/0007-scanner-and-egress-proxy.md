# ADR 0007: Web scanner, rule registry and the egress proxy

- **Status:** Accepted
- **Date:** 2026-11-27

## Scanner
- **One page, three engines.** Python Playwright loads the page once; axe-core, IBM Equal Access and HTML_CodeSniffer
  are injected as pinned bundles and run one after another on the same DOM (`runner.js`). Every result is resolved to the
  same element identity (xpath + CSS path + snippet) *inside the page*, so cross-engine matching is exact.
- **Bundles are pinned and hash-checked.** `packages/engine-bundles` copies the three engines' browser builds and writes
  `versions.json` (SHA-256 each). The scanner refuses a bundle that does not match; every scan records the engine versions,
  rule-registry version and config versions it ran with.
- **Normalisation** (`normalise.py`): one finding per (canonical rule, element); page-level rules are keyed on the
  document; violation from any engine wins; confidence = how many engines agree vs how many can detect it at all
  (high / medium / low / review). Same-defect-different-page findings share a `cluster_key` (root cause).
- **Credits:** one credit per scan job. Customer faults (bad URL, blocked, unreachable) keep it; platform faults (browser,
  engine, worker loss) return it. Redelivery is idempotent; a stuck-scan sweeper fails dead scans and returns the credit.

## Rule registry (`rules/`, YAML, validated on load)
- `wcag.yaml` (87 criteria incl. the removed 4.1.1), `standards.yaml` (WCAG 2.0/2.1/2.2 levels + Section 508, ADA II/III,
  EN 301 549, GIGW 3.0, AU target; each with legal status, citation and a review record), `canonical.yaml` (41 curated
  cross-engine equivalences), `engine-catalog.json` (generated from the pinned engines).
- Tests prove every engine rule id named in `canonical.yaml` exists in the pinned engine versions and that our SC lists do
  not contradict what the engines themselves attach, so an engine upgrade cannot silently break mappings.
- **Nothing claims compliance.** Summaries report *automated coverage* (criteria with a definite automated check) and the
  buckets failed / needs review / no issue found / not tested. The legal mappings are `review.status: draft` until a named
  accessibility SME signs them off (plan open decision 7); the UI says so.

## SSRF: why an egress proxy
Request interception inside the page cannot see redirects, WebSockets or DNS that Chromium handles in its own network
stack; a test (redirect to `169.254.169.254`) proved it. So all browser traffic goes through `EgressProxy`, which resolves
each host, requires **every** address to be public (private, loopback, link-local, CGNAT, multicast, reserved, and IPv6
forms embedding such IPv4: mapped, NAT64, 6to4, Teredo), enforces the port allow-list, and connects to the *validated* IP
(no rebinding window). Blocked requests get 403 + `X-A11y-Blocked`. The API pre-checks the URL with the same code.
- `SCAN_DEV_ALLOW_HOSTS` exempts named hosts for local fixtures only and is refused when `ENV=production`.
- **Still required in production:** run `web-worker` in a network segment with no route to internal services. The proxy is
  defence in depth, not the only control. Domain verification (file or meta tag) gates crawls above
  `scan.engines.unverified_crawl_pages`.

## Not done yet
Screenshots (full-page and element) and their storage; authenticated scans; template-level crawl deduplication beyond
`cluster_key`; benchmark suite (recall/precision against W3C BAD, GOV.UK fixtures) with a recorded baseline; the other
Phase 1 exit criteria listed in PROJECT_PLAN.
