"""The limited filing view never turns incomplete or shell data into scores."""
from unittest.mock import patch

from app.main import app
from engine.edgar import CompanyData, Fact
from engine.market import Quote
from engine.pipeline import AnalysisResult
from engine.partial_analysis import render
from engine.screen import _process_one
from fastapi.testclient import TestClient


def company(ticker, sic, forms, facts=None):
    cd = CompanyData(ticker=ticker, cik="0000000001", name=ticker + " Inc.",
                     sic=sic, sic_description="", recent_forms=forms)
    cd.quarterly = facts or {}
    return cd


def fact(metric, val):
    return Fact(metric, val, "2026-06-30", 2026, "us-gaap:" + metric,
                "10-Q", "2026-08-10", accn="0001-26-000001")


def test_qnt_quarterly_facts_and_missing_metrics():
    cd = company("QNT", "7373", ["S-1", "10-Q"],
                 {"revenue": fact("revenue", 7998000), "cash": fact("cash", 2106686000)})
    html = render(cd, None, "Quarterly filer without annual report")
    assert "7,998,000" in html and "2,106,686,000" in html
    assert "Operating income</td>" not in html
    assert "S&amp;P rank" in html and "0001-26-000001" in html


def test_spcx_quarterly_facts():
    cd = company("SPCX", "7370", ["S-1", "10-Q"],
                 {"revenue": fact("revenue", 7814000000)})
    assert "7,814,000,000" in render(cd, 113.45, "Recent IPO")


def test_financial_precombination_shell_withheld():
    cd = company("SECZ", "6199", ["10-Q", "8-K"],
                 {"total_assets": fact("total_assets", 1), "cash": fact("cash", 1)})
    cd.cik = "0002094496"
    html = render(cd, None, "financial issuer")
    assert "pre-combination shell" in html
    assert "Total assets</td>" not in html


def test_screen_flags_recent_ipo_as_unscored_but_viewable():
    from unittest.mock import MagicMock
    cd = company("QNT", "7373", ["S-1", "10-Q"])
    client = MagicMock()
    client.get_company.return_value = cd
    with patch("engine.screen.get_quote") as quote:
        row, etf = _process_one("QNT", client, {}, history_years=15)
    assert etf is None and row.excluded and row.limited_analysis
    assert row.composite is None and row.name == "QNT Inc."
    quote.assert_not_called()


def test_fragment_skips_score_for_recent_ipo(app_test_config):
    cd = company("QNT", "7373", ["S-1", "10-Q"], {"revenue": fact("revenue", 7998000)})
    res = AnalysisResult(company=cd, quote=Quote("QNT", None, None, None, "test"))
    with (TestClient(app) as client,
          patch("app.main._resolve_classification", return_value={"kind": "equity", "label": "pending"}),
          patch("app.main.run_single_ticker", return_value=res),
          patch("app.main.D.score") as score):
        response = client.get("/api/analyze/QNT/fragment")
    assert response.status_code == 200 and "7,998,000" in response.text
    score.assert_not_called()


def test_shell_guard_is_per_fact_and_preserves_later_successor():
    cd=company('SECZ','6199',['10-Q'],{'cash':fact('cash',1)})
    cd.cik='0002094496'
    # An unrelated future metric cannot expose the old shell balances.
    later=fact('unmapped',500);later.period_end='2026-09-30'
    cd.quarterly['unmapped']=later
    assert 'Cash</td>' not in render(cd,None,'financial')
    successor=fact('total_assets',9000);successor.period_end='2026-09-30'
    cd.quarterly['total_assets']=successor
    html=render(cd,None,'financial')
    assert '9,000' in html and 'Cash</td>' not in html


def test_annual_fpi_and_fund_routes_preserved():
    from engine.partial_analysis import reason
    from engine.screen import _classify
    for form in ['20-F','40-F']:
        cd=company('FPI','7373',[form,'10-Q'])
        assert reason(cd) is None
        assert _classify('FPI',cd,{})[0]=='operating_fpi'
    cd=company('FUND','6726',['10-Q','N-PORT'])
    assert _classify('FUND',cd,{})[0]=='fund'


def test_evidence_specific_reason_precedence():
    from engine.partial_analysis import reason
    for forms in (['S-1','10-Q'], ['F-1','10-Q'], ['S-1/A']):
        assert reason(company('IPO','7373',forms)) == 'Recent IPO filing; first annual report not yet available'
    assert reason(company('Q','7373',['10-Q'])) == 'Quarterly filer; annual 10-K not yet available'
    assert reason(company('UNKNOWN','7373',['8-K'])) == 'Classification or annual filing coverage unknown; no durability score available'
    assert reason(company('FIN','6199',['S-1','10-Q'])).startswith('Financial issuer;')
    for form in ['10-K','20-F','40-F']:
        assert reason(company('ANNUAL','7373',[form,'S-1','10-Q'])) is None


def test_list_and_detail_use_same_ipo_reason_and_escape_citations(app_test_config):
    from engine.partial_analysis import reason
    from unittest.mock import MagicMock
    cd = company('QNT','7373',['S-1','10-Q'], {'revenue': fact('revenue',7998000)})
    cd.quarterly['revenue'].accn = '<script>alert(1)</script>'
    reader = MagicMock(); reader.get_company.return_value = cd
    row, _ = _process_one('QNT', reader, {}, 15)
    assert row.flag == reason(cd)
    html = render(cd,None,row.flag)
    assert row.flag in html and '<script>' not in html and '&lt;script&gt;' in html
    assert row.composite is None and row.universe_ranks == {}
