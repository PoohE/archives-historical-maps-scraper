"""
Поиск в онлайн-коллекциях карт федеральных и региональных библиотек России.

Поддерживаемые источники (передавать в параметр libraries):
  prlib      — Президентская библиотека (prlib.ru), раздел «Исторические карты»
  runivers   — Руниверс: картографическая коллекция (runivers.ru)
  rgo        — Геопортал Русского географического общества (geoportal.rgo.ru)
  aonb       — ЭКБ «Русский Север», Архангельская ОНББ (ekb.aonb.ru)
  permkrai   — Пермская краевая библиотека (lib.permkrai.ru)
  nlr_cart   — РНБ: алфавитно-географический каталог карт 1700–2004 (nlr.ru)
  gpib       — ГПИБ России: электронная библиотека (elib.shpl.ru)
  kaluga_lib — Калужская ОНБИБ им. В.Г. Белинского (belinkaluga.ru)
  smolensk_lib — Смоленская ОУНБ им. А.Т. Твардовского (smolensklib.ru)
  yaroslavl_lib — Ярославская ОУНБ им. Н.А. Некрасова / Ярославика (rlib.yar.ru)
  etomesto   — ЭтоМесто: планы межевания, трёхвёрстные карты (etomesto.ru)
  retromap   — Retromap: старые карты по регионам (retromap.ru)
  southklad  — Старинные карты губерний Российской Империи (maps.southklad.ru)
  qmap       — Открытый картографический архив (q-map.ru)
  all        — все источники (по умолчанию)
"""
import re
import time
from dataclasses import dataclass, field
from typing import Iterator

import requests
from bs4 import BeautifulSoup

from triggers import ALL_POSITIVE as _MAP_KW, is_cartographic as _is_cart

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


@dataclass
class LibraryRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    place: str = ""
    scale: int | None = None
    description: str = ""
    url: str = ""
    library_id: str = ""        # prlib / runivers / rgo / aonb / permkrai / nlr_cart
    library_name: str = ""      # человекочитаемое название
    category: str = "карты"
    extra: dict = field(default_factory=dict)


# ── общие утилиты ────────────────────────────────────────────────────────────

def _get(url: str, params: dict | None = None, delay: float = 2.0) -> requests.Response:
    time.sleep(delay)
    resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=25)
    resp.raise_for_status()
    return resp


