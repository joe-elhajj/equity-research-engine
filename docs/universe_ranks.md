# Reference ranks and leaderboard

The S&P rankings tab and watchlist badges read a complete validated local or
compatible downloaded reference through `load_reference()`.
They never launch a reference build. Model scores are weighted 0–100 scores;
S&P reference percentiles are a separate comparison against the dated, local
constituent snapshot. Multiple share classes count as separate reference tickers.

## Eligibility and cache contract

The explicit builder uses the same `_process_one` scoring/classification route
as a normal screen. Funds, skipped/unclassified names, financial SIC exclusions
(unless explicitly overridden), missing scores, and completeness below 0.80 do
not enter any distribution. Exact 0.80 is eligible. Null category scores are
omitted from that category's peers, never replaced with zero.

A complete cache requires every reference ticker accounted for, at least 60%
overall coverage (302 of the current 503), and at least 100 numeric peers for
each of the six fields. The 60% cohort threshold is distinct from the 80%
per-company data-completeness rule. Exclusion reasons are stored by ticker.

Schema 2 binds the cache to the complete configuration hash, reference file
hash, and universe version. Validation rejects malformed timestamps, future or
expired builds, invalid numeric ranges/booleans, missing completeness evidence,
wrong ticker sets/counts, inconsistent exclusions, and distributions that do
not exactly match their constituent rows. Publication is atomic. Insufficient
coverage preserves any existing aggregate and the resumable progress file.

Checkpoints resume only within seven days and only after validating their rows
and exclusions. Freshness expires 90 days after the original build start, not
completion; resumed data is not relabeled as newly acquired. Build dates are
processing dates, not filing dates or live quote timestamps. EDGAR source files
may already be up to the configured cache TTL old (default one day).
Completed screen jobs revalidate reference availability on read. The browser
checks dates before rendering badges or the leaderboard and removes expired
content from an open page. Missing/stale cache responses render no ranks.

Percentile = 100 × (count below + 0.5 × count equal) / field peer count, rounded
to one decimal. Identical cohorts receive P50. The reference includes a target
when it is a constituent. Both watchlist badges and the ranking table display
one decimal (P98.5 stays P98.5). Membership is taken from validated reference
row keys, including unscored constituent rows, not inferred from a company's
name or ticker. Nonmembers are labeled “vs S&P 500 peers · not in this reference
index.” The snapshot's declared date and version are distinct from its build
date; a fresh build does not imply current index membership.

## Rankings tab and filters

Watchlist is the default tab and keeps Equities, ETFs/Funds and “Not scored -
classification or filing limits” together. The S&P rankings tab requests its
list only when opened. The URL hash records the tab, selected fields, order,
Top 25/all choice, My watchlist only and open company; refresh and browser back/forward restore
that state. Analysis never adds a constituent to the watchlist.

Top 25 and Highest first are defaults. With My watchlist only off (the default),
Show all eligible names is bounded by
the configured snapshot's ticker count (503 currently), not a request to score
or fetch companies. Lowest first lets reviewers inspect the bottom; the first
column is labeled Order in both directions. Ticker ascending breaks exact
ties. Single-field ordering uses the unrounded model score and ordinary field
percentile.

The accessible Rank by checkbox group selects one or more of the six fields.
Multiple fields use an AND intersection: every selected score must be numeric,
with no null-to-zero conversion. Each percentile uses its own **full validated
field distribution**, not the smaller intersection. Sorting uses the equal-
weight average of unrounded selected percentiles; rounding is only for display.
“Average selected percentiles” is a screening statistic, **not a fresh S&P
percentile**. The table shows each selected score/percentile, the intersection
count, each field's peer count and overall coverage. Zero selection makes no
ranking request. Missing/expired references show an explicit unavailable state
and no ranks, without starting a build.

### My watchlist only

`watchlist_only=true` reads live watchlist membership and the latest requested
server screen, reusing the same ranking function and validated S&P distributions.
It does not intersect with constituent keys: outside-index equities are eligible
when their actual completed screen row has a numeric composite, at least 80%
completeness (the existing badge gate), and numeric scores for every selected
field. Missing selected fields never become zero. A constituent also uses its
screen row, never a substitute reference score. Membership labels come only from
validated reference row keys. Single-field ordering uses the unrounded screen
score; multi-field ordering uses the existing full-precision percentile average.
There is no within-watchlist percentile calculation.

