"""
ГАРФ — Государственный архив РФ (НЕ frameset, а обычный GET-поиск)
https://fgurgia.ru/search

Скриншот 2026-07-18 показал: это простой GET-запрос, не AJAX!
URL: fgurgia.ru/search?p0=v-<query>&type=simple&p0_c=12

Параметры:
  p0    — запрос с префиксом v-
  type  — simple (остальные: ?, ?)
  p0_c  — тип документа (12 = карты/планы?)
  p0_1  — фильтр 1 (пусто)
  p0_d  — дата? (пусто)
  p0_a  — неизвестный (72425)
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote

BASE_URL = "https://fgurgia.ru"
SEARCH_URL = f"{BASE_URL}/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": SEARCH_URL,
}


@dataclass
class GarfRecord:
    title: str = ""
    fund_num: str = ""
    opisi_num: str = ""
    delo_num: str = ""
    year_from: int | None = None
    year_to: int | None = None
    url: str = ""
    library_id: str = "garf"
    library_name: str = "ГАРФ (Государственный архив РФ)"


def search(query: str, debug: bool = False) -> Iterator[GarfRecord]:
    """
    Поиск в ГАРФ. 
    Параметры подобраны из скриншота DevTools (2026-07-18).
    """
    
    params = {
        "p0": f"v-{query}",  # префикс v-
        "type": "simple",
        "p0_1": "",
        "p0_d": "",
        "p0_c": "12",  # тип документа (предположительно карты)
        "p0_a": "72425",  # копируем из скриншота
    }
    
    time.sleep(2)
    try:
        resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ГАРФ] Ошибка поиска '{query}': {e}")
        return
    
    if debug:
        print(f"\n─── HTML поиска (первые 3000 символов) ───")
        print(resp.text[:3000])
        print("─── конец ───\n")
    
    soup = BeautifulSoup(resp.text, "lxml")
    
    # Селекторы для результатов поиска (нужны уточнения по структуре HTML)
    # Пока: ищем таблицу или список результатов
    results_section = soup.find("table") or soup.find("ul", class_="results")
    
    if not results_section:
        print(f"[ГАРФ] Результаты не найдены (проверить селекторы HTML)")
        return
    
    # Парсим строки результатов
    rows = results_section.find_all("tr") if results_section.name == "table" else results_section.find_all("li")
    
    for row in rows:
        # Парсим: Фонд | Опись | Дело | Название | Даты
        cells = row.find_all("td") if row.name == "tr" else [row]
        if not cells or len(cells) < 2:
            continue
        
        try:
            # Предположительная структура: Ф.NN Оп.N Д.NN Название Даты
            text = row.get_text(" ", strip=True)
            
            # Парсим номера
            fund_match = re.search(r"Ф\.(\d+)", text)
            opisi_match = re.search(r"Оп\.(\d+)", text)
            delo_match = re.search(r"Д\.(\d+)", text)
            
            fund_num = fund_match.group(1) if fund_match else ""
            opisi_num = opisi_match.group(1) if opisi_match else ""
            delo_num = delo_match.group(1) if delo_match else ""
            
            # Парсим года
            years = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
            year_from = int(years[0]) if years else None
            year_to = int(years[-1]) if years else None
            
            yield GarfRecord(
                title=text[:100],
                fund_num=fund_num,
                opisi_num=opisi_num,
                delo_num=delo_num,
                year_from=year_from,
                year_to=year_to,
            )
        except Exception as e:
            print(f"[ГАРФ] Ошибка парсинга строки: {e}")
            continue


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Поиск в ГАРФ (fgurgia.ru)"
    )
    parser.add_argument("query", nargs="?", default="карта Калужской")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    print(f"\n[ГАРФ] Поиск: {args.query}")
    
    results = list(search(args.query, debug=args.debug))
    print(f"[ГАРФ] Найдено: {len(results)}")
    
    for r in results[:10]:
        print(f"  Ф.{r.fund_num} Оп.{r.opisi_num} Д.{r.delo_num} | {r.title[:50]}")


if __name__ == "__main__":
    main()
