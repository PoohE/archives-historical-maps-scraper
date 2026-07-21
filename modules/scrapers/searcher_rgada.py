"""
РГАДА — Российский государственный архив древних актов
https://www.rgada.info

Специализация: документы XV–XIX века, в т.ч. картографические материалы
Фонд 192: Картографический отдел (карты, атласы, чертежи)

Подтверждено от директора РГАДА (2026-07-21):
- Поиск: http://rgada.info/poisk/index.php
- Регистрация НЕ требуется
- API: НЕТ (публичного)
- Выборка по территории: точное соответствие для ф. 1354
"""

import requests
from bs4 import BeautifulSoup
from typing import Generator, Optional

BASE_URL = "http://rgada.info/poisk/index.php"


def search_rgada(query: str, max_pages: int = 5) -> Generator[dict, None, None]:
    """
    Поиск по РГАДА.

    Args:
        query: строка поиска (напр. "карта Калужская")
        max_pages: макс. количество страниц результатов

    Yields:
        dict с полями: title, shelfmark, year_from, year_to, url, description

    TODO (awaiting DevTools analysis):
    1. Найти параметры GET-запроса в форме поиска
    2. Определить селекторы результатов (class/id карточки)
    3. Проверить кодировку (UTF-8?)
    4. Найти пагинацию (если есть)
    5. Тестировать на "карта", "план", "чертёж"
    """

    # Вариант 1: GET-запрос через форму
    # params = {
    #     "q": query,  # ← УТОЧНИТЬ из DevTools
    #     "fund": "",  # для выборки по фонду (1354 = картография?)
    #     # ... другие параметры
    # }

    # for page in range(1, max_pages + 1):
    #     params["p"] = page  # ← УТОЧНИТЬ (может быть offset вместо страницы)
    #
    #     try:
    #         resp = requests.get(BASE_URL, params=params, timeout=20)
    #         resp.encoding = "utf-8"  # ← УТОЧНИТЬ
    #
    #         soup = BeautifulSoup(resp.text, "lxml")
    #
    #         # Найти карточки результатов
    #         # results = soup.find_all("div", class_="search-result")  # ← УТОЧНИТЬ селектор
    #
    #         # if not results:
    #         #     break  # Нет больше результатов
    #
    #         # for item in results:
    #         #     yield {
    #         #         "title": item.find("a", class_="title").text,  # ← УТОЧНИТЬ
    #         #         "shelfmark": item.find("span", class_="shelfmark").text,  # ← УТОЧНИТЬ
    #         #         "year_from": None,  # ← ИЗВЛЕЧЬ если есть
    #         #         "year_to": None,
    #         #         "url": item.find("a").get("href"),
    #         #         "description": item.find("p", class_="desc").text if item.find("p") else "",
    #         #     }
    #
    #     except Exception as e:
    #         print(f"[РГАДА] Ошибка страница {page}: {e}")
    #         break

    print(f"[РГАДА] Поиск '{query}' — skeleton (требуется DevTools анализ)")
    return
    yield  # type: ignore


if __name__ == "__main__":
    # Тест
    for result in search_rgada("карта Калужская", max_pages=1):
        print(result)
