# Investment Engine

A three-tier investment research system. **Tier 1** is a fully
deterministic fundamental-analysis pipeline — SEC EDGAR filings are the
authoritative data source, every number is derived arithmetically with no
model involvement, and all assumptions live in version-controlled config.
**Tier 2** adds LLM-driven qualitative extraction layered on top of the
deterministic output (verbatim red/green flag extraction from 10-K text).
**Tier 3** is an LLM council that synthesizes Tier 1 signals and Tier 2
annotations into a final research memo. Tiers 2 and 3 consume Tier 1
output; they never alter it, and no model call anywhere in the codebase
ever derives, adjusts, or overrides a numeric result.

Two ways to use it: a one-shot CLI (`analyze.py`) for a single ticker's
Markdown/HTML report, and a local FastAPI web app + dashboard
(`app/`, `frontend/`) for an ongoing watchlist — batch durability
screening, the expectations-gap band, per-ticker Tier 2/3 drill-down.

## Quick Start

Local use on macOS or Linux. Install **CPython 3.12.2** first (the tested version); Windows has not been validated.

```bash
git clone https://github.com/joe-elhajj/equity-research-engine.git
cd equity-research-engine
python3.12 --version  # should report 3.12.2
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install pip==24.2
python -m pip install -r requirements.txt
python -m pip check
```

Edit `config.yaml` and replace the `sec.user_agent` placeholder with **your own name and email**. SEC EDGAR requires a real contact; requests may return 403 without one. Then run a report and start the local dashboard:

```bash
python analyze.py AAPL
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The report is saved in `reports/`; open `http://localhost:8000` for the dashboard. The CLI and core (Tier 1) dashboard do **not** require an API key. For optional Tier 2 flags and Tier 3 council, set **your own** `ANTHROPIC_API_KEY` in your shell environment before starting the app; never commit or share it. For tests (`python -m pytest`), install Node.js 20 as well. See the full Setup and Run sections below; `app/INSTALL.md` is only for optional macOS auto-start.

## Setup

Use **CPython 3.12.2** (the tested interpreter) in a fresh virtual environment.
`requirements.txt` is the single exact-version lock for runtime and test
dependencies, including transitives. The setup targets macOS and
Linux (CI); other Python versions and Windows are not validated.

For a new checkout, use the commands below. For an existing clone, start
in its root directory and skip the first two commands.

```bash
git clone https://github.com/joe-elhajj/equity-research-engine.git
cd equity-research-engine
python3.12 --version                            # must report Python 3.12.2
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install pip==24.2
python -m pip install -r requirements.txt
python -m pip check
python -m pytest
```

Node.js 20 must also be on `PATH` for the JavaScript-backed tests, as in CI.
To update dependencies, change pins deliberately, resolve the complete
dependency set in a fresh environment, and run `pip check` and the full
test suite before committing the reviewed lock. Do not regenerate it from
an unrelated environment or upgrade packages as part of ordinary setup.
The optional macOS auto-start guide uses this same repository-local `.venv`.

Open `config.yaml` and set `sec.user_agent` to your real name + email —
**required**, SEC returns 403 without a declared contact.

Tier 2 (`/api/flags/{ticker}`) and Tier 3 (`/api/council/{ticker}`) need
`ANTHROPIC_API_KEY` in the environment at runtime; the CLI and Tier 1
web endpoints work without it.

## Run

**Single ticker, CLI:**

```bash
python analyze.py AAPL                          # fundamentals + durability
python analyze.py AAPL --peers technology       # + peer comparison (universe in config)
python analyze.py AAPL --peers MSFT,GOOGL,DELL  # + peer comparison (explicit list)
python analyze.py AAPL --price 195 --shares 15300000000   # manual market inputs; EDGAR still fetched
```

Output lands in `reports/<TICKER>_<date>.{md,html}`. The peer-comparison
path (`--peers`) is CLI-only today — the web app's analyze endpoints
don't wire it in.

**Web app + dashboard:**

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://localhost:8000`. Add tickers to a persistent watchlist
(SQLite, outside the repo at `~/.investment_engine/`), run a batch
durability screen, click any row to expand its full analysis inline —
financial position, growth, margins, valuation (including the
expectations-gap scenario band), durability scorecard, Tier 2 flags,
Tier 3 council, all from the same underlying `AnalysisResult`/
`DurabilityScore` the CLI produces. For auto-start-at-login and Dock
integration on macOS, see `app/INSTALL.md`.

**Batch screen, Python API:**

```python
from engine.screen import run_screen
# See run_screen() for arguments and supported sort modes.
```

## Architecture (separation of concerns)

