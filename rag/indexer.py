"""Build the retrieval index: documents and structured facts, chunked and embedded.

Two kinds of thing go in. Documents are the reference corpus — rules, fee schedules, methodology —
chunked on headings so a citation lands on a section rather than an arbitrary window. Structured
facts are rows turned into sentences, so a question about a specific area's yield can be answered
from the registry rather than from prose about yields in general.

Chunks carry their provenance. A chunk derived from generated data says so, and the answer that
cites it inherits that warning, because a cited number from a stand-in is still a number from a
stand-in.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import regex
import yaml

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
INDEX_PATH = ROOT / ".cache" / "index.json"
EMBED_CACHE = ROOT / ".cache" / "embeddings"

FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
HEADING = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

# Long enough to stand alone, short enough that a citation points somewhere specific.
MAX_CHUNK_CHARS = 1400
MIN_CHUNK_CHARS = 80


@dataclass
class Chunk:
    id: str
    text: str
    kind: str  # "doc" | "fact"
    title: str
    source: str
    source_url: str | None = None
    section: str | None = None
    doc_id: str | None = None
    table_ref: str | None = None
    lang: str = "en"
    status: str = "unverified"
    provenance: str = "REAL"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def citation(self) -> dict[str, Any]:
        """What a footnote needs: where this came from and how trustworthy it is."""
        return {
            "chunk_id": self.id,
            "title": self.title,
            "section": self.section,
            "source": self.source,
            "source_url": self.source_url,
            "kind": self.kind,
            "status": self.status,
            "provenance": self.provenance,
            "table_ref": self.table_ref,
        }


def _chunk_id(text: str, prefix: str) -> str:
    return f"{prefix}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"


def parse_document(path: Path) -> tuple[dict[str, Any], str]:
    """Split a corpus file into its front matter and its body."""
    raw = path.read_text()
    match = FRONT_MATTER.match(raw)
    if not match:
        return {"id": path.stem, "title": path.stem, "kind": "community"}, raw
    meta = yaml.safe_load(match.group(1)) or {}
    return meta, raw[match.end() :]


def split_sections(body: str) -> list[tuple[str | None, str]]:
    """Split on headings, so a citation lands on a section rather than a sliding window."""
    matches = list(HEADING.finditer(body))
    if not matches:
        return [(None, body.strip())]

    sections: list[tuple[str | None, str]] = []
    preamble = body[: matches[0].start()].strip()
    if len(preamble) >= MIN_CHUNK_CHARS:
        sections.append((None, preamble))

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[match.end() : end].strip()
        if len(text) < MIN_CHUNK_CHARS:
            continue
        # A very long section is split on blank lines rather than mid-sentence.
        if len(text) <= MAX_CHUNK_CHARS:
            sections.append((heading, text))
            continue
        buffer = ""
        for paragraph in text.split("\n\n"):
            if len(buffer) + len(paragraph) > MAX_CHUNK_CHARS and buffer:
                sections.append((heading, buffer.strip()))
                buffer = paragraph
            else:
                buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if buffer.strip():
            sections.append((heading, buffer.strip()))
    return sections


# Scripts, not languages: a script is decidable from the characters, a language is not, and the
# distinction that matters for retrieval here is exactly the one a script tells you. Latin text is
# left as whatever the document declared, since English and a transliteration share an alphabet.
_SCRIPTS: tuple[tuple[str, str], ...] = (
    ("ar", r"\p{Arabic}"),
    ("hi", r"\p{Devanagari}"),
)


def detect_lang(text: str, declared: str = "en") -> str:
    """The language of one chunk, from its own characters.

    The front matter declares a language per *document*, and the documents here carry an English
    body with Arabic and Hindi summaries inside it. Taking the document's value gave every chunk
    `en`, including the ones written in Arabic — so a language-aware filter would have hidden
    exactly the chunks it was meant to find, and the multilingual eval passed only because nothing
    filtered on the field.
    """
    for code, pattern in _SCRIPTS:
        matches = regex.findall(pattern, text)
        # A threshold rather than any match, so one Arabic place name in an English sentence does
        # not relabel the sentence.
        if len(matches) >= 12:
            return code
    return declared


def index_documents(corpus_dir: Path = CORPUS_DIR) -> list[Chunk]:
    """Chunk every document in the corpus."""
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        meta, body = parse_document(path)
        for section, text in split_sections(body):
            heading = (
                f"{meta.get('title', path.stem)} — {section}"
                if section
                else meta.get("title", path.stem)
            )
            chunks.append(
                Chunk(
                    id=_chunk_id(f"{path.name}:{section}:{text[:80]}", "doc"),
                    text=f"{heading}\n\n{text}",
                    kind="doc",
                    title=str(meta.get("title", path.stem)),
                    section=section,
                    source=str(meta.get("source", path.name)),
                    source_url=meta.get("source_url"),
                    doc_id=str(meta.get("id", path.stem)),
                    lang=detect_lang(text, str(meta.get("lang", "en"))),
                    status=str(meta.get("status", "unverified")),
                )
            )
    return chunks


# Communities are known by initials as often as by name: nobody searches for "Jumeirah Village
# Circle". Indexing the acronym alongside the name is what lets a lexical search find the right
# area from how people actually write it.
KNOWN_ALIASES: dict[str, tuple[str, ...]] = {
    "jumeirah village circle": ("JVC",),
    "jumeirah village triangle": ("JVT",),
    "jumeirah lake towers": ("JLT",),
    "al thanyah fifth": ("JLT", "Jumeirah Lake Towers"),
    "marsa dubai": ("Dubai Marina", "the Marina"),
    "burj khalifa": ("Downtown Dubai", "Downtown"),
    "nakhlat jumeirah": ("Palm Jumeirah", "the Palm"),
    "hadaeq sheikh mohammed bin rashid": ("Dubai Hills Estate", "Dubai Hills"),
    "nadd hessa": ("Dubai Silicon Oasis", "DSO"),
    "al barsha south fourth": ("Arjan",),
    "me'aisem first": ("Dubai Production City", "IMPZ"),
    "al hebiah fourth": ("Dubai Sports City",),
    "al hebiah third": ("Motor City",),
    "al merkadh": ("Sobha Hartland", "MBR City"),
    "al khairan first": ("Dubai Creek Harbour",),
    "madinat al mataar": ("Dubai South",),
    "al warsan first": ("International City",),
    "jabal ali first": ("Discovery Gardens", "Al Furjan"),
}


def aliases_for(area_key: str, name: str) -> list[str]:
    """Other ways people write this area's name, including its initials."""
    out = list(KNOWN_ALIASES.get(area_key.lower(), ()))
    words = [w for w in re.split(r"\s+", name) if len(w) > 2]
    if len(words) >= 2:
        acronym = "".join(w[0] for w in words).upper()
        if len(acronym) >= 2 and acronym not in out:
            out.append(acronym)
    if name.lower() != area_key.lower():
        out.append(name)
    return list(dict.fromkeys(out))


