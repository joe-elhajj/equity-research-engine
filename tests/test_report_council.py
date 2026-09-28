"""Extractive brief and lossless full-record regression tests (no model calls)."""
from copy import deepcopy
from dataclasses import asdict
from html import unescape
import re

from engine import report_council as RC
from engine.council import AdvisorOpinion, ChairmanOutput, CouncilMeta, CouncilResult, ReviewNote
from engine.market import Quote


def council():
    text = '''### VERDICT
VERDICT: HOLD
CONFIDENCE: 2
Confidence would move UP if data arrives. Confidence would move DOWN if margins fall.

### CONTRADICTION_LEDGER
1. **Valuation conflict.** Claims zero cushion but cites +22% upside. OPEN: missing gross_profit.
2. **Dilution.** Shares fell. **RESOLVED (partially)**: cash quality remains unclear.
3. No stated resolution; peer medians unavailable.

### THESIS_JOURNAL_DELTA
- If margin <25% for two years, re-review by FY2027.

### ACTION_ITEMS
1. Owner: user. Draft thesis before sizing.

### RISK_REGISTER
1. Missing interest_expense and peers.

### DISSENT
Bear disagrees. The chairman's verdict follows the cushion argument but requires a thesis before sizing.
'''
    from engine.council import _parse_chairman
    return CouncilResult('TEST', [AdvisorOpinion(name, 'HOLD', 2,
        'Margins fell despite rising sales.\nPOSITION: HOLD\nAGAINST: Competition may accelerate.\nCONFIDENCE: 2', True)
        for name in RC.SEAT_LABELS],
        [ReviewNote('BEAR_ADVOCATE', '**Strongest: A.** Cites a cash cushion.\n\n**Contradiction:** Unsupported claim conflicts with +22% upside.')],
        _parse_chairman(text), CouncilMeta('TEST','model','v1','hash','2026-09-24','acc','pre_thesis',None,
        'gross_profit is null; peer comparison unavailable.', .89,399701,9202,[],[{'input_tokens': 399701}]))


def plain(html):
    return unescape(re.sub('<[^>]+>', '', html))


def test_seat_labels_and_findings():
    html = RC.render(council())
    for label in ['Bear case','Bull case','Assumptions check','Outside view','Execution check']:
        assert label in html
    assert 'Seat findings' not in html
    assert 'Margins fell despite rising sales.' not in html
    assert RC.render(council(), full_record=True).count('Margins fell despite rising sales.') == 5
    assert 'steelman' not in html.lower()
    assert 'HOLD · 2/5' in html


def test_missing_fields_are_explicit_never_zero():
    cr = council()
    cr.advisors = []
    cr.reviews = []
    cr.chairman = ChairmanOutput(None,None,'Unstructured uncertainty.',{},False)
    cr.meta.evidence_integrity_note = ''
    html = RC.render(cr)
    assert 'not stated' in html
    assert 'Review coverage UNKNOWN' in html
    assert 'Unstructured uncertainty.' in html
    assert '$0' not in html


def test_chair_text_fidelity_and_no_synthetic_rationale():
    cr = council()
    rationale = RC._chair_rationale(cr.chairman.text)
    assert rationale in cr.chairman.text
    assert RC._labels(rationale) in plain(RC.render(cr))
    cr.chairman.text = '### VERDICT\nVERDICT: HOLD\nCONFIDENCE: 2\nConfidence would move UP if peers arrive.'
    assert RC._chair_rationale(cr.chairman.text) == 'not stated'


def test_all_safety_sections_and_review_conflicts_preserved():
    cr = council()
    text = plain(RC.render(cr))
    for key, section in cr.chairman.sections.items():
        parts = RC._split_numbered_items(section) if key == "contradiction_ledger" else [section]
        for part in parts:
            assert plain(RC._prose(RC._labels(part))) in text
    assert 'Unsupported claim conflicts with +22% upside.' in text
    assert cr.meta.evidence_integrity_note in text
    assert 'UNKNOWN' in text and 'OPEN' in text and 'RESOLVED (PARTIALLY)' in text
    assert 'not independently verified source facts' in text


