# GOV.UK accessibility tool audit: test pages

Independent ground truth for the scanner benchmark: 142 single-failure test pages from the UK Government Digital Service
accessibility team's *accessibility-tool-audit* (https://github.com/alphagov/accessibility-tool-audit, commit
`e9e46115caf55f07a9302a5ee187687870510a09`, 2019-05-22), used under the MIT licence (see `LICENSE`, Copyright (c) 2017 Crown
Copyright, Government Digital Service). Files are unmodified copies of `tests/`, `example-pages/` (12 tests are wrappers whose failure lives on a linked example
page, which is what the benchmark scans) and the `assets` they reference, plus `tests.json` (the suite's own 2017 to 2019 results for 13 tools).

Every page demonstrates ONE accessibility failure; none is a "pass" example. Some failures (for example plain-language
or consistent-navigation problems) are not detectable by any automated tool; the authors' own tool results list them as
"notfound" for every tool, so a miss there is expected and is reported separately.

We did not write or tune these pages. See `docs/benchmark.md` for results.