def _fmt(value: Any, kind: str = "number") -> str:
    if value is None:
        return "not recorded"
    if kind == "aed":
        return f"AED {float(value):,.0f}"
    if kind == "pct":
        return f"{float(value):.2f}%"
    return f"{float(value):,.1f}" if isinstance(value, float) else str(value)


def index_facts(db_path: Path | None = None) -> list[Chunk]:
    """Turn registry aggregates into sentences a retriever can find.

    Prose about yields cannot answer "what is the net yield for a one-bed in JVC". Writing each
    cell out as a sentence lets the same retrieval path serve both kinds of question, and every
    such chunk carries the SQL-backed figures it came from.
    """
    from finance.base import DEFAULT_DB, Warehouse

    path = db_path or DEFAULT_DB
    if not path.exists():
        return []

    chunks: list[Chunk] = []
    with Warehouse(path) as wh:
        provenance = wh.provenance()

        areas = wh.query(
            """
            select
                t.area_key,
                coalesce(a.name, t.area_key)     as name,
                count(*)                         as n,
                median(t.price_per_sqm)          as ppsqm,
                median(t.price_aed)              as price,
                avg(case when t.is_offplan then 1.0 else 0.0 end) as offplan
            from transactions t
            left join area a using (area_key)
            where t.ts >= (select max(ts) from transactions) - interval '12' month
            group by 1, 2
            having count(*) >= 10
            """
        ).frame

        rents = wh.query(
            """
            select area_key, rooms, count(*) as n, median(annual_rent_aed) as rent
            from rent_contracts
            where start >= (select max(start) from rent_contracts) - interval '12' month
            group by 1, 2
            having count(*) >= 5
            """
        ).frame

        rent_lookup: dict[tuple[str, Any], dict[str, Any]] = {
            (r["area_key"], r["rooms"]): r for r in rents.to_dicts()
        }

        for row in areas.to_dicts():
            text = (
                f"{row['name']} ({row['area_key']}). Over the last twelve months the registry "
                f"recorded {int(row['n']):,} sales. The median price per square metre was "
                f"{_fmt(row['ppsqm'], 'aed')} and the median sale price was "
                f"{_fmt(row['price'], 'aed')}. Off-plan sales were "
                f"{_fmt((row['offplan'] or 0) * 100, 'pct')} of the total."
            )
            alias_list = aliases_for(row["area_key"], str(row["name"]))
            if alias_list:
                text += f" Also known as {', '.join(alias_list)}."

            matching_rents = [
                r for (key, _rooms), r in rent_lookup.items() if key == row["area_key"]
            ]
            if matching_rents:
                parts = [
                    f"{'studio' if r['rooms'] == 0 else str(r['rooms']) + '-bedroom'} at "
                    f"{_fmt(r['rent'], 'aed')} a year (from {int(r['n'])} contracts)"
                    for r in sorted(matching_rents, key=lambda r: (r["rooms"] is None, r["rooms"]))
                    if r["rooms"] is not None
                ]
                if parts:
                    text += " Median registered rents: " + "; ".join(parts) + "."

            chunks.append(
                Chunk(
                    id=_chunk_id(row["area_key"], "fact"),
                    text=text,
                    kind="fact",
                    title=str(row["name"]),
                    source="Dubai Land Department transaction and Ejari registries",
                    table_ref=f"transactions,rent_contracts:{row['area_key']}",
                    status="verified" if provenance == "REAL" else "generated",
                    provenance=provenance,
                    meta={
                        "area_key": row["area_key"],
                        "aliases": alias_list,
                        "n": int(row["n"]),
                        "median_ppsqm": row["ppsqm"],
                        "median_price": row["price"],
                    },
                )
            )
    return chunks


