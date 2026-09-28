"""Narrow SEC-filing view when the operating Durability model does not apply.

Only filed XBRL 10-Q facts from the existing EDGAR reader are shown. IPO
prospectus and SPAC financials are not silently repurposed as annual facts.
"""
from __future__ import annotations

from html import escape
from typing import Optional

from engine.edgar import CompanyData

FACTS = (
    ("revenue", "Revenue"), ("operating_income", "Operating income"),
    ("net_income", "Net income"), ("cfo", "Operating cash flow"),
    ("capex", "Capital spending"), ("total_assets", "Total assets"),
    ("total_liabilities", "Total liabilities"), ("cash", "Cash"),
)


def reason(cd: CompanyData) -> Optional[str]:
    """Filing-based route, excluding funds and explicit analyst overrides upstream."""
    forms = set(cd.recent_forms)
    if any(f.startswith(("10-K", "20-F", "40-F")) for f in forms):
        return None
    sic = int(cd.sic) if str(cd.sic).isdigit() else None
    if sic is not None and 6000 <= sic <= 6799:
        return "Financial issuer; operating-company durability model is not comparable."
    if any(f.startswith("10-Q") for f in forms):
        return "Quarterly filer without an annual 10-K yet."
    if any(f.startswith(("S-1", "F-1")) for f in forms):
        return "IPO registration filed; no annual operating report yet."
    return "no annual report forms found; limited filing view available"


def _num(value: float) -> str:
    return f"{value:,.2f}" if abs(value) < 10 else f"{value:,.0f}"


def render(cd: CompanyData, price: Optional[float], note: str) -> str:
    """Escaped HTML for the existing company dialog, with no fabricated scores."""
    # SECZ's 2026-06-30 10-Q belongs to the $1 shell, before its
    # 2026-07-01 combination. Do not suppress ordinary banks or a later
    # successor-company quarter merely because they share a financial SIC.
    shell_cik = str(cd.cik).lstrip("0") == "2094496"
    entries = [(label, cd.quarterly.get(key)) for key, label in FACTS]
    entries = [(label, fact) for label, fact in entries if fact is not None and fact.form.startswith("10-Q")]
    shell_only = shell_cik and any(f.period_end <= "2026-06-30" for _, f in entries)
    entries = [(label, f) for label, f in entries if not (shell_cik and f.period_end <= "2026-06-30")]
    latest_end = max((f.period_end for _, f in entries), default=None)
    entries = [(label, fact) for label, fact in entries if fact.period_end == latest_end]
    if entries:
        rows = "".join(
            f'<tr><td class="l">{escape(label)}</td><td title="{escape(fact.source_ref(), quote=True)}">'
            f'{_num(fact.value)}</td><td>{escape(fact.period_end)}</td>'
            f'<td>{escape(fact.currency)}</td></tr>' for label, fact in entries
        )
        source = ('<p class="report-caption">10-Q XBRL facts at the latest available quarter end. Flow items cover the reported three-month period; assets and cash are period-end balances. Hover a value for its filing lineage.</p>')
        source += '<p class="report-caption filing-lineage">Source: ' + '; '.join(escape(x) for x in sorted({f.source_ref() for _, f in entries})) + '</p>'
        facts_html = source + '<div class="surface"><div class="scroll"><table><thead><tr><th class="l">Filed item</th><th>Value</th><th>Period end</th><th>Currency</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>'
    elif shell_only:
        facts_html = '<p class="report-caption">The available 10-Q facts belong to a pre-combination shell. They are withheld here rather than mislabeled as successor-company operations. The successor filing tables have not been mapped into this XBRL view.</p>'
    else:
        facts_html = '<p class="report-caption">No supported 10-Q XBRL facts are available for this ticker yet. The IPO/other filings are not parsed into scores.</p>'
    forms = ", ".join(escape(f) for f in sorted(set(cd.recent_forms)) if f.startswith(("10-Q", "S-1", "F-1", "8-K", "20-F", "40-F"))) or "none in current filing list"
    price_text = f"${price:,.2f}" if price is not None else "n/a"
    return (
        '<div class="report-fragment partial-analysis">'
        '<p class="partial-notice">Limited filing view. No durability score, S&amp;P rank, growth gap or DCF is calculated from incomplete annual history.</p>'
        '<div class="report-summary"><div class="stat"><span class="stat-label">Quote</span><span class="stat-value">' + escape(price_text) + '</span></div></div>'
        '<details class="report-section" open><summary>Filed quarterly facts</summary>' + facts_html + '</details>'
        '<details class="report-section" open><summary>Coverage &amp; limits</summary>'
        '<p class="report-caption">' + escape(note) + '</p>'
        '<p class="report-caption">Recent forms: ' + forms + '. This view does not parse S-1/F-1 prospectus tables, reconstruct pre-merger history, or score financial companies as ordinary operating businesses. Missing values remain missing.</p>'
        '</details></div>'
    )
