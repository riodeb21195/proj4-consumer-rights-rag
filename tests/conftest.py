from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
LAW_FIXTURES = FIXTURES / "laws"


@pytest.fixture
def mini_law_xml() -> bytes:
    """Hand-written law covering the edge cases of the format (TOC, lists, footnotes, repeal)."""
    return (FIXTURES / "mini_law.xml").read_bytes()
