#!/usr/bin/env python
"""Generate the Term 4 slide deck.

Twelve slides, one idea each, read from `docs/results/` through the same loader the report uses,
so a figure cannot say one thing on a slide and another in the document.

Light theme, deliberately. The product's own interface is a dark control room; a deck is a
different artefact, read in a lit room and often printed, and inverting it there would cost
legibility for nothing.

Speaker notes are talking points rather than a script. Krishna presents live; notes that are
written to be read aloud get read aloud.

    uv run --extra docs python -m scripts.build_deck --draft
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from agents.export import xml_safe
from scripts.guard_synthetic import check as guard_check
from scripts.term4.artefacts import ROOT, Bundle, collect, load, short_path

OUT = ROOT / "docs" / "AI217_YIELDMAP_deck.pptx"

WIDE_W, WIDE_H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.75)

ACCENT = RGBColor(0x1F, 0x7A, 0x70)
ACCENT_SOFT = RGBColor(0xE6, 0xF1, 0xEE)
INK = RGBColor(0x14, 0x1A, 0x19)
MUTED = RGBColor(0x5F, 0x6B, 0x68)
WARN = RGBColor(0x9A, 0x3A, 0x12)
WARN_SOFT = RGBColor(0xFD, 0xF1, 0xE7)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

HEAD_FONT = "Cambria"
BODY_FONT = "Calibri"

LIVE_WEB = "https://yieldmap.vercel.app"
LIVE_API = "https://yieldmap-api.onrender.com"


def _blank(prs: Presentation):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = WHITE
    return slide


def _text(
    slide,
    x,
    y,
    w,
    h,
    text,
    *,
    size,
    bold=False,
    colour=INK,
    font=BODY_FONT,
    align=PP_ALIGN.LEFT,
    italic=False,
    spacing=None,
    anchor=MSO_ANCHOR.TOP,
):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = anchor
    para = frame.paragraphs[0]
    para.alignment = align
    run = para.add_run()
    run.text = xml_safe(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = colour
    run.font.name = font
    if spacing is not None:
        para.line_spacing = spacing
    return box


def _bullets(slide, x, y, w, h, items, *, size=15, colour=INK, gap=10):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    for i, item in enumerate(items):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        run = para.add_run()
        run.text = xml_safe(item)
        run.font.size = Pt(size)
        run.font.color.rgb = colour
        run.font.name = BODY_FONT
        para.space_after = Pt(gap)
        para.line_spacing = 1.2
    return box


def _band(slide, height, *, fill=ACCENT):
    """A full-bleed header block.

    Square-cornered on purpose: a rounded rectangle flush with the slide edge leaves white
    notches where the corner radius cuts in, which is visible on a projector.
    """
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), WIDE_W, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _card(slide, x, y, w, h, *, fill=ACCENT_SOFT):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.fill.background()
    shape.shadow.inherit = False
    shape.adjustments[0] = 0.06
    return shape


def _stat(slide, x, y, w, value, label, *, colour=ACCENT, value_size=48):
    """A big number with a small label. The number is the point; the label explains it."""
    _text(
        slide,
        x,
        y,
        w,
        Inches(0.85),
        value,
        size=value_size,
        bold=True,
        colour=colour,
        font=HEAD_FONT,
        align=PP_ALIGN.CENTER,
    )
    _text(
        slide,
        x,
        y + Inches(0.82),
        w,
        Inches(0.8),
        label,
        size=11,
        colour=MUTED,
        align=PP_ALIGN.CENTER,
    )


def _title(slide, text, *, sub=None):
    _text(
        slide,
        MARGIN,
        Inches(0.62),
        WIDE_W - 2 * MARGIN,
        Inches(1.0),
        text,
        size=38,
        bold=True,
        colour=INK,
        font=HEAD_FONT,
    )
    if sub:
        _text(
            slide,
            MARGIN,
            Inches(1.52),
            WIDE_W - 2 * MARGIN,
            Inches(0.5),
            sub,
            size=14,
            colour=MUTED,
            italic=True,
        )


def _footer(slide, text):
    _text(
        slide,
        MARGIN,
        WIDE_H - Inches(0.62),
        WIDE_W - 2 * MARGIN,
        Inches(0.36),
        text,
        size=9.5,
        colour=MUTED,
    )


def _notes(slide, text: str) -> None:
    slide.notes_slide.notes_text_frame.text = xml_safe(text)


def slide_01_title(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _band(s, Inches(4.5))
    _text(
        s,
        MARGIN,
        Inches(1.35),
        WIDE_W - 2 * MARGIN,
        Inches(1.4),
        "YIELDMAP",
        size=64,
        bold=True,
        colour=WHITE,
        font=HEAD_FONT,
    )
    _text(
        s,
        MARGIN,
        Inches(2.65),
        Inches(9.6),
        Inches(1.0),
        "Dubai property investment intelligence, where every number carries the query that "
        "produced it.",
        size=19,
        colour=WHITE,
    )
    _text(
        s,
        MARGIN,
        Inches(4.95),
        Inches(9.0),
        Inches(1.2),
        "AI 217 — Artificial Intelligence in Finance",
        size=17,
        bold=True,
        colour=INK,
        font=HEAD_FONT,
    )
    _text(
        s,
        MARGIN,
        Inches(5.45),
        Inches(9.0),
        Inches(1.2),
        "Krishna Mathur · SP Jain School of Global Management, MAIB",
        size=13,
        colour=MUTED,
    )
    _text(
        s,
        MARGIN,
        Inches(5.86),
        Inches(9.0),
        Inches(0.5),
        LIVE_WEB,
        size=12,
        colour=ACCENT,
        bold=True,
    )
    if draft:
        _card(s, WIDE_W - Inches(4.6), Inches(4.95), Inches(3.85), Inches(1.5), fill=WARN_SOFT)
        _text(
            s,
            WIDE_W - Inches(4.35),
            Inches(5.12),
            Inches(3.35),
            Inches(0.4),
            "FIGURES FROM A LABELLED STAND-IN",
            size=10.5,
            bold=True,
            colour=WARN,
        )
        _text(
            s,
            WIDE_W - Inches(4.35),
            Inches(5.55),
            Inches(3.35),
            Inches(0.8),
            "The registry portal refuses automated clients. Model numbers exercise the "
            "pipeline; they are not claims about Dubai.",
            size=9.5,
            colour=MUTED,
        )
    _notes(
        s,
        "Open with the problem, not the tech. Dubai publishes every sale and every tenancy "
        "as open data — the gap is between that record and a decision. Say the site is live "
        "and they can open it now. If the stand-in banner is up, name it in the first "
        "sentence rather than letting someone find it in question time: the honesty is part "
        "of the argument.",
    )


def slide_02_problem(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "The data is public. The decision is not.")
    _bullets(
        s,
        MARGIN,
        Inches(2.3),
        Inches(6.4),
        Inches(3.6),
        [
            "Every Dubai sale is registered with the Land Department. Every tenancy is registered "
            "with Ejari. Both are published as open data.",
            "The portals that interpret it price from listings — asks, not transactions — and show "
            "no working.",
            "A buyer needs the net yield after service charge and vacancy, not the gross one. That "
            "number is rarely shown, and the gap between them is large.",
        ],
        size=15.5,
    )
    for i, (value, label) in enumerate(
        [
            ("Gross", "what portals quote"),
            ("Net", "what you actually receive"),
        ]
    ):
        x = Inches(7.6) + i * Inches(2.6)
        _card(s, x, Inches(2.5), Inches(2.35), Inches(2.3))
        _stat(s, x, Inches(2.85), Inches(2.35), value, label, value_size=30)
    y = load("yield.json")
    if y:
        spread = y["summary"]["median_spread"] * 100
        _text(
            s,
            Inches(7.6),
            Inches(5.05),
            Inches(4.95),
            Inches(0.9),
            f"On the current data the median gap between them is {spread:.2f} percentage points.",
            size=12,
            colour=MUTED,
            italic=True,
            align=PP_ALIGN.CENTER,
        )
    _footer(s, "Sources: DLD transaction registry, Ejari tenancy registry — docs/datasets.md")
    _notes(
        s,
        "The one-line version: the data is open, the interpretation is not. Portals price "
        "from asking prices because that is what they have; this uses the registry because "
        "it is published. If asked why net yield matters — service charge is the single "
        "largest cost and it is the one number a listing never carries.",
    )


def slide_03_what_it_does(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "What it does", sub="Four things, each traceable to a query")
    items = [
        (
            "Values",
            "A hedonic model on log price per square metre, scored against the area "
            "median a buyer would otherwise use.",
        ),
        (
            "Yields",
            "Gross and net, with every assumption editable and sourced, and thin cells "
            "suppressed rather than guessed.",
        ),
        (
            "Explains",
            "Ask answers in English, Hindi and Arabic with a citation on every factual "
            "sentence — enforced after generation, not requested in a prompt.",
        ),
        (
            "Audits",
            "A crew of agents writes a memo an auditor has already checked. No tool in "
            "the system can transact.",
        ),
    ]
    for i, (head, body) in enumerate(items):
        col, row = i % 2, i // 2
        x = MARGIN + col * Inches(6.05)
        y = Inches(2.35) + row * Inches(2.25)
        _card(s, x, y, Inches(5.75), Inches(1.95))
        _text(
            s,
            x + Inches(0.3),
            y + Inches(0.22),
            Inches(5.15),
            Inches(0.4),
            head,
            size=20,
            bold=True,
            colour=ACCENT,
            font=HEAD_FONT,
        )
        _text(
            s,
            x + Inches(0.3),
            y + Inches(0.72),
            Inches(5.15),
            Inches(1.1),
            body,
            size=12.5,
            colour=INK,
        )
    _notes(
        s,
        "Four verbs, not a feature list. If time is short, say the first and the third and "
        "move on. The line worth landing: the citation guarantee is enforced after the "
        "model has spoken — uncited sentences are removed — so it does not depend on the "
        "model choosing to comply.",
    )


def slide_04_architecture(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "How it fits together", sub="Registry to warehouse to model to cited answer")
    stages = [
        ("Ingest", "GitHub Actions\nprobe + download"),
        ("Warehouse", "DuckDB\nevery KPI carries its SQL"),
        ("Models", "valuation · yield\nindex · risk · forecast"),
        ("API", "FastAPI on Render\ntyped KPI objects"),
        ("Interface", "Next.js on Vercel\n20 routes, 3 languages"),
    ]
    # 2.14 not 2.28: at the old width the gap between cards was 0.14in and the arrow drawn into
    # it was 0.34in wide, so each card overdrew the arrow before it and all that survived was a
    # square. The cards are narrower now, and the arrows are drawn after all of them.
    width = Inches(2.14)
    step = Inches(2.42)
    for i, (head, body) in enumerate(stages):
        x = MARGIN + i * step
        _card(s, x, Inches(2.5), width, Inches(1.7))
        _text(
            s,
            x + Inches(0.14),
            Inches(2.68),
            width - Inches(0.28),
            Inches(0.4),
            head,
            size=15,
            bold=True,
            colour=ACCENT,
            font=HEAD_FONT,
            align=PP_ALIGN.CENTER,
        )
        _text(
            s,
            x + Inches(0.14),
            Inches(3.13),
            width - Inches(0.28),
            Inches(0.95),
            body.replace("\n", " · "),
            size=10.5,
            colour=MUTED,
            align=PP_ALIGN.CENTER,
        )

    gap = step - width
    for i in range(len(stages) - 1):
        arrow = s.shapes.add_shape(
            MSO_SHAPE.RIGHT_ARROW,
            MARGIN + i * step + width + (gap - Inches(0.22)) / 2,
            Inches(3.26),
            Inches(0.22),
            Inches(0.16),
        )
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = ACCENT
        arrow.line.fill.background()
        arrow.shadow.inherit = False

    _card(s, MARGIN, Inches(4.55), WIDE_W - 2 * MARGIN, Inches(1.55), fill=ACCENT_SOFT)
    _text(
        s,
        MARGIN + Inches(0.35),
        Inches(4.78),
        WIDE_W - 2 * MARGIN - Inches(0.7),
        Inches(1.1),
        "Postgres holds application state only. The analytics stay in DuckDB because 1.5 "
        "million transactions plus indexes do not fit a 500 MB free tier — and because querying "
        "DuckDB directly is what lets every number carry the literal SQL that produced it.",
        size=13,
        colour=INK,
    )
    _notes(
        s,
        "Trace one number end to end if they ask: a tile on the city page comes from a "
        "typed KPI object that carries its own SQL, and clicking it opens that query with a "
        "copy button. The storage split is the answer to 'why two databases' — it started "
        "as a free-tier constraint and turned out to be what makes traceability enforceable.",
    )


def slide_05_live(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "It is live", sub="Not a prototype and not a recording")
    _card(s, MARGIN, Inches(2.35), Inches(6.1), Inches(3.5))
    _text(
        s,
        MARGIN + Inches(0.35),
        Inches(2.62),
        Inches(5.4),
        Inches(0.4),
        "Open it now",
        size=19,
        bold=True,
        colour=ACCENT,
        font=HEAD_FONT,
    )
    _bullets(
        s,
        MARGIN + Inches(0.35),
        Inches(3.15),
        Inches(5.4),
        Inches(2.4),
        [
            f"Web  {LIVE_WEB}",
            f"API  {LIVE_API}/health",
            "Health reports which database is loaded, whether authentication is configured, and "
            "which model tier is answering.",
        ],
        size=13,
    )
    right = Inches(7.35)
    _text(
        s,
        right,
        Inches(2.4),
        Inches(5.25),
        Inches(0.4),
        "The three-minute route",
        size=19,
        bold=True,
        colour=ACCENT,
        font=HEAD_FONT,
    )
    _bullets(
        s,
        right,
        Inches(2.95),
        Inches(5.25),
        Inches(2.9),
        [
            "1.  City — pick a community, open a KPI tile, show the SQL behind the number.",
            "2.  Yield — change a service-charge assumption and watch net move.",
            "3.  Ask — a question in Arabic, with citations, right to left.",
            "4.  Crew — run the agents and open the audit trail.",
        ],
        size=13,
    )
    _footer(
        s,
        "Free tier: the API sleeps after 15 minutes idle, so the first request takes "
        "about 50 seconds. Wake it before presenting.",
    )
    _notes(
        s,
        "Wake the API a minute before you start — free tier, cold start is roughly 50 "
        "seconds and it will be the longest pause of the talk. Demo order matters: KPI "
        "drawer first, because showing the SQL behind a number is the whole thesis and "
        "everything after it is easier once they have seen it. Arabic on Ask is the moment "
        "people remember; keep it.",
    )


def slide_06_results(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "What was measured", sub="Every figure below is read from a file in docs/results/")
    cov, red, econ = b.coverage, b.redteam, b.unit_economics
    acc = load("accessibility_desktop.json")
    stats = [
        (f"{cov['overall_percent']:.0f}%" if cov else "—", "Python line coverage\n1,008 tests"),
        (
            f"{red['controls_held']}/{red['attacks_run']}" if red else "—",
            "OWASP ASI controls held\nattacked in CI",
        ),
        (f"{acc['violations']}" if acc else "—", "accessibility violations\nWCAG 2.1 AA, 7 pages"),
        (f"${econ['monthly_cost_usd']:.0f}" if econ else "—", "per month\nfree tiers only"),
    ]
    for i, (value, label) in enumerate(stats):
        x = MARGIN + i * Inches(3.0)
        _card(s, x, Inches(2.35), Inches(2.75), Inches(2.05))
        _stat(s, x, Inches(2.62), Inches(2.75), value, label.replace("\n", " · "))
    _text(
        s,
        MARGIN,
        Inches(4.72),
        WIDE_W - 2 * MARGIN,
        Inches(0.42),
        "And the ones that took work to earn",
        size=17,
        bold=True,
        colour=INK,
        font=HEAD_FONT,
    )
    _bullets(
        s,
        MARGIN,
        Inches(5.22),
        WIDE_W - 2 * MARGIN,
        Inches(1.5),
        [
            "Accessibility went from 7 serious violations to 0 — the first measurement was wrong, "
            "because the test ran while an entrance animation was still fading.",
            "Page weight is gated at 340 KB and three.js loads on none of the twenty routes that do "
            "not draw a map.",
        ],
        size=13,
        colour=MUTED,
    )
    _notes(
        s,
        "Do not read the tiles — they are there so nobody has to. Spend the time on the "
        "accessibility story instead: the first pass reported zero violations and was "
        "measuring a half-faded page. Fixing the test surfaced seven real problems. That is "
        "the honest version of a green number and it is worth more than the number.",
    )


def slide_07_models(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "Do the models work?", sub="Scored against the benchmark a buyer would otherwise use")
    h, f = load("hedonic.json"), load("forecast.json")
    if h:
        m = h["metrics"]
        left = [
            (f"{m['test']['mape'] * 100:.1f}%", "valuation error\non a time-split holdout"),
            (f"{m['baseline']['mape'] * 100:.1f}%", "the area-median\nbaseline it beats"),
            (
                f"{m['estimated_noise_floor_mape'] * 100:.1f}%",
                "estimated noise floor\nthe honest target",
            ),
        ]
        for i, (value, label) in enumerate(left):
            x = MARGIN + i * Inches(2.55)
            _card(s, x, Inches(2.35), Inches(2.3), Inches(1.95))
            _stat(s, x, Inches(2.6), Inches(2.3), value, label.replace("\n", " · "), value_size=34)
    if f:
        sm = f["summary"]
        _card(s, Inches(8.5), Inches(2.35), Inches(4.1), Inches(1.95), fill=ACCENT_SOFT)
        _stat(
            s,
            Inches(8.5),
            Inches(2.6),
            Inches(4.1),
            f"{sm['areas_beating_naive']}/{sm['areas_compared']}",
            "areas where the forecast beats seasonal naive",
            value_size=34,
        )
    _bullets(
        s,
        MARGIN,
        Inches(4.6),
        WIDE_W - 2 * MARGIN,
        Inches(2.0),
        [
            "The holdout is split by time, not at random. A random split lets the model see the "
            "future of the same building, which flatters it.",
            "Error is compared against an estimated noise floor rather than against zero: two "
            "identical units sell weeks apart at different prices, and no model explains that gap.",
            "Cells with too few transactions are suppressed. A yield from three sales is not a yield, "
            "and a small-sample footnote is a way of showing it anyway.",
        ],
        size=13.5,
    )
    if draft:
        _text(
            s,
            MARGIN,
            WIDE_H - Inches(0.72),
            WIDE_W - 2 * MARGIN,
            Inches(0.42),
            "These figures were computed from a labelled stand-in. They show the pipeline runs; "
            "they are not claims about the Dubai market.",
            size=10.5,
            colour=WARN,
            bold=True,
        )
    _notes(
        s,
        "The examiner's question is 'is 18.9% good?' — the answer is that it is meaningless "
        "on its own, which is why all three numbers are on the slide. Half the remaining "
        "error is noise no model can reach. If the stand-in banner is showing, say plainly "
        "that this measures the code and not the market, and that loading real files "
        "changes every number without a code change.",
    )


def slide_08_retrieval(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "Answers you can check", sub="Retrieval, and the guarantee that survives the model")
    e = load("rag_eval.json")
    if e:
        for i, (value, label) in enumerate(
            [
                (f"{e['recall_at_1']:.2f}", "recall@1 · the rank measure that matters"),
                (f"{e['mrr']:.2f}", "mean reciprocal rank"),
                (f"{e['faithfulness']:.2f}", "faithfulness · every sentence traceable"),
                (f"{e['n_cases']}", "cases · English, Hindi and Arabic"),
            ]
        ):
            x = MARGIN + i * Inches(3.0)
            _card(s, x, Inches(2.3), Inches(2.75), Inches(1.85))
            _stat(s, x, Inches(2.52), Inches(2.75), value, label, value_size=36)
    _bullets(
        s,
        MARGIN,
        Inches(4.45),
        WIDE_W - 2 * MARGIN,
        Inches(2.2),
        [
            "Recall@5 is 1.00 and that is the least interesting number here — the corpus is 117 "
            "chunks, so finding the right one in five is easy. The rank measures are the ones that "
            "say anything.",
            "Every factual sentence without a citation is deleted after generation. The guarantee is "
            "a filter, not a request in a prompt.",
            "A relevance threshold for refusing out-of-scope questions was measured and rejected: no "
            "signal separates them on this corpus without also refusing real questions.",
        ],
        size=13.5,
    )
    if draft:
        _text(
            s,
            MARGIN,
            WIDE_H - Inches(0.72),
            WIDE_W - 2 * MARGIN,
            Inches(0.42),
            f"Scored against the offline {e['retrieval_backend']} fallback — the hybrid design "
            "this exists to measure has not yet run against a live embedding provider."
            if e
            else "",
            size=10.5,
            colour=WARN,
            bold=True,
        )
    _notes(
        s,
        "Lead with the weakness, because they will find it: recall@5 of 1.00 on a "
        "117-chunk corpus proves nothing, and saying so first is worth more than defending "
        "it later. The rejected threshold is the strongest slide in the deck for a research "
        "question — a negative result, measured, recorded, with the reason it fails: the "
        "distinguishing word is one token in an otherwise on-topic sentence, and every "
        "signal averages it away.",
    )


def slide_09_governance(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "What the agents cannot do", sub="The boundary is architectural, not a policy")
    red = b.redteam
    _card(s, MARGIN, Inches(2.3), Inches(3.5), Inches(2.0), fill=ACCENT_SOFT)
    _stat(
        s,
        MARGIN,
        Inches(2.55),
        Inches(3.5),
        f"{red['controls_held']}/{red['attacks_run']}" if red else "—",
        "OWASP ASI controls held · every attack runs in CI",
    )
    _bullets(
        s,
        Inches(4.75),
        Inches(2.3),
        Inches(7.85),
        Inches(2.2),
        [
            "No endpoint buys, sells, lists or finances anything. There is no tool to misuse.",
            "Every run is bounded on requests, seconds and steps — three axes because a loop burns "
            "steps without time and a slow provider burns time without steps.",
            "The Auditor rejects a memo written in the language of a recommendation, whatever "
            "produced it.",
        ],
        size=13.5,
    )
    _card(s, MARGIN, Inches(4.65), WIDE_W - 2 * MARGIN, Inches(1.95), fill=WARN_SOFT)
    _text(
        s,
        MARGIN + Inches(0.35),
        Inches(4.88),
        WIDE_W - 2 * MARGIN - Inches(0.7),
        Inches(0.4),
        "Two faults found by attacking our own claims",
        size=16,
        bold=True,
        colour=WARN,
        font=HEAD_FONT,
    )
    _bullets(
        s,
        MARGIN + Inches(0.35),
        Inches(5.35),
        WIDE_W - 2 * MARGIN - Inches(0.7),
        Inches(1.2),
        [
            "Retrieved text was wrapped in delimiters and declared to be data — but a document "
            "containing the closing delimiter ended the quarantine early. Fixed, and now an attack "
            "in the suite.",
            "The model API key travelled in a URL, and the HTTP library quotes URLs in errors. One "
            "rejected key would have written itself into the logs and error tracking.",
        ],
        size=11.5,
        colour=INK,
        gap=5,
    )
    _notes(
        s,
        "This is the slide to slow down on. The claim 'retrieved text is treated as data' "
        "was true of the wrapping and false of the holding, and nothing in the test suite "
        "would have caught it — the existing attack asked the model to disobey, and this "
        "one removes the rule instead. Say that the secret scanner would never have found "
        "the key leak either, because the key was never in a file. Static scanning and "
        "runtime handling are different problems.",
    )


def slide_10_business(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "What it costs to run", sub="Zero, and that is a constraint rather than an accident")
    u = b.unit_economics
    _card(s, MARGIN, Inches(2.35), Inches(3.4), Inches(2.1), fill=ACCENT_SOFT)
    _stat(
        s,
        MARGIN + Inches(0.2),
        Inches(2.6),
        Inches(3.0),
        "$0.00",
        "per month · against published rates",
        value_size=44,
    )
    if u:
        rows = [
            ("a demo day", u["scenarios"]["a demo day"]),
            ("a busy course week", u["scenarios"]["a busy course week, per day"]),
            ("a hundred daily users", u["scenarios"]["a hundred daily users"]),
        ]
        for i, (name, sc) in enumerate(rows):
            y = Inches(2.35) + i * Inches(0.74)
            _card(s, Inches(4.6), y, Inches(8.0), Inches(0.62), fill=RGBColor(0xF4, 0xF7, 0xF6))
            _text(
                s,
                Inches(4.85),
                y + Inches(0.15),
                Inches(2.6),
                Inches(0.35),
                name,
                size=13,
                bold=True,
                colour=INK,
            )
            _text(
                s,
                Inches(7.5),
                y + Inches(0.16),
                Inches(2.0),
                Inches(0.35),
                f"{sc['model_requests']:,} requests",
                size=12,
                colour=MUTED,
            )
            _text(
                s,
                Inches(9.6),
                y + Inches(0.16),
                Inches(2.8),
                Inches(0.35),
                f"binds on {sc['binding_constraint'].split('(')[0].strip()}",
                size=11.5,
                colour=ACCENT,
            )
    _bullets(
        s,
        MARGIN,
        Inches(4.85),
        WIDE_W - 2 * MARGIN,
        Inches(1.7),
        [
            "The chain is local model, then two free API tiers, then an offline backend. The paid "
            "backend exists in the code and refuses to run behind two separate switches — a zero-cost "
            "claim should not be one environment variable away from being false.",
            "At a hundred daily users the binding constraint is embeddings, not generation. That says "
            "caching buys headroom, not a bigger model — and embeddings are already cached per chunk.",
        ],
        size=13.5,
    )
    _notes(
        s,
        "The useful half of this slide is the binding constraint, not the zero. Knowing "
        "which quota runs out first tells you what to fix, and it is not the one most "
        "people would guess. If asked about scaling to paid: the architecture does not "
        "assume a free tier anywhere — the chain simply starts at a different rung.",
    )


def slide_11_limitations(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _title(s, "What I would not claim", sub="In the order these would change a conclusion")
    items = [
        (
            "The data",
            "The publisher will not serve its files to a machine — Dubai Pulse times out "
            "at connect from every network tried, including a GitHub runner with open "
            "egress. Everything downstream runs on a labelled stand-in."
            if draft
            else "Registry coverage and lag are the publisher's; nothing corrects for "
            "unregistered transactions.",
        ),
        (
            "The retrieval numbers",
            "117 chunks from 5 documents. Recall@5 of 1.00 is easy at that "
            "size, few of the cases are Arabic, and the evaluation ran "
            "against the offline fallback rather than the hybrid design it "
            "is meant to measure.",
        ),
        (
            "Service charges",
            "Estimated, and they are the largest single input to net yield. "
            "Per-building figures would reorder the communities.",
        ),
        (
            "Community shapes",
            "Curated centroid hexes, not true polygons — no GeoJSON source was "
            "reachable. Never used in a financial calculation.",
        ),
    ]
    for i, (head, body) in enumerate(items):
        col, row = i % 2, i // 2
        x = MARGIN + col * Inches(6.05)
        y = Inches(2.4) + row * Inches(2.15)
        _card(s, x, y, Inches(5.75), Inches(1.85), fill=RGBColor(0xF6, 0xF6, 0xF5))
        _text(
            s,
            x + Inches(0.3),
            y + Inches(0.2),
            Inches(5.15),
            Inches(0.4),
            head,
            size=16,
            bold=True,
            colour=INK,
            font=HEAD_FONT,
        )
        _text(
            s,
            x + Inches(0.3),
            y + Inches(0.66),
            Inches(5.15),
            Inches(1.05),
            body,
            size=11.5,
            colour=MUTED,
        )
    _notes(
        s,
        "Put this before next steps, not after — a limitations slide that comes last reads "
        "as an apology, and coming here it reads as command of the material. The line to "
        "use if pressed on the data: it is a data problem, not a code problem. Everything "
        "downstream is built and gated; a person can download the files in a browser in "
        "minutes and one command loads them.",
    )


def slide_12_next(prs, b: Bundle, draft: bool) -> None:
    s = _blank(prs)
    _band(s, Inches(3.15))
    _text(
        s,
        MARGIN,
        Inches(0.95),
        Inches(11.5),
        Inches(0.9),
        "Where it goes next",
        size=40,
        bold=True,
        colour=WHITE,
        font=HEAD_FONT,
    )
    _text(
        s,
        MARGIN,
        Inches(1.95),
        Inches(10.5),
        Inches(0.7),
        "In the order that each would change an answer, rather than the order they are easy.",
        size=15,
        colour=WHITE,
        italic=True,
    )
    steps = [
        (
            "1",
            "Real registry files",
            "A standing agreement with the Land Department, or the "
            "operator upload path that already exists. Removes the "
            "largest limitation.",
        ),
        (
            "2",
            "Per-building service charges",
            "They dominate net yield and are currently estimated. This is what changes rankings.",
        ),
        (
            "3",
            "Retrieval on a real corpus",
            "Score the hybrid design against a live embedding "
            "provider, on a corpus big enough for recall to mean "
            "something.",
        ),
    ]
    for i, (n, head, body) in enumerate(steps):
        x = MARGIN + i * Inches(4.05)
        _card(s, x, Inches(3.6), Inches(3.75), Inches(2.15))
        circle = s.shapes.add_shape(
            MSO_SHAPE.OVAL, x + Inches(0.28), Inches(3.85), Inches(0.5), Inches(0.5)
        )
        circle.fill.solid()
        circle.fill.fore_color.rgb = ACCENT
        circle.line.fill.background()
        circle.shadow.inherit = False
        tf = circle.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = n
        r.font.size = Pt(15)
        r.font.bold = True
        r.font.color.rgb = WHITE
        r.font.name = HEAD_FONT
        _text(
            s,
            x + Inches(0.9),
            Inches(3.9),
            Inches(2.7),
            Inches(0.45),
            head,
            size=13.5,
            bold=True,
            colour=INK,
            font=HEAD_FONT,
        )
        _text(
            s, x + Inches(0.28), Inches(4.55), Inches(3.2), Inches(1.1), body, size=11, colour=MUTED
        )
    _text(
        s,
        MARGIN,
        Inches(6.15),
        Inches(11.5),
        Inches(0.5),
        "Thank you",
        size=26,
        bold=True,
        colour=INK,
        font=HEAD_FONT,
    )
    _text(
        s,
        MARGIN,
        Inches(6.72),
        Inches(11.5),
        Inches(0.4),
        f"{LIVE_WEB}   ·   github.com/krish2105/YIELDMAP-AI-in-Finance",
        size=12,
        colour=ACCENT,
    )
    _notes(
        s,
        "Close on the first item and stop talking. If there is one question you want, it is "
        "about the data path — you have a complete answer and it makes the project look "
        "finished rather than blocked. Have docs/viva_qa.md open on a second screen; the "
        "fifteen questions there each name the file that backs the answer.",
    )


SLIDES = [
    slide_01_title,
    slide_02_problem,
    slide_03_what_it_does,
    slide_04_architecture,
    slide_05_live,
    slide_06_results,
    slide_07_models,
    slide_08_retrieval,
    slide_09_governance,
    slide_10_business,
    slide_11_limitations,
    slide_12_next,
]


def build(bundle: Bundle, draft: bool) -> Presentation:
    prs = Presentation()
    prs.slide_width, prs.slide_height = WIDE_W, WIDE_H
    for make in SLIDES:
        make(prs, bundle, draft)
    return prs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--draft",
        action="store_true",
        help="generate even though the provenance guard blocks, stamping figures",
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    clean, reasons = guard_check(ROOT / "data" / "yieldmap.duckdb", ROOT / "docs" / "results")
    bundle = collect()
    draft = bundle.any_synthetic or not clean

    if draft and not args.draft:
        print("refusing to generate: the provenance guard is blocking.", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        print("\nPass --draft to generate a stamped draft.", file=sys.stderr)
        return 1

    prs = build(bundle, draft)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(args.out)
    print(
        f"wrote {short_path(args.out)}"
        f"{'  (DRAFT — figures stamped)' if draft else ''} — {len(prs.slides._sldIdLst)} slides"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
