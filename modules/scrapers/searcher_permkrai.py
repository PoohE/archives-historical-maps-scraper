"""
ПЕРМСКАЯ ГОСУДАРСТВЕННАЯ КРАЕВАЯ БИБЛИОТЕКА им. А.М. ГОРЬКОГО
https://lib.permkrai.ru

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

CMS:         ELiS (lib.elibsystem.ru) — Drupal-based CMS для российских библиотек
Версия:      определить из meta Generator="ELiS ..."

ПОИСК:
  URL:       https://lib.permkrai.ru/search/fulltext/{query}
             query — UTF-8 URL-encoded в PATH (не ?keys=..., как в Drupal 7)
  ПАГИНАЦИЯ: нет — все результаты на одной странице (списки обычно ≤20 записей)
  ФИЛЬТР:    поиск полнотекстовый; категорию «Карты, схемы, планы» проверять
             на странице карточки, не в выдаче

КАРТОЧКА:
  URL:       https://lib.permkrai.ru/node/{id}
  Поля:
    - Заголовок         → <h1> или .page-title
    - Категория         → breadcrumb / тег рядом с заголовком
    - Дата публикации   → label «Дата публикации:» → следующий элемент
    - Библ. описание    → label «Библиографическое описание:»
    - Источник          → label «Источник:» → <a href="...">
    - Фондодержатель    → label «Фондодержатель (владелец)»
    - «В открытом доступе» — бейдж/текст
    - Теги              → .field-name-field-tags a / .tags a
    - Кнопка «ОТКРЫТЬ» → /node/{id}/view (viewer; это не прямая ссылка на файл)

══════════════════════════════════════════════════════════════
ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ И ПРАВИЛА
══════════════════════════════════════════════════════════════

1. ГЕОБЛОК: сайт доступен только с российских IP. С зарубежных — timeout.
   При ошибке подключения — сразу пробрасывать исключение наверх (не пропускать тихо).

2. НЕСТАНДАРТНЫЙ ПОИСК: URL типа /search/fulltext/{запрос} без параметра page=.
   НЕ использовать /search/node?keys=... (это устаревший Drupal 7 endpoint, на этом
   сайте он возвращает пустой результат).

3. ВОПРОС ПАГИНАЦИИ: пагинации нет видимой в интерфейсе. Если результатов будет много
   — проверить наличие /?page=1 в исходнике и добавить поддержку.

4. КАТЕГОРИЯ «Карты, схемы, планы» проверяется на странице карточки, не в выдаче.
   Другие категории (книги, статьи, рукописи) отфильтровывать.

5. ПОЛЕ «ИСТОЧНИК»: ссылка типа knpam.rusneb.ru, elib.shpl.ru — это каталожная
   запись, а не прямая ссылка на файл. Сохранять как url_source, не как url (url —
   адрес самой карточки lib.permkrai.ru/node/{id}).

6. Кнопка «ОТКРЫТЬ» ведёт на /node/{id}/view — это встроенный viewer IIIF/DjVu.
   Для автоматической загрузки файла этот viewer надо анализировать отдельно.

══════════════════════════════════════════════════════════════
ПРОВЕРОЧНЫЙ URL
══════════════════════════════════════════════════════════════

Карточка с картой: https://lib.permkrai.ru/node/33626
  Название: «Карта, представляющая течение реки Чусовой...»
  Год: 1775, категория: Карты, схемы, планы, источник: knpam.rusneb.ru

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_permkrai.py "карта Пермская губерния"
  python searcher_permkrai.py "план уезд" --year-from 1700 --year-to 1917
  python searcher_permkrai.py "атлас" --debug          # дамп HTML карточки
  python searcher_permkrai.py "карта" --check-node 33626  # проверить одну карточку
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

BASE_URL = "https://lib.permkrai.ru"
SEARCH_PATH = "/search/fulltext"  # НЕ /search/node — тот не работает
TARGET_CATEGORY = "карты, схемы, планы"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}


@dataclass
class PermRecord:
    title: str = ""
    year_from: int | None = None
    year_to: int | None = None
    url: str = ""
    url_source: str = ""       # внешний каталог (knpam.rusneb.ru и т.д.)
    description: str = ""
    bibliography: str = ""
    owner: str = ""            # фондодержатель
    open_access: bool = False
    tags: list[str] = field(default_factory=list)
    library_id: str = "permkrai"
    library_name: str = "Пермская краевая библиотека"


def _get(url: str, delay: float = 2.0) -> requests.Response:
    time.sleep(delay)
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return resp


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _in_range(y_from, y_to, filter_from, filter_to) -> bool:
    if filter_from and y_to and y_to < filter_from:
        return False
    if filter_to and y_from and y_from > filter_to:
        return False
    return True


def _field_value(soup: BeautifulSoup, label_re: str) -> str:
    """
    Ищет label по regex и возвращает текст следующего элемента.
    ELiS использует разные структуры в зависимости от версии темы:
      Вариант A (dl/dt/dd):   <dt>Дата...</dt><dd>1775</dd>
      Вариант B (div/label):  <div class="field-label">Дата...</div>
                               <div class="field-items"><div class="field-item">1775</div></div>
    """
    pattern = re.compile(label_re, re.I)

    # Вариант A: <dt> + <dd>
    for dt in soup.find_all("dt", string=pattern):
        dd = dt.find_next_sibling("dd")
        if dd:
            return dd.get_text(" ", strip=True)

    # Вариант B: элемент с текстом-лейблом → ближайший следующий с текстом
    for el in soup.find_all(string=pattern):
        parent = el.find_parent()
        if not parent:
            continue
        # Ищем значение в следующем sibling или в родительском контейнере
        nxt = parent.find_next_sibling()
        if nxt:
            val = nxt.get_text(" ", strip=True)
            if val and val != parent.get_text(" ", strip=True):
                return val
        # Fallback: parent container → искать field-item
        container = parent.find_parent()
        if container:
            item = container.select_one(".field-item, .field-items")
            if item:
                return item.get_text(" ", strip=True)

    return ""


def _field_link(soup: BeautifulSoup, label_re: str) -> str:
    """Ищет label, возвращает href первой ссылки в следующем элементе."""
    pattern = re.compile(label_re, re.I)
    for el in soup.find_all(string=pattern):
        parent = el.find_parent()
        if not parent:
            continue
        # Ищем в следующих sibling'ах
        for nxt in (parent.find_next_sibling(), parent.find_parent()):
            if not nxt:
                continue
            a = nxt.find("a", href=True)
            if a and a["href"] and not a["href"].startswith("/node/"):
                return a["href"]
    return ""


def get_result_urls(query: str) -> list[str]:
    """
    Получает список URL карточек (/node/{id}) из поисковой выдачи.
    ELiS: результаты — все на одной странице, пагинации нет.
    Если вдруг появится /?page=N — добавить цикл.
    """
    url = f"{BASE_URL}{SEARCH_PATH}/{quote(query)}"
    print(f"[ПГКБ] Поиск: {url}")
    resp = _get(url)  # исключение пробрасывается наверх (геоблок, timeout)

    soup = BeautifulSoup(resp.text, "lxml")
    node_re = re.compile(r"^/node/\d+$")
    seen: set[str] = set()
    urls: list[str] = []

    for a in soup.find_all("a", href=node_re):
        href = a["href"]
        if href not in seen:
            seen.add(href)
            urls.append(f"{BASE_URL}{href}")

    # Проверить наличие пагинации (на случай будущих обновлений CMS)
    pager = soup.select_one(".pager, .pagination, [class*=pager]")
    if pager:
        print(f"[ПГКБ] Обнаружена пагинация — добавить цикл по страницам!")

    print(f"[ПГКБ] Найдено карточек для проверки: {len(urls)}")
    return urls


def parse_card(url: str, year_from: int | None = None, year_to: int | None = None,
               debug: bool = False) -> PermRecord | None:
    """
    Парсит страницу карточки /node/{id}.
    Возвращает None если:
      - категория не «Карты, схемы, планы»
      - год вне диапазона [year_from, year_to]
      - не удалось извлечь заголовок
    """
    resp = _get(url, delay=1.5)  # исключение пробрасывается наверх
    soup = BeautifulSoup(resp.text, "lxml")

    if debug:
        print(f"\n{'─'*60}")
        print(f"HTML карточки: {url}")
        print("─" * 60)
        print(soup.prettify()[:4000])
        print("─" * 60)

    # ── Категория ─────────────────────────────────────────────────────────────
    page_text = soup.get_text(" ", strip=True).lower()
    if TARGET_CATEGORY not in page_text:
        return None

    # ── Заголовок ─────────────────────────────────────────────────────────────
    title_el = (
        soup.select_one("h1.page-header")
        or soup.select_one("h1")
        or soup.select_one(".node-title")
        or soup.select_one(".field--name-title")
    )
    title = title_el.get_text(" ", strip=True) if title_el else ""
    if not title:
        return None

    # ── Год ───────────────────────────────────────────────────────────────────
    date_raw = _field_value(soup, r"Дата публикации")
    if not date_raw:
        # Fallback: ищем 4-значный год в тексте страницы (1500–1920)
        m = re.search(r"\b(1[5-9]\d{2})\b", page_text)
        date_raw = m.group(1) if m else ""

    y_from, y_to = _parse_years(date_raw)
    if not _in_range(y_from, y_to, year_from, year_to):
        return None

    # ── Остальные поля ────────────────────────────────────────────────────────
    bibliography = _field_value(soup, r"Библиографическое описание")
    description_el = soup.select_one(
        ".field--name-body, .field-name-body, .field-name-field-description, "
        ".field-name-field-abstract, #content .node-body"
    )
    description = description_el.get_text(" ", strip=True)[:500] if description_el else ""

    url_source = _field_link(soup, r"Источник")
    owner = _field_value(soup, r"Фондодержатель")

    open_access = bool(re.search(r"открыт[омые]+\s+доступ", page_text, re.I))

    tags_els = soup.select(
        ".field--name-field-tags a, .field-name-field-tags a, .tags a"
    )
    tags = [a.get_text(strip=True) for a in tags_els if a.get_text(strip=True)]

    return PermRecord(
        title=title,
        year_from=y_from,
        year_to=y_to,
        url=url,
        url_source=url_source,
        description=description,
        bibliography=bibliography,
        owner=owner,
        open_access=open_access,
        tags=tags,
    )


def search(query: str,
           year_from: int | None = None,
           year_to: int | None = None,
           debug: bool = False) -> Iterator[PermRecord]:
    """
    Yield-ит записи карт из Пермской краевой библиотеки.
    Исключения (timeout, HTTP-ошибки) пробрасываются наверх — вызывающий код
    должен различать сетевые ошибки и пустой результат.
    """
    urls = get_result_urls(query)
    for url in urls:
        try:
            rec = parse_card(url, year_from, year_to, debug=debug)
        except Exception as e:
            print(f"[ПГКБ] Ошибка карточки {url}: {e}")
            continue  # пропускаем карточку, но не прерываем весь поиск
        if rec:
            yield rec
        time.sleep(0.8)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск карт в Пермской краевой библиотеке (lib.permkrai.ru)"
    )
    parser.add_argument("query", nargs="?", default="карта Пермская губерния",
                        help="Поисковый запрос")
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--debug", action="store_true",
                        help="Выводить HTML карточек для отладки структуры")
    parser.add_argument("--check-node", dest="check_node", default="",
                        help="Проверить конкретную карточку: --check-node 33626")
    args = parser.parse_args()

    if args.check_node:
        url = f"{BASE_URL}/node/{args.check_node}"
        print(f"[ПГКБ] Проверяем карточку: {url}")
        rec = parse_card(url, debug=True)
        if rec:
            print(f"\n✓ Карточка успешно разобрана:")
            print(f"  Название:  {rec.title}")
            print(f"  Год:       {rec.year_from}–{rec.year_to}")
            print(f"  Источник:  {rec.url_source}")
            print(f"  Владелец:  {rec.owner}")
            print(f"  Открытый:  {rec.open_access}")
            print(f"  Теги:      {', '.join(rec.tags)}")
            print(f"  Библ.:     {rec.bibliography[:120]}")
        else:
            print("✗ Карточка не подошла (не карта или вне диапазона лет)")
        return

    results = list(search(args.query, args.year_from, args.year_to, debug=args.debug))
    print(f"\n[ПГКБ] Итого карт в диапазоне {args.year_from}–{args.year_to}: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} {r.title[:65]}")
        print(f"             {r.url}")
        if r.url_source:
            print(f"             Источник: {r.url_source}")


if __name__ == "__main__":
    main()
