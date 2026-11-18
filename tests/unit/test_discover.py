import httpx

from rag.config import LawSelection
from rag.ingest.discover import check_selection, fetch_toc, parse_toc

TOC = b"""<?xml version="1.0" encoding="UTF-8" ?>
<items>
<item><title>Preisangabenverordnung</title><link>http://www.gesetze-im-internet.de/pangv_2022/xml.zip</link></item>
<item><title>B\xc3\xbcrgerliches Gesetzbuch</title><link>http://www.gesetze-im-internet.de/bgb/xml.zip</link></item>
<item><title>broken</title><link>http://example.test/</link></item>
</items>"""


def test_parse_toc():
    toc = parse_toc(TOC)
    assert set(toc) == {"pangv_2022", "bgb"}
    assert toc["bgb"].title == "Bürgerliches Gesetzbuch"


def test_check_selection_reports_missing():
    toc = parse_toc(TOC)
    missing = check_selection([LawSelection(slug="bgb"), LawSelection(slug="evo")], toc)
    assert missing == ["evo"]


def test_fetch_toc():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=TOC)))
    assert "bgb" in fetch_toc("https://example.test", client=client)
