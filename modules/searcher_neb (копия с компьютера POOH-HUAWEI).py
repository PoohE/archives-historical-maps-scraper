"""Модуль поиска в НЭБ (rusneb.ru) — карты, рукописи, книги."""
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterator
import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://rusneb.ru/search/"
MARC_URL = "https://rusneb.ru/local/components/exalead/search.page.detail/ajax/marcExport.php"
MARC_NS = "http://www.loc.gov/MARC21/slim"

# Коды категорий НЭБ
CATEGORIES = {
    "карты": "7",
    "рукописи": "15",
    "книги": "25",
    "изодокументы": "23",
}


@dataclass
class NebRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    place: str = ""
    scale: int | None = None          # знаменатель масштаба
    size_mm: str = ""                 # размер листа
    series: str = ""
    language: str = "Русский"
    institution: str = ""             # источник / библиотека
    description: str = ""
    url: str = ""
    neb_id: str = ""
    category: str = "карты"
    extra: dict = field(default_factory=dict)


def _get(url: str, params: dict | None = None, delay: float = 1.5) -> requests.Response:
    """GET-запрос с задержкой и User-Agent."""
    time.sleep(delay)
    headers = {"User-Agent": "Mozilla/5.0 (research bot; contact: down.pooh@gmail.com)"}
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp


def _parse_marc(xml_bytes: bytes) -> dict:
    """Разбирает MARC21 XML и возвращает словарь полей."""
    result = {}
    try:
        # НЭБ нередко отдаёт cp1251 несмотря на объявление UTF-8
        for enc in ("utf-8", "cp1251", "cp1252"):
            try:
                text = xml_bytes.decode(enc)
                import re as _re
                text = _re.sub(r'encoding="[^"]*"', 'encoding="utf-8"', text)
                xml_bytes = text.encode("utf-8")
                break
            except UnicodeDecodeError:
                continue
        root = ET.fromstring(xml_bytes)
        record = root.find(f"{{{MARC_NS}}}record")
        if record is None:
            return result

        def get(tag: str, sub: str) -> str:
            el = record.find(f".//{{{MARC_NS}}}datafield[@tag='{tag}']/{{{MARC_NS}}}subfield[@code='{sub}']")
            return (el.text or "").strip() if el is not None else ""

        def get_all(tag: str, sub: str) -> list[str]:
            els = record.findall(f".//{{{MARC_NS}}}datafield[@tag='{tag}']/{{{MARC_NS}}}subfield[@code='{sub}']")
            return [(e.text or "").strip() for e in els]

        result["title"] = get("245", "a")
        result["author"] = get("245", "c") or get("100", "a") or get("700", "a")
        result["place"] = get("260", "a")
        result["year_raw"] = get("260", "c")
        result["scale_raw"] = get("255", "a")   # напр. "[1:84 000]"
        result["scale_b"] = get("034", "b")      # знаменатель масштаба
        result["size"] = get("300", "c")         # напр. "37x48 см"
        result["series"] = get("490", "a")
        result["language"] = get("041", "a") or "rus"
        result["description"] = get("520", "a")
        result["dates"] = get("534", "b")        # даты оригинала
    except ET.ParseError:
        pass
    return result


def _parse_years(year_raw: str) -> tuple[int | None, int | None]:
    """Из строки типа '1846-1866' или '[1785]' извлекает (нижняя, верхняя)."""
    import re
    nums = re.findall(r"\d{4}", year_raw)
    if not nums:
        return None, None
    if len(nums) == 1:
        y = int(nums[0])
        return y, y
    return int(nums[0]), int(nums[-1])


def _parse_scale(scale_b: str) -> int | None:
    """Из знаменателя масштаба возвращает целое число."""
    import re
    nums = re.findall(r"\d+", scale_b.replace(" ", ""))
    return int("".join(nums)) if nums else None