def test_unknown_status_and_qualified_resolution():
    assert RC._status_chip('No explicit status.')[0] == 'UNKNOWN'
    assert RC._status_chip('RESOLVED: explained.')[0] == 'RESOLVED'
    assert RC._status_chip('**RESOLVED (partially)** still risky.')[0] == 'RESOLVED (PARTIALLY)'


def test_full_record_complete_and_rendering_does_not_mutate_rounds_or_numbers():
    cr = council()
    before = deepcopy(asdict(cr))
    full = plain(RC.render(cr, full_record=True))
    RC.render(cr)
    for a in cr.advisors:
        assert plain(RC._prose(a.text)) in full
    for r in cr.reviews:
        assert plain(RC._prose(r.text)) in full
    assert plain(RC._prose(cr.chairman.text)) in full
    for key in before['meta']:
        assert key in full
    assert asdict(cr) == before
    assert '399701' in full and '9202' in full and '0.89' in full


def test_historical_price_never_uses_current_quote():
    cr = council()
    q = Quote('TEST',999,100,99900,'current')
    assert '$999' not in RC.render(cr,quote=q)
    cr.chairman.text += '\nThe $286.80 price is cited.'
    assert '$286.80 (cited in council; unverified)' in RC.render(cr,quote=q)
    cr.advisors[0].text += '\nThe $250.00 price differs.'
    assert 'no unambiguous run-price citation' in RC.render(cr,quote=q)


def test_print_layout_uses_letter_readable_text_and_splittable_blocks():
    html = RC.render(council())
    assert 'size: letter' in html
    assert '11pt/1.25' in html
    assert 'break-inside: auto' in html
    assert 'break-inside:avoid' not in html
    assert 'break-after: avoid' in html
    assert '<table' not in html
    assert 'overflow: hidden' not in html
    assert 'line-clamp' not in html
    assert 'record.pdf' in html


def test_untrusted_output_escaped_and_missing_pointer_honest():
    cr = council()
    cr.advisors[0].text = '<script>alert(1)</script>.'
    html = RC.render(cr, full_record=True)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert RC._pointers('No citation.') == 'not stated'
    assert RC._pointers('Cites `dcf.bear.upside_vs_price`.') == 'dcf.bear.upside_vs_price'


def test_intu_regression_preserves_chair_resolution_and_all_caveats():
    import json
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / 'fixtures/intu_council.json').read_text())
    cr = CouncilResult(raw['ticker'], [AdvisorOpinion(**a) for a in raw['advisors']],
                       [ReviewNote(**r) for r in raw['reviews']], ChairmanOutput(**raw['chairman']), CouncilMeta(**raw['meta']))
    before = deepcopy(asdict(cr))
    brief = plain(RC.render(cr))
    for item in RC._split_numbered_items(cr.chairman.sections['contradiction_ledger']):
        assert plain(RC._prose(RC._labels(item))) in brief
    for key in ['dissent', 'risk_register', 'action_items', 'thesis_journal_delta']:
        assert plain(RC._prose(RC._labels(cr.chairman.sections[key]))) in brief
    assert 'mathematically contradicts' in brief
    assert '350.11' in brief and '0.221' in brief
    assert 'gross_profit' in brief and 'interest_expense' in brief and 'peer_pe_median' in brief
    assert RC._chair_rationale(cr.chairman.text) in cr.chairman.text
    full = plain(RC.render(cr,full_record=True))
    for a in cr.advisors:
        assert plain(RC._prose(a.text)) in full
    for r in cr.reviews:
        assert plain(RC._prose(r.text)) in full
    assert plain(RC._prose(cr.chairman.text)) in full
    assert asdict(cr) == before


