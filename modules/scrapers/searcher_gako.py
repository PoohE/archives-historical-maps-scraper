"""
ГАКО — Государственный архив Калужской области
https://archive.admoblkaluga.ru — Электронный каталог

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

URL поиска:  https://archive.admoblkaluga.ru/gako/search
Метод:       GET
Параметры:
  p0.v            — значение поиска
  type            — тип запроса ("simple")
  p0.t            — (пустое)
  p0.d            — (пустое)
  searchObjectType — тип объекта поиска:
                     "Doc"  → Дела   (37 для запроса "карта") ← нас интересует
                     "I"    → Описи  (114 для запроса "карта")
                     "F"    → Фонды  (1)
  page            — страница (при пагинации)

Результаты (из скрина 2026-07-16):
  Вкладка "Дело (37)": список дел с шифрами Ф.Ф-30 Оп.1 Д.XXX
  URL дела: вероятно /gako/docs/{id} или аналогичный

⚠ ВАЖНО: если searchObjectType="Doc" не работает — запустить с --debug,
  открыть archive.admoblkaluga.ru в браузере → вкладка "Дело" → DevTools Network
  → скопировать значение searchObjectType из URL.

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_gako.py "карта Калужская губерния"
  python searcher_gako.py "карта" --debug
  python searcher_gako.py "план" --search-type Doc
  python searcher_gako.py --all-queries --year-from 1700 --year-to 1920
"""

import re
import sys
import time
import argparse
from dataclasses import dataclass
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE_URL   = "https://archive.admoblkaluga.ru"
SEARCH_URL = f"{BASE_URL}/gako/search"

KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж"]
TERRITORIES = [
    "Калужская губерния", "Калужское наместничество",
    "Калужской", "Калужского",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": BASE_URL,
}


@dataclass
class GakoRecord:
    title:      str = ""
    cipher:     str = ""      # Ф.Ф-30 Оп.1 Д.757
    fund:       str = ""
    inventory:  str = ""
    case_num:   str = ""
    year_from:  int | None = None
    year_to:    int | None = None
    url:        str = ""
    library_id:   str = "gako"
    library_name: str = "ГАКО — Государственный архив Калужской области"


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


def _parse_cipher(text: str) -> tuple[str, str, str, str]:
    """Извлекает (шифр, фонд, опись, дело) из строки."""
    cipher = ""
    m = re.search(r"(Ф[.\s][\w.-]+\s+[Оо]п[.\s]\S+\s+Д[.\s]\S+)", text)
    if m:
        cipher = m.group(1).strip()
    fund = inv = case = ""
    m2 = re.search(r"Ф[.\s]+([\w.-]+)", text)
    if m2:
        fund = m2.group(1)
    m3 = re.search(r"[Оо]п[.\s]+(\S+)", text)
    if m3:
        inv = m3.group(1)
    m4 = re.search(r"Д[.\s]+(\d+\w*)", text)
    if m4:
        case = m4.group(1)
    return cipher, fund, inv, case


