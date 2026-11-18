"""Helpers to simulate upstream changes in law XML files."""

from pathlib import Path

from lxml import etree


def _tree(path: Path) -> etree._ElementTree:
    return etree.parse(str(path), etree.XMLParser(load_dtd=False, no_network=True))


def _find_norm(tree: etree._ElementTree, enbez: str) -> etree._Element:
    for norm in tree.getroot().iter("norm"):
        if (norm.findtext("metadaten/enbez") or "").strip() == enbez:
            return norm
    raise KeyError(enbez)


def change_text(path: Path, enbez: str, old: str, new: str) -> None:
    tree = _tree(path)
    norm = _find_norm(tree, enbez)
    for elem in norm.iter("P"):
        if elem.text and old in elem.text:
            elem.text = elem.text.replace(old, new)
            tree.write(str(path), xml_declaration=True, encoding="UTF-8")
            return
    raise ValueError(f"{old!r} not found in {enbez}")


def repeal(path: Path, enbez: str) -> None:
    """Mark a provision as '(weggefallen)' the way the official XML does."""
    tree = _tree(path)
    norm = _find_norm(tree, enbez)
    norm.find("metadaten/titel").text = "(weggefallen)"
    content = norm.find("textdaten/text/Content")
    for child in list(content):
        content.remove(child)
    etree.SubElement(content, "P")
    tree.write(str(path), xml_declaration=True, encoding="UTF-8")


def bump_builddate(path: Path, builddate: str = "20991231235959") -> None:
    tree = _tree(path)
    tree.getroot().set("builddate", builddate)
    tree.write(str(path), xml_declaration=True, encoding="UTF-8")
