"""Streamlit UI: chat with citations and the evaluation results page."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.client import ApiClient, ApiError, evaluation_table

API_URL = os.environ.get("RAG_API_URL", "http://localhost:8000")
DISCLAIMER = (
    "Dieses Tool ersetzt keine Rechtsberatung. Es zeigt die passendsten Vorschriften aus "
    "gesetze-im-internet.de, ohne Gewähr für Vollständigkeit oder Aktualität."
)


@st.cache_resource
def client() -> ApiClient:
    return ApiClient(API_URL)


def chat_page() -> None:
    st.title("Was steht mir als Verbraucher zu?")
    st.warning(DISCLAIMER, icon="⚖️")
    with st.sidebar:
        mode = st.selectbox("Suchmodus", ["vector", "hybrid", "fulltext"], index=0)
        k = st.slider("Anzahl Quellen", 1, 10, 5)

    if "history" not in st.session_state:
        st.session_state.history = []
    for turn in st.session_state.history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            for src in turn.get("sources", []):
                render_source(src)

    question = st.chat_input("z. B. Wie lange kann ich einen Online-Kauf widerrufen?")
    if not question:
        return
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Suche passende Vorschriften …"):
                result = client().ask(question, k=k, mode=mode)
        except ApiError as exc:
            st.error(str(exc))
            return
        st.markdown(result["answer"])
        for src in result["sources"]:
            render_source(src)
        st.caption(f"Antwort-ID {result['answer_id']} (Lineage: /lineage/{result['answer_id']})")
    st.session_state.history.append(
        {"role": "assistant", "content": result["answer"], "sources": result["sources"]}
    )


def render_source(src: dict[str, object]) -> None:
    with st.expander(f"[{src['n']}] {src['citation']}: {src['heading']}"):
        st.markdown(str(src["text"]))
        st.caption(f"{src['stand']} · Score {float(str(src['score'])):.3f}")
        st.link_button("Auf gesetze-im-internet.de öffnen", str(src["url"]))


def evaluation_page() -> None:
    st.title("Evaluation")
    st.caption("Retrieval-Qualität auf den Testfragen in evaluation/questions.jsonl")
    try:
        results = client().evaluation()
    except ApiError as exc:
        st.error(str(exc))
        return
    if not results:
        st.info("Noch keine Ergebnisse. `make eval` ausführen.")
        return
    st.subheader("Neuester Lauf je Variante")
    st.dataframe(evaluation_table(results), hide_index=True)
    st.subheader("Verlauf Hit-Rate@5")
    history = [
        {
            "created_at": r["created_at"],
            "variant": r["variant"],
            "hit_rate@5": r["metrics"].get("hit_rate@5"),
        }
        for r in results
    ]
    st.line_chart(history, x="created_at", y="hit_rate@5", color="variant")


pages = [
    st.Page(chat_page, title="Chat", icon="💬", default=True),
    st.Page(evaluation_page, title="Evaluation", icon="📊"),
]
st.navigation(pages).run()