def _parse_search_page(html: str, debug: bool = False) -> tuple[list[dict], bool, int]:
    """
    Парсит страницу результатов.
    Возвращает (записи, есть_следующая, всего_результатов).
    """
    if debug:
        print("\n─── HTML поиска (первые 5000 символов) ───")
        print(html[:5000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    records: list[dict] = []

    total = 0
    total_m = re.search(r"Результаты[^:]*:\s*[\d-]+\s+из\s+(\d+)", soup.get_text())
    if total_m:
        total = int(total_m.group(1))

    # Ищем ссылки на страницы дел
    doc_re = re.compile(r"/gako/", re.I)
    seen: set[str] = set()
    for a in soup.find_all("a", href=doc_re):
        href = a["href"]
        # Пропускаем служебные ссылки
        if any(x in href for x in ["search", "javascript", "#"]):
            continue
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        container = a.find_parent("tr") or a.find_parent("li") or a.parent
        row_text = container.get_text(" ", strip=True) if container else title
        records.append({"title": title, "url": url, "row_text": row_text})

    # Если ссылки не нашлись — ищем строки с шифрами дел напрямую
    if not records:
        for row in soup.select("tr, .result-row, .search-item"):
            text = row.get_text(" ", strip=True)
            if re.search(r"Ф\.\s*[\w-]+\s+[Оо]п\.\s*\d+\s+Д\.\s*\d+", text):
                link = row.find("a", href=True)
                url = ""
                if link:
                    href = link["href"]
                    url = href if href.startswith("http") else BASE_URL + href
                records.append({
                    "title": row.find("a").get_text(strip=True) if row.find("a") else text[:80],
                    "url":   url,
                    "row_text": text,
                })

    has_next = bool(
        soup.find("a", string=re.compile(r"Следующ|»", re.I))
        or soup.find("a", rel="next")
        or soup.select_one("a.next, li.next > a")
    )

    return records, has_next, total


def search_query(session: requests.Session, query: str,
                 year_from: int | None = None, year_to: int | None = None,
                 search_type: str = "Doc", debug: bool = False) -> Iterator[GakoRecord]:
    page = 1
    found_total = 0
    seen: set[str] = set()

    while True:
        params: dict[str, str | int] = {
            "p0.v":           query,
            "type":           "simple",
            "p0.t":           "",
            "p0.d":           "",
            "searchObjectType": search_type,
        }
        if page > 1:
            params["page"] = page

        time.sleep(2.0)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=25)
            resp.raise_for_status()
        except Exception as e:
            print(f"[ГАКО] Ошибка стр.{page}: {e}")
            break

        raw, has_next, total = _parse_search_page(resp.text, debug=(debug and page == 1))

        if not raw:
            if page == 1:
                if search_type == "Doc":
                    print(f"[ГАКО] {query!r}: дела не найдены (searchObjectType={search_type!r}).")
                    print("  → Если 0 результатов — открыть вкладку «Дело» в браузере,"
                          " DevTools→Network, скопировать значение searchObjectType из URL,"
                          " передать через --search-type")
                else:
                    print(f"[ГАКО] {query!r}: записей не найдено. "
                          f"Запустить с --debug для анализа HTML.")
            break

        if page == 1 and total:
            print(f"[ГАКО] {query!r}: {total} результатов (тип={search_type})")

        for rec in raw:
            if rec["url"] in seen:
                continue
            seen.add(rec["url"])

            y_from, y_to = _parse_years(rec["row_text"])
            if year_from and y_to and y_to < year_from:
                continue
            if year_to and y_from and y_from > year_to:
                continue

            cipher, fund, inv, case = _parse_cipher(rec["row_text"])
            found_total += 1
            yield GakoRecord(
                title=rec["title"],
                cipher=cipher,
                fund=fund,
                inventory=inv,
                case_num=case,
                year_from=y_from,
                year_to=y_to,
                url=rec["url"],
            )

        print(f"[ГАКО]   стр.{page}: {len(raw)} найдено, итого {found_total}")

        if not has_next:
            break
        page += 1


def search(query: str, year_from: int | None = None, year_to: int | None = None,
           search_type: str = "Doc", debug: bool = False) -> Iterator[GakoRecord]:
    session = _make_session()
    yield from search_query(session, query, year_from, year_to, search_type, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Поиск дел в ГАКО (archive.admoblkaluga.ru)"
    )
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--year-from",   type=int, default=1700, dest="year_from")
    parser.add_argument("--year-to",     type=int, default=1920, dest="year_to")
    parser.add_argument("--search-type", default="Doc", dest="search_type",
                        help="Значение searchObjectType (по умолчанию Doc; "
                             "попробовать также: I, F, Inv, Document)")
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
                for rec in search_query(session, q, args.year_from, args.year_to,
                                        args.search_type):
                    if rec.url not in seen:
                        seen.add(rec.url)
                        total += 1
                        yr = f"{rec.year_from or '?'}–{rec.year_to or '?'}"
                        print(f"  {yr:<12} {rec.title[:65]}")
        print(f"\n[ГАКО] Итого: {total}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to,
                          args.search_type, args.debug))
    print(f"\n[ГАКО] Найдено: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} {r.cipher or r.title[:55]}")
        if r.cipher:
            print(f"             {r.title[:70]}")
        if r.url:
            print(f"             {r.url}")


if __name__ == "__main__":
    main()
