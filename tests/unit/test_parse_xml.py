from datetime import datetime

import pytest

from rag.ingest.parse_xml import (
    XmlParseError,
    in_ranges,
    norm_url,
    paragraph_sort_key,
    parse_law,
)
from tests.conftest import LAW_FIXTURES


def test_law_metadata(mini_law_xml):
    law = parse_law(mini_law_xml, "testg")
    assert law.abbreviation == "TG"
    assert law.title == "Testgesetz"
    assert law.stand == "Zuletzt geändert 2026"
    assert law.builddate == datetime(2026, 1, 1, 12, 0, 0)


def test_structural_norms_are_skipped(mini_law_xml):
    law = parse_law(mini_law_xml, "testg")
    assert [n.enbez for n in law.norms] == ["§ 1", "§ 2", "§ 2a", "Anlage"]


def test_absaetze_lists_and_footnotes(mini_law_xml):
    norm = parse_law(mini_law_xml, "testg").norms[0]
    assert norm.title == "Anwendungsbereich"
    assert norm.section == "Abschnitt 1 Allgemeines"
    assert norm.absaetze == (
        "(1) Dieses Gesetz gilt für Verbraucher.",
        "(2) Es gilt nicht für\n1. Unternehmer,\n2. Behörden.\nSatz nach der Liste.",
    )
    assert "Amtlicher Hinweis" not in norm.text


def test_repealed_detection(mini_law_xml):
    norms = {n.enbez: n for n in parse_law(mini_law_xml, "testg").norms}
    assert norms["§ 2"].repealed
    assert not norms["§ 2a"].repealed


def test_content_hash_changes_with_text(mini_law_xml):
    changed = mini_law_xml.replace(b"Preise sind anzugeben.", b"Preise sind immer anzugeben.")
    a = {n.enbez: n.content_hash for n in parse_law(mini_law_xml, "t").norms}
    b = {n.enbez: n.content_hash for n in parse_law(changed, "t").norms}
    assert a["§ 2a"] != b["§ 2a"]
    assert a["§ 1"] == b["§ 1"]


@pytest.mark.parametrize(
    "xml",
    [
        b"<dokumente><norm>",
        b"<other/>",
        b"<dokumente builddate='20260101000000'/>",
        b"<dokumente><norm/></dokumente>",
    ],
)
def test_invalid_documents_raise(xml):
    with pytest.raises(XmlParseError):
        parse_law(xml, "broken")


def test_missing_head_metadata_raises():
    with pytest.raises(XmlParseError):
        parse_law(b"<dokumente builddate='20260101000000'><norm/></dokumente>", "x")


@pytest.mark.parametrize(
    ("label", "key"),
    [("§ 312g", (312, "g")), ("312", (312, "")), ("§§ 3", (3, "")), ("Anlage", None)],
)
def test_paragraph_sort_key(label, key):
    assert paragraph_sort_key(label) == key


def test_ranges(mini_law_xml):
    norms = {n.enbez: n for n in parse_law(mini_law_xml, "t").norms}
    assert in_ranges(norms["Anlage"], None)
    assert not in_ranges(norms["Anlage"], [("1", "2")])
    assert in_ranges(norms["§ 2a"], [("2", "2b")])
    assert not in_ranges(norms["§ 2a"], [("1", "2")])
    with pytest.raises(ValueError):
        in_ranges(norms["§ 1"], [("x", "y")])


def test_norm_url():
    assert norm_url("https://g.de", "bgb", "§ 312g") == "https://g.de/bgb/__312g.html"
    assert norm_url("https://g.de", "pangv_2022", "Anlage") == "https://g.de/pangv_2022/"


def test_real_bgb_fixture():
    law = parse_law((LAW_FIXTURES / "bgb.xml").read_bytes(), "bgb")
    norms = {n.enbez: n for n in law.norms}
    assert law.abbreviation == "BGB"
    assert "(2) Die Widerrufsfrist beträgt 14 Tage." in norms["§ 355"].text
    assert norms["§ 312g"].title == "Widerrufsrecht"
    assert norms["§ 13"].section.startswith("Buch 1 Allgemeiner Teil")
