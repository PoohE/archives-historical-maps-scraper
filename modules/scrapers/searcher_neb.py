"""
НАЦИОНАЛЬНАЯ ЭЛЕКТРОННАЯ БИБЛИОТЕКА (НЭБ)
https://rusneb.ru

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

Поиск:
  URL:    https://rusneb.ru/search/
  Params: q={запрос}&access[]=open&catalog[]=Карты
  Пагинация: &page=N (1-based)
  Размер страницы: ~10 результатов

Важные параметры фильтрации:
  access[]=open          — только свободный доступ
  catalog[]=Карты        — только тип «Карты» (ключевой фильтр)
  catalog[]=Книги        — книги (если нужны атласы в виде книг)

Карточка документа:
  URL: https://rusneb.ru/catalog/{id}/
  Поля:
    - Заглавие
    - Автор
    - Год издания
    - Место издания
    - Издательство
    - Источник (РГБ / РНБ / региональная библиотека)
    - Доступ (свободный / только в ЭЧЗ)
    - Ссылка на просмотр / скачивание
    - Описание (аннотация)
    - Коллекции

══════════════════════════════════════════════════════════════
ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ И ПРАВИЛА
══════════════════════════════════════════════════════════════

1. ДВУХФАЗНЫЙ ПАРСИНГ: поиск → список URL карточек → заход на каждую.
   Без захода на карточку не получить полное библ. описание и ссылку на файл.

2. ФИЛЬТР catalog[]=Карты обязателен — иначе в результатах книги и статьи,
   упоминающие слово «карта» в тексте.

3. Результатов мало — «карта Калужская» + фильтр Карты → ~10-20 записей.
   Пагинацию проверять, но обычно всё на одной странице.

4. access[]=open — только свободный доступ. Записи «только в ЭЧЗ» не содержат
   ссылки на файл и для нашего каталога менее ценны (но можно включить).

5. НЭБ агрегирует из РГБ, РНБ и региональных библиотек — могут быть дубли
   с другими источниками (gpib, permkrai и т.д.). Проверять по заголовку.

6. Robots.txt НЭБ разрешает поисковый обход. Задержка ≥ 2 сек.

══════════════════════════════════════════════════════════════
ПРОВЕРОЧНЫЕ URL
══════════════════════════════════════════════════════════════

  https://rusneb.ru/search/?q=карта+Калужская&access%5B%5D=open&catalog%5B%5D=Карты
  https://rusneb.ru/search/?q=карта+Пермская&access%5B%5D=open&catalog%5B%5D=Карты

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_neb.py "карта Калужская губерния"
  python searcher_neb.py "план Пермская" --no-filter-maps   # без фильтра Карты
  python searcher_neb.py --all-queries                       # все 4 губернии
  python searcher_neb.py "карта Калужская" --debug           # дамп HTML
"""

import re
import time
import argparse
from dataclasses import dataclass, field
from typing import Iterator
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://rusneb.ru"
SEARCH_URL = f"{BASE_URL}/search/"

KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж"]
TERRITORIES = [
    "Калужская губерния", "Калужское наместничество",
    "Пермская губерния", "Пермское наместничество",
    "Смоленская губерния", "Смоленское наместничество",
    "Ярославская губерния", "Ярославское наместничество",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}


@dataclass
class NebRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    place: str = ""
    publisher: str = ""
    source_lib: str = ""        # РГБ / РНБ / ...
    access: str = ""            # свободный / только в ЭЧЗ
    url: str = ""               # карточка на rusneb.ru
    url_viewer: str = ""        # ссылка на просмотр/скачивание
    description: str = ""
    collections: list[str] = field(default_factory=list)
    library_id: str = "neb"
    library_name: str = "Национальная электронная библиотека (НЭБ)"