def build_index(
    *, corpus_dir: Path = CORPUS_DIR, db_path: Path | None = None, out: Path | None = None
) -> dict[str, Any]:
    """Build the whole index and write it to disk."""
    chunks = index_documents(corpus_dir) + index_facts(db_path)
    body = {
        "n_chunks": len(chunks),
        "n_documents": sum(1 for c in chunks if c.kind == "doc"),
        "n_facts": sum(1 for c in chunks if c.kind == "fact"),
        "provenance": "SYNTHETIC" if any(c.provenance == "SYNTHETIC" for c in chunks) else "REAL",
        "chunks": [asdict(c) for c in chunks],
    }
    target = out or INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(body, indent=2, default=str))
    return body


def load_index(path: Path | None = None) -> list[Chunk]:
    target = path or INDEX_PATH
    if not target.exists():
        return []
    body = json.loads(target.read_text())
    return [Chunk(**c) for c in body["chunks"]]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS_DIR)
    parser.add_argument("--out", type=Path, default=INDEX_PATH)
    args = parser.parse_args(argv)

    body = build_index(corpus_dir=args.corpus, out=args.out)
    print(
        f"indexed {body['n_chunks']} chunks "
        f"({body['n_documents']} from documents, {body['n_facts']} from the registry), "
        f"provenance {body['provenance']}"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
