"""
ГАПК — Государственный архив Пермского края
https://archives.permkrai.ru — Архивы Прикамья

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (из скрина 2026-07-16)
══════════════════════════════════════════════════════════════

URL списка фондов:   https://archives.permkrai.ru/archive1/funds
  Показаны записи 1-20 из 2753.
  Колонки: Номер | Заголовок фонда | Крайние даты | [иконка фото]
  Поле фильтра: «Заголовок фонда» (inline-фильтр в таблице)

Фильтр по ключевому слову в названии фонда:
  GET-параметр: FundSearch%3BFUND_NAME_SHORT%3D=<слово>
  (Декодировано: FundSearch;FUND_NAME_SHORT=<слово>)
  Пример: ?FundSearch%3BFUND_NAME_SHORT%3D=лес → 72 фонда
  Для карт: попробовать "карт", "план", "чертеж", "геодез", "межев"

URL фонда:  https://archives.permkrai.ru/archive1/funds/{id}
  (например /archive1/funds/100062 — Ф.184)
  Поля: Фонд №, Крайние даты, Описи фонда (таблица)
  Таблица описей: Заголовок | Даты документов

Описи: ссылки вида /archive1/funds/{fond_id}/inventories/{inv_id} (предположительно)
  или /archive1/inventories/{inv_id}

Стратегия:
  1. Фильтруем фонды по картографическим ключевым словам в названии
  2. Для каждого найденного фонда → переходим на страницу фонда
  3. Получаем список описей
  4. Для каждой описи → получаем список дел (если есть поиск/перечень)
  5. Фильтруем дела по территории

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  # Только список подходящих фондов (быстро)
  python searcher_gapk.py --list-funds

  # Поиск фондов по конкретному ключевому слову
  python searcher_gapk.py --keyword карт --list-funds

  # Полный обход с фильтром по территории
  python searcher_gapk.py --geo Перм
  python searcher_gapk.py --geo "Калуж" --debug

  # Все MAP_FUND_KEYWORDS, все описи
  python searcher_gapk.py

  # Раздел /archive/ портала (2026-07-17). ГЕОБЛОК: запускать ТОЛЬКО без VPN.
  # Шаг 1 — разведка структуры (быстро, покажет фонды или дамп HTML):
  python searcher_gapk.py --archive archive --list-funds --debug
  # Шаг 2 — если фонды нашлись, полный обход:
  python searcher_gapk.py --archive archive
"""

import re
import sys
import time
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# Импортировать TERRITORIES из modules/territories.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from territories import TERRITORIES

BASE_URL = "https://archives.permkrai.ru"

# Разделы портала «Архивы Прикамья»:
#   archive1 — ГАПК (2753 фонда, структура проверена по скринам 2026-07-16)
#   archive  — раздел https://archives.permkrai.ru/archive/ (добавлен 2026-07-17;
#              структура НЕ проверена — геоблок нероссийских IP, запускать без VPN)
DEFAULT_ARCHIVE = "archive1"


def _fund_list_url(archive: str) -> str:
    return f"{BASE_URL}/{archive}/funds"

# Ключевые слова для поиска картографических фондов по названию
MAP_FUND_KEYWORDS = ["карт", "план", "чертеж", "геодез", "топограф", "съемк", "межев"]

# Расширенный список территорий (49 вместо 4)
TERRITORY_KEYS = TERRITORIES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class GapkRecord:
    title:      str = ""
    fond_num:   str = ""
    fond_title: str = ""
    opisi_num:  str = ""
    delo_num:   str = ""
    year_from:  int | None = None
    year_to:    int | None = None
    url:        str = ""
    library_id:   str = "gapk"
    library_name: str = "ГАПК — Государственный архив Пермского края"


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _fund_filter_url(keyword: str, archive: str = DEFAULT_ARCHIVE) -> str:
    """Строит URL фильтра фондов по ключевому слову в названии."""
    # Параметр с точки зрения сервера: FundSearch;FUND_NAME_SHORT=<слово>
    # В URL закодирован как FundSearch%3BFUND_NAME_SHORT%3D=<слово>
    encoded_key = "FundSearch%3BFUND_NAME_SHORT%3D"
    return f"{_fund_list_url(archive)}?{encoded_key}={quote(keyword)}"


