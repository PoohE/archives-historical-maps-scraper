"""
ГИС УИАД — Государственная информационная система Единого архивного информационного пространства
https://online.archives.ru/search/full/

Российский государственный архив (Росархив) — система для поиска по 13 федеральным архивам
Содержит: 20+ млн документов, 66,000 фондов, 100,000+ описей

Подтверждено от директора Росархива (2026-07-21):
- URL поиска: https://online.archives.ru/search/full/
- Параметров поиска в документации НЕТ (нужен DevTools анализ)
- Ключевые слова поддерживаются но реализовано не везде
- Фонды с картографией НЕ кодируются централизованно
- Внешнее обращение: неизвестно
"""

import requests
from bs4 import BeautifulSoup
from typing import Generator, Optional
import json

BASE_URL = "https://online.archives.ru/search/full/"


def search_gis_uiad(query: str, max_pages: int = 5) -> Generator[dict, None, None]:
    """
    Поиск по ГИС УИАД.

    Args:
        query: строка поиска (напр. "карта Калужская")
        max_pages: макс. количество страниц результатов

    Yields:
        dict с полями: title, shelfmark, year_from, year_to, url, description, archive_name

    TODO (awaiting DevTools analysis):
    1. Открыть https://online.archives.ru/search/full/ в Chrome DevTools
    2. Выполнить поиск "карта" → Network tab
    3. Найти XHR запрос (может быть JSON API)
    4. Извлечь параметры URL и body
    5. Определить структуру ответа (JSON или HTML?)
    6. Парсить карточки результатов
    7. Обработать пагинацию

    ГИПОТЕЗЫ:
    - Может быть AJAX/JSON API (как ГАКО)
    - Может быть простой GET с параметрами
    - Результаты могут быть в HTML или JSON
    """

    # Вариант 1: GET-запрос
    # params = {
    #     "q": query,  # ← УТОЧНИТЬ
    #     # ... другие параметры из DevTools
    # }

    # Вариант 2: AJAX JSON API
    # headers = {
    #     "X-Requested-With": "XMLHttpRequest",
    #     "Accept": "application/json",
    # }
    # api_url = "https://online.archives.ru/api/search"  # ← УТОЧНИТЬ
    # payload = {"query": query, "page": 1}  # ← УТОЧНИТЬ структуру

    # for page in range(1, max_pages + 1):
    #     try:
    #         # Вариант A: HTML
    #         # resp = requests.get(BASE_URL, params={**params, "page": page}, timeout=20)
    #         # soup = BeautifulSoup(resp.text, "lxml")
    #         # results = soup.find_all("div", class_="search-result")  # ← УТОЧНИТЬ
    #
    #         # Вариант B: JSON
    #         # payload["page"] = page
    #         # resp = requests.post(api_url, json=payload, headers=headers, timeout=20)
    #         # data = resp.json()
    #         # results = data.get("items", [])  # ← УТОЧНИТЬ структуру
    #
    #         # if not results:
    #         #     break
    #
    #         # for item in results:
    #         #     yield {
    #         #         "title": item.get("title"),  # ← УТОЧНИТЬ ключи
    #         #         "shelfmark": item.get("shelfmark"),
    #         #         "year_from": item.get("year_from"),
    #         #         "year_to": item.get("year_to"),
    #         #         "url": item.get("url"),
    #         #         "description": item.get("description"),
    #         #         "archive_name": item.get("archive"),  # какой архив содержит документ
    #         #     }
    #
    #     except Exception as e:
    #         print(f"[ГИС УИАД] Ошибка страница {page}: {e}")
    #         break

    print(f"[ГИС УИАД] Поиск '{query}' — skeleton (требуется DevTools анализ)")
    return
    yield  # type: ignore


if __name__ == "__main__":
    # Тест
    for result in search_gis_uiad("карта Калужская", max_pages=1):
        print(result)
