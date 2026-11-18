"""Answer composition: always cites sources; an LLM (Ollama) is optional.

Without an LLM the answer is extractive: the most relevant provisions, each with its citation.
With an LLM the model is instructed to answer only from the numbered sources and cite them.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from rag.store.vector_store import SearchHit

log = logging.getLogger(__name__)

DISCLAIMER = "Hinweis: Diese Auskunft ersetzt keine Rechtsberatung."


@dataclass(frozen=True)
class Answer:
    text: str
    llm_model: str | None


def citation(hit: SearchHit) -> str:
    absatz = f" Abs. {hit.absatz}" if hit.absatz and "-" not in hit.absatz else ""
    return f"{hit.paragraph}{absatz} {hit.law_abbreviation}"


def extractive_answer(hits: Sequence[SearchHit], max_chars: int = 600) -> str:
    if not hits:
        return "Zu dieser Frage wurde keine passende Vorschrift gefunden. " + DISCLAIMER
    lines = ["Die relevantesten Vorschriften:"]
    for n, hit in enumerate(hits, start=1):
        text = hit.text if len(hit.text) <= max_chars else hit.text[:max_chars].rstrip() + " …"
        lines.append(f"\n[{n}] {citation(hit)}: {hit.heading}\n{text}")
    lines.append(f"\n{DISCLAIMER}")
    return "\n".join(lines)


def build_prompt(question: str, hits: Sequence[SearchHit]) -> str:
    sources = "\n\n".join(
        f"[{n}] {citation(h)} ({h.heading})\n{h.text}" for n, h in enumerate(hits, start=1)
    )
    return (
        "Du beantwortest Fragen zu deutschem Verbraucherrecht. Antworte auf Deutsch, knapp und "
        "nur auf Grundlage der folgenden Quellen. Belege jede Aussage mit der Quellennummer, "
        "z. B. [1]. Wenn die Quellen die Frage nicht beantworten, sage das.\n\n"
        f"Quellen:\n{sources}\n\nFrage: {question}\nAntwort:"
    )


class OllamaGenerator:
    def __init__(self, base_url: str, model: str, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = client or httpx.Client(timeout=120.0)

    def answer(self, question: str, hits: Sequence[SearchHit]) -> Answer:
        if not hits:
            return Answer(extractive_answer(hits), None)
        try:
            resp = self.client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": build_prompt(question, hits), "stream": False},
            )
            resp.raise_for_status()
            text = str(resp.json()["response"]).strip()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning(
                "LLM unavailable, falling back to extractive answer", extra={"err": str(exc)}
            )
            return Answer(extractive_answer(hits), None)
        sources = "\n".join(f"[{n}] {citation(h)}" for n, h in enumerate(hits, start=1))
        return Answer(f"{text}\n\nQuellen:\n{sources}\n\n{DISCLAIMER}", self.model)


class ExtractiveGenerator:
    def answer(self, question: str, hits: Sequence[SearchHit]) -> Answer:
        return Answer(extractive_answer(hits), None)