def _get(url: str, params: dict | None = None, delay: float = 2.0,
         retries: int = 3) -> requests.Response:
    # rusneb.ru периодически отдаёт ReadTimeout — без повторов падает весь прогон
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        time.sleep(delay * attempt)
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            print(f"[НЭБ] Попытка {attempt}/{retries} не удалась: {exc}")
    raise last_exc


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _get_search_urls(query: str, filter_maps: bool = True,
                     debug: bool = False) -> list[str]:
    """
    Выполняет поиск и возвращает список URL карточек.
    """
    # Строим URL вручную — НЭБ использует access[] и catalog[] как массивы
    params_parts = [f"q={quote(query)}"]
    params_parts.append("access%5B%5D=open")
    if filter_maps:
        params_parts.append(f"catalog%5B%5D={quote('Карты')}")

    url = f"{SEARCH_URL}?{'&'.join(params_parts)}"
    print(f"[НЭБ] {url}")

    urls: list[str] = []
    page = 1

    while True:
        page_url = url + (f"&page={page}" if page > 1 else "")
        try:
            resp = _get(page_url)
        except Exception:
            raise

        soup = BeautifulSoup(resp.text, "lxml")

        if debug and page == 1:
            print("\n─── HTML поиска (первые 5000 символов) ───")
            print(soup.prettify()[:5000])
            print("─── конец ───\n")

        # Количество результатов
        if page == 1:
            count_el = soup.select_one(".search-results__count, .results-count, h2")
            if count_el:
                m = re.search(r"(\d+)", count_el.get_text())
                if m:
                    print(f"[НЭБ] Найдено: {m.group(1)}")

        # Ссылки на карточки — href вида /catalog/{id}/
        found_on_page = 0
        catalog_re = re.compile(r"^/catalog/[^/]+/?$")
        seen = set(urls)
        for a in soup.find_all("a", href=catalog_re):
            href = a["href"].rstrip("/")
            full_url = f"{BASE_URL}{href}/"
            if full_url not in seen:
                seen.add(full_url)
                urls.append(full_url)
                found_on_page += 1

        if found_on_page == 0:
            break  # больше результатов нет

        # Проверяем наличие следующей страницы
        next_btn = soup.select_one(
            "a[rel=next], .pagination__next, a.next, [aria-label='Следующая']"
        )
        if not next_btn:
            break
        page += 1
        time.sleep(1.0)

    print(f"[НЭБ] Карточек для обхода: {len(urls)}")
    return urls


