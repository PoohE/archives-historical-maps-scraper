"""
ГАПК Архивы Прикамья — раздел /archive/ (сводный каталог фондов)
https://archives.permkrai.ru/archive/

2026-07-18: добавлен поддержка `/archive/search` с AJAX-поиском.
"""

import re
import time
import argparse
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://archives.permkrai.ru/archive"
SEARCH_URL = f"{BASE_URL}/search"

KEYWORDS = ["карта", "план", "чертеж", "геодез", "съемк", "межев"]
TERRITORIES = [
    "Калужск", "Пермск", "Смоленск", "Ярославск",
    "Калужи", "Перми", "Смоленск", "Ярославск"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class SearchRecord:
    title: str = ""
    fond_num: str = ""
    opisi_num: str = ""
    delo_num: str = ""
    year_from: int | None = None
    year_to: int | None = None
    url: str = ""
    library_id: str = "gapk_search"
    library_name: str = "ГАПК Архивы Прикамья (поиск)"


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def search(query: str, year_from: int = 1700, year_to: int = 1920,
           debug: bool = False) -> Iterator[SearchRecord]:
    """Ищет в /archive/search."""
    
    params = {
        "search": query,
        "from": year_from,
        "to": year_to,
    }
    
    time.sleep(2.0)
    try:
        resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ГАПК-поиск] Ошибка при поиске '{query}': {e}")
        return
    
    if debug:
        print(f"\n─── HTML поиска (3000 символов) ───")
        print(resp.text[:3000])
        print("─── конец ───\n")
    
    soup = BeautifulSoup(resp.text, "lxml")
    
    # Ссылки на единицы хранения: /archive/unit/NNNNN или /archive1/unit/NNNNN
    unit_re = re.compile(r"/archive\d*/unit/(\d+)$")
    seen: set[str] = set()
    
    for a in soup.find_all("a", href=unit_re):
        href = a["href"]
        unit_url = href if href.startswith("http") else f"{BASE_URL.rsplit('/', 1)[0]}{href}"
        if unit_url in seen:
            continue
        seen.add(unit_url)
        
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        
        # Хлебные крошки: Главная / Архив / Ф.NN / Оп.N / Д.NNN
        row = a.find_parent("tr") or a.find_parent("li") or a.parent
        row_text = row.get_text(" ", strip=True) if row else title
        
        # Парсим номера фонда/описи/дела из текста
        fond_match = re.search(r"Ф\.(\d+)", row_text)
        opisi_match = re.search(r"Оп\.(\d+)", row_text)
        delo_match = re.search(r"Д\.(\d+)", row_text)
        
        fond_num = fond_match.group(1) if fond_match else ""
        opisi_num = opisi_match.group(1) if opisi_match else ""
        delo_num = delo_match.group(1) if delo_match else ""
        
        y_from, y_to = _parse_years(row_text)
        
        yield SearchRecord(
            title=title,
            fond_num=fond_num,
            opisi_num=opisi_num,
            delo_num=delo_num,
            year_from=y_from,
            year_to=y_to,
            url=unit_url,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск в /archive/search (Архивы Прикамья)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос")
    parser.add_argument("--year-from", type=int, default=1700, dest="year_from")
    parser.add_argument("--year-to", type=int, default=1920, dest="year_to")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries",
                        help="Все ключевые слова × территории")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    if args.all_queries:
        seen: set[str] = set()
        total = 0
        for kw in KEYWORDS:
            for terr in TERRITORIES:
                q = f"{kw} {terr}"
                for rec in search(q, args.year_from, args.year_to, debug=args.debug):
                    key = rec.title + str(rec.year_from)
                    if key not in seen:
                        seen.add(key)
                        total += 1
                        yr = f"{rec.year_from or '?'}–{rec.year_to or '?'}"
                        print(f"  {yr:<12} Ф.{rec.fond_num} Оп.{rec.opisi_num} Д.{rec.delo_num}  {rec.title[:50]}")
                        print(f"             {rec.url}")
        print(f"\n[ГАПК-поиск] Итого уникальных: {total}")
        return
    
    if not args.query:
        parser.error("Укажите запрос или --all-queries")
    
    results = list(search(args.query, args.year_from, args.year_to, debug=args.debug))
    print(f"\n[ГАПК-поиск] Найдено: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} Ф.{r.fond_num} {r.title[:60]}")
        print(f"             {r.url}")


if __name__ == "__main__":
    main()