def _get_fund_links(session: requests.Session, keyword: str,
                    archive: str = DEFAULT_ARCHIVE,
                    debug: bool = False) -> list[tuple[str, str, str]]:
    """
    Ищет фонды с ключевым словом в названии.
    Возвращает [(fund_id_url, fond_num, fond_title), ...]
    """
    url = _fund_filter_url(keyword, archive)
    time.sleep(2.0)
    try:
        resp = session.get(url, timeout=25)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ГАПК] Ошибка при фильтре '{keyword}': {e}")
        return []

    if debug:
        print(f"\n─── Список фондов для '{keyword}' (5000 символов) ───")
        print(resp.text[:5000])
        print("─── конец ───\n")

    soup = BeautifulSoup(resp.text, "lxml")
    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    # Ссылки на страницы фондов
    fund_re = re.compile(r"/archive\d*/funds/(\d+)$")
    for a in soup.find_all("a", href=fund_re):
        href = a["href"]
        fund_url = href if href.startswith("http") else BASE_URL + href
        if fund_url in seen:
            continue
        seen.add(fund_url)

        fond_title = a.get_text(" ", strip=True)
        # Номер фонда — в соседней ячейке или из самого текста строки
        container = a.find_parent("tr")
        fond_num = ""
        if container:
            cells = container.find_all("td")
            if cells:
                fond_num = cells[0].get_text(strip=True)

        results.append((fund_url, fond_num, fond_title))

    return results


def _get_inventories(session: requests.Session, fund_url: str,
                     debug: bool = False) -> list[tuple[str, str]]:
    """
    Получает список описей фонда.
    Возвращает [(inv_url, inv_title), ...]
    """
    time.sleep(1.5)
    try:
        resp = session.get(fund_url, timeout=25)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ГАПК] Ошибка страницы фонда {fund_url}: {e}")
        return []

    if debug:
        print(f"\n─── Страница фонда {fund_url} (3000 символов) ───")
        print(resp.text[:3000])
        print("─── конец ───\n")

    soup = BeautifulSoup(resp.text, "lxml")
    inv_links: list[tuple[str, str]] = []
    seen: set[str] = set()

    inv_re = re.compile(r"/inventories?/\d+|/archive\d*/inventories?/\d+", re.I)
    for a in soup.find_all("a", href=inv_re):
        href = a["href"]
        inv_url = href if href.startswith("http") else BASE_URL + href
        if inv_url in seen:
            continue
        seen.add(inv_url)
        inv_links.append((inv_url, a.get_text(" ", strip=True)))

    # Если описи не нашлись по паттерну — ищем все внутренние ссылки из таблицы описей
    if not inv_links:
        tables = soup.select("table")
        for tbl in tables:
            hdr = tbl.get_text(" ").lower()
            if "опис" in hdr or "заголовок" in hdr:
                for a in tbl.find_all("a", href=True):
                    href = a["href"]
                    inv_url = href if href.startswith("http") else BASE_URL + href
                    if inv_url not in seen and inv_url != fund_url:
                        seen.add(inv_url)
                        inv_links.append((inv_url, a.get_text(" ", strip=True)))

    return inv_links


def _get_cases(session: requests.Session, inv_url: str,
               geo_filter: str = "", debug: bool = False) -> list[dict]:
    """
    Получает список дел описи (одна страница).
    Возвращает [{title, delo_num, url, year_raw}, ...]
    """
    time.sleep(1.5)
    try:
        resp = session.get(inv_url, timeout=25)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ГАПК] Ошибка страницы описи {inv_url}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    cases: list[dict] = []

    # Ищем строки дел в таблице
    case_re = re.compile(r"/cases?/\d+|/delo/\d+|/documents?/\d+", re.I)
    for a in soup.find_all("a", href=case_re):
        href = a["href"]
        url = href if href.startswith("http") else BASE_URL + href
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        if geo_filter and geo_filter.lower() not in title.lower():
            continue
        container = a.find_parent("tr") or a.parent
        row_text = container.get_text(" ", strip=True) if container else title
        delo_num = ""
        m = re.search(r"\b(\d+)\b", row_text.split(title)[0] if title in row_text else "")
        if m:
            delo_num = m.group(1)
        cases.append({"title": title, "url": url, "row_text": row_text,
                      "delo_num": delo_num})

    # Если ссылок на дела нет — возможно, список дел в другом формате
    if not cases and debug:
        print("[ГАПК] Дела не найдены по ссылкам. HTML описи:")
        print(resp.text[:3000])

    return cases


