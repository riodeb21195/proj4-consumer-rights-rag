"""Parse the gesetze-im-internet.de XML format (gii-norm.dtd) into laws and norms.

One ``<dokumente>`` per law contains many ``<norm>`` elements:
- the first norm carries law-level metadata (abbreviation, long title, "Stand"),
- ``gliederungseinheit`` norms are section headings,
- all other norms with an ``enbez`` ("§ 312g", "Anlage", ...) are the actual provisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from lxml import etree

from rag.ingest.hashing import content_hash, normalize_text

_PARAGRAPH_RE = re.compile(r"^§+\s*(\d+)\s*([a-z]*)", re.IGNORECASE)
_ABSATZ_RE = re.compile(r"^\((\d+[a-z]?)\)\s*")
# Norms that structure the document but contain no provision text.
_SKIP_ENBEZ = {"Inhaltsübersicht", "Eingangsformel", "Schlussformel"}
# Elements whose text must not end up in the provision (footnote markers, footnote bodies, TOCs).
_SKIP_TAGS = {"FnR", "Footnotes", "Footnote", "TOC", "noindex"}
_BLOCK_TAGS = {"P", "DT", "DD", "LA", "row", "BR", "Title", "Ident"}


class XmlParseError(ValueError):
    """The file is not a valid gesetze-im-internet.de law document."""


@dataclass(frozen=True)
class Norm:
    law_slug: str
    doknr: str
    enbez: str
    title: str
    section: str
    absaetze: tuple[str, ...]
    repealed: bool

    @property
    def text(self) -> str:
        return "\n".join(self.absaetze)

    @property
    def content_hash(self) -> str:
        return content_hash(self.enbez, self.title, self.text)

    @property
    def paragraph_key(self) -> tuple[int, str] | None:
        return paragraph_sort_key(self.enbez)


@dataclass(frozen=True)
class Law:
    slug: str
    abbreviation: str
    title: str
    builddate: datetime
    stand: str
    norms: list[Norm] = field(default_factory=list)


def paragraph_sort_key(label: str) -> tuple[int, str] | None:
    """``"§ 312g"`` -> ``(312, "g")``; ``"312g"`` works too. ``None`` for non-paragraph labels."""
    m = _PARAGRAPH_RE.match(label if label.lstrip().startswith("§") else f"§ {label}")
    if not m:
        return None
    return int(m.group(1)), m.group(2).lower()


def _text_of(elem: etree._Element) -> str:
    """Flatten an element to text, keeping list/paragraph structure as line breaks."""
    parts: list[str] = []

    def walk(node: etree._Element) -> None:
        tag = node.tag if isinstance(node.tag, str) else ""
        if tag in _SKIP_TAGS:
            if node.tail:
                parts.append(node.tail)
            return
        if tag in _BLOCK_TAGS:
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        for child in node:
            walk(child)
        if tag == "DT":
            parts.append(" ")
        elif tag in _BLOCK_TAGS:
            parts.append("\n")
        if node.tail:
            parts.append(node.tail)

    walk(elem)
    lines = (normalize_text(line) for line in "".join(parts).split("\n"))
    return "\n".join(line for line in lines if line)


def _join_list_markers(text: str) -> str:
    """``"1.\\nfoo"`` -> ``"1. foo"`` so enumerations stay readable."""
    return re.sub(r"(?m)^(\d+[a-z]?\.|[a-z]\)|[a-z]{2}\))\n", r"\1 ", text)


def _absaetze(content: etree._Element) -> tuple[str, ...]:
    """Split a norm's ``Content`` into Absätze. Each top-level ``<P>`` starts a new one."""
    blocks: list[str] = []
    for p in content.iterchildren():
        if not isinstance(p.tag, str):
            continue
        text = _join_list_markers(_text_of(p))
        if not text:
            continue
        # A <P> without "(n)" after an Absatz is its continuation (e.g. a sentence after a list).
        if blocks and _ABSATZ_RE.match(blocks[-1]) and not _ABSATZ_RE.match(text):
            blocks[-1] = f"{blocks[-1]}\n{text}"
        else:
            blocks.append(text)
    return tuple(blocks)


