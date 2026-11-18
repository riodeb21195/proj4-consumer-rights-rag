import pytest

from rag.process.chunk import NormInput, chunk_norm, split_long

NORM = NormInput(
    law_abbreviation="BGB",
    norm_key="§ 355",
    title="Widerrufsrecht bei Verbraucherverträgen",
    section="Buch 2 > Untertitel 2 Widerrufsrecht bei Verbraucherverträgen",
    absaetze=(
        "(1) Wird einem Verbraucher ein Widerrufsrecht eingeräumt, ist er nicht gebunden.",
        "(2) Die Widerrufsfrist beträgt 14 Tage.",
        "(3) Im Falle des Widerrufs sind die Leistungen zurückzugewähren.",
    ),
)


def test_paragraph_strategy_keeps_short_norm_together():
    chunks = chunk_norm(NORM, "paragraph", 2000)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.absatz == "1-3"
    assert c.paragraph == "§ 355"
    assert c.heading == "BGB § 355 Widerrufsrecht bei Verbraucherverträgen"
    assert c.embed_text.startswith("BGB § 355 Abs. 1-3 Widerrufsrecht")
    assert "Untertitel 2 Widerrufsrecht" in c.embed_text
    assert "Buch 2" not in c.embed_text  # only the innermost section is used as context


def test_paragraph_strategy_cuts_at_absatz_boundaries():
    chunks = chunk_norm(NORM, "paragraph", 140)
    assert [c.absatz for c in chunks] == ["1-2", "3"]
    assert all(c.text.startswith("(") for c in chunks)


def test_absatz_strategy():
    chunks = chunk_norm(NORM, "absatz", 2000)
    assert [c.absatz for c in chunks] == ["1", "2", "3"]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert chunks[1].embed_text.startswith("BGB § 355 Abs. 2 ")


def test_unnumbered_norm_has_no_absatz():
    norm = NormInput("PAngV", "§ 1", "", "", ("Preise sind anzugeben.",))
    (chunk,) = chunk_norm(norm, "absatz", 100)
    assert chunk.absatz is None
    assert chunk.heading == "PAngV § 1"


def test_continuation_inherits_absatz_label():
    norm = NormInput("X", "§ 1", "T", "", ("(1) " + "a" * 50 + ".\n1. " + "b" * 50,))
    chunks = chunk_norm(norm, "absatz", 60)
    assert [c.absatz for c in chunks] == ["1", "1"]


def test_unknown_strategy():
    with pytest.raises(ValueError):
        chunk_norm(NORM, "characters", 100)


def test_split_long_prefers_lines_then_sentences_then_words():
    assert split_long("kurz", 10) == ["kurz"]
    assert split_long("Zeile eins\nZeile zwei", 12) == ["Zeile eins", "Zeile zwei"]
    assert split_long("Satz eins. Satz zwei.", 12) == ["Satz eins.", "Satz zwei."]
    assert split_long("abc def ghi", 7) == ["abc def", "ghi"]


def test_content_hash_depends_on_embed_text():
    a = chunk_norm(NORM, "paragraph", 2000)[0]
    b = chunk_norm(
        NormInput("BGB", "§ 356", NORM.title, NORM.section, NORM.absaetze), "paragraph", 2000
    )[0]
    assert a.content_hash != b.content_hash
