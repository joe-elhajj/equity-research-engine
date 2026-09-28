# Reference ranks and leaderboard

The leaderboard and watchlist badges read `.cache/universe/aggregate_ranks.json`.
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
when it is a constituent. Leaderboard rows sort score descending, then ticker
ascending; the first column is display order, while tied scores share the same
percentile. Watchlist compact badges round that percentile to a whole number.

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
profile and intercepts all application requests. It checks desktop 1440×1000
and mobile 390×844, all six fields, fresh badges, missing/stale hiding, row
navigation/back, no non-GET requests, no unexpected/paid endpoints, and no page
horizontal overflow. Screenshots are clearly labeled fixtures.

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
