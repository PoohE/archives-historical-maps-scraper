"""
РОССИЙСКИЙ ГОСУДАРСТВЕННЫЙ ИСТОРИЧЕСКИЙ АРХИВ (РГИА)
Электронный каталог: https://fgurgia.ru

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (из скринов 2026-07-10)
══════════════════════════════════════════════════════════════

РЕЖИМ 1 — Предметный указатель (тематические группы карт):
  URL:  GET https://fgurgia.ru/search
  Параметры:
    type=custom
    searchObjectType=SUBINDEX
    customSearchUnique=d
    p0.v=карта       ← поисковый термин
    p0.t=0           ← смещение (offset)
    p0.d=0
    p0.c=128         ← предположительно, ID коллекции или кол-во на странице
  Результат: список наименований (КАРТА ГАТЧИНСКОГО УЕЗДА, КАРТА МЕСТНОСТИ...)
  каждое — ссылка на объект → fgurgia.ru/object/{id}
  Пагинация: << < 1 из N > >> (параметр смещения для перебора)

РЕЖИМ 2 — Общий поиск (полнотекстовый по заголовкам дел):
  URL:  GET https://fgurgia.ru/search
  Параметры:
    type=simple
    p0.v=карта+Пермская   ← запрос
    p0.i=n                ← регистронезависимый поиск (n=no case)
    p0.d=0                ← смещение в результатах
    p0.c=128
    p0.t=0
  Результат: дела (Шифр, Заголовок, Крайние даты)
  Указывает на fgurgia.ru/object/{id}

Карточка объекта (fgurgia.ru/object/{id}):
  Наименование, Наименование группы, Библиографический источник,
  Примечание, Постоянная ссылка
  Раздел «Дела»:
    Шифр хранения (Ф. NNN Оп. NNN Д. NNN)
    Заголовок дела
    Крайние даты

══════════════════════════════════════════════════════════════
СТРАТЕГИЯ ПОИСКА
══════════════════════════════════════════════════════════════

ПРЕДМЕТНЫЙ УКАЗАТЕЛЬ — для систематического обхода картографических материалов:
  Запросы: "карта", "план", "атлас" → список десятков/сотен тематических групп
  Далее фильтруем по территории в заголовке (Калужская, Пермская и т.д.)

ОБЩИЙ ПОИСК — для прицельного поиска по губернии:
  Запросы: "карта Калужской", "план Пермской" и т.д.
  Возвращает конкретные дела с шифрами.

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_rgia.py "карта Калужской"
  python searcher_rgia.py "карта Пермской" --debug
  python searcher_rgia.py --mode subindex --term карта
  python searcher_rgia.py --all-queries
"""

import re
import sys
import time
import argparse
from dataclasses import dataclass
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE_URL   = "https://fgurgia.ru"
SEARCH_URL = "https://fgurgia.ru/search"

TERRITORIES = [
    "Калужской", "Калужского", "Калужская",
    "Пермской",  "Пермского",  "Пермская",
    "Смоленской", "Смоленского", "Смоленская",
    "Ярославской", "Ярославского", "Ярославская",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://fgurgia.ru/",
}

# Шаг пагинации — кол-во записей на странице (уточнить после теста)
PAGE_SIZE = 20


@dataclass
class RgiaRecord:
    title: str = ""
    fund_code: str = ""        # Шифр: Ф.NNN Оп.NNN Д.NNN
    subject_group: str = ""    # Наименование группы (в предметном указателе)
    year_from: int | None = None
    year_to: int | None = None
    bib_source: str = ""       # Библиографический источник
    notes: str = ""
    url: str = ""              # fgurgia.ru/object/{id}
    library_id: str = "rgia"
    library_name: str = "РГИА (fgurgia.ru)"


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