Filtered eligible counts are separate from overall reference coverage and peer
counts. Missing screen rows, unscored names and incomplete rows are counted with
a Watchlist link; funds are excluded. Show all is bounded by the live watchlist,
not a new scoring population. Snapshot/build dates and the screen timestamp are
shown. A newer running or failed screen suppresses older results. Completed jobs
are process-local; a server restart requires an explicit screen refresh for this
mode. `/api/screen/latest` reads existing state only, pruning removed names.
Restoring a filter URL does not start scoring; the explicit refresh control runs
the existing screen. Toggling, changing fields/order/size, or returning from
analysis only reads data. Membership is reread on each ranking request; screen
completion and local removals refresh an active filter, while tab return and
visibility changes reread current state. Missing/expired references always fail
closed. With the option off, the existing constituent-only API response and
selection semantics are unchanged.

The read-only endpoint retains `field` compatibility and accepts `fields` as a
comma-separated unique subset, `order=asc|desc`, `limit` from 1 through snapshot
count (default 25), and `all_names=true`. Invalid/empty/duplicate fields and
out-of-bound limits are rejected. All mode still returns only eligible rows
from the validated snapshot. No universe, cache schema, eligibility, scoring or
freshness settings are changed.

## Read-only evidence checked for this UI correction

On 2026-09-28, local cached NVO filings reproduced an unrounded durability score
of **84.83931600204866**, completeness 0.80, without market or model calls. The
validated July 2 snapshot, built September 28, contains 503 tickers and 389
composite peers; NVO is not a constituent. Its comparison is 383 / 389 × 100 =
98.45758354755784%, displayed **P98.5**. The same reference has ANET at
84.63640999115995 / P98.3 and LULU at 85.64832096838278 / P98.6. These are dated
verification observations, not new live scores or reference updates.

Cached SEC submissions show QNT and SPCX both have S-1 registration evidence,
10-Qs and no annual report, so IPO wording takes precedence over quarterly-only
wording. QNT's 10-Q is accession 0001628280-26-056743 (2026-08-13); SPCX's is
0001628280-26-052535 (2026-08-04). SECZ has SIC 6199 and accession
0001628280-26-056788 (2026-08-13); its June 30 pre-combination shell facts remain
withheld. Financial non-comparability takes precedence over IPO wording.
Annual 20-F/40-F and fund routes are unchanged. A missing annual report alone
never establishes IPO status, and the unscored list and limited view share the
same evidence-specific reason.

## Build approval estimate — 2026-09-28

The configured file contains 503 unique tickers and identifies itself as a
2026-07-02 snapshot, version 2026-Q3. This is not a verification of today's S&P
membership. No constituent or config file was changed.

- SEC: one ticker-map request plus up to two documents per ticker = 1,007 cold
  requests. Local inspection maps all 503 tickers and finds 30 currently fresh
  documents, suggesting about 977 requests if those files remain fresh. Shared
  CIKs, failures, and cache expiration can change this estimate.
- Market: up to 503 primary `yfinance.Ticker.info` lookups, normally about three
  Yahoo HTTP requests each. Existing financial exclusion/fund checks also call
  `fetch_etf_profile`, including fund operations/holdings. The local cached
  metadata identifies 99 financial-SIC names before override decisions. Budget
  roughly 1,900–2,300 Yahoo requests before retries/session setup; no exact cap
  is guaranteed by yfinance.
- Runtime: unbenchmarked planning estimate 30–90 minutes, sequential. SEC's
  builder’s 0.25-second delay alone adds about 4.1 minutes for 977 requests;
  network latency, quote throttling, parsing, and scoring dominate the rest.
  Widespread timeouts can take substantially longer.
- Paid Extract, Consult, Flags, Council and LLM calls: zero. The builder's route
  imports EDGAR, market, classification, pipeline and durability code, with no
  paid model route. Browser verification intercepts all application requests.

SEC requires an identifying User-Agent and fair access, currently at most ten
requests/second across clients. This builder uses a single sequential client
with at least a 0.25-second request delay. Source:
https://www.sec.gov/about/privacy-information

