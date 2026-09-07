"""Export a memo as Markdown, HTML or a Word document.

The export carries the same guarantees as the page: the citations travel with it, the provenance
warning travels with it, and the advice notice travels with it. A memo that loses its caveats on
the way out of the application is worse than one that was never exported, because it looks
authoritative and is no longer checkable.
"""

from __future__ import annotations

import html
import re
from typing import Any

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^[-*]\s+(.*)$")
EMPHASIS = re.compile(r"\*([^*]+)\*")

NOTICE = (
    "Information, not advice. Every figure comes from published Dubai Land Department data by way "
    "of a recorded query. YIELDMAP cannot carry out any transaction."
)


def _blocks(markdown: str) -> list[tuple[str, str]]:
    """Flatten the memo into (kind, text) blocks the writers can render."""
    out: list[tuple[str, str]] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        if match := HEADING.match(line):
            out.append((f"h{len(match.group(1))}", match.group(2).strip()))
        elif match := BULLET.match(line.strip()):
            out.append(("li", match.group(1).strip()))
        else:
            out.append(("p", line.strip()))
    return out


def to_markdown(memo: dict[str, Any]) -> str:
    """The memo with its citations and caveats appended."""
    parts = [memo.get("memo_md") or "*This memo was withheld by the audit.*", ""]

    if memo.get("provenance") == "SYNTHETIC":
        parts += [
            "> **These figures come from generated data, not the Dubai registry.** They exist to "
            "exercise the pipeline and must not be cited as facts about Dubai.",
            "",
        ]

    if memo.get("citations"):
        parts += ["## Sources", ""]
        for citation in memo["citations"]:
            records = f", {citation['n_records']:,} records" if citation.get("n_records") else ""
            parts.append(
                f"{citation['n']}. {citation['title']} — {citation.get('source', 'unknown')}"
                f" (established by {citation.get('agent', 'the crew')}{records})"
            )
        parts.append("")

    audit = memo.get("audit") or {}
    if audit.get("findings"):
        parts += ["## Audit", ""]
        for finding in audit["findings"]:
            parts.append(f"- **{finding['severity']}** {finding['rule']}: {finding['detail']}")
        parts.append("")

    parts += ["---", "", f"*{NOTICE}*"]
    return "\n".join(parts)


# Two different reasons, worth keeping apart.
#
# Forbidden: XML 1.0 allows tab, newline, carriage return and everything from 0x20 up, so the rest
# of the C0 range cannot appear at all, and a lone surrogate is not a character. html.escape does
# not know that — it handles markup, not encoding — so a model emitting one stray byte produces a
# .docx that Word rejects as corrupt, from an API call that returned 200.
#
# Merely discouraged: 0x7f-0x9f are legal in XML 1.0 and flagged as compatibility characters. They
# are stripped too, because they are C1 control codes rather than text, but a document containing
# one would have opened.
_XML_FORBIDDEN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f\ud800-\udfff\ufffe\uffff]"
)


def xml_safe(text: str) -> str:
    """Drop the characters XML cannot carry, so a stray byte cannot corrupt a document."""
    return _XML_FORBIDDEN.sub("", text)


def to_html(memo: dict[str, Any]) -> str:
    """A self-contained HTML document, for printing or emailing."""
    title = f"YIELDMAP memo — {html.escape(str(memo.get('area_key', 'area')))}"
    body: list[str] = []
    in_list = False

    for kind, text in _blocks(to_markdown(memo)):
        escaped = EMPHASIS.sub(r"<em>\1</em>", html.escape(text))
        if kind == "li":
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{escaped}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        body.append(f"<{kind}>{escaped}</{kind}>" if kind.startswith("h") else f"<p>{escaped}</p>")
    if in_list:
        body.append("</ul>")

    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        f'<meta charset="utf-8">\n<title>{title}</title>\n'
        "<style>"
        "body{font-family:Georgia,serif;max-width:44rem;margin:3rem auto;padding:0 1.5rem;"
        "line-height:1.6;color:#222}"
        "h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:2rem;color:#1f7a70}"
        "li{margin:.3rem 0}"
        "</style>\n</head>\n<body>\n" + "\n".join(body) + "\n</body>\n</html>\n"
    )


def to_docx(memo: dict[str, Any]) -> bytes:
    """A Word document.

    Written with the standard library's zipfile rather than a dependency: a .docx is a zip of a
    handful of XML parts, and the memo's structure is simple enough that generating it directly is
    less code than wiring up a document library, with nothing to keep up to date.
    """
    import io
    import zipfile
    from xml.etree import ElementTree

    def esc(text: str) -> str:
        # quote=False is right here: this only ever lands in element text, never an attribute.
        # xml_safe is not optional — html.escape handles & < > and leaves the control characters
        # XML forbids, which do not fail loudly. They produce a .docx that Word calls corrupt.
        return html.escape(xml_safe(text), quote=False)

    paragraphs: list[str] = []
    for kind, text in _blocks(to_markdown(memo)):
        content = esc(text)
        if kind.startswith("h"):
            level = min(int(kind[1:]), 3)
            paragraphs.append(
                f'<w:p><w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
                f'<w:r><w:t xml:space="preserve">{content}</w:t></w:r></w:p>'
            )
        elif kind == "li":
            paragraphs.append(
                '<w:p><w:pPr><w:ind w:left="360"/></w:pPr>'
                f'<w:r><w:t xml:space="preserve">• {content}</w:t></w:r></w:p>'
            )
        else:
            paragraphs.append(f'<w:p><w:r><w:t xml:space="preserve">{content}</w:t></w:r></w:p>')

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paragraphs)}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )

    # Parse before shipping. Escaping is the fix; this is the check that the fix was applied
    # everywhere, and it turns a download that fails silently in Word into an error here. It costs
    # microseconds on a document this size.
    try:
        ElementTree.fromstring(document)
    except ElementTree.ParseError as exc:  # pragma: no cover - unreachable while esc() is used
        raise ValueError(
            f"the generated document.xml is not well formed ({exc}); some text reached it without "
            "going through esc()"
        ) from exc

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()
