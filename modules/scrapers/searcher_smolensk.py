"""
СМОЛЕНСКАЯ ОБЛАСТНАЯ УНИВЕРСАЛЬНАЯ НАУЧНАЯ БИБЛИОТЕКА им. А.Т. ТВАРДОВСКОГО
Электронная библиотека: https://elib.smolensklib.ru

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

ПОИСКА НЕТ — библиотека работает только как коллекция документов.
Поле «Введите автора, заглавие, тему...» существует, но поиск картографических
слов («карта», «план» и т.д.) возвращает ненадёжные результаты. Единственный
надёжный способ — обойти всю коллекцию целиком.

КОЛЛЕКЦИЯ ДЛЯ ОБХОДА:
  Название:  Отечественные старопечатные издания 19 в.
  URL:       https://elib.smolensklib.ru/search/result
             ?q=&f=group_collection%3A{COLLECTION_NAME}
  Всего:     311 документов (проверено 2026-07-06)
  Страниц:   32 (по ~10 документов)
  Пагинация: ?page=N, где N = 1..32 (1-based)

ФИЛЬТР ПО ТЕМАТИКЕ (боковой фасет):
  Приоритет: тематика содержит «Геогра» → 9 документов на дату проверки
  Остальные: проверяем заголовок на картографические ключевые слова

СТРУКТУРА ЭЛЕМЕНТА СПИСКА:
  Тег:               li или div.result-item (уточнить по HTML)
  Заголовок:         <a> → ссылка на карточку
  Поля:
    - Авторы
    - Другие авторы
    - Организация
    - Выходные сведения (место, издатель, год)
    - Коллекция
    - Тематика   ← ключевой фильтр
    - Тип файла  (PDF)
    - Размер файла

КАРТОЧКА ДОКУМЕНТА:
  URL: определяется из href заголовка в списке (предположительно /catalog/doc/{id})
  Дополнительные поля уточнить при первом запуске.

══════════════════════════════════════════════════════════════
ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ И ПРАВИЛА
══════════════════════════════════════════════════════════════

1. НЕТ ПОИСКА — только обход коллекции. Не пытаться искать по ключевым словам
   через строку поиска — результаты ненадёжны.

2. ЕДИНСТВЕННАЯ КОЛЛЕКЦИЯ — «Отечественные старопечатные издания 19 в.» содержит
   все 311 документов сайта. Другие разделы карт не содержат.

3. ФАСЕТ «ГЕОГРАФИЯ» — в боковой панели доступен фильтр по тематике. URL фасета:
   ?q=&f=group_collection%3A...&f=subject%3AГеография
   Точное имя параметра уточнить при первом запуске (subject или topic или field).

4. ПАГИНАЦИЯ: ?page=N, N начинается с 1. Первая страница доступна и без параметра,
   и с ?page=1 — проверить при запуске.

5. ВСЕ ДОКУМЕНТЫ — PDF. Прямой ссылки на скачивание в списке нет — нужно
   переходить на карточку.

6. ТЕМАТИКА В СПИСКЕ — поле «Тематика» присутствует прямо в элементе списка,
   поэтому дополнительный запрос к карточке нужен только для получения
   прямой ссылки на PDF.

══════════════════════════════════════════════════════════════
ПРОВЕРОЧНЫЙ URL
══════════════════════════════════════════════════════════════

Список (стр. 1):
  https://elib.smolensklib.ru/search/result?q=&f=group_collection%3AОтечественные+старопечатные+издания+19+в.

Фасет «Geography» (предположительно):
  ...&f=subject%3AГеография

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_smolensk.py                    # обойти всю коллекцию
  python searcher_smolensk.py --debug            # дамп HTML первой страницы
  python searcher_smolensk.py --max-pages 3      # только первые 3 страницы (тест)
  python searcher_smolensk.py --geo-only         # только тематика «Геогра» (быстро)
"""

import re
import sys
import time
import argparse
from dataclasses import dataclass, field
from typing import Iterator
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://elib.smolensklib.ru"
COLLECTION = "Отечественные старопечатные издания 19 в."
SEARCH_URL = f"{BASE_URL}/search/result"

# Картографические ключевые слова для фильтрации заголовков
MAP_KEYWORDS = [
    "карт", "план", "атлас", "топограф", "съёмк", "геодез",
    "чертёж", "чертеж", "межев", "географ", "картограф",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}


@dataclass
class SmolRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    subject: str = ""            # Тематика
    organization: str = ""       # Организация
    publication: str = ""        # Выходные сведения
    url: str = ""
    pdf_url: str = ""
    library_id: str = "smolensk"
    library_name: str = "Смоленская ОУНБ им. А.Т. Твардовского (elib)"


def _get(url: str, params: dict | None = None, delay: float = 2.0) -> requests.Response:
    time.sleep(delay)
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _is_cartographic(title: str, subject: str) -> bool:
    text = (title + " " + subject).lower()
    return any(kw in text for kw in MAP_KEYWORDS)


