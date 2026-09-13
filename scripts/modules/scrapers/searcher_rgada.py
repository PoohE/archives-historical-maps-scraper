"""
РГАДА — поиск по электронным описям.

Подтверждённый маршрут (2026-09-07):
  http://rgada.info/poisk/index.php
  GET: list_name=<строка>, fund_name=<строка>, Sk=<размер>, page=<номер>

Сайт не предоставляет общего полнотекстового API: поиск выполняется по полям
«Название фонда» и «Название описи». Результат — карточки описей, не дела.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import asdict, dataclass
from typing import Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://rgada.info/"
SEARCH_URL = urljoin(BASE_URL, "poisk/index.php")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; historical-maps-research/1.0)"}


@dataclass
class RgadaRecord:
    fund_number: str = ""
    fund_name: str = ""
    list_number: str = ""
    list_name: str = ""
    repository: str = ""
    years: str = ""
    year_from: int | None = None
    year_to: int | None = None
    case_count: str = ""
    annotation: str = ""
    url: str = ""
    library_id: str = "rgada"
    library_name: str = "РГАДА (rgada.info)"


def _years(value: str) -> tuple[int | None, int | None]:
    found = [int(x) for x in re.findall(r"\b(1[5-9]\d{2}|20\d{2})\b", value)]
    return (min(found), max(found)) if found else (None, None)


def _get(session: requests.Session, params: dict[str, str | int], retries: int = 2) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(SEARCH_URL, params=params, timeout=25)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or "utf-8"
            return response
        except (requests.RequestException, OSError) as exc:
            last = exc
            if attempt < retries:
                print(f"[РГАДА] Временная ошибка; повтор через 3 с ({attempt}/{retries})")
                time.sleep(3)
    assert last is not None
    raise last


def _parse_page(html: str, debug: bool = False) -> tuple[list[RgadaRecord], bool]:
    soup = BeautifulSoup(html, "lxml")
    if debug:
        print("\n─── РГАДА HTML (первые 3000 символов) ───")
        print(html[:3000])
        print("─── конец ───\n")

    records: list[RgadaRecord] = []
    table = next(
        (t for t in soup.find_all("table")
         if "№ фонда" in t.get_text(" ", strip=True)
         and "Название описи" in t.get_text(" ", strip=True)),
        None,
    )
    if table is None:
        return records, False

    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 9:
            continue
        values = [c.get_text(" ", strip=True) for c in cells[:9]]
        if values[0] == "№ фонда":
            continue
        link = cells[8].find("a", href=True)
        if not link:
            continue
        y_from, y_to = _years(values[5])
        records.append(RgadaRecord(
            fund_number=values[0], fund_name=values[1], list_number=values[2],
            list_name=values[3], repository=values[4], years=values[5],
            year_from=y_from, year_to=y_to, case_count=values[6],
            annotation=values[7], url=urljoin(SEARCH_URL, link["href"]),
        ))

    has_next = any(
        a.get("href", "").startswith("?fund_number=") and "page=" in a.get("href", "")
        for a in soup.find_all("a", href=True)
    )
    return records, has_next


def search_rgada(query: str, max_pages: int = 5, delay: float = 1.0,
                 debug: bool = False) -> Iterator[RgadaRecord]:
    """Ищет строку в названиях фондов и описей, удаляя повторы по URL."""
    session = requests.Session()
    session.headers.update(HEADERS)
    seen: set[str] = set()
    for field in ("list_name", "fund_name"):
        for page in range(1, max_pages + 1):
            params: dict[str, str | int] = {field: query, "Sk": 30}
            if page > 1:
                params["page"] = page
            try:
                response = _get(session, params)
            except Exception as exc:
                print(f"[РГАДА] Ошибка {field}, стр.{page}: {exc}")
                break
            records, has_next = _parse_page(response.text, debug=(debug and page == 1))
            print(f"[РГАДА] {field}={query!r}, стр.{page}: {len(records)} описей")
            added = 0
            for record in records:
                if record.url not in seen:
                    seen.add(record.url)
                    added += 1
                    yield record
            # Некоторые страницы РГАДА сохраняют ссылку «следующая» после
            # последней страницы и возвращают уже виденные строки. Без этого
            # условия полный проход бессмысленно повторяет один и тот же набор.
            if not has_next or not records or added == 0:
                break
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Поиск описей РГАДА")
    parser.add_argument("query", nargs="?", default="Калуж")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--csv", help="Путь для CSV-экспорта")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    results = list(search_rgada(args.query, args.max_pages, args.delay, args.debug))
    print(f"\n[РГАДА] Уникальных описей: {len(results)}")
    if args.csv:
        fields = list(asdict(results[0]).keys()) if results else list(RgadaRecord().__dict__.keys())
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(asdict(row) for row in results)
        print(f"[РГАДА] CSV: {args.csv}")
    else:
        for row in results:
            print(f"  Ф.{row.fund_number} Оп.{row.list_number} {row.list_name[:100]}")
            print(f"             {row.url}")


if __name__ == "__main__":
    main()
