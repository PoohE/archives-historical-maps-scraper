"""
РОСАРХИВ ОНЛАЙН (online.archives.ru)
Поисковая система федеральных архивов.

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (из скрина 2026-07-10)
══════════════════════════════════════════════════════════════

URL поиска: http://online.archives.ru/search/?q=<запрос>
Протокол:   HTTP (не HTTPS)
Сортировка: по релевантности / префиксу / популярности / частоте вхождений

Результаты: иерархический список Фонд / Опись / Дело
  Каждый элемент: кликабельная ссылка на карточку дела
  URL записи: /search/{id_фонда}/{id_описи}/.../#{!}

Карточка дела (вкладка "Карточка дела"):
  Номер дела, Том, Год начала/окончания дела,
  Крайние даты документов в деле, Аннотация, География,
  Персоналии, Ключевые слова, Количество документов в деле

══════════════════════════════════════════════════════════════
ЦЕННЫЕ ИСТОЧНИКИ (Фонд 1356)
══════════════════════════════════════════════════════════════

Фонд 1356 — Губернские, уездные и городские атласы, карты и планы
генерального межевания 1766-1883 гг. (коллекция), Опись 1.
Содержит: уездные карты Калужской, Пермской, Смоленской, Ярославской губерний.

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_rosarchive.py "карта калужская"
  python searcher_rosarchive.py "карта калужская" --debug
  python searcher_rosarchive.py --all-queries --year-from 1700 --year-to 1920
"""

import re
import sys
import time
import argparse
from dataclasses import dataclass
from typing import Iterator

import ssl
import requests
import urllib3
from requests.adapters import HTTPAdapter
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup


class _NoSSLVerifyAdapter(HTTPAdapter):
    """Отключает проверку SSL-сертификата на уровне urllib3 (обход Windows CA)."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)

SEARCH_URL = "https://online.archives.ru/search/"
BASE_URL   = "https://online.archives.ru"

KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж"]
TERRITORIES = [
    "Калужская", "Калужской", "Калужского",
    "Пермская",  "Пермской",  "Пермского",
    "Смоленская", "Смоленской", "Смоленского",
    "Ярославская", "Ярославской", "Ярославского",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class RosarchiveRecord:
    title: str = ""
    fund: str = ""
    inventory: str = ""
    case_num: str = ""
    year_from: int | None = None
    year_to: int | None = None
    annotation: str = ""
    geography: str = ""
    keywords: str = ""
    doc_count: str = ""
    url: str = ""
    library_id: str = "rosarchive"
    library_name: str = "Росархив Онлайн"


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    s.mount("https://", _NoSSLVerifyAdapter())
    return s


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _extract_case_url(href: str) -> str:
    """Нормализует ссылку на дело, убирая #! fragment."""
    if href.startswith("http"):
        url = href
    else:
        url = BASE_URL + href
    # Убираем fragment #! (он нужен только для SPA-навигации браузера)
    url = url.split("#")[0].rstrip("/") + "/"
    return url


