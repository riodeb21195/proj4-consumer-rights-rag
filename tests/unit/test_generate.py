import httpx

from rag.retrieval.generate import (
    DISCLAIMER,
    ExtractiveGenerator,
    OllamaGenerator,
    build_prompt,
    citation,
    extractive_answer,
)
from rag.store.vector_store import SearchHit

HIT = SearchHit(
    1,
    0.9,
    "bgb",
    "BGB",
    "§ 355",
    "2",
    "BGB § 355 Widerrufsrecht",
    "(2) Die Widerrufsfrist beträgt 14 Tage.",
    "s",
    "u",
    1,
)


def test_citation_formats():
    assert citation(HIT) == "§ 355 Abs. 2 BGB"
    ranged = SearchHit(**{**HIT.__dict__, "absatz": "1-3"})
    assert citation(ranged) == "§ 355 BGB"


def test_extractive_answer_cites_and_disclaims():
    text = extractive_answer([HIT])
    assert "[1] § 355 Abs. 2 BGB" in text
    assert "14 Tage" in text
    assert DISCLAIMER in text
    assert "keine passende Vorschrift" in extractive_answer([])


def test_extractive_answer_truncates():
    long = SearchHit(**{**HIT.__dict__, "text": "x" * 1000})
    assert "…" in extractive_answer([long], max_chars=100)


def test_prompt_contains_numbered_sources():
    prompt = build_prompt("Wie lange?", [HIT])
    assert "[1] § 355 Abs. 2 BGB" in prompt
    assert "Frage: Wie lange?" in prompt


def _ollama(handler) -> OllamaGenerator:
    return OllamaGenerator(
        "http://ollama:11434", "m", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_ollama_answer_appends_sources():
    def handler(request):
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"response": "14 Tage [1]."})

    answer = _ollama(handler).answer("Wie lange?", [HIT])
    assert answer.llm_model == "m"
    assert answer.text.startswith("14 Tage [1].")
    assert "[1] § 355 Abs. 2 BGB" in answer.text


def test_ollama_falls_back_when_unavailable():
    answer = _ollama(lambda r: httpx.Response(500)).answer("Wie lange?", [HIT])
    assert answer.llm_model is None
    assert "Die relevantesten Vorschriften" in answer.text
    assert _ollama(lambda r: httpx.Response(200)).answer("x", []).llm_model is None


def test_extractive_generator():
    assert ExtractiveGenerator().answer("x", [HIT]).llm_model is None
