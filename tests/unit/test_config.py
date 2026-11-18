import pytest
from pydantic import ValidationError

from rag.config import DEFAULT_LAWS, LawSelection, Settings


def test_defaults_cover_the_spec_laws():
    slugs = {law.slug for law in DEFAULT_LAWS}
    assert slugs == {"bgb", "evo_2023", "pangv_2022", "enwg_2005", "tkg_2021"}


def test_bgb_is_restricted_to_consumer_parts():
    bgb = next(law for law in DEFAULT_LAWS if law.slug == "bgb")
    assert bgb.ranges is not None
    assert ("13", "14") in bgb.ranges


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("RAG_TOP_K", "7")
    monkeypatch.setenv("RAG_LAWS", '[{"slug": "pangv_2022"}]')
    settings = Settings()
    assert settings.top_k == 7
    assert [law.slug for law in settings.laws] == ["pangv_2022"]


def test_secret_is_not_printed():
    assert "minioadmin" not in repr(Settings().s3_secret_key)


@pytest.mark.parametrize("slug", ["", "../etc", "a b"])
def test_invalid_slug_rejected(slug):
    with pytest.raises(ValidationError):
        LawSelection(slug=slug)
