"""
ЭБИД — Электронная библиотека исторических документов
(docs.historyrussia.org, проект Российского исторического общества / ИнфоРост)

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (из скринов 2026-07-10)
══════════════════════════════════════════════════════════════

Поиск:
  URL:    GET https://docs.historyrussia.org/ru/nodes/search
  Параметры:
    query=<запрос>           ← основной запрос
    commit=Найти             ← служебный
    meta_data=on             ← искать в метаданных (чекбокс)
    texts=on                 ← искать в текстах (чекбокс)

  Пагинация: page=1, page=2... (уточнить после теста)

Фасет «Виды документов: Карта»:
  В интерфейсе есть, кол-во показывает «Карта (6)» при запросе «карта Калужская».
  URL-параметр фасета — TODO: выяснить в DevTools (Drupal-паттерн: f[0]=field_vid:карта)
  Пока используем постфильтрацию по полю «Виды документов» в карточке.

Результаты: таблица (#, Название [ссылка], Тематика, Библ.описание, ...)
  Ссылки: /ru/nodes/{id}

Карточка документа (/ru/nodes/{id}):
  Drupal 7/8-разметка: div.field > div.field-label + div.field-items > div.field-item
  Поля: Тип материала, Название документа, Дата документа, Шифр, Архив,
        География, Даты, Организации, Тематика, Виды документов,
        Источник документа, Составитель записи

Пример с картой: /ru/nodes/87317
  Виды документов: Карта
  Архив: ЦХАФ АК (Алтайский край)
  Дата: 1924

══════════════════════════════════════════════════════════════
ВАЖНО: 10 000 результатов на «карта Калужская»
══════════════════════════════════════════════════════════════

Поиск идёт по текстам документов → большинство — не карты.
Фильтры:
  1. Постфильтр по полю «Виды документов» == «Карта» (реализован)
  2. Узкий запрос с топонимом: «карта Калужской губернии» вместо «карта Калужская»
  3. TODO: добавить фасетный параметр когда выясним его имя

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_ebid.py "карта Калужской губернии"
  python searcher_ebid.py "карта Калужской губернии" --debug
  python searcher_ebid.py --all-queries
"""

import re
import time
import argparse
from dataclasses import dataclass, field
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE_URL   = "https://docs.historyrussia.org"
SEARCH_URL = "https://docs.historyrussia.org/ru/nodes/search"

TERRITORIES = [
    "Калужской губернии", "Калужской губернии", "Калужское",
    "Пермской губернии",  "Пермского наместничества",
    "Смоленской губернии", "Смоленского наместничества",
    "Ярославской губернии", "Ярославского наместничества",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://docs.historyrussia.org/",
}