def _parse_card(url: str, debug: bool = False) -> NebRecord | None:
    """
    Парсит страницу карточки документа на rusneb.ru/catalog/{id}/.
    Возвращает None если документ не является картой.
    """
    resp = _get(url, delay=1.5)
    soup = BeautifulSoup(resp.text, "lxml")

    if debug:
        print(f"\n─── HTML карточки {url} (5000 символов) ───")
        print(soup.prettify()[:5000])
        print("─── конец ───\n")

    # Заголовок
    title_el = (
        soup.select_one("h1.card__title")
        or soup.select_one("h1")
        or soup.select_one(".document-title")
    )
    title = title_el.get_text(" ", strip=True) if title_el else ""
    if not title:
        return None

    # Метаданные — НЭБ использует dl/dt/dd или таблицу свойств
    meta: dict[str, str] = {}
    meta_links: dict[str, str] = {}  # поля со ссылками (url просмотра и т.д.)

    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            key = dt.get_text(" ", strip=True).rstrip(":")
            val = dd.get_text(" ", strip=True)
            meta[key] = val
            a = dd.find("a", href=True)
            if a:
                meta_links[key] = a["href"]

    # Если dl не работает — парсим из .card-info или .metadata
    if not meta:
        for row in soup.select(".card-info__row, .metadata-row, .biblio-row"):
            label = row.select_one(".card-info__label, .label, dt")
            value = row.select_one(".card-info__value, .value, dd")
            if label and value:
                key = label.get_text(strip=True).rstrip(":")
                meta[key] = value.get_text(" ", strip=True)
                a = value.find("a", href=True)
                if a:
                    meta_links[key] = a["href"]

    # Год
    year_raw = (
        meta.get("Год издания", "")
        or meta.get("Год", "")
        or meta.get("Дата", "")
    )
    y_from, y_to = _parse_years(year_raw or title)

    # Источник (библиотека-фондодержатель)
    source_lib = (
        meta.get("Источник", "")
        or meta.get("Фондодержатель", "")
        or meta.get("Организация", "")
    )

    # Доступ
    access_el = soup.select_one(".access-type, .access-label, [class*=access]")
    access = access_el.get_text(strip=True) if access_el else meta.get("Доступ", "")

    # Ссылка на просмотр/скачивание
    viewer_url = ""
    for a in soup.select("a[href]"):
        href = a["href"]
        if any(x in href for x in ["/viewer/", "/read/", "/download/", "iiif"]):
            viewer_url = href if href.startswith("http") else BASE_URL + href
            break

    # Описание
    desc_el = soup.select_one(
        ".card__description, .annotation, .description, [class*=annotation]"
    )
    description = desc_el.get_text(" ", strip=True)[:400] if desc_el else ""

    # Коллекции
    collections = [
        a.get_text(strip=True)
        for a in soup.select(".collections a, .collection-link, [class*=collection] a")
    ]

    return NebRecord(
        title=title,
        author=meta.get("Автор", "") or meta.get("Составитель", ""),
        year_from=y_from,
        year_to=y_to,
        place=meta.get("Место издания", "") or meta.get("Место", ""),
        publisher=meta.get("Издательство", "") or meta.get("Издатель", ""),
        source_lib=source_lib,
        access=access,
        url=url,
        url_viewer=viewer_url,
        description=description,
        collections=collections,
    )


def search(query: str,
           year_from: int | None = None,
           year_to: int | None = None,
           filter_maps: bool = True,
           debug: bool = False) -> Iterator[NebRecord]:
    """
    Поиск по НЭБ. Исключения пробрасываются наверх.
    """
    card_urls = _get_search_urls(query, filter_maps=filter_maps, debug=debug)

    for url in card_urls:
        try:
            rec = _parse_card(url, debug=debug)
        except Exception as e:
            print(f"[НЭБ] Ошибка карточки {url}: {e}")
            continue

        if not rec:
            continue

        if year_from and rec.year_to and rec.year_to < year_from:
            continue
        if year_to and rec.year_from and rec.year_from > year_to:
            continue

        yield rec


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск карт в НЭБ (rusneb.ru)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос")
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--no-filter-maps", action="store_true", dest="no_filter",
                        help="Не фильтровать по типу документа «Карты»")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries",
                        help="Все ключевые слова × 4 губернии")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.all_queries:
        seen: set[str] = set()
        total = 0
        for kw in KEYWORDS:
            for territory in TERRITORIES:
                q = f"{kw} {territory}"
                try:
                    recs = list(search(q, args.year_from, args.year_to,
                                       filter_maps=not args.no_filter))
                except Exception as exc:
                    print(f"[НЭБ] Запрос «{q}» пропущен: {exc}")
                    continue
                for rec in recs:
                    key = rec.title + str(rec.year_from)
                    if key not in seen:
                        seen.add(key)
                        total += 1
                        yr = f"{rec.year_from or '?'}–{rec.year_to or '?'}"
                        print(f"  {yr:<12} [{rec.source_lib}] {rec.title[:60]}")
                        print(f"             {rec.url}")
        print(f"\n[НЭБ] Итого уникальных: {total}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to,
                          filter_maps=not args.no_filter, debug=args.debug))
    print(f"\n[НЭБ] Найдено: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} {r.title[:65]}")
        print(f"             Источник: {r.source_lib}  Доступ: {r.access}")
        print(f"             {r.url}")
        if r.url_viewer:
            print(f"             Просмотр: {r.url_viewer}")


if __name__ == "__main__":
    main()