def _parse_years(text: str) -> tuple[int | None, int | None]:
    """Извлекает диапазон лет (1500–2000) из строки."""
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _check(url: str) -> bool:
    """Проверяет доступность URL. True если HTTP < 400."""
    try:
        r = requests.head(url, headers={"User-Agent": UA}, timeout=8, allow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


def _in_year_range(y_from: int | None, y_to: int | None,
                   filter_from: int | None, filter_to: int | None) -> bool:
    """True если запись попадает в заданный фильтр по годам."""
    if filter_from and y_to and y_to < filter_from:
        return False
    if filter_to and y_from and y_from > filter_to:
        return False
    return True


# ── Президентская библиотека (prlib.ru) ──────────────────────────────────────

PRLIB_SEARCH = "https://www.prlib.ru/search/"
# Прямая ссылка на раздел «Исторические карты» — для справки
# https://www.prlib.ru/section/1157354

def _search_prlib(query: str, year_from: int | None, year_to: int | None,
                  max_pages: int) -> Iterator[LibraryRecord]:
    """
    Президентская библиотека (prlib.ru) — Bitrix CMS.
    Поиск: /search/?q=<query>&PAGEN_1=<page>&type=StillImage
    Результаты: .search-result__item → ссылки на /item/<id>

    Если структура HTML изменится — уточнить CSS-селекторы в _parse_prlib_item().
    """
    if not _check(PRLIB_SEARCH):
        print("[ПрБ] Сайт prlib.ru недоступен, пропуск.")
        return

    for page in range(1, max_pages + 1):
        params: dict = {"q": query, "PAGEN_1": page, "type": "StillImage"}
        try:
            resp = _get(PRLIB_SEARCH, params=params)
        except Exception as e:
            print(f"[ПрБ] Ошибка стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(
            ".search-result__item, .search-page__item, article.result-item"
        )
        if not items:
            break

        for item in items:
            link = item.find("a", href=re.compile(r"/item/"))
            if not link:
                continue
            href = link["href"]
            item_url = href if href.startswith("http") else f"https://www.prlib.ru{href}"

            title_el = item.select_one("h2, h3, .title, .search-result__title")
            date_el = item.select_one(".date, .year, time, .search-result__meta")
            desc_el = item.select_one("p, .description, .search-result__snippet")

            title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
            date_raw = date_el.get_text(strip=True) if date_el else ""
            y_from, y_to = _parse_years(date_raw)

            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            yield LibraryRecord(
                title=title,
                year_from=y_from,
                year_to=y_to,
                description=(desc_el.get_text(strip=True)[:400] if desc_el else ""),
                url=item_url,
                library_id="prlib",
                library_name="Президентская библиотека",
            )


# ── Руниверс (runivers.ru) ───────────────────────────────────────────────────

RUNIVERS_SEARCH = "https://runivers.ru/search/index.php"
# Каталог всех карт: https://runivers.ru/mp/all-maps.php

def _search_runivers(query: str, year_from: int | None, year_to: int | None,
                     max_pages: int) -> Iterator[LibraryRecord]:
    """
    Руниверс (runivers.ru) — поиск через /search/index.php?q=<query>.
    Фильтр ?type=maps для ограничения категорией «Карты».
    Ссылки на карты ведут на /mp/<id>/ или /lib/maps/<id>/.
    """
    if not _check(RUNIVERS_SEARCH):
        print("[Руниверс] Сайт runivers.ru недоступен, пропуск.")
        return

    for page in range(1, max_pages + 1):
        params: dict = {"q": query, "type": "maps"}
        if page > 1:
            params["page"] = page
        try:
            resp = _get(RUNIVERS_SEARCH, params=params)
        except Exception as e:
            print(f"[Руниверс] Ошибка стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".search-result-item, .result-block, .map-item, li.item")
        if not items:
            # Запасной вариант: ссылки на /mp/ в основном тексте
            items = soup.select("a[href*='/mp/'], a[href*='/lib/maps']")
        if not items:
            break

        seen: set[str] = set()
        for el in items:
            if el.name == "a":
                link = el
            else:
                link = el.find("a")
            if not link:
                continue

            href = link.get("href", "")
            item_url = href if href.startswith("http") else f"https://runivers.ru{href}"
            if item_url in seen:
                continue
            seen.add(item_url)

            title_el = el.select_one("h2, h3, .title, strong") if el.name != "a" else None
            title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

            date_el = (el.select_one(".date, .year, .meta")
                       if el.name != "a" else None)
            date_raw = date_el.get_text(strip=True) if date_el else ""
            y_from, y_to = _parse_years(date_raw or title)

            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            yield LibraryRecord(
                title=title or href,
                year_from=y_from,
                year_to=y_to,
                url=item_url,
                library_id="runivers",
                library_name="Руниверс",
            )


# ── Геопортал РГО (geoportal.rgo.ru) ─────────────────────────────────────────

RGO_SEARCH = "https://geoportal.rgo.ru/search"
# Каталог «Старинные атласы и карты / Россика»:
# https://geoportal.rgo.ru/catalog/starinnye-atlasy-i-karty/rossika

def _search_rgo(query: str, year_from: int | None, year_to: int | None,
                max_pages: int) -> Iterator[LibraryRecord]:
    """
    Геопортал РГО (geoportal.rgo.ru) — Drupal CMS.
    Поиск: /search?q=<query>&page=<n>
    Результаты: .view-content article или li.views-row
    """
    if not _check(RGO_SEARCH):
        print("[РГО] Геопортал rgo.ru недоступен, пропуск.")
        return

    for page in range(0, max_pages):
        params: dict = {"q": query, "page": page}
        try:
            resp = _get(RGO_SEARCH, params=params)
        except Exception as e:
            print(f"[РГО] Ошибка стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(".view-content article, li.views-row, .search-result")
        if not items:
            break

        for item in items:
            link = item.find("a")
            if not link:
                continue
            href = link.get("href", "")
            item_url = href if href.startswith("http") else f"https://geoportal.rgo.ru{href}"

            title_el = item.select_one("h2, h3, .title, .node__title")
            title = (title_el.get_text(strip=True) if title_el
                     else link.get_text(strip=True))

            date_el = item.select_one(".date, time, .field--type-datetime")
            date_raw = date_el.get_text(strip=True) if date_el else ""
            y_from, y_to = _parse_years(date_raw or title)

            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            desc_el = item.select_one(
                ".description, .body, .field--type-text-with-summary"
            )
            yield LibraryRecord(
                title=title,
                year_from=y_from,
                year_to=y_to,
                description=(desc_el.get_text(strip=True)[:400] if desc_el else ""),
                url=item_url,
                library_id="rgo",
                library_name="Геопортал РГО",
            )


# ── ЭКБ «Русский Север», Архангельск (ekb.aonb.ru) ──────────────────────────

AONB_MAPS = "https://ekb.aonb.ru/index.php?id=1082"
AONB_SEARCH = "https://ekb.aonb.ru/index.php"

def _search_aonb(query: str, year_from: int | None, year_to: int | None,
                 max_pages: int) -> Iterator[LibraryRecord]:
    """
    Электронная краеведческая библиотека «Русский Север» (ekb.aonb.ru).
    Раздел «Карты и атласы»: /index.php?id=1082
    Поиск: GET /index.php?id=1082&search=<query>
    Сайт не разбит на страницы — результаты фильтруются по вхождению запроса.
    """
    if not _check(AONB_MAPS):
        print("[АОНБ] Сайт ekb.aonb.ru недоступен, пропуск.")
        return

    params: dict = {"id": 1082, "search": query}
    try:
        resp = _get(AONB_SEARCH, params=params)
    except Exception as e:
        print(f"[АОНБ] Ошибка запроса: {e}")
        return

    soup = BeautifulSoup(resp.text, "lxml")

    # Список документов в разделе карт: ссылки внутри блока контента
    main = soup.select_one("#content, .content, main, #main-content, .region-content")
    links = (main.select("a[href]") if main
             else soup.select("td a, .document-list a, .file-list a"))
    if not links:
        return

    seen: set[str] = set()
    for link in links:
        href = link.get("href", "")
        if not href or href.startswith("#") or "mailto:" in href:
            continue
        item_url = href if href.startswith("http") else f"https://ekb.aonb.ru{href}"
        if item_url in seen:
            continue
        seen.add(item_url)

        title = link.get_text(strip=True)
        if not title:
            continue
        # Мягкая фильтрация: хотя бы одно слово из запроса есть в названии
        query_words = [w.lower() for w in query.split() if len(w) > 3]
        if query_words and not any(w in title.lower() for w in query_words):
            continue

        y_from, y_to = _parse_years(title)
        if not _in_year_range(y_from, y_to, year_from, year_to):
            continue

        yield LibraryRecord(
            title=title,
            year_from=y_from,
            year_to=y_to,
            url=item_url,
            library_id="aonb",
            library_name="ЭКБ Архангельск",
        )


# ── Пермская краевая библиотека (lib.permkrai.ru) ────────────────────────────

PERM_MAPS_NODE = "https://lib.permkrai.ru/node/33626"
PERM_SEARCH = "https://lib.permkrai.ru/search/node"

def _search_permkrai(query: str, year_from: int | None, year_to: int | None,
                     max_pages: int) -> Iterator[LibraryRecord]:
    """
    Пермская краевая библиотека (lib.permkrai.ru) — Drupal CMS.
    Поиск: /search/node?keys=<query>&page=<n>
    Результаты: ol.search-results li.search-result
    Дополнительно: страница коллекции карт /node/33626 просматривается отдельно.
    """
    if not _check(PERM_SEARCH):
        print("[ПКББ] Сайт lib.permkrai.ru недоступен, пропуск.")
        return

    # Стандартный поиск Drupal
    for page in range(0, max_pages):
        params: dict = {"keys": query}
        if page > 0:
            params["page"] = page
        try:
            resp = _get(PERM_SEARCH, params=params)
        except Exception as e:
            print(f"[ПКББ] Ошибка стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(
            "li.search-result, .search-results article, .node-search-result"
        )
        if not items:
            break

        for item in items:
            link = item.find("a")
            if not link:
                continue
            href = link.get("href", "")
            item_url = href if href.startswith("http") else f"https://lib.permkrai.ru{href}"

            title_el = item.select_one("h3.title, h2.title, h2, h3")
            title = (title_el.get_text(strip=True) if title_el
                     else link.get_text(strip=True))

            # Пропускаем явно не картографические материалы
            if not _is_cart(title):
                continue

            date_el = item.select_one(
                ".search-snippet-info, .submitted, .meta, .date"
            )
            date_raw = date_el.get_text(strip=True) if date_el else ""
            y_from, y_to = _parse_years(date_raw or title)

            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            desc_el = item.select_one(".search-snippet, .body, p")
            yield LibraryRecord(
                title=title,
                year_from=y_from,
                year_to=y_to,
                description=(desc_el.get_text(strip=True)[:400] if desc_el else ""),
                url=item_url,
                library_id="permkrai",
                library_name="Пермская краевая библиотека",
            )

    # Коллекция карт: просматриваем страницу /node/33626 если запрос не дал результатов
    try:
        resp = _get(PERM_MAPS_NODE)
        soup = BeautifulSoup(resp.text, "lxml")
        main = soup.select_one(".node__content, .field--type-text-with-summary, #content")
        if main:
            for link in main.select("a[href]"):
                title = link.get_text(strip=True)
                if not title:
                    continue
                query_words = [w.lower() for w in query.split() if len(w) > 3]
                if query_words and not any(w in title.lower() for w in query_words):
                    continue
                href = link.get("href", "")
                item_url = href if href.startswith("http") else f"https://lib.permkrai.ru{href}"
                y_from, y_to = _parse_years(title)
                if not _in_year_range(y_from, y_to, year_from, year_to):
                    continue
                yield LibraryRecord(
                    title=title,
                    year_from=y_from,
                    year_to=y_to,
                    url=item_url,
                    library_id="permkrai",
                    library_name="Пермская краевая библиотека",
                )
    except Exception as e:
        print(f"[ПКББ] Не удалось загрузить коллекцию карт: {e}")


# ── РНБ: каталог карт (nlr.ru) ───────────────────────────────────────────────

NLR_CART_URL = "https://nlr.ru/e-case3/sc2.php/cart"
NLR_HIST_URL = "https://nlr.ru/e-case3/sc2.php/hist_rus"

def _search_nlr_cart(query: str, year_from: int | None, year_to: int | None,
                     max_pages: int) -> Iterator[LibraryRecord]:
    """
    РНБ: Алфавитно-географический каталог русских печатных карт 1700–2004.
    Это карточный каталог с поиском по разделителю (sf=<первые_буквы>).
    URL поиска: nlr.ru/e-case3/sc2.php/cart/find?sf=<слово>

    Результаты — ссылки на разделители /lc/<id>/<page>
    По каждой ссылке получаем список карточек с метаданными.
    """
    if not _check(NLR_CART_URL):
        print("[РНБ-карт] Каталог nlr.ru недоступен, пропуск.")
        return

    first_word = query.split()[0] if query else query
    find_url = f"{NLR_CART_URL}/find"
    try:
        resp = _get(find_url, params={"sf": first_word, "lang": "ru"})
    except Exception as e:
        print(f"[РНБ-карт] Ошибка поиска по разделителю: {e}")
        return

    soup = BeautifulSoup(resp.text, "lxml")
    # Список разделителей: ссылки вида /lc/<id>/1
    sep_links = soup.select("a[href*='/lc/'], a.separator, td a")
    if not sep_links:
        return

    seen: set[str] = set()
    count = 0
    for sep in sep_links[:20]:  # первые 20 разделителей
        sep_title = sep.get_text(strip=True)
        if not sep_title:
            continue
        query_words = [w.lower() for w in query.split() if len(w) > 3]
        if query_words and not any(w in sep_title.lower() for w in query_words):
            continue

        href = sep.get("href", "")
        sep_url = href if href.startswith("http") else f"https://nlr.ru{href}"
        if sep_url in seen:
            continue
        seen.add(sep_url)

        # Загружаем страницу разделителя и читаем карточки
        try:
            sep_resp = _get(sep_url, delay=1.5)
            sep_soup = BeautifulSoup(sep_resp.text, "lxml")
            cards = sep_soup.select("td, .card-entry, .record")
            for card in cards:
                card_link = card.find("a")
                card_title = card.get_text(strip=True) if not card_link else card_link.get_text(strip=True)
                if not card_title or len(card_title) < 5:
                    continue
                card_url = sep_url
                if card_link:
                    ch = card_link.get("href", "")
                    card_url = ch if ch.startswith("http") else f"https://nlr.ru{ch}"

                y_from, y_to = _parse_years(card_title)
                if not _in_year_range(y_from, y_to, year_from, year_to):
                    continue

                yield LibraryRecord(
                    title=card_title[:200],
                    year_from=y_from,
                    year_to=y_to,
                    url=card_url,
                    library_id="nlr_cart",
                    library_name="РНБ: каталог карт",
                )
                count += 1
                if count >= max_pages * 10:
                    return
        except Exception as e:
            print(f"[РНБ-карт] Ошибка загрузки разделителя {sep_url}: {e}")
            continue


# ── ГПИБ России (elib.shpl.ru) ───────────────────────────────────────────────

GPIB_SEARCH = "http://elib.shpl.ru/ru/nodes/search"   # правильный URL поиска
GPIB_OPAC   = "https://unis.shpl.ru/cgi-bin/irbis64r_14/cgiirbis_64.exe"
GPIB_OPAC_PARAMS = {
    "LNG": "RUS", "Z21ID": "", "I21DBN": "GPIB", "P21DBN": "GPIB",
    "S21FMT": "fullwebr", "S21ALL": "", "S21CNT": "20",
    "S21P01": "0", "S21P02": "1", "S21P03": "I=", "S21STR": "",
}


def _search_gpib(query: str, year_from: int | None, year_to: int | None,
                 max_pages: int) -> Iterator[LibraryRecord]:
    """
    ГПИБ: цифровая библиотека elib.shpl.ru/ru/nodes/search?query=<q>&page=<n>
    Результаты — таблица tbody tr: [#][Название+ссылка][Тип][Автор][...]
    Строки без числа в первой ячейке — страницы внутри документа, пропускаем.
    """
    # elib.shpl.ru rate-limit: HEAD (_check) сразу даёт 429, поэтому не проверяем —
    # идём прямо в GET с паузой 3 сек; при 429 ждём 30 сек и повторяем
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        params: dict = {"query": query, "page": page}
        try:
            resp = _get(GPIB_SEARCH, params=params, delay=3.0)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                print(f"[ГПИБ] 429 rate-limit стр.{page}, пауза 30 сек...")
                time.sleep(30)
                try:
                    resp = _get(GPIB_SEARCH, params=params, delay=5.0)
                except Exception as e2:
                    print(f"[ГПИБ] повторная ошибка стр.{page}: {e2}")
                    break
            else:
                print(f"[ГПИБ] HTTP ошибка стр.{page}: {e}")
                break
        except Exception as e:
            print(f"[ГПИБ] Ошибка стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select("table tbody tr")
        if not rows:
            break

        found = 0
        for row in rows:
            cells = row.find_all("td")
            if not cells:
                continue
            # Пропускаем строки страниц внутри документа (первая ячейка пустая)
            num_text = cells[0].get_text(strip=True)
            if not num_text.isdigit():
                continue

            link = row.find("a")
            if not link:
                continue
            href = link.get("href", "")
            item_url = href if href.startswith("http") else f"http://elib.shpl.ru{href}"
            if item_url in seen:
                continue
            seen.add(item_url)

            title = cells[1].get_text(strip=True) if len(cells) > 1 else link.get_text(strip=True)
            title = title[:200]
            if not _is_cart(title):
                continue

            y_from, y_to = _parse_years(title)
            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            yield LibraryRecord(
                title=title, year_from=y_from, year_to=y_to,
                url=item_url, library_id="gpib", library_name="ГПИБ России",
            )
            found += 1

        if found == 0:
            break

    # 2. ИРБИС-каталог unis.shpl.ru
    if _check(GPIB_OPAC):
        params = dict(GPIB_OPAC_PARAMS)
        params["S21STR"] = query
        try:
            resp = _get(GPIB_OPAC, params=params, delay=2.0)
            soup = BeautifulSoup(resp.text, "lxml")
            # ИРБИС выдаёт результаты в таблице с полями
            rows = soup.select("table tr, .irbis-record, .biblio_record")
            seen: set[str] = set()
            for row in rows:
                title_el = row.select_one("td:nth-child(2), .irbis-title, b")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                if not _is_cart(title):
                    continue
                if title in seen:
                    continue
                seen.add(title)
                y_from, y_to = _parse_years(title)
                if not _in_year_range(y_from, y_to, year_from, year_to):
                    continue
                link = row.find("a")
                href = link.get("href", "") if link else ""
                item_url = (href if href.startswith("http")
                            else f"https://unis.shpl.ru{href}") if href else GPIB_OPAC
                yield LibraryRecord(
                    title=title, year_from=y_from, year_to=y_to,
                    url=item_url, library_id="gpib", library_name="ГПИБ России",
                )
        except Exception as e:
            print(f"[ГПИБ] Ошибка ИРБИС: {e}")


# ── Региональные библиотеки: общий шаблон ─────────────────────────────────────

def _search_regional_lib(query: str, year_from: int | None, year_to: int | None,
                         max_pages: int, search_url: str, base_url: str,
                         lib_id: str, lib_name: str) -> Iterator[LibraryRecord]:
    """
    Универсальный поиск для региональных библиотек на стандартных CMS
    (Drupal, Joomla, WordPress, bitrix).
    Пробует параметры q/keys/query/search; фильтрует по картографическим ключевым словам.
    """
    if not _check(search_url):
        print(f"[{lib_name}] Недоступен ({search_url}), пропуск.")
        return

    # Пробуем разные параметры поиска
    for param_key in ("q", "keys", "query", "search", "text"):
        for page in range(0, max_pages):
            params: dict = {param_key: query}
            if page > 0:
                params["page"] = page
            try:
                resp = _get(search_url, params=params, delay=2.0)
            except Exception as e:
                print(f"[{lib_name}] Ошибка ({param_key}) стр.{page}: {e}")
                break

            soup = BeautifulSoup(resp.text, "lxml")

            # Проверяем что форма поиска сработала (есть результаты)
            results_block = soup.select_one(
                ".search-results, #search-results, .views-view, "
                ".catalog-results, .catalog__list, .results"
            )
            if results_block is None and page == 0:
                continue  # попробуем другой параметр

            items = soup.select(
                "li.search-result, .search-result, article.node, "
                ".views-row, .catalog-item, li.item"
            )
            if not items:
                # Запасной вариант: любые ссылки в основном контенте
                main = soup.select_one(
                    "#content, .content, main, .region-content"
                )
                if main:
                    items = main.select("a[href]")

            found = 0
            seen: set[str] = set()
            for el in items:
                if el.name == "a":
                    link = el
                    title = el.get_text(strip=True)
                else:
                    link = el.find("a")
                    if not link:
                        continue
                    title_el = el.select_one("h2, h3, .title, strong, b")
                    title = (title_el.get_text(strip=True) if title_el
                             else link.get_text(strip=True))

                if not title or len(title) < 5:
                    continue
                if not _is_cart(title):
                    continue

                href = link.get("href", "")
                if not href or href.startswith("#") or "mailto:" in href:
                    continue
                item_url = href if href.startswith("http") else f"{base_url}{href}"
                if item_url in seen:
                    continue
                seen.add(item_url)

                y_from, y_to = _parse_years(title)
                if not _in_year_range(y_from, y_to, year_from, year_to):
                    continue

                desc_el = (el.select_one(".search-snippet, .body, p")
                           if el.name != "a" else None)
                yield LibraryRecord(
                    title=title, year_from=y_from, year_to=y_to,
                    description=(desc_el.get_text(strip=True)[:400]
                                 if desc_el else ""),
                    url=item_url, library_id=lib_id, library_name=lib_name,
                )
                found += 1

            if found == 0:
                break  # нет результатов — дальше не листать
        break  # если дошли до этой точки, параметр сработал


def _search_kaluga_lib(query: str, year_from: int | None, year_to: int | None,
                       max_pages: int) -> Iterator[LibraryRecord]:
    """Калужская ОНБИБ им. В.Г. Белинского (belinkaluga.ru)."""
    yield from _search_regional_lib(
        query, year_from, year_to, max_pages,
        search_url="https://belinkaluga.ru/search",
        base_url="https://belinkaluga.ru",
        lib_id="kaluga_lib", lib_name="Калужская ОНБИБ",
    )


def _search_smolensk_lib(query: str, year_from: int | None, year_to: int | None,
                         max_pages: int) -> Iterator[LibraryRecord]:
    """
    Смоленская ОУНБ им. А.Т. Твардовского (smolensklib.ru).
    Дополнительно просматривает цифровую библиотеку «Наследие Смоленской земли».
    """
    yield from _search_regional_lib(
        query, year_from, year_to, max_pages,
        search_url="http://www.smolensklib.ru/search/node",
        base_url="http://www.smolensklib.ru",
        lib_id="smolensk_lib", lib_name="Смоленская ОУНБ",
    )
    # Цифровая библиотека «Наследие Смоленской земли»
    heritage_url = "http://www.smolensklib.ru/nasledie"
    try:
        if _check(heritage_url):
            resp = _get(heritage_url, delay=2.0)
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.select("a[href]"):
                title = link.get_text(strip=True)
                if not title or not _is_cart(title):
                    continue
                href = link.get("href", "")
                item_url = (href if href.startswith("http")
                            else f"http://www.smolensklib.ru{href}")
                y_from, y_to = _parse_years(title)
                if not _in_year_range(y_from, y_to, year_from, year_to):
                    continue
                yield LibraryRecord(
                    title=title, year_from=y_from, year_to=y_to,
                    url=item_url, library_id="smolensk_lib",
                    library_name="Смоленская ОУНБ / Наследие",
                )
    except Exception as e:
        print(f"[Смоленск ОУНБ] Ошибка цифровой библиотеки: {e}")


def _search_yaroslavl_lib(query: str, year_from: int | None, year_to: int | None,
                          max_pages: int) -> Iterator[LibraryRecord]:
    """
    Ярославская ОУНБ им. Н.А. Некрасова (rlib.yar.ru).
    Дополнительно обходит проект «Ярославика» (краеведческая коллекция).
    """
    yield from _search_regional_lib(
        query, year_from, year_to, max_pages,
        search_url="https://rlib.yar.ru/search",
        base_url="https://rlib.yar.ru",
        lib_id="yaroslavl_lib", lib_name="Ярославская ОУНБ",
    )
    # Ярославика — краеведческий цифровой проект
    yaroslavika_url = "https://rlib.yar.ru/yaroslavika"
    try:
        if _check(yaroslavika_url):
            resp = _get(yaroslavika_url, delay=2.0)
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.select("a[href]"):
                title = link.get_text(strip=True)
                if not title:
                    continue
                words = [w.lower() for w in query.split() if len(w) > 3]
                if words and not any(w in title.lower() for w in words):
                    continue
                if not _is_cart(title):
                    continue
                href = link.get("href", "")
                item_url = (href if href.startswith("http")
                            else f"https://rlib.yar.ru{href}")
                y_from, y_to = _parse_years(title)
                if not _in_year_range(y_from, y_to, year_from, year_to):
                    continue
                yield LibraryRecord(
                    title=title, year_from=y_from, year_to=y_to,
                    url=item_url, library_id="yaroslavl_lib",
                    library_name="Ярославская ОУНБ / Ярославика",
                )
    except Exception as e:
        print(f"[Ярославль ОУНБ] Ошибка Ярославики: {e}")


# ── Картографические порталы ──────────────────────────────────────────────────

# Коды регионов для порталов (по 4 губерниям гранта)
_PROVINCE_SLUGS = {
    "калужская": "kaluga",
    "калуга":    "kaluga",
    "пермская":  "perm",
    "пермь":     "perm",
    "смоленская": "smolensk",
    "смоленск":   "smolensk",
    "ярославская": "yaroslavl",
    "ярославль":   "yaroslavl",
}

_SOUTHKLAD_SLUGS = {
    "калужская": "kaluzhskaya-guberniya",
    "пермская":  "permskaya-guberniya",
    "смоленская": "smolenskaya-guberniya",
    "ярославская": "yaroslavskaya-guberniya",
}


def _search_etomesto(query: str, year_from: int | None, year_to: int | None,
                     max_pages: int) -> Iterator[LibraryRecord]:
    """
    ЭтоМесто (etomesto.ru) — планы генерального межевания, трёхвёрстные карты,
    карты Шуберта/Менде/Стрельбицкого с географической привязкой.
    Обходит страницы регионов (если совпадают с запросом) и общий поиск.
    """
    BASE = "http://www.etomesto.ru"

    if not _check(BASE):
        print("[ЭтоМесто] Сайт недоступен, пропуск.")
        return

    q_low = query.lower()

    # Региональные страницы для губерний гранта
    regions_to_check: list[str] = []
    for kw, slug in _PROVINCE_SLUGS.items():
        if kw in q_low and slug not in regions_to_check:
            regions_to_check.append(slug)
    if not regions_to_check:
        # Запрос не содержит губернию — обходим все 4
        regions_to_check = ["kaluga", "perm", "smolensk", "yaroslavl"]

    for region in regions_to_check:
        region_url = f"{BASE}/map-{region}/"
        try:
            resp = _get(region_url, delay=2.0)
        except Exception as e:
            print(f"[ЭтоМесто] Ошибка региона {region}: {e}")
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        # Ссылки на карты внутри блока каталога
        main = soup.select_one("#content, .content, main, .catalog")
        links = main.select("a[href]") if main else soup.select("a[href*='/map']")

        seen: set[str] = set()
        for link in links:
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            if not _is_cart(title):
                # Мягкая фильтрация для ЭтоМесто — карты не всегда в названии
                if not re.search(r"\d{4}", title):
                    continue
            href = link.get("href", "")
            if not href or href.startswith("#"):
                continue
            item_url = href if href.startswith("http") else f"{BASE}{href}"
            if item_url in seen:
                continue
            seen.add(item_url)

            y_from, y_to = _parse_years(title)
            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            yield LibraryRecord(
                title=title, year_from=y_from, year_to=y_to,
                url=item_url, library_id="etomesto",
                library_name="ЭтоМесто",
            )

    # Общий поиск
    search_url = f"{BASE}/search.php"
    if _check(search_url):
        try:
            resp = _get(search_url, params={"q": query}, delay=2.0)
            soup = BeautifulSoup(resp.text, "lxml")
            for link in soup.select("a[href*='/map']"):
                title = link.get_text(strip=True)
                if not title:
                    continue
                href = link.get("href", "")
                item_url = href if href.startswith("http") else f"{BASE}{href}"
                y_from, y_to = _parse_years(title)
                if not _in_year_range(y_from, y_to, year_from, year_to):
                    continue
                yield LibraryRecord(
                    title=title, year_from=y_from, year_to=y_to,
                    url=item_url, library_id="etomesto",
                    library_name="ЭтоМесто / поиск",
                )
        except Exception as e:
            print(f"[ЭтоМесто] Ошибка поиска: {e}")


def _search_retromap(query: str, year_from: int | None, year_to: int | None,
                     max_pages: int) -> Iterator[LibraryRecord]:
    """
    Retromap (retromap.ru) — старые карты России по регионам.
    Обходит страницу каталога и фильтрует по губерниям гранта.
    """
    BASE = "https://retromap.ru"
    CATALOG = f"{BASE}/catalog.php"

    if not _check(CATALOG):
        print("[Retromap] Сайт недоступен, пропуск.")
        return

    q_low = query.lower()
    PROVINCES = {"калуга", "пермь", "смоленск", "ярославль",
                 "калужская", "пермская", "смоленская", "ярославская"}

    try:
        resp = _get(CATALOG, delay=2.0)
        soup = BeautifulSoup(resp.text, "lxml")
        seen: set[str] = set()
        for link in soup.select("a[href]"):
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            title_low = title.lower()
            # Фильтр: должны быть наши губернии или слова из запроса
            has_region = any(p in title_low for p in PROVINCES)
            has_kw_from_query = any(
                w.lower() in title_low for w in query.split() if len(w) > 3
            )
            if not (has_region or has_kw_from_query):
                continue
            if not _is_cart(title):
                continue

            href = link.get("href", "")
            if not href or href.startswith("#"):
                continue
            item_url = href if href.startswith("http") else f"{BASE}{href}"
            if item_url in seen:
                continue
            seen.add(item_url)

            y_from, y_to = _parse_years(title)
            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            yield LibraryRecord(
                title=title, year_from=y_from, year_to=y_to,
                url=item_url, library_id="retromap",
                library_name="Retromap",
            )
    except Exception as e:
        print(f"[Retromap] Ошибка каталога: {e}")


def _search_southklad(query: str, year_from: int | None, year_to: int | None,
                      max_pages: int) -> Iterator[LibraryRecord]:
    """
    maps.southklad.ru — каталог карт Российской Империи по губерниям.
    Обходит страницы губерний Калужской, Пермской, Смоленской, Ярославской.
    """
    BASE = "https://maps.southklad.ru"

    if not _check(BASE):
        print("[Southklad] Сайт недоступен, пропуск.")
        return

    q_low = query.lower()
    # Определяем губернии из запроса или берём все 4
    provinces_to_check: list[tuple[str, str]] = []
    for kw, slug in _SOUTHKLAD_SLUGS.items():
        if kw in q_low:
            provinces_to_check.append((kw, slug))
    if not provinces_to_check:
        provinces_to_check = list(_SOUTHKLAD_SLUGS.items())

    for prov_name, slug in provinces_to_check:
        prov_url = f"{BASE}/{slug}/"
        try:
            resp = _get(prov_url, delay=2.0)
        except Exception as e:
            print(f"[Southklad] Ошибка губернии {prov_name}: {e}")
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        seen: set[str] = set()
        for link in soup.select("a[href]"):
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            if not _is_cart(title):
                continue
            href = link.get("href", "")
            if not href or href.startswith("#") or "southklad.ru" not in (
                href if href.startswith("http") else BASE + href
            ):
                continue
            item_url = href if href.startswith("http") else f"{BASE}{href}"
            if item_url in seen:
                continue
            seen.add(item_url)

            y_from, y_to = _parse_years(title)
            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            yield LibraryRecord(
                title=title, year_from=y_from, year_to=y_to,
                url=item_url, library_id="southklad",
                library_name=f"Карты Российской Империи / {prov_name.title()}",
            )


def _search_qmap(query: str, year_from: int | None, year_to: int | None,
                 max_pages: int) -> Iterator[LibraryRecord]:
    """
    Q-map / Открытый картографический архив (q-map.ru).
    Поиск через сайт и обход категорий Россия XVIII–XX вв.
    """
    BASE = "https://q-map.ru"

    if not _check(BASE):
        print("[Q-map] Сайт недоступен, пропуск.")
        return

    PROVINCES = {"калуга", "пермь", "смоленск", "ярославль",
                 "калужская", "пермская", "смоленская", "ярославская"}
    for page in range(1, max_pages + 1):
        search_url = f"{BASE}/?s={query}"
        if page > 1:
            search_url = f"{BASE}/page/{page}/?s={query}"
        try:
            resp = _get(search_url, delay=2.0)
        except Exception as e:
            print(f"[Q-map] Ошибка стр.{page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        items = soup.select(
            "article, .post, li.search-result, .entry, .attachment"
        )
        if not items:
            break

        found = 0
        seen: set[str] = set()
        for item in items:
            link = item.find("a")
            if not link:
                continue
            title_el = item.select_one("h2, h3, .entry-title, .title")
            title = (title_el.get_text(strip=True) if title_el
                     else link.get_text(strip=True))
            if not title:
                continue
            title_low = title.lower()
            if not _is_cart(title):
                continue

            href = link.get("href", "")
            item_url = href if href.startswith("http") else f"{BASE}{href}"
            if item_url in seen:
                continue
            seen.add(item_url)

            y_from, y_to = _parse_years(title)
            if not _in_year_range(y_from, y_to, year_from, year_to):
                continue

            yield LibraryRecord(
                title=title, year_from=y_from, year_to=y_to,
                url=item_url, library_id="qmap",
                library_name="Открытый картографический архив",
            )
            found += 1

        if found == 0:
            break


# ── Единая точка входа ────────────────────────────────────────────────────────

LIBRARY_IDS: tuple[str, ...] = (
    "prlib", "runivers", "rgo", "aonb", "permkrai", "nlr_cart",
    "gpib", "kaluga_lib", "smolensk_lib", "yaroslavl_lib",
    "etomesto", "retromap", "southklad", "qmap",
)

_SEARCHERS = {
    "prlib":         _search_prlib,
    "runivers":      _search_runivers,
    "rgo":           _search_rgo,
    "aonb":          _search_aonb,
    "permkrai":      _search_permkrai,
    "nlr_cart":      _search_nlr_cart,
    "gpib":          _search_gpib,
    "kaluga_lib":    _search_kaluga_lib,
    "smolensk_lib":  _search_smolensk_lib,
    "yaroslavl_lib": _search_yaroslavl_lib,
    "etomesto":      _search_etomesto,
    "retromap":      _search_retromap,
    "southklad":     _search_southklad,
    "qmap":          _search_qmap,
}


def search(query: str, year_from: int | None = None, year_to: int | None = None,
           libraries: str = "all", max_pages: int = 3) -> Iterator[LibraryRecord]:
    """
    Ищет карты в онлайн-коллекциях российских библиотек.

    libraries: 'all' или список через запятую:
               'prlib,runivers,rgo,aonb,permkrai,nlr_cart'
    """
    if libraries == "all":
        targets = LIBRARY_IDS
    else:
        targets = tuple(
            lib.strip()
            for lib in libraries.split(",")
            if lib.strip() in _SEARCHERS
        )

    for lib_id in targets:
        fn = _SEARCHERS[lib_id]
        try:
            yield from fn(query, year_from, year_to, max_pages)
        except Exception as e:
            print(f"[libraries:{lib_id}] Необработанная ошибка: {e}")
