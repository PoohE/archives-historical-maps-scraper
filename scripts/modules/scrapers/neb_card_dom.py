"""Parse a public NEB card from a saved rendered DOM; never fetch a viewer or file."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://rusneb.ru"


def _text(node) -> str:
    if not node:
        return ""
    value = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
    return re.sub(r"\s*Скопировать\s*$", "", value).strip()


def parse_card(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    meta: dict[str, str] = {}
    bibliography = ""
    for section in soup.select("div.cards-section"):
        heading = _text(section.select_one("h2"))
        if heading == "Библиографическое описание":
            bibliography = _text(section.select_one("div.span_biblio"))
        elif heading == "Детальная информация":
            for row in section.select("div.cards-table__row"):
                label, value = row.select_one(".cards-table__left"), row.select_one(".cards-table__right")
                if label and value:
                    meta[_text(label).rstrip(":")] = _text(value)
    identifier = meta.get("Код документа в НЭБ", url.rstrip("/").rsplit("/", 1)[-1])
    pdf = next((urljoin(BASE, a["href"]) for a in soup.select('a[href*="/local/tools/exalead/getFiles.php?book_id="]')), "")
    catalog = meta.get("Каталог", "")
    return {
        "title": _text(soup.select_one("h1.title")), "bibliography": bibliography,
        "meta": meta, "identifier": identifier, "url": url,
        "pdf_url": pdf,
        "viewer_url": f"{BASE}/catalog/{identifier}/viewer/" if soup.select_one("a.boockard-read-button") else "",
        "is_map": "карт" in catalog.casefold(), "catalog_raw": catalog,
        "bbk_raw": meta.get("ББК", ""),
    }
