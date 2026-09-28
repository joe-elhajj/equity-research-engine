"""Read-only, extractive council exports. The cached CouncilResult is authoritative.

The brief selects explicitly labelled excerpts; it never rewrites an opinion.
Contradictions and dissent are reproduced in full, even when unusual runs
exceed the page budget. Integrity excerpts are labelled and retain data caveats. Full Council Record retains all raw responses and metadata.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from html import escape
from pathlib import Path
from typing import Optional

from engine.council import CouncilResult, _cache_key, _split_sections
from engine.market import Quote

SEAT_LABELS = {
    "BEAR_ADVOCATE": "Bear case",
    "BULL_STEELMAN": "Bull case",
    "ASSUMPTION_AUDITOR": "Assumptions check",
    "BASE_RATE_OUTSIDER": "Outside view",
    "EXECUTION_REALIST": "Execution check",
}
SEAT_JOBS = {
    "BEAR_ADVOCATE": "Makes the strongest case against buying.",
    "BULL_STEELMAN": "Makes the strongest honest case for buying.",
    "ASSUMPTION_AUDITOR": "Checks valuation inputs and missing data.",
    "BASE_RATE_OUTSIDER": "Looks for comparable cases and base rates.",
    "EXECUTION_REALIST": "Checks timing, sizing and monitoring risks.",
    "CHAIR": "Weighs disagreements and states the conclusion.",
}
# Only derived exports are versioned; council JSON keys/semantics are unchanged.
REPORT_VERSION = "decision-brief-v3"


def _labels(text: str) -> str:
    for key, label in SEAT_LABELS.items():
        text = text.replace(key, label)
    text = re.sub(r"\bBEAR\b", "Bear case", text)
    text = re.sub(r"\bBULL\b", "Bull case", text)
    return re.sub(r"\bchairman\b", "Chair", text, flags=re.I)


def _inline(text: str) -> str:
    t = escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`([^`]+?)`", r"<code>\1</code>", t)
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", t)
    return t


def _prose(text: Optional[str]) -> str:
    """Blocks separated by a blank line; each block is either a paragraph
    or a run of "- " / "N. " list items, rendered as <ul>/<ol>."""
    if not text or not text.strip():
        return ""
    blocks = re.split(r"\n\s*\n|\n(?=- |\d+\. |### )", text.strip())
    html_parts = []
    for block in blocks:
        lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if all(re.match(r"^-\s+", ln) for ln in lines):
            items = "".join(f"<li>{_inline(re.sub(r'^-\s+', '', ln))}</li>" for ln in lines)
            html_parts.append(f"<ul class=\"prose-list\">{items}</ul>")
        elif all(re.match(r"^\d+\.\s+", ln) for ln in lines):
            items = "".join(f"<li>{_inline(re.sub(r'^\d+\.\s+', '', ln))}</li>" for ln in lines)
            start = int(re.match(r"^(\d+)\.", lines[0]).group(1))
            html_parts.append(f'<ol class="prose-list" start="{start}">{items}</ol>')
        else:
            html_parts.append(f"<p>{_inline(' '.join(lines))}</p>")
    return "".join(html_parts)


def _split_numbered_items(text: Optional[str]) -> list[str]:
    """Splits a "1. ...\n\n2. ...\n\n3. ..." section into its numbered
    items — each item keeps everything up to (not including) the next
    top-level number, so a multi-paragraph item stays intact."""
    if not text or not text.strip():
        return []
    matches = list(re.finditer(r"(?m)^(\d+)\.\s+", text))
    if not matches:
        return [text.strip()]
    items = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        items.append(text[start:end].strip())
    return items


def _sentences(text: str) -> list[str]:
    # Do not split decimal numbers or dotted evidence paths.
    return re.split(r'(?<=[.!?])\s+(?=[A-Z"“])', text.strip()) if text.strip() else []


def _chair_rationale(text: str) -> str:
    sections = _split_sections(text)
    # The prompt puts the conclusion's reasoning in DISSENT on some runs.
    for sentence in _sentences(sections.get("DISSENT", "")):
        if re.search(r"\b(?:chairman|chair)'?s?\b.*\bverdict\b", sentence, re.I):
            # A self-contained concluding clause is a shorter verbatim excerpt.
            clause = sentence.rsplit(" — ", 1)[-1]
            if clause != sentence and 15 <= len(clause.split()) <= 70:
                return clause
            return sentence
    verdict = sections.get("VERDICT", "")
    lines = [line for line in verdict.splitlines()
             if not re.match(r"\s*(?:VERDICT|CONFIDENCE):", line, re.I)]
    for sentence in _sentences(" ".join(lines)):
        if not re.search(r"confidence|move UP|move DOWN", sentence, re.I):
            return sentence
    return "not stated"


def _status_chip(text: str) -> tuple[str, str, str]:
    bold = re.search(r"\*\*\s*((?:OPEN|RESOLVED|UNKNOWN)[^*]*)\*\*", text, re.I)
    plain = re.search(r"\b(OPEN|RESOLVED|UNKNOWN)(?=[:\s]|$)", text)
    m = bold or plain
    if not m:
        return "UNKNOWN", "unknown", text
    label = m.group(1).strip().upper()
    # Keep the whole qualification and resolution explanation in the prose.
    return label, label.split()[0].lower(), text


def _pointers(text: str) -> str:
    refs = list(dict.fromkeys(re.findall(r"`([^`]+)`", text)))
    return "; ".join(refs) if refs else "not stated"


def _section(title: str, text: str, css: str = "", *, labels: bool = True) -> str:
    return f'<section class="{css}"><h2>{escape(title)}</h2>{_prose(_labels(text or "not stated") if labels else (text or "not stated"))}</section>'


def _run_price(cr: CouncilResult) -> str:
    # Current Quote is NOT historical evidence. Only report an explicit cited
    # price, label it a model citation, and abstain if citations disagree.
    text = "\n".join([cr.chairman.text] + [a.text for a in cr.advisors])
    values = set(re.findall(r"\$([\d,]+\.\d{2})\s+(?:price|current price)", text))
    return "$" + next(iter(values)) + " (cited in council; unverified)" if len(values) == 1 else "not stated (no unambiguous run-price citation)"


def _roster(cr: CouncilResult) -> str:
    by_name = {a.name: a for a in cr.advisors}
    rows = []
    for name, label in list(SEAT_LABELS.items()) + [("CHAIR", "Chair")]:
        a = cr.chairman if name == "CHAIR" else by_name.get(name)
        stance = (cr.chairman.verdict if name == "CHAIR" else a.position if a else None) or "not stated"
        confidence = f"{a.confidence}/5" if a and a.confidence is not None else "not stated"
        rows.append(f'<div class="seat"><div class="seat-heading"><strong>{label}</strong>'
                    f'<span>{escape(stance)} · {confidence}</span></div><p>{SEAT_JOBS[name]}</p></div>')
    return '<section class="roster"><h2>The council</h2>' + ''.join(rows) + '</section>'


def _integrity_bullets(note: str) -> str:
    """Extract the enumerated note without synthesizing factual claims.

    The recognized four-part format uses short sentence/clause excerpts.
    Unknown formats retain every word, divided into sentences for readability.
    """
    parts = re.split(r"\b(?:First|Second|Third|Fourth),\s+", note)
    labels = ["Gross profit gap", "Interest expense gap", "Computed expectations signal", "Peer comparison gap"]
    expected = ["gross_profit", "interest_expense", "expectations_gap", "peer_pe_median"]
    if len(parts) == 5 and all(key in part for key, part in zip(expected, parts[1:])):
        excerpts = [_sentences(part)[0] for part in parts[1:]]
        # Remove only the known diagnostic explanations, never the gap itself.
        excerpts[0] = excerpts[0].split(", yet the engine successfully computed", 1)[0]
        excerpts[1] = excerpts[1].split(" — again in", 1)[0]
        # Keep the stated computed signal, omitting the repeated growth inputs
        # and instructions to advisors. If this exact clause is absent, retain
        # the whole sentence rather than guessing at a shorter interpretation.
        signal = re.search(r"this (.*?not a data gap)", excerpts[2])
        if signal:
            excerpts[2] = signal.group(1)
        items = [f'<li><strong>{label}:</strong> {_inline(excerpt)}</li>' for label, excerpt in zip(labels, excerpts)]
    else:
        items = [f'<li>{_inline(sentence)}</li>' for sentence in _sentences(note or "not stated")]
    return ('<section class="integrity-note"><h2>Evidence integrity · model-note excerpts</h2>'
            '<p>Excerpts, not independently verified facts; full note in Full Council Record.</p><ul>' + ''.join(items) + '</ul></section>')


def _decision(cr: CouncilResult) -> str:
    verdict = _split_sections(cr.chairman.text).get("VERDICT", "")
    mover = "\n".join(line for line in verdict.splitlines()
                      if not re.match(r"\s*(?:VERDICT|CONFIDENCE):", line, re.I)).strip()
    support = counter = "not stated"
    # Explicit ranking only. Never turn a generic bull/bear role into a finding.
    m = re.search(r"\(([^()]*strongest[^()]*)\)", cr.chairman.text, re.I)
    if m:
        support = m.group(1)
    m = re.search(r'strongest surviving argument.*?:\s*["“](.+?)["”]', cr.chairman.text, re.S | re.I)
    if m:
        counter = m.group(1)
    return (
        _section("Chair rationale · excerpt", _chair_rationale(cr.chairman.text))
        + _section("Strongest supporting point · chair’s explicit ranking", support)
        + _section("Strongest counterargument · chair’s surviving-argument excerpt", counter)
        + _section("What would raise or lower confidence · chair text", mover)
    )


def _challenge(cr: CouncilResult, flags_status: Optional[dict] = None) -> str:
    sections = cr.chairman.sections or {}
    rows = []
    for i, item in enumerate(_split_numbered_items(sections.get("contradiction_ledger")), 1):
        label, status, _ = _status_chip(item)
        rows.append(f'<div class="ledger"><h3><span class="status {status}">{escape(label)}</span> Chair ledger {i}</h3>'
                    + _prose(_labels(item))
                    + f'<p class="pointer">Evidence pointers (as cited): {_inline(_pointers(item))}</p></div>')
    reviews = []
    for review in cr.reviews:
        match = re.search(r"(?:\*\*Contradiction[^*]*\*\*|(?:\(3\)\s*)?Contradiction:)\s*(.*)", review.text, re.I | re.S)
        text = match.group(1) if match else review.text
        reviews.append(f'<p><strong>{escape(SEAT_LABELS.get(review.reviewer, review.reviewer))} · UNKNOWN:</strong> '
                       + _inline(_labels(text or "not stated")) + '</p>')
    review_html = '<section><h2>Blind-review challenges · original excerpts</h2><p class="note">A–D labels are local to each blind review. Disposition here is UNKNOWN; the chair ledger states its own resolutions.</p>' + ''.join(reviews) + '</section>'
    return ('<section class="challenge"><h2>What survived challenge</h2>'
            '<p class="note">Model conclusions, not independently verified source facts. Status is the chair’s stated disposition; '
            'UNKNOWN means no explicit disposition. Evidence pointers are citations, not verification.</p>'
            + (''.join(rows) or '<p>Contradiction ledger: not stated. Review coverage UNKNOWN.</p>')
            + '</section>' + _provenance(cr, flags_status) + _section("Dissent · preserved in full", sections.get("dissent", ""), "dissent challenge-dissent") + review_html + _integrity_bullets(cr.meta.evidence_integrity_note))


def _provenance(cr: CouncilResult, flags_status: Optional[dict]) -> str:
    meta = cr.meta
    flags = (f"{flags_status.get('count', 'not stated')} cached flag(s); filing {flags_status.get('accession', 'not stated')}"
             if flags_status and flags_status.get("cached") else "cached flag status not available")
    return _section("Provenance and missing data", (
        f"Run: {meta.convened_at}. Model: {meta.model}; prompt: {meta.prompt_version}; config: {meta.config_hash}. "
        f"Accession: {meta.accession}. Thesis: {meta.thesis_status}. Flags: {flags}. "
        f"Run status: {', '.join(meta.status_flags) or 'no status flags recorded'}. "
        "The original evidence bundle is not stored in CouncilResult; source verification is unavailable from this record alone."
    ), "provenance")


_STYLE = """
@page { size: letter; margin: .55in .6in; @bottom-right { content: counter(page); font-size: 11pt; } }
* { box-sizing: border-box; }
body { margin: 0; color: #202b35; background: white; font: 11pt/1.25 Arial, sans-serif; }
main { max-width: 7.3in; margin: auto; overflow-wrap: anywhere; }
h1 { font-size: 24pt; margin: 4pt 0 8pt; }
h2 { font-size: 12pt; color: #174b61; border-bottom: 1px solid #b8c9d0; padding-bottom: 4pt; margin: 7pt 0 4pt; }
h3 { font-size: 11pt; margin: 8pt 0 3pt; }
p { margin: 3pt 0 5pt; }
header { border-top: 5pt solid #174b61; padding-top: 8pt; }
.kicker { text-transform: uppercase; letter-spacing: 1pt; font-size: 11pt; }
.verdict { font-size: 15pt; font-weight: bold; }
.note, .pointer, footer { color: #4c5961; font-size: 11pt; }
.seat { border-bottom: 1px solid #d5dfe3; padding: 4pt 0; }
.seat-heading { display: flex; justify-content: space-between; gap: 8pt; }
.seat-heading span { text-align: right; }
.seat p { margin: 3pt 0 0; }
.status { display: inline; font-size: 11pt; padding: 2pt 5pt; border: 1px solid; }
.open, .unknown { color: #853b14; }
.resolved { color: #246240; }
.dissent { border-left: 4pt solid #853b14; padding-left: 10pt; }
code { font: inherit; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 11pt/1.3 monospace; }
ul, ol { padding-left: 18pt; margin: 5pt 0; }
li { margin-bottom: 5pt; }
.integrity-note li { margin-bottom: 2pt; }
.integrity-note h2 { margin-top: 5pt; }
.integrity-note p { margin-bottom: 3pt; }
a { color: #174b61; }
@media print {
  .export-links { display: none; }
  section, .ledger, .dissent, .record, pre, li { break-inside: auto; }
  h1, h2, h3 { break-after: avoid; }
  p { orphans: 2; widows: 2; }
  .challenge, .challenge-dissent, .checkpoints { break-before: page; }
  .seat { break-inside: avoid; }
}
"""


def render(council_result: CouncilResult, quote: Optional[Quote] = None,
           config: Optional[dict] = None, company_name: Optional[str] = None,
           flags_status: Optional[dict] = None, *, full_record: bool = False) -> str:
    """Pure view; quote is optional current context, never substituted for run price."""
    cr = council_result
    title = "Full Council Record" if full_record else "Council Decision Brief"
    confidence = f"{cr.chairman.confidence}/5" if cr.chairman.confidence is not None else "not stated"
    body = (f'<header><div class="kicker">{title}</div><h1>{escape(cr.ticker)}'
            f'<span> · {escape(company_name or "company name not stated")}</span></h1>'
            f'<p>Run date: {escape(cr.meta.convened_at[:10])} · Price at run: {escape(_run_price(cr))}</p>'
            f'<p class="verdict">Chair: {escape(cr.chairman.verdict or "not stated")} · confidence {confidence}</p></header>')
    if full_record:
        body += '<p>Complete cached deliberation. Raw responses retain internal seat IDs, numbers and wording. These are model outputs.</p>'
        for a in cr.advisors:
            body += _section(f"Round 1 · {SEAT_LABELS.get(a.name, a.name)}", a.text, "record", labels=False)
            body += f'<p>Stored stance: {escape(a.position or "not stated")}; confidence: {a.confidence}; parsed: {a.parsed}</p>'
        for r in cr.reviews:
            body += _section(f"Round 2 · {SEAT_LABELS.get(r.reviewer, r.reviewer)}", r.text, "record", labels=False)
        body += _section("Round 3 · Chair · complete output", cr.chairman.text, "record", labels=False)
        # A machine-readable, lossless copy also preserves any extra parsed
        # sections and metadata that differ from the raw responses.
        for key, value in (cr.chairman.sections or {}).items():
            if value not in cr.chairman.text:
                body += _section(f"Stored chair section · {key}", str(value))
        body += _section('Evidence integrity · original model note', cr.meta.evidence_integrity_note, labels=False)
        body += '<h2>Complete run metadata</h2><pre>' + escape(json.dumps(asdict(cr.meta), indent=2, ensure_ascii=False)) + '</pre>'
        body += f'<p>Chair parsed: {cr.chairman.parsed}; stored verdict: {escape(cr.chairman.verdict or "not stated")}; confidence: {cr.chairman.confidence}</p>'
    else:
        body += '<p class="note">Model conclusions; selected excerpts. Full deliberation: separate Full Council Record. Contradictions and dissent retained in full; no source facts independently verified.</p>'
        body += _roster(cr) + _decision(cr) + _challenge(cr, flags_status)
        sections = cr.chairman.sections or {}
        body += _section("Thesis checkpoints · proposed by the Chair", "Criteria proposed by the Chair, not adopted or independently verified. All numeric thresholds below are proposals.\n\n" + sections.get("thesis_journal_delta", "not stated"), "checkpoints")
        body += _section("Next actions · chair’s priority order", sections.get("action_items", ""))
        body += _section("Risk register", sections.get("risk_register", ""))
        if not cr.chairman.parsed:
            body += _section("Unparsed chair output · review required", cr.chairman.text, "dissent")
    body += (f'<nav class="export-links"><a href="/api/council/{escape(cr.ticker)}/record.pdf">Full Council Record PDF</a></nav>'
             '<footer>Decision support from language models. Not investment advice. Full Council Record preserves the complete deliberation and metadata.</footer>')
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{escape(cr.ticker)} · {title}</title><style>{_STYLE}</style></head><body><main>{body}</main></body></html>'


def _report_path(cache_dir: Path, accession: str, thesis_tag: str, prompt_version: str, model: str, ext: str) -> Path:
    return cache_dir / f"{_cache_key(accession, thesis_tag, prompt_version, model)}.{ext}"


def is_html_cached(cache_dir: Path, accession: str, thesis_tag: str, prompt_version: str, model: str) -> bool:
    return _report_path(cache_dir, accession, thesis_tag, prompt_version, model, "html").exists()


def load_cached_html(cache_dir: Path, accession: str, thesis_tag: str, prompt_version: str, model: str) -> Optional[str]:
    p = _report_path(cache_dir, accession, thesis_tag, prompt_version, model, "html")
    return p.read_text(encoding="utf-8") if p.exists() else None


def save_cached_html(cache_dir: Path, accession: str, thesis_tag: str, prompt_version: str, model: str, html: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _report_path(cache_dir, accession, thesis_tag, prompt_version, model, "html").write_text(html, encoding="utf-8")


def is_pdf_cached(cache_dir: Path, accession: str, thesis_tag: str, prompt_version: str, model: str) -> bool:
    return _report_path(cache_dir, accession, thesis_tag, prompt_version, model, "pdf").exists()


def load_cached_pdf(cache_dir: Path, accession: str, thesis_tag: str, prompt_version: str, model: str) -> Optional[bytes]:
    p = _report_path(cache_dir, accession, thesis_tag, prompt_version, model, "pdf")
    return p.read_bytes() if p.exists() else None


def save_cached_pdf(cache_dir: Path, accession: str, thesis_tag: str, prompt_version: str, model: str, pdf_bytes: bytes) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _report_path(cache_dir, accession, thesis_tag, prompt_version, model, "pdf").write_bytes(pdf_bytes)