def _parse_case_page(html: str, debug: bool = False) -> dict:
    """Парсит страницу карточки дела."""
    if debug:
        print("\n─── case HTML (первые 3000 символов) ───")
        print(html[:3000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    data: dict[str, str] = {}

    # Заголовок
    h1 = soup.find("h1")
    if h1:
        data["_title"] = h1.get_text(strip=True)

    # Таблица или dl с полями карточки
    # Вариант 1: таблица с парами <th>/<td>
    for row in soup.select("table tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            key = cells[0].get_text(strip=True).rstrip(":")
            val = cells[1].get_text(" ", strip=True)
            if key:
                data[key] = val

    # Вариант 2: div-пары label/value (распространённая CMS-разметка)
    if len(data) <= 1:
        for label in soup.select(".field-label, .prop-name, .card-label"):
            val_el = label.find_next_sibling(
                class_=re.compile(r"field-item|prop-val|card-val")
            )
            if val_el:
                data[label.get_text(strip=True).rstrip(":")] = val_el.get_text(" ", strip=True)

    # Вариант 3: dl/dt/dd
    if len(data) <= 1:
        for dl in soup.select("dl"):
            for dt in dl.find_all("dt"):
                dd = dt.find_next_sibling("dd")
                if dd:
                    data[dt.get_text(strip=True).rstrip(":")] = dd.get_text(" ", strip=True)

    return data


def _parse_search_page(html: str, debug: bool = False) -> list[tuple[str, str]]:
    """
    Парсит страницу результатов поиска.
    Возвращает: [(url, link_text), ...]
    """
    if debug:
        print("\n─── search HTML (первые 4000 символов) ───")
        print(html[:4000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Ищем ссылки с числовыми путями (иерархические ID узлов Росархива)
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # URL вида /search/1000.../1000.../.../ или аналогичный
        if re.search(r"/search/\d{8,}", href) or re.search(r"/\d{14,}/", href):
            url = _extract_case_url(href)
            if url not in seen:
                seen.add(url)
                results.append((url, a.get_text(strip=True)))

    return results


def _has_next_page(soup: BeautifulSoup, current: int) -> bool:
    """Проверяет есть ли следующая страница пагинации."""
    # Ищем «следующая», «>» или числовой диапазон «из N»
    text = soup.get_text()
    m = re.search(r"Найдено\s+(\d+)\s+результат", text, re.I)
    if m:
        total = int(m.group(1))
        # предполагаем ~10 результатов на страницу (скорректировать после теста)
        return current * 10 < total
    next_a = soup.find("a", string=re.compile(r"следующ|Следующ|»|>", re.I))
    return next_a is not None


def search_query(session: requests.Session, query: str,
                 year_from: int | None = None, year_to: int | None = None,
                 debug: bool = False) -> Iterator[RosarchiveRecord]:
    """Поиск по одному запросу."""
    page = 1
    found_total = 0
    seen: set[str] = set()

    while True:
        params: dict[str, str | int] = {"q": query}
        if page > 1:
            params["page"] = page

        time.sleep(2.0)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"[Росархив] Ошибка стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        results = _parse_search_page(resp.text, debug=(debug and page == 1))

        if not results:
            if page == 1:
                print(f"[Росархив] {query!r}: ссылки на дела не найдены "
                      f"(нужна проверка HTML-структуры — запустить с --debug)")
            break

        if page == 1:
            # Пробуем вычитать общее число результатов
            m = re.search(r"Найдено\s+(\d+)\s+результат", soup.get_text(), re.I)
            total_str = m.group(1) if m else "?"
            print(f"[Росархив] {query!r}: {total_str} результатов, страница {page}")

        for url, link_text in results:
            if url in seen:
                continue
            seen.add(url)

            time.sleep(1.5)
            try:
                r = session.get(url, timeout=20)
                r.raise_for_status()
            except Exception as e:
                print(f"[Росархив] Ошибка {url}: {e}")
                continue

            data = _parse_case_page(r.text, debug=(debug and found_total == 0))

            title = data.get("_title", link_text)

            date_text = (
                data.get("Год начала дела", "") + " " +
                data.get("Год окончания дела", "") + " " +
                data.get("Крайние даты документов в деле", "")
            )
            y_from, y_to = _parse_years(date_text)

            if year_from and y_to and y_to < year_from:
                continue
            if year_to and y_from and y_from > year_to:
                continue

            found_total += 1
            yield RosarchiveRecord(
                title=title,
                case_num=data.get("Номер дела", ""),
                year_from=y_from,
                year_to=y_to,
                annotation=data.get("Аннотация", "")[:300],
                geography=data.get("География", ""),
                keywords=data.get("Ключевые слова", ""),
                doc_count=data.get("Количество документов в деле", ""),
                url=url,
            )

        print(f"[Росархив]   стр.{page}: {len(results)} дел, итого {found_total}")

        if not _has_next_page(soup, page):
            break
        page += 1


def search(query: str, year_from: int | None = None,
           year_to: int | None = None,
           debug: bool = False) -> Iterator[RosarchiveRecord]:
    session = _make_session()
    yield from search_query(session, query, year_from, year_to, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск дел в Росархив Онлайн (online.archives.ru)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос")
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.all_queries:
        session = _make_session()
        seen: set[str] = set()
        total = 0
        for kw in KEYWORDS:
            for ter in TERRITORIES:
                q = f"{kw} {ter}"
                for rec in search_query(session, q, args.year_from, args.year_to):
                    if rec.url not in seen:
                        seen.add(rec.url)
                        total += 1
                        yr = f"{rec.year_from or '?'}–{rec.year_to or '?'}"
                        print(f"  {yr:<12} {rec.title[:60]}")
        print(f"\n[Росархив] Итого уникальных дел: {total}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to, args.debug))
    print(f"\n[Росархив] Дел: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} {r.title[:65]}")
        print(f"             {r.url}")
        if r.annotation:
            print(f"             {r.annotation[:80]}")


if __name__ == "__main__":
    main()