The yfinance project is unofficial and states that Yahoo Finance data access
is intended for personal use, subject to Yahoo's terms; the software license
does not grant data redistribution rights. Source:
https://github.com/ranaroussi/yfinance/blob/main/README.md
Yahoo's published terms prohibit automated collection without express prior
permission. The US terms page returned HTTP 999 during this review; the
published Canada English terms contain that restriction:
https://legal.yahoo.com/ca/en/yahoo/terms/otos/
Developer terms: https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html
This review does not establish that a particular Yahoo account has permission.

The user approved the full reference build on 2026-09-28 with these transport limits:

- A dedicated Yahoo session spaces all HTTP requests, including cookie/crumb,
  quote, fund data and redirects, by at least 1.05 seconds. Transient 5xx
  responses back off 2 then 4 seconds, with at most three attempts.
- Yahoo HTTP 429 or SEC 403/429 immediately stops the run, preserving completed
  tickers and leaving the interrupted ticker pending. A separate retry file
  enforces at least 15 minutes of cooldown (or longer Retry-After), doubling
  on repeated interruptions up to one day. Rerunning before that time makes
  no vendor requests.
- SEC request delay is clamped to at least 0.25 seconds (at most four per second
  in this sequential process), without modifying config.yaml.
- Aggregate, progress, retry files, logs and raw EDGAR data stay under ignored
  `.cache/`; none should be staged or committed.

Approved command:

```sh
python -m engine.universe_ranks --config config.yaml
```

## Verification

`tests/test_universe_ranks.py` covers eligibility boundaries, malformed and
mismatched caches, date/coverage/distribution validation, resumable checkpoints,
exclusions, tie handling, all fields, and read-only endpoint behavior.

`tests/browser_universe_ranks.cjs` uses Playwright with an isolated Chrome
profile and intercepts all application requests. It checks desktop 1440×1050
and mobile 390×844, all six single fields, multi-field AND selection, zero
selection, races, Top 25/all, highest/lowest, URL refresh/back/forward, lazy
loading, precision/membership labels, missing/stale/live expiry, no non-GET or
unexpected/paid requests, and no document overflow. Screenshots are labeled
FIXTURE. `tests/browser_partial_analysis.cjs` also checks cached QNT/SPCX facts,
SECZ shell suppression, contrast, keyboard analysis and back navigation using
an explicit `LIMITED_VIEWS` fixture path.

```sh
python -m pytest -q
NODE_PATH=/path/to/node_modules RANKS_SCREENSHOT_DIR=/tmp/ranks-screenshots node tests/browser_universe_ranks.cjs
```

No live ranks, peer counts, or real-data screenshots are claimed before the
approved build completes. Existing config, report changes, older tests, and
`output/` remain unstaged and preserved.

## Completed approved build

The approved run completed on 2026-09-28 at 16:36:23 UTC, after 34.5 minutes.
It made 1,898 Yahoo HTTP requests through the throttled session, with no
rate-limit pause. All 503 tickers were accounted for: 389 qualified (77.3%)
and 114 were excluded. Ninety-seven exclusions were financial SIC issuers;
the remaining seventeen were unclassifiable/missing registrants or lacked
eligible scores/completeness. Full per-ticker reasons are in the ignored cache.

| Field | Numeric peers |
| --- | ---: |
| Total durability | 389 |
| Reinvestment | 353 |
| Quality | 389 |
| Resilience | 389 |
| Discipline | 388 |
| Optionality | 382 |

Minimum included completeness is exactly 0.80. Schema, config and universe
hashes, full ticker accounting, all distributions and exclusion mappings
passed validation. The cache expires on 2026-12-27 at 16:01:53 UTC, measured
from the original build start. Completion retired the progress file; no retry
file remained. Cache freshness does not update the July 2 constituent list.

Full tests after the transport change: 988 passed, 3 skipped, 2 expected failures.
Offline fixtures checked all six selectors, missing/stale hiding, analysis
navigation and no watchlist mutation. All six fields also rendered from the
validated real cache at desktop/mobile sizes in a read-only preview. The
preview uses an empty watchlist to avoid launching another screen job; the
leaderboard values and peer counts are from the completed build.

No paid Extract/Consult/Flags/Council/LLM calls were used. No files were staged
or committed, and config.yaml, report files and older test changes were
preserved. Cache, build log and raw EDGAR data remain ignored.