def _lang_ru(code: str) -> str:
    mapping = {"rus": "Русский", "lat": "Латинский", "ger": "Немецкий",
               "fre": "Французский", "pol": "Польский"}
    return mapping.get(code[:3].lower(), "Другой")


def _fetch_html_meta(neb_id: str) -> dict:
    """Запасной вариант: метаданные из HTML-страницы записи НЭБ."""
    meta = {}
    try:
        resp = _get(f"https://rusneb.ru/catalog/{neb_id}/", delay=0)
        soup = BeautifulSoup(resp.text, "lxml")
        h1 = soup.find("h1")
        if h1:
            meta["title"] = h1.get_text(strip=True)
        # Автор обычно над заголовком в .author или отдельном теге
        author_el = soup.select_one(".author, [itemprop='author']")
        if author_el:
            meta["author"] = author_el.get_text(strip=True)
        # Год из мета-тега или строки «Место, год»
        place_year = soup.select_one(".place-year, .publish-info")
        if place_year:
            text = place_year.get_text(strip=True)
            meta["year_raw"] = text
            meta["place"] = text
    except Exception:
        pass
    return meta


def _fetch_marc(neb_id: str) -> dict:
    """Загружает MARC21 XML для конкретной записи НЭБ, при ошибке — HTML-фолбек."""
    try:
        resp = _get(MARC_URL, params={"book_id": neb_id})
        data = _parse_marc(resp.content)
        # Если MARC не дал заголовка — дополняем из HTML
        if not data.get("title"):
            html_meta = _fetch_html_meta(neb_id)
            data.update({k: v for k, v in html_meta.items() if v and not data.get(k)})
        return data
    except Exception as e:
        return _fetch_html_meta(neb_id) or {"error": str(e)}


def search(query: str, year_from: int | None = None, year_to: int | None = None,
           category: str = "карты", max_pages: int = 3) -> Iterator[NebRecord]:
    """
    Ищет источники в НЭБ и возвращает записи.
    category: 'карты', 'рукописи', 'книги', 'изодокументы'
    """
    cat_id = CATEGORIES.get(category, "7")
    params: dict = {"q": query, "c[]": cat_id}
    if year_from:
        params["publishyear_prev"] = year_from
    if year_to:
        params["publishyear_next"] = year_to

    for page in range(1, max_pages + 1):
        params["PAGEN_1"] = page
        try:
            resp = _get(SEARCH_URL, params=params)
        except Exception as e:
            print(f"[НЭБ] Ошибка запроса стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")

        # Ссылки на карточки результатов
        cards = soup.select("a[href*='/catalog/']")
        ids_seen: set[str] = set()
        for card in cards:
            href = card.get("href", "")
            # ID вида /catalog/000199_000009_005438478/
            parts = [p for p in href.split("/") if p]
            if len(parts) >= 2 and parts[0] == "catalog":
                neb_id = parts[1]
                if neb_id in ids_seen:
                    continue
                ids_seen.add(neb_id)

                marc = _fetch_marc(neb_id)
                y_from, y_to = _parse_years(marc.get("dates") or marc.get("year_raw", ""))

                rec = NebRecord(
                    title=marc.get("title", "").strip("[]"),
                    author=marc.get("author", "").strip("[]"),
                    year_from=y_from,
                    year_to=y_to,
                    place=marc.get("place", "").strip("[]"),
                    scale=_parse_scale(marc.get("scale_b", "")),
                    size_mm=marc.get("size", ""),
                    series=marc.get("series", ""),
                    language=_lang_ru(marc.get("language", "rus")),
                    institution="НЭБ / РГБ",
                    description=marc.get("description", ""),
                    url=f"https://rusneb.ru/catalog/{neb_id}/",
                    neb_id=neb_id,
                    category=category,
                )
                yield rec

        # Проверка наличия следующей страницы
        next_link = soup.select_one(f"a[href*='PAGEN_1={page + 1}']")
        if not next_link:
            break
