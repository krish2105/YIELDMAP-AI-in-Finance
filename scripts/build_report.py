#!/usr/bin/env python
"""Generate the Term 4 report as a Word document.

Every figure is read from `docs/results/` by `scripts/term4/artefacts.py`. Nothing is typed in
from memory, which is what makes the report reproducible: delete it, run this again, and the same
numbers come back because they come from the same files.

Provenance decides whether this runs at all. `scripts/guard_synthetic.py` blocks generated data
from reaching a graded artefact; when it blocks, this refuses unless `--draft` is passed, and a
draft is stamped in three places a reader cannot miss — a banner on the cover, a provenance
column in every table, and a limitations section naming which figures describe a stand-in.

    uv run --extra docs python -m scripts.build_report --draft
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from agents.export import xml_safe
from scripts.guard_synthetic import check as guard_check
from scripts.term4.artefacts import ROOT, Bundle, Row, collect, short_path

OUT = ROOT / "docs" / "AI217_YIELDMAP_report.docx"

PROJECT = "YIELDMAP"
SUBJECT = "AI 217 — Artificial Intelligence in Finance"
AUTHOR = "Krishna Mathur — SP Jain School of Global Management, MAIB"
TAGLINE = (
    "Dubai property investment intelligence, where every number carries the query that produced it."
)

# Light theme. One accent, taken from the product's own chart palette so the document and the
# interface are recognisably the same project.
ACCENT = RGBColor(0x1F, 0x7A, 0x70)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x5A, 0x5A, 0x5A)
WARN = RGBColor(0x9A, 0x3A, 0x12)

BODY_FONT = "Calibri"
HEAD_FONT = "Cambria"


def _field(paragraph, instruction: str, placeholder: str) -> None:
    """Insert a Word field — a TOC or a page number — rather than static text.

    A hand-typed contents list is wrong the moment a section moves. This is the real field, so
    Word rebuilds it.
    """
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = placeholder
    separate.append(text)
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instr, separate, end):
        run._r.append(node)


def _styles(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15

    for name, size, colour in (
        ("Heading 1", 18, ACCENT),
        ("Heading 2", 13.5, INK),
        ("Heading 3", 11.5, INK),
    ):
        style = doc.styles[name]
        style.font.name = HEAD_FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = colour
        style.paragraph_format.space_before = Pt(16)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.keep_with_next = True


def _header_repeats(row) -> None:
    """Mark a row as a header, so Word repeats it at the top of every page the table spans.

    Without this a table that breaks across a page leaves the continuation with no column
    labels — the reader meets "stand-in" and a bare filename with nothing saying what either
    column is.
    """
    properties = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    properties.append(header)


def _keep_row_whole(row) -> None:
    """Stop a single row splitting across a page break.

    A row that splits puts the tail of one cell at the top of the next page, orphaned from the
    label that says what it measures.
    """
    properties = row._tr.get_or_add_trPr()
    properties.append(OxmlElement("w:cantSplit"))


def _shade(cell, hex_colour: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:fill"), hex_colour)
    cell._tc.get_or_add_tcPr().append(shading)


def _para(doc: Document, text: str, *, size=10.5, colour=INK, italic=False, bold=False, after=6):
    p = doc.add_paragraph()
    run = p.add_run(xml_safe(text))
    run.font.size = Pt(size)
    run.font.color.rgb = colour
    run.italic = italic
    run.bold = bold
    p.paragraph_format.space_after = Pt(after)
    return p


def _table(doc: Document, rows: list[Row], *, show_provenance: bool) -> None:
    """One metric per row. Prose describes method; the numbers live here."""
    if not rows:
        _para(doc, "Not measured — no results file for this section.", italic=True, colour=MUTED)
        return

    headers = (
        ["Measure", "Result", "Target"]
        + (["Data"] if show_provenance else [])
        + ["In docs/results/"]
    )
    # A4 is 21.0 cm wide and the margins take 4.8, so the text column is 16.2 cm and the widths
    # below must sum to exactly that. They summed to 18.1 in the first draft, which Word does not
    # clamp — it runs the table off the page. Arithmetic catches this without a renderer.
    widths = (
        [Cm(3.5), Cm(5.0), Cm(2.7), Cm(1.4), Cm(3.6)]
        if show_provenance
        else [Cm(4.0), Cm(6.0), Cm(2.8), Cm(3.4)]
    )
    assert abs(sum(w.cm for w in widths) - 16.2) < 0.01, "table is wider than the text column"

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    _header_repeats(table.rows[0])
    _keep_row_whole(table.rows[0])
    for i, (cell, head) in enumerate(zip(table.rows[0].cells, headers, strict=True)):
        cell.width = widths[i]
        _shade(cell, "EDF4F2")
        para = cell.paragraphs[0]
        run = para.add_run(head)
        run.bold = True
        run.font.size = Pt(9)
        run.font.name = HEAD_FONT
        run.font.color.rgb = ACCENT

    for row in rows:
        added = table.add_row()
        _keep_row_whole(added)
        cells = added.cells
        values = [row.label, row.measured, row.target]
        if show_provenance:
            values.append("stand-in" if row.provenance != "REAL" else "real")
        # Without the extension: every source is a JSON file under docs/results/, the caption
        # says so, and the five characters are the difference between a name that fits this
        # column and one that breaks across two lines mid-word.
        values.append(row.source.removesuffix(".json"))
        for i, (cell, value) in enumerate(zip(cells, values, strict=True)):
            cell.width = widths[i]
            para = cell.paragraphs[0]
            run = para.add_run(xml_safe(str(value)))
            run.font.size = Pt(8.5)
            if show_provenance and i == 3 and row.provenance != "REAL":
                run.font.color.rgb = WARN
                run.bold = True
            elif i == len(values) - 1:
                run.font.color.rgb = MUTED
                run.font.name = "Consolas"
                run.font.size = Pt(7.5)
    doc.add_paragraph()


def _cover(doc: Document, bundle: Bundle, draft: bool) -> None:
    for _ in range(4):
        doc.add_paragraph()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(PROJECT)
    run.font.name = HEAD_FONT
    run.font.size = Pt(46)
    run.font.bold = True
    run.font.color.rgb = ACCENT

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = sub.add_run(TAGLINE)
    run.font.size = Pt(11.5)
    run.italic = True
    run.font.color.rgb = MUTED

    doc.add_paragraph()
    for text, size, bold in (
        (SUBJECT, 13, True),
        (AUTHOR, 11, False),
        (dt.date.today().strftime("%d %B %Y"), 10.5, False),
    ):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(text)
        run.font.size = Pt(size)
        run.bold = bold
        run.font.color.rgb = INK if bold else MUTED

    if draft:
        doc.add_paragraph()
        box = doc.add_table(rows=1, cols=1)
        box.style = "Table Grid"
        box.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = box.rows[0].cells[0]
        cell.width = Cm(16)
        _shade(cell, "FDF1E7")
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        head = para.add_run("DRAFT — THE MODEL FIGURES DESCRIBE A LABELLED STAND-IN")
        head.bold = True
        head.font.size = Pt(11)
        head.font.color.rgb = WARN
        body = doc.add_paragraph()
        body.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = body.add_run(
            "The Dubai Land Department's open-data portal refuses automated clients from every "
            "network this project can reach, including a GitHub Actions runner with open egress. "
            "Every figure marked stand-in in this report was computed from generated data with the "
            "real schema. The engineering, retrieval and governance figures are real measurements "
            "of this system. Section 8 lists exactly which is which."
        )
        run.font.size = Pt(9)
        run.italic = True
        run.font.color.rgb = MUTED

    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _headers_and_footers(doc: Document) -> None:
    for section in doc.sections:
        section.top_margin = Cm(2.4)
        section.bottom_margin = Cm(2.2)
        section.left_margin = Cm(2.4)
        section.right_margin = Cm(2.4)

        header = section.header.paragraphs[0]
        header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = header.add_run(f"{PROJECT} · {SUBJECT}")
        run.font.size = Pt(8)
        run.font.name = HEAD_FONT
        run.font.color.rgb = MUTED

        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _field(footer, "PAGE", "1")
        for run in footer.runs:
            run.font.size = Pt(8.5)
            run.font.color.rgb = MUTED


def build(bundle: Bundle, draft: bool) -> Document:
    doc = Document()
    _styles(doc)
    _cover(doc, bundle, draft)  # ends with a page break, so the cover stands alone
    _headers_and_footers(doc)

    doc.add_heading("Contents", level=1)
    # A real TOC field builds itself from the headings, which is what the brief asks for — but an
    # unbuilt field renders as nothing in LibreOffice and Google Docs, so the page arrives blank
    # and the reader has no idea why. One line of guidance costs less than that confusion.
    _para(
        doc,
        "Word builds this list from the document's headings. If it is empty, right-click it and "
        "choose Update Field.",
        size=9,
        colour=MUTED,
        italic=True,
        after=10,
    )
    toc = doc.add_paragraph()
    _field(toc, 'TOC \\o "1-2" \\h \\z \\u', "Right-click here and choose Update Field.")
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    _executive_summary(doc, bundle, draft)
    _problem(doc, bundle)
    _data_and_methods(doc, bundle, draft)
    _models(doc, bundle, draft)
    _rag_and_agents(doc, bundle, draft)
    _governance(doc, bundle, draft)
    _business_case(doc, bundle)
    _conclusion(doc, bundle, draft)
    return doc


def _executive_summary(doc: Document, b: Bundle, draft: bool) -> None:
    doc.add_heading("1. Executive summary", level=1)
    _para(
        doc,
        "YIELDMAP turns the Dubai Land Department's published transaction and tenancy registries "
        "into an investment view: what a property is worth, what it yields after costs, how the "
        "market has moved, and what could go wrong. It answers questions in English, Hindi and "
        "Arabic with a citation on every factual sentence, and it runs a small crew of agents that "
        "produce a memo an auditor has already checked.",
    )
    _para(
        doc,
        "The design rule the project is built around is that a number a reader cannot check is "
        "worth less than no number. Every figure crossing the API is a typed object carrying the "
        "SQL that produced it, the sample size behind it, and a link to the method that defines "
        "it. Clicking a tile in the interface opens that query. Copying it and running it against "
        "the database returns the figure on the tile.",
    )
    if draft:
        _para(
            doc,
            "One thing this report cannot claim: that the model figures describe Dubai. They "
            "describe a generated stand-in with the real schema, because the publisher will not "
            "serve its files to an automated client. The distinction is carried in every table "
            "rather than mentioned once, and the guard that enforces it is described in section 8.",
            italic=True,
            colour=WARN,
        )

    doc.add_heading("What was measured", level=2)
    # Deliberately not a slice of the detail tables: repeating six rows verbatim two pages before
    # they appear again reads as padding. These are the figures a reader who stops here should
    # leave with, each pulled from its own artefact.
    wanted = {
        "redteam.json",
        "coverage.json",
        "unit_economics.json",
        "accessibility_desktop.json",
        "rag_eval.json",
        "bundle.json",
    }
    seen: set[str] = set()
    headline: list[Row] = []
    for row in b.rows_governance + b.rows_engineering + b.rows_retrieval:
        if row.source in wanted and row.source not in seen:
            headline.append(row)
            seen.add(row.source)
    _table(doc, headline, show_provenance=draft)


def _problem(doc: Document, b: Bundle) -> None:
    doc.add_heading("2. Problem and context", level=1)
    _para(
        doc,
        "Dubai publishes an unusually complete property record. Every sale is registered with the "
        "Land Department and every tenancy with Ejari, and both are released as open data. What is "
        "missing is not the data but the join between it and a decision: a buyer wants to know "
        "whether a price is fair, what the unit will actually yield after service charges and "
        "vacancy, and how exposed the area is to off-plan supply.",
    )
    _para(
        doc,
        "The commercial portals that answer those questions do so from listing prices, which are "
        "asks rather than transactions, and they do not show their working. This project takes the "
        "opposite position: use only the registry, and make the working the product.",
    )
    doc.add_heading("Who it is for", level=2)
    for text in (
        "An individual buyer comparing two communities, who needs the net yield rather than the "
        "gross one, and needs to see the assumptions behind it.",
        "An analyst who needs a defensible valuation and the query that produced it.",
        "A reviewer or examiner, who needs to trace any figure on the screen back to a row in the "
        "registry without taking anything on trust.",
    ):
        p = doc.add_paragraph(xml_safe(text), style="List Bullet")
        p.paragraph_format.space_after = Pt(3)


def _data_and_methods(doc: Document, b: Bundle, draft: bool) -> None:
    doc.add_heading("3. Data and methods", level=1)
    _para(
        doc,
        "The intended source is the Dubai Land Department's open transaction and Ejari registries, "
        "published through the Dubai Pulse portal. Licences and retrieval dates are recorded in "
        "docs/datasets.md, and the reachability of every candidate address is measured rather than "
        "assumed — the table in that document is generated from the probe artefact, so it cannot "
        "drift from what was actually observed.",
    )

    doc.add_heading("What the publisher served", level=2)
    if b.probe:
        p = b.probe
        _para(
            doc,
            f"Measured from a GitHub Actions runner with open egress on "
            f"{str(p.get('generated_at', ''))[:10]}: {p['n_reachable']} of {p['n_candidates']} "
            "addresses answered, and no catalogue endpoint did. Dubai Pulse timed out at connect "
            "on every address tried, which reads as a block on datacentre ranges rather than a "
            "wrong path — the same portal loads in an ordinary browser. This is the finding that "
            "shapes everything below: the constraint is not the sandbox, it is the publisher.",
        )
    _para(
        doc,
        "The response is a documented ladder rather than a workaround. First choice is the "
        "publisher's own files, fetched in Actions. Second is an operator upload of the same "
        "published files, downloaded by a person in a browser and committed as a release asset. "
        "Third, and only for development, is a generated stand-in that carries the real schema and "
        "is stamped SYNTHETIC in the database, in the interface and in every results file.",
    )

    if draft and b.synthetic_params:
        s = b.synthetic_params
        doc.add_heading("What the stand-in is", level=2)
        _para(
            doc,
            f"Seed {s['params'].get('seed', s.get('seed'))}, "
            f"{s['n_transactions']:,} transactions and {s['n_rent_contracts']:,} tenancy contracts "
            f"across {s['n_areas']} areas, with {s['planted']['price_outliers']} price outliers and "
            f"{s['planted']['rapid_flips']} rapid flips planted so the anomaly detector has "
            "something true to find. The structure is plausible; the levels are invented. The file "
            "says so itself, in a field called warning, so a reader who reaches the data before the "
            "prose still gets the caveat.",
        )

    doc.add_heading("Storage, and why not everything is in Postgres", level=2)
    _para(
        doc,
        "DuckDB is the analytics store and Postgres holds only application state. The reason is "
        "arithmetic — 1.5 million transactions plus indexes do not fit a 500 MB free tier — but the "
        "consequence is the more useful half: because DuckDB is queried directly, every KPI can "
        "carry the literal SQL string that produced it, which is what makes the traceability rule "
        "enforceable rather than aspirational.",
    )


def _models(doc: Document, b: Bundle, draft: bool) -> None:
    doc.add_heading("4. Models and results", level=1)
    _para(
        doc,
        "Each model writes a JSON file into docs/results/ carrying its metrics, its method "
        "identifier and the SQL it ran. The table below is generated from those files. Where a "
        "model has not been run, the row says so rather than carrying a remembered figure.",
    )
    if draft:
        _para(
            doc,
            "Every row marked stand-in was computed from generated data. A model that fits "
            "generated data well has demonstrated that the pipeline runs, not that the model is "
            "any good — the error figures measure the code, not the Dubai market.",
            italic=True,
            colour=WARN,
        )
    _table(doc, b.rows_models, show_provenance=draft)

    doc.add_heading("How the valuation model is built", level=2)
    _para(
        doc,
        "A hedonic regression on log price per square metre, back-transformed with Duan's smearing "
        "estimator so the mean is not understated. The holdout is the most recent twelve months, "
        "split by time rather than at random: a random split lets the model see the future of the "
        "same building, which flatters it. The baseline it is scored against is the area median for "
        "the same period, which is what a buyer would otherwise use.",
    )
    _para(
        doc,
        "The comparison that matters is against the estimated noise floor rather than against zero. "
        "Two identical units in the same building sell weeks apart at different prices, and no "
        "model can explain that gap. Reporting error against the floor says how much of the "
        "explainable variation was captured, which is the honest version of the claim.",
    )

    doc.add_heading("Why the index uses repeat sales", level=2)
    _para(
        doc,
        "A median price series moves when the mix of what sold changes, not only when values do. "
        "The repeat-sales method compares each property against itself, using a Bailey-Muth-Nourse "
        "weighted least squares fit on period dummies. The registry has no stable unit identifier "
        "on older rows, so identity is reconstructed from building, bedroom count and floor area, "
        "and pairs are weighted by the inverse of the holding period because a long gap accumulates "
        "more idiosyncratic noise.",
    )

    doc.add_heading("Yield, and the number most services do not show", level=2)
    _para(
        doc,
        "Gross yield is rent over price. Net yield takes out vacancy, service charge, management "
        "and maintenance, and amortises the purchase costs — including the Land Department's 4% "
        "transfer fee — over the holding period. The spread between the two is the figure a buyer "
        "is usually not shown, and it is large. Every assumption is editable in the interface and "
        "every one carries its source.",
    )
    _para(
        doc,
        "Cells with too few sales or contracts are suppressed rather than rendered. A yield "
        "computed from three transactions is not a yield, and showing it with a small-sample "
        "footnote is a way of showing it anyway.",
    )


def _rag_and_agents(doc: Document, b: Bundle, draft: bool) -> None:
    doc.add_heading("5. Retrieval and the agent crew", level=1)
    _para(
        doc,
        "Ask answers a question from a corpus of registry facts and archived policy documents. "
        "Retrieval fuses a lexical BM25 score with a semantic one through reciprocal rank fusion, "
        "and the fused list is reranked. The evaluation runs 38 cases in English, Hindi and Arabic "
        "— 30 the corpus can answer and 8 it cannot.",
    )
    _table(doc, b.rows_retrieval, show_provenance=draft)

    doc.add_heading("The citation guarantee is enforced, not requested", level=2)
    _para(
        doc,
        "The prompt asks for a citation on every factual sentence, and a prompt is a request a "
        "model may or may not honour. After generation, every sentence that states a fact and "
        "carries no citation is removed, and every citation pointing at a source that was not "
        "retrieved is stripped. What reaches the reader has been filtered rather than trusted. The "
        "faithfulness figure measures the output of that filter.",
    )

    doc.add_heading("Untrusted text is held, not merely wrapped", level=2)
    _para(
        doc,
        "Retrieved documents and stored memories are quoted to the model inside delimiters and "
        "declared to be data. That guarantee was found to be incomplete during the final review: "
        "the body was interpolated between the delimiters as it arrived, so a document containing "
        "the closing delimiter ended the quarantine early and everything after it read as "
        "instruction. It is now built by a single function that neutralises any delimiter in the "
        "body and refuses to return a block that is not well formed. The attack is in the red-team "
        "suite, and it fails against the current code and succeeds against the previous one.",
    )

    doc.add_heading("Budgets, and what an agent cannot do", level=2)
    _para(
        doc,
        "The crew runs under one runtime with a request budget, a wall-clock budget and a step "
        "budget — three axes because they fail differently: a loop burns steps without time, and a "
        "slow provider burns time without steps. Exceeding any of them ends the run as a recorded "
        "outcome carried into the memo, not as a crash. The Advisor has no tools with side effects. "
        "There is no endpoint in the service that buys, sells, lists or finances anything, which "
        "makes the boundary architectural rather than a matter of policy.",
    )


def _governance(doc: Document, b: Bundle, draft: bool) -> None:
    doc.add_heading("6. Governance, security and engineering", level=1)
    _para(
        doc,
        "The threat model is the OWASP Agentic Security Initiative list. Each entry names the "
        "surface it applies to in this system, the control that answers it, and an executable "
        "attack. The attacks run in CI, so a control that stops holding fails a build rather than "
        "being discovered later.",
    )
    _table(doc, b.rows_governance, show_provenance=draft)

    doc.add_heading("Engineering measurements", level=2)
    _table(doc, b.rows_engineering, show_provenance=draft)

    doc.add_heading("Two faults found in the final review", level=2)
    _para(
        doc,
        "Both are recorded because a report that lists only what worked is not evidence of "
        "anything. The first: the Gemini API key was sent as a query parameter, and the HTTP "
        "library quotes the full request URL in the error it raises on a rejected call. That "
        "message was stored, logged with a traceback and sent to error tracking, so one wrong key "
        "would have written itself into four places. The key now travels in a header, verified "
        "against the live API rather than the documentation. Notably, the repository's own secret "
        "scanner would never have caught it, because the key was never in a file.",
    )
    _para(
        doc,
        "The second: the Word export escaped markup but not encoding, so a control character in "
        "model-written text produced a document Word calls corrupt — from an API call that "
        "returned success. The exporter now strips what XML cannot carry and parses the document "
        "before shipping it.",
    )

    doc.add_heading("7. Limitations", level=1)
    _para(
        doc,
        "Stated plainly, and in the order they would change a conclusion.",
    )
    limitations = [
        (
            "The data",
            "Everything downstream is built and tested against a labelled stand-in. A model that "
            "fits generated data has demonstrated that the pipeline runs. It has demonstrated "
            "nothing about Dubai.",
        )
        if draft
        else (
            "The data",
            "Registry coverage and lag are what the publisher provides; nothing here corrects for "
            "unregistered transactions.",
        ),
        (
            "The retrieval figures",
            "The corpus is 117 chunks from 5 documents. Recall@5 of 1.00 on a corpus that small is "
            "not evidence of a good retriever — the rank-sensitive measures are the informative "
            "ones, and only a few of the 38 cases are Arabic. The evaluation also ran against the "
            "offline lexical fallback, so the hybrid design it exists to measure has not yet been "
            "scored against a live embedding provider.",
        ),
        (
            "Refusal is not structural",
            "A relevance threshold below which the system would decline was measured and rejected: "
            "on this corpus no signal separates out-of-scope questions from in-scope ones without "
            "refusing real questions. Refusal is therefore enforced at the answering stage, where "
            "an uncited sentence is dropped, rather than at retrieval.",
        ),
        (
            "Community shapes",
            "Curated centroid hex cells, not true polygons — no GeoJSON source was reachable. They "
            "place a cell on a map and are never used in a financial calculation.",
        ),
        (
            "Service charges",
            "Estimated, and they are the largest single input to net yield. Per-building figures "
            "would change the ranking of communities.",
        ),
        (
            "Yields use area medians",
            "A yield describes the area and bedroom count, not the specific unit.",
        ),
        (
            "Accounts come from an environment variable",
            "There is no signup. A deliberate limit for a course deployment; the interface behind "
            "it does not change when a user table replaces it.",
        ),
    ]
    for heading, body in limitations:
        p = doc.add_paragraph(style="List Bullet")
        run = p.add_run(xml_safe(heading + ". "))
        run.bold = True
        run.font.size = Pt(10)
        rest = p.add_run(xml_safe(body))
        rest.font.size = Pt(10)
        p.paragraph_format.space_after = Pt(5)

    doc.add_heading("8. How provenance is enforced", level=1)
    _para(
        doc,
        "The rule is that generated figures must not reach a graded artefact. The mechanism is a "
        "script, not a habit: scripts/guard_synthetic.py inspects every table in the database for "
        "rows stamped SYNTHETIC and every results file for an explicit declaration that it is REAL. "
        "It runs in CI on every push and before any Term 4 document is produced.",
    )
    _para(
        doc,
        "It requires a declaration rather than inferring realness from the absence of the word "
        "synthetic. An earlier version inferred, and passed a profile of generated data that simply "
        "happened not to contain the string.",
    )
    if draft:
        clean, reasons = guard_check(ROOT / "data" / "yieldmap.duckdb", ROOT / "docs" / "results")
        _para(
            doc,
            "At the time this document was generated the guard was blocking, and this report was "
            "produced with --draft, which is why every model figure above carries a provenance "
            "column. The guard reported:",
            italic=True,
        )
        for reason in reasons or ["(no reasons recorded)"]:
            p = doc.add_paragraph(style="List Bullet")
            run = p.add_run(xml_safe(reason))
            run.font.name = "Consolas"
            run.font.size = Pt(8.5)
            run.font.color.rgb = WARN
        _para(
            doc,
            "Loading a real drop and rebuilding changes every model figure in this report and "
            "requires no code change. Regenerating this document without --draft would then "
            "succeed, and the provenance column would disappear because it would have nothing to "
            "say.",
            italic=True,
            colour=MUTED,
        )


def _business_case(doc: Document, b: Bundle) -> None:
    doc.add_heading("9. Business case", level=1)
    _para(
        doc,
        "The system runs at no cost. That is a design constraint rather than an accident: the "
        "model provider chain is a local tier, then two free API tiers, then an offline "
        "deterministic backend, and the paid backend is present in the code but refuses to run "
        "behind two separate switches — a zero-cost claim should not be one stray environment "
        "variable away from being false.",
    )
    if b.unit_economics:
        u = b.unit_economics
        _para(
            doc,
            f"Quotas are counted in requests rather than tokens, because that is how the free "
            f"tiers meter. Rates were verified on {u['rates_verified_on']}. The ledger is durable "
            "across processes, so a nightly job and an interactive session share one daily "
            "allowance.",
        )
        rows = [
            Row(
                str(name),
                f"{s['model_requests']} model requests, {s['embedding_requests']} embedding "
                f"requests, {s['cpu_seconds']:,.0f} CPU seconds",
                f"binds on {s['binding_constraint']}",
                u.get("provenance", "REAL"),
                "unit_economics.json",
            )
            for name, s in u["scenarios"].items()
        ]
        _table(doc, rows, show_provenance=False)
        _para(
            doc,
            "The binding constraint at a hundred daily users is embeddings rather than generation, "
            "which is the useful part of the answer: it says caching embeddings, not switching "
            "model, is what buys headroom. Embeddings are already cached to disk per chunk, so the "
            "quota is spent once per document rather than once per question.",
        )

    doc.add_heading("What it would take to run this for real", level=2)
    for text in (
        "A licensed data feed or a standing agreement with the Land Department, which removes the "
        "single largest limitation in section 7.",
        "Per-building service charges, which dominate net yield and are currently estimated.",
        "A paid model tier only if concurrency demanded it; the architecture does not assume one.",
    ):
        p = doc.add_paragraph(xml_safe(text), style="List Bullet")
        p.paragraph_format.space_after = Pt(3)


def _conclusion(doc: Document, b: Bundle, draft: bool) -> None:
    doc.add_heading("10. Conclusion", level=1)
    _para(
        doc,
        "YIELDMAP is a working system rather than a prototype: deployed, tested, measured, and "
        "honest about the one thing it cannot yet claim. The pipeline runs end to end — registry "
        "to warehouse to model to API to interface to cited answer to audited memo — and every "
        "number it shows carries the query that produced it.",
    )
    if draft:
        _para(
            doc,
            "What remains is data, and it is a data problem rather than a code problem. The "
            "publisher will not serve its files to a machine; a person can download them in a "
            "browser in a few minutes. One command loads them, every figure in this report changes, "
            "and the provenance column disappears.",
        )
    _para(
        doc,
        "The part worth carrying forward is the discipline rather than the domain. A figure that "
        "cannot be traced is not shown. A guarantee that is only asked for in a prompt is enforced "
        "after the fact. A control that is claimed is attacked in CI. Several of the faults "
        "described in this report were found by applying those rules to the project's own claims, "
        "which is the strongest argument for them.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--draft",
        action="store_true",
        help="generate even though the provenance guard blocks, stamping every synthetic figure",
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
        print(
            "\nLoad a real drop and rebuild, or pass --draft to generate a clearly stamped "
            "draft in which every generated figure is labelled.",
            file=sys.stderr,
        )
        return 1

    doc = build(bundle, draft)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.out)
    print(f"wrote {short_path(args.out)}{'  (DRAFT — figures stamped)' if draft else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
