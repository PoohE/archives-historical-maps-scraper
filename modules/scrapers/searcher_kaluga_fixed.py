"""
Калужская ОНБИБ (библиотека им. В.И. Белинского)
URL: https://ibald.ru (Веб-ИРБИС 64)

Документация: Веб-ИРБИС POST-параметры (скачана 2026-07-18)
Система требует:
1. POST запрос к CGI серверу
2. Параметры: database, query, searchtype, format
3. Возможно требуется session/cookie

Эта библиотека особенно интересна для Калужской губернии.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlencode

BASE_URL = "https://ibald.ru"
SEARCH_CGI = f"{BASE_URL}/cgi-bin/irbis64r_99"  # или другой CGI

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class KalugaRecord:
    title: str = ""
    cipher: str = ""  # Ф.Р-79 Оп.1 Д.2162 (шифр ИРБИС)
    year_from: int | None = None
    year_to: int | None = None
    url: str = ""
    library_id: str = "kaluga_lib"
    library_name: str = "Калужская ОНБИБ им. В.И. Белинского"


def search(query: str, debug: bool = False) -> Iterator[KalugaRecord]:
    """
    Поиск в Калужской библиотеке (Веб-ИРБИС).
    
    POST-параметры Веб-ИРБИС (из документации):
    - database (IBD): выбор базы (обычно имя файла без расширения)
    - searchtype: Шифр, Реквизиты и т.д.
    - query: поисковый запрос
    - count: кол-во результатов
    - sort: сортировка
    """
    
    # Параметры для Веб-ИРБИС POST запроса
    data = {
        "database": "ibald",  # имя БД (нужна проверка)
        "searchtype": "I",  # I = Информационный поиск (может быть другое)
        "query": query,
        "count": "100",  # запросить 100 результатов
        "sort": "DESC",  # по убыванию
        "format": "HTML",
    }
    
    time.sleep(2)
    session = requests.Session()
    session.headers.update(HEADERS)
    
    try:
        # Попробовать POST запрос к CGI
        resp = session.post(SEARCH_CGI, data=data, timeout=30)
        resp.encoding = "windows-1251"  # ИРБИС использует кодировку windows-1251
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        print(f"[Калуга] Таймаут при поиске '{query}' (сервер медленный)")
        return
    except Exception as e:
        print(f"[Калуга] Ошибка POST запроса: {e}")
        # Fallback на GET запрос
        try:
            resp = session.get(f"{BASE_URL}/search?query={query}", timeout=30)
            resp.encoding = "windows-1251"
        except Exception as e2:
            print(f"[Калуга] Ошибка GET запроса: {e2}")
            return
    
    if debug:
        print(f"\n─── HTML поиска (первые 2000 символов) ───")
        print(resp.text[:2000])
        print("─── конец ───\n")
    
    soup = BeautifulSoup(resp.text, "lxml")
    
    # Парсим результаты (селекторы могут отличаться)
    # Типичная структура ИРБИС: таблица с кодом записи (Ф.Р-79), названием, датами
    rows = soup.find_all("tr")
    
    if not rows:
        print(f"[Калуга] Строки результатов не найдены (проверить селекторы)")
        return
    
    for row in rows[1:]:  # пропускаем заголовок
        try:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            
            text = row.get_text(" ", strip=True)
            
            # Парсим шифр (Ф.Р-79 Оп.1 Д.2162)
            cipher_match = re.search(r"Ф\.Р-\d+\s+Оп\.\d+\s+Д\.\d+", text)
            cipher = cipher_match.group(0) if cipher_match else ""
            
            # Парсим года
            years = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
            year_from = int(years[0]) if years else None
            year_to = int(years[-1]) if years else None
            
            yield KalugaRecord(
                title=text[:150],
                cipher=cipher,
                year_from=year_from,
                year_to=year_to,
            )
        except Exception as e:
            print(f"[Калуга] Ошибка парсинга: {e}")
            continue


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Поиск в Калужской ОНБИБ (Веб-ИРБИС)"
    )
    parser.add_argument("query", nargs="?", default="карта Калужской")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    
    print(f"\n[Калуга] Поиск: {args.query}")
    print("[Калуга] ВНИМАНИЕ: параметры ИРБИС нужно уточнить опытным путём!")
    
    results = list(search(args.query, debug=args.debug))
    print(f"[Калуга] Найдено: {len(results)}")
    
    for r in results[:10]:
        yr = f"{r.year_from}-{r.year_to}" if r.year_from else "?"
        print(f"  {r.cipher} [{yr}] {r.title[:50]}")


if __name__ == "__main__":
    main()
