"""
ГАЯО — Государственный архив Ярославской области
Интернет-портал архивной службы Ярославской области
https://af.yar-archives.ru

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

URL поиска:  https://af.yar-archives.ru/archive/search
Метод:       GET
Параметры:
  q        — поисковый запрос (морфологический при morph=Y)
  archive  — код архива (0 = все архивы)
  morph    — Y/N (морфологический поиск, рекомендуется Y)
  from, to — год начала / конца документов
  fnum     — номер фонда (необязательно)
  onum     — номер описи (необязательно)
  page     — страница результатов (1-based)

Результаты поиска:
  Два таба: Фонды | Дела  (нас интересуют Дела)
  Строка: Ф.Р-79 Оп.1 т.2 Д.2162 | Название дела | Даты | Архив
  "карта" → 5331 дел; "карта Ярославская губерния" → значительно меньше

URL дела:    https://af.yar-archives.ru/archive{N}/unit/{id}
  Поля: h1=заголовок, хлебные крошки=Фонд/Опись/Дело,
        Кол-во листов, Даты документов, статус оцифровки

Пагинация:   &page=N (проверить при большом числе результатов)

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_gayao.py "карта Ярославская губерния" --year-to 1920
  python searcher_gayao.py "карта" --year-from 1700 --year-to 1917 --debug
  python searcher_gayao.py --all-queries --year-from 1700 --year-to 1920
"""

import re
import sys
import time
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator

import requests
from bs4 import BeautifulSoup

# Импортировать TERRITORIES из modules/territories.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from territories import TERRITORIES

BASE_URL   = "https://af.yar-archives.ru"
SEARCH_URL = f"{BASE_URL}/archive/search"

KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж"]
# TERRITORIES: 49 территорий (4 губ + 4 наместничества + 41 уезд, загружены в Notion 2026-07-18)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": BASE_URL,
}

UNIT_RE = re.compile(r"/archive\d+/unit/\d+")


@dataclass
class GayaoRecord:
    title:      str = ""
    cipher:     str = ""      # Ф.Р-79 Оп.1 Д.2162
    fund:       str = ""
    inventory:  str = ""
    case_num:   str = ""
    year_from:  int | None = None
    year_to:    int | None = None
    archive:    str = ""      # ГБУ ЯО РЦОМиАД и т.д.
    url:        str = ""
    library_id:   str = "gayao"
    library_name: str = "ГАЯО — Государственный архив Ярославской области"


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


def _parse_cipher(text: str) -> tuple[str, str, str]:
    """Извлекает (фонд, опись, дело) из шифра вида 'Ф.Р-79 Оп.1 т.2 Д.2162'."""
    fund = inv = case = ""
    m = re.search(r"Ф[.\s]+([\w-]+)", text)
    if m:
        fund = m.group(1)
    m = re.search(r"[Оо]п[.\s]+(\S+)", text)
    if m:
        inv = m.group(1)
    m = re.search(r"Д[.\s]+(\d+\w*)", text)
    if m:
        case = m.group(1)
    return fund, inv, case


