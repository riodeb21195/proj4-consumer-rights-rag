import numpy as np
import pytest

from rag.process.embed import FakeEmbedder, make_embedder


def test_fake_embedder_is_normalised_and_deterministic():
    e = FakeEmbedder()
    a = e.embed_passages(["Widerruf binnen 14 Tagen", "Miete"])
    assert a.shape == (2, 384)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0)
    assert np.allclose(a[0], e.embed_passages(["Widerruf binnen 14 Tagen"])[0])


def test_fake_embedder_lexical_similarity():
    e = FakeEmbedder()
    q = e.embed_query("Widerruf Frist")
    docs = e.embed_passages(["Die Frist für den Widerruf", "Mietvertrag über Wohnraum"])
    assert docs[0] @ q > docs[1] @ q


def test_fake_embedder_edge_cases():
    e = FakeEmbedder()
    assert e.embed_passages([]).shape == (0, 384)
    assert e.embed_query("!!!")[0] == 1.0


def test_make_embedder_fake():
    assert make_embedder("fake-hashing").model_name == "fake-hashing"


def test_sentence_transformer_embedder():
    pytest.importorskip("sentence_transformers")
    e = make_embedder("intfloat/multilingual-e5-small")
    q = e.embed_query("Wie lange kann ich widerrufen?")
    docs = e.embed_passages(["Die Widerrufsfrist beträgt 14 Tage.", "Der Mieter zahlt die Miete."])
    assert e.dim == 384
    assert q.shape == (384,)
    assert docs[0] @ q > docs[1] @ q