def _parse_object_page(html: str, obj_url: str, debug: bool = False) -> RgiaRecord:
    """Парсит карточку объекта fgurgia.ru/object/{id}."""
    if debug:
        print("\n─── object HTML (первые 3000 символов) ───")
        print(html[:3000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")

    # Заголовок
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_el = soup.select_one(".title, .name, .heading")
        if title_el:
            title = title_el.get_text(strip=True)

    fields: dict[str, str] = {}

    # Поля — возможны варианты разметки
    # Вариант 1: dl/dt/dd
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            fields[dt.get_text(strip=True).rstrip(":")] = dd.get_text(" ", strip=True)

    # Вариант 2: таблица
    if not fields:
        for row in soup.select("table tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                val = cells[1].get_text(" ", strip=True)
                if key:
                    fields[key] = val

    # Вариант 3: div-пары
    if not fields:
        for el in soup.select(".field, .prop"):
            label = el.select_one(".label, .name")
            value = el.select_one(".value, .val")
            if label and value:
                fields[label.get_text(strip=True).rstrip(":")] = value.get_text(" ", strip=True)

    # Шифр хранения из раздела «Дела»
    fund_code = ""
    cases_section = soup.find(string=re.compile(r"Дела", re.I))
    if cases_section:
        parent = cases_section.find_parent(["div", "section", "ul"])
        if parent:
            # Ищем шифр в виде «Ф. NNN Оп. NNN Д. NNN»
            code_m = re.search(r"Ф\.\s*[\d\-]+\s+Оп\.\s*[\d\-]+[^<\n]*Д\.\s*[\d\-]+",
                                parent.get_text())
            if code_m:
                fund_code = code_m.group(0).strip()

    # Даты
    date_text = (
        fields.get("Крайние даты", "") + " " +
        fields.get("Дата", "") + " " +
        title
    )
    y_from, y_to = _parse_years(date_text)

    return RgiaRecord(
        title=title or fields.get("Наименование", ""),
        fund_code=fund_code or fields.get("Шифр", ""),
        subject_group=fields.get("Наименование группы", ""),
        year_from=y_from,
        year_to=y_to,
        bib_source=fields.get("Библиографический источник", "")[:200],
        notes=fields.get("Примечание", "")[:200],
        url=obj_url,
    )


def _parse_result_links(html: str, debug: bool = False) -> list[str]:
    """
    Извлекает ссылки на объекты из страницы результатов поиска.
    Возвращает: ['/object/NNN', ...]  (абсолютные URL)
    """
    if debug:
        print("\n─── search results HTML (первые 4000 символов) ───")
        print(html[:4000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=re.compile(r"/object/\d+")):
        href: str = a["href"]
        url = BASE_URL + href if href.startswith("/") else href
        if url not in seen:
            seen.add(url)
            links.append(url)

    return links


def _count_total_pages(html: str) -> int:
    """Извлекает общее число страниц из пагинатора «1 из N»."""
    m = re.search(r"из\s+(\d+)", html)
    return int(m.group(1)) if m else 1


def search_simple(session: requests.Session, query: str,
                  year_from: int | None = None, year_to: int | None = None,
                  debug: bool = False) -> Iterator[RgiaRecord]:
    """
    Общий поиск по РГИА (type=simple).
    Хорошо для запросов вида «карта Калужской губернии».
    """
    offset = 0

    while True:
        params = {
            "type":  "simple",
            "p0.v":  query,
            "p0.i":  "n",
            "p0.d":  str(offset),
        }
        time.sleep(2.0)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"[РГИА] Ошибка offset={offset}: {e}")
            break

        links = _parse_result_links(resp.text, debug=(debug and offset == 0))
        if offset == 0:
            total_pages = _count_total_pages(resp.text)
            print(f"[РГИА] {query!r}: {total_pages} стр. результатов")

        if not links:
            break

        for obj_url in links:
            time.sleep(1.5)
            try:
                r = session.get(obj_url, timeout=20)
                r.raise_for_status()
            except Exception as e:
                print(f"[РГИА] Ошибка {obj_url}: {e}")
                continue

            rec = _parse_object_page(r.text, obj_url, debug=(debug and offset == 0))

            if year_from and rec.year_to and rec.year_to < year_from:
                continue
            if year_to and rec.year_from and rec.year_from > year_to:
                continue

            yield rec

        # Следующая страница (смещение)
        offset += PAGE_SIZE
        if offset >= total_pages * PAGE_SIZE:
            break


def search_subindex(session: requests.Session, term: str = "карта",
                    territory_filter: str = "",
                    year_from: int | None = None, year_to: int | None = None,
                    debug: bool = False) -> Iterator[RgiaRecord]:
    """
    Предметный указатель РГИА (searchObjectType=SUBINDEX).
    Возвращает тематические группы карт и их дела.
    """
    offset = 0

    while True:
        params = {
            "type":                "custom",
            "searchObjectType":    "SUBINDEX",
            "customSearchUnique":  "d",
            "p0.v":  term,
            "p0.d":  str(offset),
        }
        time.sleep(2.0)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"[РГИА/предм.] Ошибка offset={offset}: {e}")
            break

        if offset == 0:
            total_pages = _count_total_pages(resp.text)
            print(f"[РГИА/предм.] term={term!r}: {total_pages} стр. в указателе")

        links = _parse_result_links(resp.text, debug=(debug and offset == 0))
        if not links:
            break

        for obj_url in links:
            # Фильтр по территории на уровне URL перед загрузкой — не применяем,
            # чтобы не пропустить нестандартные названия; фильтруем по тексту карточки.
            time.sleep(1.5)
            try:
                r = session.get(obj_url, timeout=20)
                r.raise_for_status()
            except Exception as e:
                print(f"[РГИА/предм.] Ошибка {obj_url}: {e}")
                continue

            rec = _parse_object_page(r.text, obj_url, debug=(debug and offset == 0))

            if territory_filter:
                searchable = (rec.title + rec.subject_group + rec.notes).lower()
                if territory_filter.lower() not in searchable:
                    continue

            if year_from and rec.year_to and rec.year_to < year_from:
                continue
            if year_to and rec.year_from and rec.year_from > year_to:
                continue

            yield rec

        offset += PAGE_SIZE
        if offset >= _count_total_pages(resp.text) * PAGE_SIZE:
            break


def search(query: str, year_from: int | None = None,
           year_to: int | None = None, debug: bool = False) -> Iterator[RgiaRecord]:
    """Поиск через общий режим."""
    session = _make_session()
    yield from search_simple(session, query, year_from, year_to, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск карт в РГИА (fgurgia.ru)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос (для --mode simple)")
    parser.add_argument("--mode", choices=["simple", "subindex"], default="simple",
                        help="simple = общий поиск; subindex = предметный указатель")
    parser.add_argument("--term", default="карта",
                        help="Термин для предметного указателя (по умолчанию: карта)")
    parser.add_argument("--territory", default="",
                        help="Фильтр по территории для режима subindex")
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    session = _make_session()

    if args.mode == "subindex" or not args.query:
        results = list(search_subindex(
            session, args.term, args.territory,
            args.year_from, args.year_to, args.debug
        ))
    elif args.all_queries:
        seen: set[str] = set()
        results = []
        for ter in TERRITORIES:
            for kw in ("карта", "план", "атлас"):
                q = f"{kw} {ter}"
                for rec in search_simple(session, q, args.year_from, args.year_to):
                    if rec.url not in seen:
                        seen.add(rec.url)
                        results.append(rec)
    else:
        results = list(search_simple(
            session, args.query, args.year_from, args.year_to, args.debug
        ))

    print(f"\n[РГИА] Итого: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} [{r.fund_code[:20]}] {r.title[:55]}")
        print(f"             {r.url}")
        if r.bib_source:
            print(f"             Источник: {r.bib_source[:70]}")


if __name__ == "__main__":
    main()