@dataclass
class EbidRecord:
    title: str = ""
    doc_type: str = ""          # Виды документов (Карта / Схема / ...)
    bib_description: str = ""   # Библиографическое описание
    date_raw: str = ""
    year_from: int | None = None
    year_to: int | None = None
    fund_code: str = ""         # Шифр
    archive: str = ""           # Архив
    geography: str = ""
    thematic: str = ""          # Тематика
    source: str = ""            # Источник документа
    url: str = ""
    library_id: str = "ebid"
    library_name: str = "ЭБИД (docs.historyrussia.org)"


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _parse_drupal_fields(soup: BeautifulSoup) -> dict[str, str]:
    """
    Парсит поля Drupal-страницы.
    Пробует три варианта разметки (7/8/9).
    """
    fields: dict[str, str] = {}

    # Drupal 7: div.field > div.field-label + div.field-items
    for div in soup.select("div[class*='field-name-']"):
        label_el = div.select_one(".field-label")
        items_el = div.select_one(".field-items")
        if label_el and items_el:
            key = label_el.get_text(strip=True).rstrip(":").rstrip("\xa0")
            val = items_el.get_text(" ", strip=True)
            if key:
                fields[key] = val

    # Fallback: dl/dt/dd
    if not fields:
        for dl in soup.select("dl"):
            for dt in dl.find_all("dt"):
                dd = dt.find_next_sibling("dd")
                if dd:
                    fields[dt.get_text(strip=True).rstrip(":")] = dd.get_text(" ", strip=True)

    # Fallback: таблица
    if not fields:
        for row in soup.select("table tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                val = cells[1].get_text(" ", strip=True)
                if key:
                    fields[key] = val

    return fields


def _parse_record_page(html: str, url: str, debug: bool = False) -> EbidRecord | None:
    """
    Парсит страницу документа. Возвращает None если это не карта.
    """
    if debug:
        print("\n─── ЭБИД record HTML (первые 3000 символов) ───")
        print(html[:3000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    fields = _parse_drupal_fields(soup)

    # Фильтр: только «Карта» (или схема, план, чертёж)
    # Требуем ЯВНОЕ наличие типа — если поле пустое, это не карта (слишком много шума)
    doc_type = fields.get("Виды документов", "")
    map_keywords = ("карта", "план", "атлас", "схема", "чертёж")
    if not any(kw in doc_type.lower() for kw in map_keywords):
        return None  # поле пустое или тип не картографический

    date_raw = fields.get("Дата документа", "") or fields.get("Даты", "")
    y_from, y_to = _parse_years(date_raw)

    return EbidRecord(
        title=title or fields.get("Название документа", ""),
        doc_type=doc_type,
        bib_description=fields.get("Библиографическое описание", "")[:300],
        date_raw=date_raw,
        year_from=y_from,
        year_to=y_to,
        fund_code=fields.get("Шифр", ""),
        archive=fields.get("Архив", ""),
        geography=fields.get("География", ""),
        thematic=fields.get("Тематика", "")[:150],
        source=fields.get("Источник документа", "")[:150],
        url=url,
    )


def _parse_search_results(html: str, debug: bool = False) -> list[str]:
    """Извлекает URL документов из страницы результатов."""
    if debug:
        print("\n─── ЭБИД search HTML (первые 4000 символов) ───")
        print(html[:4000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=re.compile(r"/ru/nodes/\d+")):
        href: str = a["href"].split("?")[0]  # убираем query string
        url = (BASE_URL + href) if href.startswith("/") else href
        if url not in seen:
            seen.add(url)
            links.append(url)

    return links


def search_query(session: requests.Session, query: str,
                 year_from: int | None = None, year_to: int | None = None,
                 max_pages: int = 20,
                 debug: bool = False) -> Iterator[EbidRecord]:
    """Поиск по одному запросу, постфильтрация по «Виды документов == карта»."""
    found_total = 0

    for page in range(1, max_pages + 1):
        params: dict[str, str | int] = {
            "query":     query,
            "commit":    "Найти",
            "meta_data": "on",
            "texts":     "on",
        }
        if page > 1:
            params["page"] = page

        time.sleep(2.0)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"[ЭБИД] Ошибка стр.{page}: {e}")
            break

        if debug and page == 1:
            # Показываем полный URL запроса
            print(f"[ЭБИД] URL: {resp.url}")

        links = _parse_search_results(resp.text, debug=(debug and page == 1))
        if not links:
            if page == 1:
                print(f"[ЭБИД] {query!r}: ссылки не найдены (проверь --debug)")
            break

        if page == 1:
            m = re.search(r"Найдено\s+(\d+)\s+результат", resp.text, re.I)
            total_str = m.group(1) if m else "?"
            print(f"[ЭБИД] {query!r}: {total_str} результатов (фильтруем по типу «Карта»)")

        maps_on_page = 0
        for doc_url in links:
            time.sleep(1.5)
            try:
                r = session.get(doc_url, timeout=20)
                r.raise_for_status()
            except Exception as e:
                print(f"[ЭБИД] Ошибка {doc_url}: {e}")
                continue

            rec = _parse_record_page(r.text, doc_url, debug=(debug and found_total == 0))
            if rec is None:
                continue  # не карта

            if year_from and rec.year_to and rec.year_to < year_from:
                continue
            if year_to and rec.year_from and rec.year_from > year_to:
                continue

            found_total += 1
            maps_on_page += 1
            yield rec

        print(f"[ЭБИД]   стр.{page}: {len(links)} документов, из них карт: {maps_on_page} "
              f"(итого карт: {found_total})")

        # Если на странице нет карт несколько страниц подряд — можно остановить досрочно
        # (осторожно: карты могут быть разбросаны среди других документов)


def search(query: str, year_from: int | None = None,
           year_to: int | None = None,
           max_pages: int = 20,
           debug: bool = False) -> Iterator[EbidRecord]:
    session = _make_session()
    yield from search_query(session, query, year_from, year_to, max_pages, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск карт в ЭБИД (docs.historyrussia.org)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос")
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--max-pages", type=int, default=20,   dest="max_pages")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.all_queries:
        session = _make_session()
        seen: set[str] = set()
        total = 0
        for ter in TERRITORIES:
            for kw in ("карта", "план", "атлас"):
                q = f"{kw} {ter}"
                for rec in search_query(session, q, args.year_from, args.year_to,
                                        max_pages=5):
                    if rec.url not in seen:
                        seen.add(rec.url)
                        total += 1
                        yr = f"{rec.year_from or '?'}–{rec.year_to or '?'}"
                        print(f"  {yr:<12} [{rec.archive[:15]}] {rec.title[:50]}")
        print(f"\n[ЭБИД] Итого уникальных карт: {total}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to,
                          args.max_pages, args.debug))
    print(f"\n[ЭБИД] Карт: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} [{r.fund_code[:18]}] {r.title[:50]}")
        print(f"             {r.url}")
        if r.geography:
            print(f"             {r.geography[:80]}")


if __name__ == "__main__":
    main()
