"""
ГАРФ — Государственный архив Российской Федерации
http://opisi.garf.su — онлайн-опись

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (из скрина 2026-07-16)
══════════════════════════════════════════════════════════════

Ключевой фонд:
  Ф.1829 «КОЛЛЕКЦИЯ ПЛАНОВ, КАРТ, ЧЕРТЕЖЕЙ И "РАППОРТОВ"»
  Оп.1 — Дела постоянного хранения. 1854–1917 гг.

URL фонда (v=2 = список описей):
  http://opisi.garf.su/default.asp?base=garf&menu=2&v=2
    &node=42&fond=2012

URL описи (v=5 = просмотр списка дел) формируется сайтом из актуального
идентификатора описи; старые значения cf/co больше не используются.

Параметры:
  base   = garf
  menu   = 2
  v      = 5   (просмотр списка дел описи)
  node   = 42
  fond   = 2012      (внутренний ID Ф.1829)
  opis   = 6965      (ID Оп.1; извлекается из страницы фонда)
  cd     = 18392829 (контекст списка; извлекается из страницы описи)
  cp     = N         (номер страницы, 20 дел на страницу)

Формат записей (из скрина):
  1829 1 1  | Карта Польши XVII в. и 1862 г.           | (год)
  1829 1 2  | Карты Европейской части России, 1875-1908 |  1897
  ...
  Пагинация: 10 страниц на скрине (≥200 дел в фонде)

Фильтрация:
  Дело проходит если в названии есть хотя бы одно из TERRITORY_KEYS
  (или запущено с --all).

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  # Только дела с территориями по умолчанию (Калуж/Перм/Смолен/Яросл)
  python searcher_garf.py

  # Конкретная территория
  python searcher_garf.py --geo Калуж

  # Все дела без фильтра территории
  python searcher_garf.py --all

  # Дамп HTML для отладки
  python searcher_garf.py --debug
"""

import re
import sys
import time
import argparse
import csv
import json
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs
try:
    from .garf_card import parse_card
except ImportError:
    from garf_card import parse_card
from dataclasses import asdict, dataclass
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE_URL   = "http://opisi.garf.su"
SEARCH_URL = f"{BASE_URL}/default.asp"

# Параметры Ф.1829 Оп.1 (из скрина 2026-07-16)
FOND_1829_PARAMS = {
    "base": "garf",
    "menu": "2",
    "v":    "2",
    "node": "42",
    "fond": "2012",
}