def _parse_search_page(html: str, debug: bool = False) -> tuple[list[dict], bool]:
    """
    Парсит страницу результатов поиска.
    Возвращает (список записей, есть_следующая_страница).
    """
    if debug:
        print("\n─── HTML поиска (первые 5000 символов) ───")
        print(html[:5000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    records: list[dict] = []
    seen_urls: set[str] = set()

    # Все ссылки на страницы дел /archiveN/unit/ID
    for a in soup.find_all("a", href=UNIT_RE):
        href = a["href"]
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen_urls:
            continue
        seen_urls.add(url)

        title = a.get_text(" ", strip=True)

        # Пробуем найти строку-контейнер (tr или li) для доп. данных
        container = a.find_parent("tr") or a.find_parent("li") or a.parent
        row_text = container.get_text(" ", strip=True) if container else title

        records.append({"title": title, "url": url, "row_text": row_text})

    has_next = bool(
        soup.find("a", string=re.compile(r"Следующ|»|>", re.I))
        or soup.find("a", rel="next")
    )
    # Запасной вариант: ссылки на страницы пагинации
    if not has_next:
        pager = soup.select(".pagination a, .pager a, ul.pages a")
        nums = [a.get_text(strip=True) for a in pager if a.get_text(strip=True).isdigit()]
        has_next = len(nums) > 1

    return records, has_next


def search_query(session: requests.Session, query: str,
                 year_from: int | None = None, year_to: int | None = None,
                 debug: bool = False) -> Iterator[GayaoRecord]:
    """Поиск по одному запросу с пагинацией."""
    page = 1
    found_total = 0
    seen: set[str] = set()

    while True:
        params: dict[str, str | int] = {
            "q":       query,
            "archive": 0,
            "morph":   "Y",
        }
        if year_from:
            params["from"] = year_from
        if year_to:
            params["to"] = year_to
        if page > 1:
            params["page"] = page

        time.sleep(2.0)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=25)
            resp.raise_for_status()
        except Exception as e:
            print(f"[ГАЯО] Ошибка стр.{page}: {e}")
            break

        raw, has_next = _parse_search_page(resp.text, debug=(debug and page == 1))

        if not raw:
            if page == 1:
                print(f"[ГАЯО] {query!r}: записей не найдено. "
                      f"Запустить с --debug для анализа HTML.")
            break

        if page == 1:
            soup = BeautifulSoup(resp.text, "lxml")
            cnt_el = soup.select_one(".results-count, .search-count, h2, .count")
            if cnt_el:
                m = re.search(r"(\d[\d\s]*\d|\d)", cnt_el.get_text())
                if m:
                    print(f"[ГАЯО] {query!r}: найдено ~{m.group(1).replace(' ', '')} дел")

        for rec in raw:
            if rec["url"] in seen:
                continue
            seen.add(rec["url"])

            y_from, y_to = _parse_years(rec["row_text"])
            if year_from and y_to and y_to < year_from:
                continue
            if year_to and y_from and y_from > year_to:
                continue

            fund, inv, case = _parse_cipher(rec["row_text"])
            # Шифр из начала строки (до заголовка)
            cipher_m = re.match(r"(Ф\.[\w.\s-]+Д\.\s*\w+)", rec["row_text"])
            cipher = cipher_m.group(1).strip() if cipher_m else ""

            # Архив — обычно в конце строки
            arch_m = re.search(r"(ГБУ|МКУ|ГАУ|ГБУК)\s+[\w\s]+$", rec["row_text"])
            archive = arch_m.group(0).strip() if arch_m else ""

            found_total += 1
            yield GayaoRecord(
                title=rec["title"],
                cipher=cipher,
                fund=fund,
                inventory=inv,
                case_num=case,
                year_from=y_from,
                year_to=y_to,
                archive=archive,
                url=rec["url"],
            )

        print(f"[ГАЯО]   стр.{page}: {len(raw)} найдено, итого {found_total}")

        if not has_next:
            break
        page += 1


def search(query: str, year_from: int | None = None,
           year_to: int | None = None, debug: bool = False) -> Iterator[GayaoRecord]:
    session = _make_session()
    yield from search_query(session, query, year_from, year_to, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Поиск дел в ГАЯО (af.yar-archives.ru)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос")
    parser.add_argument("--year-from", type=int, default=1700, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries",
                        help="Все ключевые слова × территории")
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
                        print(f"  {yr:<12} {rec.title[:65]}")
                        if rec.url:
                            print(f"             {rec.url}")
        print(f"\n[ГАЯО] Итого уникальных: {total}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to, args.debug))
    print(f"\n[ГАЯО] Найдено: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} {r.cipher or r.title[:50]}")
        if r.cipher:
            print(f"             {r.title[:70]}")
        print(f"             {r.url}")


if __name__ == "__main__":
    main()