def _parse_list_page(soup: BeautifulSoup, debug: bool = False) -> list[dict]:
    """
    Извлекает записи из страницы списка.
    Возвращает список словарей с полями: title, url, author, publication, subject, organization.
    Структура HTML уточняется при первом запуске через --debug.
    """
    if debug:
        print("\n─── HTML (первые 5000 символов) ───")
        print(soup.prettify()[:5000])
        print("─── конец HTML ───\n")

    records = []

    # Пробуем несколько вариантов структуры (уточнить после первого запуска)
    # Вариант A: нумерованный список ol > li
    items = soup.select("ol.search-results > li, ul.results > li, .result-item")

    # Вариант B: div с порядковым номером
    if not items:
        items = soup.select("div.document-item, div.record, article.result")

    # Вариант C: таблица
    if not items:
        items = soup.select("table.results tr:not(:first-child)")

    # Вариант D: любой элемент с классом содержащим result или document
    if not items:
        items = soup.find_all(
            lambda tag: tag.name in ("li", "div", "article")
            and tag.get("class")
            and any("result" in c or "document" in c or "item" in c
                    for c in tag.get("class", []))
        )

    if not items:
        print("[СОУНБ] Не удалось найти элементы списка — запустите с --debug")
        return []

    for item in items:
        # Заголовок и URL
        title_el = item.find("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        href = title_el.get("href", "")
        url = href if href.startswith("http") else f"{BASE_URL}{href}"

        # Метаданные из строк «Поле: Значение»
        meta: dict[str, str] = {}
        # Пробуем dl/dt/dd
        for dt in item.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                meta[dt.get_text(strip=True).rstrip(":")] = dd.get_text(" ", strip=True)
        # Пробуем span с именем поля
        if not meta:
            for label in item.find_all(class_=re.compile(r"label|field-name|meta-key")):
                value = label.find_next_sibling()
                if value:
                    meta[label.get_text(strip=True).rstrip(":")] = value.get_text(" ", strip=True)
        # Пробуем парсить текст как «Ключ: Значение»
        if not meta:
            text = item.get_text("\n", strip=True)
            for line in text.split("\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()

        author = meta.get("Авторы", "") or meta.get("Автор", "")
        publication = meta.get("Выходные сведения", "") or meta.get("Год", "")
        subject = meta.get("Тематика", "") or meta.get("Тема", "")
        organization = meta.get("Организация", "")

        y_from, y_to = _parse_years(publication or title)

        records.append({
            "title": title,
            "url": url,
            "author": author,
            "publication": publication,
            "subject": subject,
            "organization": organization,
            "year_from": y_from,
            "year_to": y_to,
        })

    return records


def get_collection_page(page: int, geo_only: bool = False) -> requests.Response:
    """Загружает страницу коллекции. page=1..32."""
    params: dict = {
        "q": "",
        "f": f"group_collection%3A{COLLECTION}",
    }
    if geo_only:
        # Добавить фасет по тематике «Геогра» — точный параметр уточнить при запуске
        params["f2"] = "subject%3AГеография"
    if page > 1:
        params["page"] = page
    # Передаём f вручную (уже URL-encoded), строим URL сами
    url = f"{SEARCH_URL}?q=&f=group_collection%3A{quote(COLLECTION)}"
    if geo_only:
        url += f"&f=subject%3A{quote('География')}"
    if page > 1:
        url += f"&page={page}"
    return _get(url)


def search(year_from: int | None = None,
           year_to: int | None = None,
           max_pages: int = 32,
           geo_only: bool = False,
           debug: bool = False) -> Iterator[SmolRecord]:
    """
    Обходит коллекцию «Отечественные старопечатные издания 19 в.»,
    фильтрует по картографическим признакам.
    Исключения пробрасываются наверх (сетевые ошибки).
    """
    total_found = 0

    for page in range(1, max_pages + 1):
        print(f"[СОУНБ] Страница {page}/{max_pages}...", end=" ")
        try:
            resp = get_collection_page(page, geo_only=geo_only)
        except Exception:
            raise  # пробрасываем наверх

        soup = BeautifulSoup(resp.text, "lxml")

        # Проверяем что страница не пустая
        page_text = soup.get_text(" ", strip=True)
        if "Найдено документов: 0" in page_text or len(page_text) < 200:
            print("пусто, стоп")
            break

        records = _parse_list_page(soup, debug=(debug and page == 1))
        if not records:
            print("элементы не найдены, стоп")
            break

        print(f"{len(records)} элементов", end=" → ")

        matched = 0
        for rec in records:
            # Фильтр по картографическим признакам
            if not _is_cartographic(rec["title"], rec["subject"]):
                continue

            # Фильтр по годам
            y_from, y_to = rec["year_from"], rec["year_to"]
            if year_from and y_to and y_to < year_from:
                continue
            if year_to and y_from and y_from > year_to:
                continue

            matched += 1
            total_found += 1
            yield SmolRecord(
                title=rec["title"],
                author=rec["author"],
                year_from=y_from,
                year_to=y_to,
                subject=rec["subject"],
                organization=rec["organization"],
                publication=rec["publication"],
                url=rec["url"],
            )

        print(f"{matched} карт")
        time.sleep(1.0)

    print(f"[СОУНБ] Итого: {total_found} картографических документов")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Обход коллекции Смоленской электронной библиотеки (elib.smolensklib.ru)"
    )
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--max-pages", type=int, default=32,   dest="max_pages",
                        help="Макс. страниц для обхода (32 = вся коллекция)")
    parser.add_argument("--geo-only", action="store_true", dest="geo_only",
                        help="Только тематика «Геогра» (9 документов — быстрее)")
    parser.add_argument("--debug", action="store_true",
                        help="Вывести HTML первой страницы для отладки структуры")
    args = parser.parse_args()

    results = list(search(
        year_from=args.year_from,
        year_to=args.year_to,
        max_pages=args.max_pages,
        geo_only=args.geo_only,
        debug=args.debug,
    ))

    print(f"\n[СОУНБ] Найдено карт в {args.year_from}–{args.year_to}: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} [{r.subject}] {r.title[:60]}")
        print(f"             {r.url}")


if __name__ == "__main__":
    main()