def _first(elem: etree._Element, path: str) -> str:
    found = elem.find(path)
    return _text_of(found).replace("\n", " ") if found is not None else ""


def parse_law(xml: bytes, slug: str) -> Law:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(xml, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise XmlParseError(f"{slug}: malformed XML: {exc}") from exc
    if root.tag != "dokumente":
        raise XmlParseError(f"{slug}: unexpected root element <{root.tag!s}>")
    norm_elems = root.findall("norm")
    if not norm_elems:
        raise XmlParseError(f"{slug}: document contains no <norm>")

    try:
        builddate = datetime.strptime(root.get("builddate", ""), "%Y%m%d%H%M%S")
    except ValueError as exc:
        raise XmlParseError(f"{slug}: missing or invalid builddate") from exc

    head = norm_elems[0].find("metadaten")
    if head is None:
        raise XmlParseError(f"{slug}: first norm has no metadata")
    abbreviation = _first(head, "amtabk") or _first(head, "jurabk")
    title = _first(head, "langue") or abbreviation
    stand = ""
    for sa in head.findall("standangabe"):
        if _first(sa, "standtyp") == "Stand":
            stand = _first(sa, "standkommentar")
            break

    law = Law(slug=slug, abbreviation=abbreviation, title=title, builddate=builddate, stand=stand)
    # gliederungskennzahl encodes depth in 3-digit groups ("010", "010020", ...).
    sections: dict[int, str] = {}
    for norm in norm_elems[1:]:
        meta = norm.find("metadaten")
        if meta is None:
            continue
        unit = meta.find("gliederungseinheit")
        if unit is not None:
            depth = max(len(_first(unit, "gliederungskennzahl")) // 3, 1)
            sections = {d: t for d, t in sections.items() if d < depth}
            sections[depth] = " ".join(
                p for p in (_first(unit, "gliederungsbez"), _first(unit, "gliederungstitel")) if p
            )
            continue
        enbez = normalize_text(_first(meta, "enbez"))
        if not enbez or enbez in _SKIP_ENBEZ:
            continue
        norm_title = _first(meta, "titel")
        content = norm.find("textdaten/text/Content")
        absaetze = _absaetze(content) if content is not None else ()
        repealed = (
            enbez.startswith("(XXXX)")
            or norm_title.strip() == "(weggefallen)"
            or not absaetze
            or absaetze == ("(weggefallen)",)
        )
        law.norms.append(
            Norm(
                law_slug=slug,
                doknr=norm.get("doknr", ""),
                enbez=enbez,
                title=norm_title,
                section=" > ".join(sections[d] for d in sorted(sections)),
                absaetze=absaetze,
                repealed=repealed,
            )
        )
    return law


def in_ranges(norm: Norm, ranges: list[tuple[str, str]] | None) -> bool:
    """Is the norm selected? Non-paragraph norms (e.g. "Anlage") only pass without ranges."""
    if ranges is None:
        return True
    key = norm.paragraph_key
    if key is None:
        return False
    for start, end in ranges:
        lo, hi = paragraph_sort_key(start), paragraph_sort_key(end)
        if lo is None or hi is None:
            raise ValueError(f"invalid paragraph range {start!r}-{end!r}")
        if lo <= key <= hi:
            return True
    return False


def norm_url(base_url: str, slug: str, enbez: str) -> str:
    """Deep link to the provision on gesetze-im-internet.de; falls back to the law's index page."""
    key = paragraph_sort_key(enbez)
    if key is None:
        return f"{base_url}/{slug}/"
    return f"{base_url}/{slug}/__{key[0]}{key[1]}.html"