def test_real_intu_print_layout_opt_in(tmp_path):
    """RUN_PDF_LAYOUT_TESTS=1 runs Chrome; default suite stays subprocess-free."""
    import os
    import json
    import subprocess
    from pathlib import Path
    import pytest
    if os.environ.get('RUN_PDF_LAYOUT_TESTS') != '1':
        pytest.skip('Opt-in real Chrome PDF regression')
    from app.pdf import html_to_pdf
    raw = json.loads((Path(__file__).parent / 'fixtures/intu_council.json').read_text())
    cr = CouncilResult(raw['ticker'], [AdvisorOpinion(**a) for a in raw['advisors']],
                       [ReviewNote(**r) for r in raw['reviews']], ChairmanOutput(**raw['chairman']), CouncilMeta(**raw['meta']))
    path = tmp_path / 'brief.pdf'
    path.write_bytes(html_to_pdf(RC.render(cr, company_name='Intuit Inc.')))
    info = subprocess.check_output(['pdfinfo', str(path)], text=True)
    assert 3 <= int(re.search(r'Pages:\s+(\d+)', info).group(1)) <= 4
    assert '612 x 792 pts (letter)' in info


def test_numbered_items_keep_original_priority_numbers():
    html = RC._prose('1. First.\n2. Second.\n3. Third.')
    assert 'start="1"' in html and 'start="2"' in html and 'start="3"' in html


def test_extra_stored_chair_sections_survive_full_record():
    cr = council()
    cr.chairman.sections['extra'] = 'Additional uncertainty not in raw text.'
    assert 'Additional uncertainty not in raw text.' in RC.render(cr, full_record=True)


def test_roster_separates_jobs_from_findings_and_includes_chair():
    cr = council()
    html = RC.render(cr)
    roster = html.split('<section class="roster">', 1)[1].split('</section>', 1)[0]
    assert roster.count('class="seat"') == 6
    assert roster.count('HOLD · 2/5') == 6
    assert '<strong>Chair</strong>' in roster
    for job in RC.SEAT_JOBS.values():
        assert job in roster
    assert 'Margins fell' not in roster  # role description is not a run finding
    assert html.index('The council') < html.index('Chair rationale')
    cr.advisors = []
    assert 'not stated · not stated' in RC._roster(cr)
    assert RC.SEAT_JOBS['BASE_RATE_OUTSIDER'] in RC._roster(cr)


def test_integrity_excerpts_are_labelled_and_full_record_keeps_original():
    import json
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / 'fixtures/intu_council.json').read_text())
    note = raw['meta']['evidence_integrity_note']
    html = RC._integrity_bullets(note)
    assert html.count('<li>') == 4
    for label in ['Gross profit gap','Interest expense gap','Computed expectations signal','Peer comparison gap']:
        assert label in html
    for term in ['gross_profit','interest_expense','-26.9%','peer_pe_median','peer_ev_ebitda_median','peer_fcf_yield_median']:
        assert term in html
    assert 'not independently verified facts' in html
    cr = council()
    cr.meta.evidence_integrity_note = note
    full = RC.render(cr, full_record=True)
    assert RC._prose(note) in full
    unknown = 'Unfamiliar data gap. Another unresolved caveat.'
    assert all(sentence in RC._integrity_bullets(unknown) for sentence in RC._sentences(unknown))


def test_proposed_thresholds_and_dissent_layout_are_explicit():
    html = RC.render(council())
    assert 'not adopted or independently verified' in html
    assert 'All numeric thresholds below are proposals.' in html
    assert 'class="dissent challenge-dissent"' in html
    assert '.challenge, .challenge-dissent, .checkpoints { break-before: page; }' in html
    assert 'overflow-wrap: anywhere' in html
    assert not re.search(r'(?:font-size:|font:)\s*(?:9|10)pt', RC._STYLE)


def test_brief_uses_consistent_display_names_without_changing_originals():
    original = 'BEAR_ADVOCATE and BULL_STEELMAN (BEAR, BULL); chairman.'
    assert RC._labels(original) == 'Bear case and Bull case (Bear case, Bull case); Chair.'
    assert 'BEAR_ADVOCATE' in original