```
analyze.py             Single-ticker CLI entry point
engine/
  edgar.py              SEC EDGAR client: ticker→CIK, SIC, companyfacts, concept resolution
  market.py              price/shares/market-cap (yfinance; isolated from filings)
  metrics.py             PURE math — CAGR, margins, ratios, R&D capitalization — unit tested
  pipeline.py             EDGAR data → derived metrics → valuation (no LLM or I/O)
  valuation.py            relative multiples, 2-stage DCF, reverse-DCF, the bull/base/bear
                          expectations-gap scenario band
  durability.py           five-category business-durability scorecard, the R&D capitalization
                          regime, and the balance-sheet-leverage gate (raw-metric veto)
  peers.py                comp-set construction (SIC + size band) + relative scoring — wired
                          into analyze.py's CLI only, not yet the web app
  universe.py             S&P 500 reference population for universe-relative percentile scoring
  etf.py                  ETF/fund profile via yfinance (market-vendor tier, fully defensive)
  screen.py               batch screener: routes tickers to Equities / ETFs & Funds / Excluded
  filings.py               Tier 2: fetch/parse 10-K text into Item 1/1A/7 sections
  flags.py                 Tier 2: LLM verbatim-selection flag extraction + validator
  council.py               Tier 3: adversarial council synthesis (5 advisors → peer review → Chairman)
  report.py                render AnalysisResult to Markdown, full EDGAR citation per figure
  report_html.py           render AnalysisResult to HTML (standalone doc + dashboard fragment)
  report_council.py        render a CouncilResult to self-contained HTML/PDF
app/                     FastAPI web layer wrapping the engine (watchlist, screen, analyze,
                          flags, council endpoints) — see app/INSTALL.md for the local-service setup
frontend/                 dashboard UI (vanilla JS + CSS, no build step)
config.yaml               every assumption + curated peer universes (version-controlled)
docs/assumptions.md       every owned assumption, its external anchor, and review cadence
audit/                    dated audit evidence and sensitivity harnesses (see below)
tests/                    pytest regression suite (synthetic fixtures + cached data)
```

## Design decisions worth knowing

- **Concept resolution with fallbacks.** XBRL tags differ across
  companies and years. Each logical metric resolves against an ordered
  list of GAAP tags; the report shows the exact concept used. Debt
  aggregation counts overlapping current portions only once.
- **Provenance on every fundamental number.** Each figure cites its
  EDGAR concept, fiscal-period end, form, and filing date. Every
  renderer's "Data gaps" section lists anything that could not be
  resolved, loudly — absence is never silently treated as zero.
- **Assumptions live in config, never invented at runtime.** DCF WACC,
  terminal growth, per-year FCF growth, durability weights/thresholds,
  the R&D-capitalization regime, and the balance-sheet gate's
  threshold/cap are all yours, versioned in `config.yaml`, and anchored
  with rationale in `docs/assumptions.md`. The reverse-DCF runs under
  all three owned scenario bundles (bull/base/bear), not just base, and
  discloses when the resulting signal's sign depends on which bundle
  you pick.
- **Config-hash discipline.** Every `DurabilityScore` embeds a
  16-hex-char fingerprint of the resolved assumption set (weights,
  thresholds, R&D regime, gates, universe version) so cross-company or
  cross-date comparisons under different assumptions are identifiable,
  never silently conflated.
- **A raw-metric gate caps the composite independently of the weighted
  score.** A company that's over-levered on net debt/EBITDA gets its
  durability composite capped regardless of how strong its other
  categories look — the gate reads raw filing data, never a derived
  sub-score, and both the gated and ungated numbers are always
  preserved and disclosed.
- **The only sanctioned model use is verbatim selection (Tier 2) and
  evidence synthesis (Tier 3).** No model call ever derives, adjusts,
  or computes a number. See `docs/assumptions.md` for the full invariant list.
- **Meaningless ratios return n/a + a reason**, never a misleading
  number (P/E on negative earnings, ROE on negative equity, etc.).

## Engineering evidence

The [historical audit](audit/session_d/report.md), supporting files in
`audit/`, and [architecture snapshot](docs/architecture_snapshot.md)
record the repository at the time of inspection. They are retained as
engineering evidence, not a current unresolved-issue ledger. Subsequent
fixes and regression tests supersede findings in those snapshots.

## Known limits

- Fiscal years are labeled by period-end year; companies with
  off-calendar year-ends get a label that can be off by one. The
  underlying data and CAGR spans use actual dates, so the math is
  correct.
- `yfinance` is free but fragile; isolate-and-swap is built in
  (`engine/market.py`).