def search_funds(session: requests.Session, keywords: list[str],
                 geo_filter: str = "", year_from: int | None = None,
                 year_to: int | None = None, list_only: bool = False,
                 archive: str = DEFAULT_ARCHIVE,
                 debug: bool = False) -> Iterator[GapkRecord]:
    """Ищет фонды по ключевым словам, затем обходит их описи."""

    seen_funds: set[str] = set()
    found_total = 0

    for kw in keywords:
        print(f"[ГАПК/{archive}] Поиск фондов по ключевому слову: '{kw}'")
        fund_list = _get_fund_links(session, kw, archive=archive, debug=debug)

        if not fund_list:
            print(f"[ГАПК]   Фонды не найдены для '{kw}'")
            continue

        print(f"[ГАПК]   Найдено фондов: {len(fund_list)}")

        for fund_url, fond_num, fond_title in fund_list:
            if fund_url in seen_funds:
                continue
            seen_funds.add(fund_url)

            print(f"[ГАПК] Фонд {fond_num}: {fond_title[:60]}")

            if list_only:
                found_total += 1
                yield GapkRecord(
                    fond_num=fond_num,
                    fond_title=fond_title,
                    url=fund_url,
                )
                continue

            # Получаем описи фонда
            inv_list = _get_inventories(session, fund_url, debug=debug)
            if not inv_list:
                print(f"[ГАПК]   Описи не найдены для фонда {fond_num}")
                continue

            for inv_url, inv_title in inv_list:
                # Получаем дела описи
                cases = _get_cases(session, inv_url, geo_filter=geo_filter, debug=debug)
                for case in cases:
                    y_from, y_to = _parse_years(case["row_text"])
                    if year_from and y_to and y_to < year_from:
                        continue
                    if year_to and y_from and y_from > year_to:
                        continue
                    found_total += 1
                    yield GapkRecord(
                        title=case["title"],
                        fond_num=fond_num,
                        fond_title=fond_title,
                        opisi_num=inv_title,
                        delo_num=case["delo_num"],
                        year_from=y_from,
                        year_to=y_to,
                        url=case["url"],
                    )

    if found_total == 0:
        print("[ГАПК] Результатов не найдено. Запустить с --debug или --list-funds.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Поиск картографических фондов в ГАПК (archives.permkrai.ru)"
    )
    parser.add_argument("--keyword", default="",
                        help="Ключевое слово для фильтра фондов (по умолчанию: перебор MAP_FUND_KEYWORDS)")
    parser.add_argument("--geo", default="",
                        help="Фильтр дел по территории (подстрока)")
    parser.add_argument("--year-from", type=int, default=1700, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--list-funds", action="store_true", dest="list_funds",
                        help="Только вывести список подходящих фондов без перехода в описи")
    parser.add_argument("--archive", default=DEFAULT_ARCHIVE,
                        help="Раздел портала: archive1 = ГАПК (по умолчанию), "
                             "archive = archives.permkrai.ru/archive/")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    keywords = [args.keyword] if args.keyword else MAP_FUND_KEYWORDS
    session = _make_session()

    results = list(search_funds(
        session, keywords,
        geo_filter=args.geo,
        year_from=args.year_from,
        year_to=args.year_to,
        list_only=args.list_funds,
        archive=args.archive,
        debug=args.debug,
    ))

    print(f"\n[ГАПК] Итого: {len(results)}")
    for r in results:
        if args.list_funds:
            print(f"  Ф.{r.fond_num:<8} {r.fond_title[:65]}")
            print(f"             {r.url}")
        else:
            yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
            print(f"  Ф.{r.fond_num} Оп.{r.opisi_num} Д.{r.delo_num}  {yr:<12} {r.title[:50]}")
            if r.url:
                print(f"             {r.url}")


if __name__ == "__main__":
    main()
