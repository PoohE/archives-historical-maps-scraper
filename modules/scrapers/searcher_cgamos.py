"""
ЦГА Москвы — Центральный государственный архив г. Москвы (Главархив)
https://cgamos.ru — Электронный каталог

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (из скрина 2026-07-16)
══════════════════════════════════════════════════════════════

URL поиска:  https://cgamos.ru/book_search
Метод:       GET
Режим:       «По архивным документам» (по умолчанию)

Параметры расширенного поиска:
  title   — слова в заголовке дела   ← основной параметр
  from    — год начала периода
  to      — год конца периода
  fnd     — название фонда (необязательно)
  inv     — название описи (необязательно)
  page    — страница пагинации

Поля карточки результата (предположительно):
  Шифр дела: Фонд / Опись / Дело
  Название
  Даты документов
  Ссылка на карточку дела

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_cgamos.py "карта Калужской губернии"
  python searcher_cgamos.py "карта" --year-from 1750 --year-to 1917
  python searcher_cgamos.py --all-queries --year-from 1700 --year-to 1920
  python searcher_cgamos.py "план" --debug
"""

import re
import sys
import time
import argparse
from dataclasses import dataclass
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE_URL   = "https://cgamos.ru"
SEARCH_URL = f"{BASE_URL}/book_search"

KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж"]
TERRITORIES = [
    "Калужская губерния", "Калужской",
    "Пермская губерния",  "Пермской",
    "Смоленская губерния", "Смоленской",
    "Ярославская губерния", "Ярославской",
    "Московская губерния",  "Московской",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": BASE_URL,
}


@dataclass
class CgamosRecord:
    title:      str = ""
    fund:       str = ""
    fund_name:  str = ""
    inventory:  str = ""
    case_num:   str = ""
    year_from:  int | None = None
    year_to:    int | None = None
    url:        str = ""
    library_id:   str = "cgamos"
    library_name: str = "ЦГА Москвы — Центральный государственный архив г. Москвы"


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
    """Извлекает (фонд, опись, дело) из текста."""
    fund = inv = case = ""
    m = re.search(r"Ф[.\s]+([\w.-]+)", text)
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
    Парсит страницу результатов.
    Возвращает (записи, есть_следующая_страница).
    """
    if debug:
        print("\n─── HTML поиска (первые 5000 символов) ───")
        print(html[:5000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    records: list[dict] = []
    seen: set[str] = set()

    # Вариант 1: ссылки с паттерном /book/{id}/ или /docs/{id}/ или /arch-doc/
    doc_re = re.compile(r"/(book|docs|doc|arch-doc|delo|item)/\d+", re.I)
    for a in soup.find_all("a", href=doc_re):
        href = a["href"]
        url = href if href.startswith("http") else BASE_URL + href
        if url in seen:
            continue
        seen.add(url)
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        container = a.find_parent("tr") or a.find_parent("li") or a.find_parent("div") or a.parent
        row_text = container.get_text(" ", strip=True) if container else title
        records.append({"title": title, "url": url, "row_text": row_text})

    # Вариант 2: если не нашлось — искать ссылки с book_search и конкретными ID
    if not records:
        for a in soup.find_all("a", href=re.compile(r"/book_search/\d+")):
            href = a["href"]
            url = href if href.startswith("http") else BASE_URL + href
            if url in seen:
                continue
            seen.add(url)
            title = a.get_text(" ", strip=True)
            container = a.find_parent("tr") or a.parent
            row_text = container.get_text(" ", strip=True) if container else title
            records.append({"title": title, "url": url, "row_text": row_text})

    # Вариант 3: строки таблицы с шифрами
    if not records:
        for row in soup.select("tr, .result-item, .search-result"):
            text = row.get_text(" ", strip=True)
            if re.search(r"\d{3,}\s*/\s*\d+\s*/\s*\d+", text):  # паттерн номер/опись/дело
                link = row.find("a", href=True)
                if link:
                    href = link["href"]
                    url = href if href.startswith("http") else BASE_URL + href
                    if url not in seen:
                        seen.add(url)
                        records.append({
                            "title": link.get_text(strip=True),
                            "url":   url,
                            "row_text": text,
                        })

    has_next = bool(
        soup.find("a", string=re.compile(r"Следующ|»", re.I))
        or soup.find("a", rel="next")
        or soup.select_one("a.next, li.next > a, .pagination__next")
    )

    return records, has_next


def search_query(session: requests.Session, query: str,
                 year_from: int | None = None, year_to: int | None = None,
                 debug: bool = False) -> Iterator[CgamosRecord]:
    page = 1
    found_total = 0
    seen: set[str] = set()

    while True:
        params: dict[str, str | int] = {"title": query}
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
            print(f"[ЦГА Москвы] Ошибка стр.{page}: {e}")
            break

        raw, has_next = _parse_search_page(resp.text, debug=(debug and page == 1))

        if not raw:
            if page == 1:
                print(f"[ЦГА Москвы] {query!r}: записей не найдено. "
                      f"Запустить с --debug для анализа HTML.")
            break

        if page == 1:
            soup = BeautifulSoup(resp.text, "lxml")
            cnt_m = re.search(r"(\d[\d\s]*)\s*запис|Найдено[:\s]+(\d+)", soup.get_text(), re.I)
            if cnt_m:
                n = (cnt_m.group(1) or cnt_m.group(2)).replace(" ", "")
                print(f"[ЦГА Москвы] {query!r}: ~{n} записей")

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
            found_total += 1
            yield CgamosRecord(
                title=rec["title"],
                fund=fund,
                inventory=inv,
                case_num=case,
                year_from=y_from,
                year_to=y_to,
                url=rec["url"],
            )

        print(f"[ЦГА Москвы]   стр.{page}: {len(raw)} найдено, итого {found_total}")

        if not has_next:
            break
        page += 1


def search(query: str, year_from: int | None = None,
           year_to: int | None = None, debug: bool = False) -> Iterator[CgamosRecord]:
    session = _make_session()
    yield from search_query(session, query, year_from, year_to, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Поиск дел в ЦГА Москвы (cgamos.ru)"
    )
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--year-from", type=int, default=1700, dest="year_from")
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
                        print(f"  {yr:<12} {rec.title[:65]}")
        print(f"\n[ЦГА Москвы] Итого: {total}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to, args.debug))
    print(f"\n[ЦГА Москвы] Найдено: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        cipher = " ".join(filter(None, [r.fund, r.inventory, r.case_num]))
        print(f"  {yr:<12} {cipher}")
        print(f"             {r.title[:70]}")
        if r.url:
            print(f"             {r.url}")


if __name__ == "__main__":
    main()