- Trailing multiples only (no forward estimates).
- Single-user, local-only web app — see `app/INSTALL.md`'s own
  limitations section (SQLite watchlist is single-process; the EDGAR
  disk cache isn't written atomically).

## Limited filing views

**Not scored - classification or filing limits** keeps unsupported names separate
from scored equities. S-1/F-1 evidence with no annual report gets the recent-IPO
reason; a 10-Q without IPO evidence gets the quarterly-only reason. Financial
issuers get an operating-model non-comparability explanation; unknown coverage
stays unknown. The list and company detail use the same reason.

The filing-only view shows supported latest-quarter 10-Q facts with filing
accessions and leaves missing metrics missing. No durability score, rank,
growth gap or DCF is displayed. SECZ's pre-combination June 30, 2026 shell facts
remain withheld. Annual 20-F/40-F issuers and fund/ETF routing are unchanged.

## Optional prebuilt S&P ranks (derived scores only)

A completed local build is usable offline. Missing/stale ranks never trigger a
reference build. Building, exporting and uploading are separate operations:

```bash
# Explicit operator build only; Yahoo <= 1 request/1.05s, SEC <= 4 requests/s.
python -m engine.universe_ranks --config config.yaml
# Export locally only. No vendor calls, rebuild, or upload.
python -m engine.universe_rank_release --config config.yaml --output .cache/release-review/universe-ranks.json
```

Review that exact asset before approving any upload. Public schema 2 includes
per-ticker weighted model scores, derived completeness scores (eligibility
metadata), six distributions, peer counts, coverage, universe/scoring
fingerprints, source-schema version, original build-start/completion and expiry
times. Unscored tickers have empty rows. It contains no raw Yahoo prices, market
caps or share counts, company names, SEC contact, config dump, local config hash,
or exclusion narratives. Percentiles are recomputed from the distributions.

Import validation reuses the hardened local schema validator. It requires
complete ticker accounting, >=80% completeness for every scored row, >=60%
overall coverage (**at least 302 of the current 503 tickers**), >=100 peers in
every field, valid 0–100 scores, exact row/distribution consistency and matching
peer counts. Unknown fields, old prototype schemas, mismatched scoring settings
or reference-file bytes, future dates, and expired data are rejected. Expiry
remains 90 days after the original build start; export/import cannot refresh it.
Different SEC contact details or local reference-file paths do not invalidate
otherwise compatible public data.

The proposed release destination is the **public** GitHub repository
`joe-elhajj/equity-research-engine`, tag `equity-ranks`, asset `universe-ranks.json`.
The old `InvestmentEngine` remote redirects to this canonical repository.
Its audience is anyone on the internet, including unauthenticated downloaders.
**Stop for explicit approval of the exact reviewed file and its SHA-256 before
creating a release or uploading/replacing an asset.** Nothing in the exporter
publishes. Never upload aggregate_ranks.json, config.yaml, source caches or logs.
Do not replace an existing release asset without reviewing the current release
and separately approving that replacement. Verify the final asset and URL after
an authorized upload before claiming availability.

A clone with neither a valid local build nor a valid downloaded asset checks
that dedicated release at most once per process per six hours. Only the named
JSON asset on the published, non-prerelease tag is accepted; redirects, response
size and request timeouts are bounded. Failure leaves ranks hidden. The explicit
read-only download command is:

```bash
python -m engine.universe_rank_release --config config.yaml --download
```

Downloaded data is stored separately at `.cache/universe/published-ranks.json`.
A valid local build causes no network request. If both sources validate, the
newer original build-start time wins (then completion time), with local preferred
on a tie. An older download never replaces a fresher validated downloaded copy.
The original local cache is never overwritten. All caches/export artifacts stay
ignored by Git; publication is an explicit reviewed release operation.


### Watchlist and S&P rankings

The header separates your Watchlist (the default) from **S&P rankings**, which
loads a completed reference only when opened. The URL preserves the tab and
filters across refresh and analysis/back navigation. Rankings start with Total
durability, Top 25 and Highest first; select multiple fields, show all eligible
constituents or switch to Lowest first to screen the benchmark's other end.

**My watchlist only** is off by default. Turn it on to screen the latest completed
watchlist scores, including eligible outside-index equities such as NVO/ASML,
against the same S&P reference. The filter never starts a screen or builds a
reference. With no completed screen, use **Run / refresh watchlist screen**;
missing scores and filing/classification limits are counted with a Watchlist link.
Funds remain in their own section. Filter selection persists in the URL.

Percentile badges keep one decimal and compare against the dated S&P 500
snapshot, while durability remains a weighted 0–100 model score. Outside-index
watchlist names are explicitly labeled. Multi-field mode requires every
selected score and displays **Average selected percentiles**, an equal-weight
screening statistic rather than a new S&P percentile. Missing/expired reference
data shows an unavailable state and never starts a build. See
[reference semantics and verification](docs/universe_ranks.md).