TERRITORY_KEYS = ["Калуж", "Перм", "Смолен", "Яросл", "Москов"]
MAP_KEYS       = ["карт", "план", "чертеж", "атлас", "схем", "съем"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


@dataclass
class GarfRecord:
    title:     str = ""
    fond_num:  str = "1829"
    opisi_num: str = "1"
    delo_num:  str = ""
    year_from: int | None = None
    year_to:   int | None = None
    url:       str = ""
    sheets: str = ""
    annotation: str = ""
    notes: str = ""
    date_raw: str = ""
    extra_json: str = ""
    library_id:   str = "garf"
    library_name: str = "ГАРФ — Государственный архив РФ (Ф.1829)"


def fetch_case_record(session, listed):
    """Fetch one same-site v=7 card; never silently substitute list metadata."""
    url = listed['url']
    parts = urlsplit(url)
    if (parts.netloc != 'opisi.garf.su' or parts.scheme not in ('http', 'https')
            or parts.path != '/default.asp' or parse_qs(parts.query).get('v') != ['7']):
        raise ValueError('Missing or unexpected GARF detail-card URL')
    time.sleep(1.5)
    response = session.get(url, timeout=25, allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(f'GARF detail HTTP {response.status_code}')
    raw = response.content
    detail = parse_card(raw)
    if detail['case_number'] != listed['delo_num']:
        raise ValueError('GARF case number mismatch')
    detail['listing'] = listed
    detail['provenance'] = dict(url=url, sha256=hashlib.sha256(raw).hexdigest(),
                               retrieved_at=datetime.now(timezone.utc).isoformat(), http_status=200,
                               transport=parts.scheme, encoding='windows-1251')
    return GarfRecord(title=detail['title'], delo_num=detail['case_number'],
                      year_from=detail['year_from'], year_to=detail['year_to'], url=url,
                      sheets=detail['sheets'], annotation=detail['annotation'],
                      notes=detail['notes'], date_raw=detail['date_raw'],
                      extra_json=json.dumps(detail, ensure_ascii=False))


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _get_with_retry(session: requests.Session, params: dict, attempts: int = 2) -> requests.Response:
    """GET с одной повторной попыткой при временном обрыве старого сервера ГАРФ."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(SEARCH_URL, params=params, timeout=25)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts:
                wait = 5 * attempt
                print(f"[ГАРФ] Временная ошибка запроса; повтор через {wait} с")
                time.sleep(wait)
    raise last_error or RuntimeError("неизвестная ошибка запроса ГАРФ")


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _parse_delo_page(html: str, debug: bool = False) -> tuple[list[dict], int]:
    """
    Парсит одну страницу списка дел описи ГАРФ.
    Возвращает (записи, номер_последней_страницы).
    """
    if debug:
        print("\n─── HTML описи (первые 5000 символов) ───")
        print(html[:5000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    records: list[dict] = []

    # Список дел — таблица с колонками: чекбокс | иконка | номер | название | дата
    # Строки дел: каждая строка начинается с паттерна "1829 1 N"
    DELO_NUM_RE = re.compile(r"\b1829\s+1\s+(\d+)\b")

    # Ищем строки в таблице
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        row_text = row.get_text(" ", strip=True)
        m = DELO_NUM_RE.search(row_text)
        if not m:
            continue
        delo_num = m.group(1)

        # Название — в ячейке со ссылкой
        link = row.find("a", href=True)
        if link:
            title = link.get_text(" ", strip=True)
            href = link["href"]
            url = href if href.startswith("http") else BASE_URL + "/" + href.lstrip("/")
        else:
            # название в последней непустой ячейке
            title = ""
            for cell in cells:
                t = cell.get_text(strip=True)
                if t and not DELO_NUM_RE.search(t) and len(t) > 5:
                    title = t
            url = ""

        # Год — обычно последняя ячейка
        year_raw = cells[-1].get_text(strip=True)
        y_from, y_to = _parse_years(year_raw or title)

        records.append({
            "title":    title,
            "delo_num": delo_num,
            "year_raw": year_raw,
            "url":      url,
            "y_from":   y_from,
            "y_to":     y_to,
        })

    # Определяем последнюю страницу пагинации
    last_page = 1
    for a in soup.find_all("a", href=re.compile(r"page=\d+|pages=\d+|cp=\d+", re.I)):
        m = re.search(r"page[s]?=(\d+)", a["href"], re.I)
        if not m:
            m = re.search(r"(?:^|[?&])cp=(\d+)", a["href"], re.I)
        if m:
            n = int(m.group(1))
            if n > last_page:
                last_page = n
    # Если пагинация через GET-параметр &p=, &stpage= или &cp=
    for a in soup.find_all("a", href=re.compile(r"[?&](p|stpage|pg|cp)=\d+", re.I)):
        m = re.search(r"[?&](?:p|stpage|pg)=(\d+)", a["href"], re.I)
        if not m:
            m = re.search(r"[?&]cp=(\d+)", a["href"], re.I)
        if m:
            n = int(m.group(1))
            if n > last_page:
                last_page = n

    return records, last_page


def iter_fond(session: requests.Session, geo_filter: list[str] | None = None,
              year_from: int | None = None, year_to: int | None = None,
              all_records: bool = False, debug: bool = False) -> Iterator[GarfRecord]:
    """Обходит все страницы Ф.1829 Оп.1, фильтрует по территории и годам."""

    # Сначала получаем актуальный ID Оп.1 из страницы фонда.
    try:
        fond_resp = _get_with_retry(session, FOND_1829_PARAMS)
        fond_soup = BeautifulSoup(fond_resp.text, "lxml")
        opisi_href = None
        for link in fond_soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(" ", strip=True).lower()
            if "v=5" in href and "opis=" in href and ("дела постоянного хранения" in text or "оп.1" in text):
                opisi_href = href
                break
        if not opisi_href:
            raise RuntimeError("не найдена ссылка на Оп.1 в странице фонда")
        from urllib.parse import parse_qs, urlparse
        discovered = {k: v[-1] for k, v in parse_qs(urlparse(opisi_href).query).items()}
        FOND_1829_PARAMS.update({k: discovered[k] for k in ("opis", "fond", "node", "base", "menu") if k in discovered})
        FOND_1829_PARAMS["v"] = "5"
    except Exception as e:
        print(f"[ГАРФ] Не удалось определить актуальную Оп.1: {e}")
        return

    page = 1
    max_page = 1  # уточняется после первого запроса
    found_total = 0
    context_id = ""

    while page <= max_page:
        params = dict(FOND_1829_PARAMS)
        if context_id:
            params["cd"] = context_id
        if page > 1:
            params["cp"] = str(page)

        time.sleep(2.0)
        try:
            resp = _get_with_retry(session, params)
        except Exception as e:
            print(f"[ГАРФ] Ошибка стр.{page}: {e}")
            break

        raw, discovered_last = _parse_delo_page(resp.text, debug=(debug and page == 1))

        if not context_id:
            hidden = BeautifulSoup(resp.text, "lxml").find("input", attrs={"name": "cd"})
            if hidden and hidden.get("value"):
                context_id = hidden["value"]

        if discovered_last > max_page:
            max_page = discovered_last
            print(f"[ГАРФ] Найдено страниц: {max_page}")

        if not raw and page == 1:
            print("[ГАРФ] Дела не найдены. Запустить с --debug для анализа HTML.")
            break

        for rec in raw:
            title_lower = rec["title"].lower()

            if not all_records:
                # Фильтр территории
                if geo_filter:
                    if not any(g.lower() in title_lower for g in geo_filter):
                        continue
                else:
                    if not any(k.lower() in title_lower for k in TERRITORY_KEYS):
                        continue

            # Фильтр карт (страховка: все дела в Ф.1829 это карты/планы/чертежи)
            # Можно убрать, если фонд чисто картографический
            # if not any(k in title_lower for k in MAP_KEYS):
            #     continue

            detail_record = fetch_case_record(session, rec)
            y_from = detail_record.year_from
            y_to = detail_record.year_to
            if year_from and y_to and y_to < year_from:
                continue
            if year_to and y_from and y_from > year_to:
                continue

            found_total += 1
            yield detail_record

        print(f"[ГАРФ] стр.{page}/{max_page}: {len(raw)} дел, "
              f"подходящих {found_total}")
        page += 1


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Обход Ф.1829 в ГАРФ (opisi.garf.su) — Коллекция планов, карт, чертежей"
    )
    parser.add_argument("--geo", default="", dest="geo",
                        help="Фильтр территории (подстрока), напр. Калуж. "
                             "Можно несколько через запятую.")
    parser.add_argument("--year-from", type=int, default=1700, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--all",  action="store_true",
                        help="Не фильтровать по территории, вернуть все дела")
    parser.add_argument("--csv", help="Путь для CSV-экспорта")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    geo_filter = [g.strip() for g in args.geo.split(",")] if args.geo else None
    session = _make_session()

    results = list(iter_fond(
        session,
        geo_filter=geo_filter,
        year_from=args.year_from,
        year_to=args.year_to,
        all_records=args.all,
        debug=args.debug,
    ))

    print(f"\n[ГАРФ] Подходящих дел: {len(results)}")
    if args.csv:
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(asdict(GarfRecord()).keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(asdict(row) for row in results)
        print(f"[ГАРФ] CSV: {args.csv}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  1829/1/{r.delo_num:<6} {yr:<12} {r.title[:60]}")
        if r.url:
            print(f"             {r.url}")


if __name__ == "__main__":
    main()
