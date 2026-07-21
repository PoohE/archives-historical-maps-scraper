"""
РНБ — Сводный каталог русских печатных карт XVIII века
https://nlr.ru/rlin/kartogr18.php

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

Форма: POST https://nlr.ru/rlin/kartogr18.php
Кодировка: windows-1251
Кнопка поиска: image input name="Poisk" → передавать Poisk.x=10&Poisk.y=10
Кнопка «вперёд»: image input name="Next_poisk" → передавать Next_poisk.x=10

Поля поиска:
  field0=SE1   → Географический заголовок  (наш приоритет)
  field0=SE5   → Заглавие
  field0=SE4   → Персоналия
  field0=SE6   → Год издания
  field0=SE8   → Место издания
  field0=SE12  → Предметная рубрика

  znach0=<запрос>  (в windows-1251)
  operator0=начало строки | содержит строку | все слова | любое слово

Скрытые поля (обязательны):
  database=karpgr18
  basename=... (из формы)
  basesize=518
  search=<строка из предыдущего ответа при пагинации>

База: 518 записей (карты XVIII века), обновление 2007-12-25.

Rusmarc: rusmarc.php?numer=<N>&database=karpgr18  (popup, структурированные данные)
  numer = порядковый номер в базе (на 1 меньше отображаемого номера записи)

══════════════════════════════════════════════════════════════
РЕЗУЛЬТАТЫ (18 записей по «Калуж»)
══════════════════════════════════════════════════════════════

Каждая запись: шифр РНБ + полное библиографическое описание + ссылка Rusmarc.
Шифр: РНБ К 1-Росс 2/15а и аналоги.

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_rnb_kart.py                   # все 4 губернии
  python searcher_rnb_kart.py --geo Калуж       # одна губерния
  python searcher_rnb_kart.py --geo Калуж --debug
"""

import re
import sys
import time
import argparse
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator

import requests
from bs4 import BeautifulSoup

# Импортировать TERRITORIES из modules/territories.py
sys.path.insert(0, str(Path(__file__).parent.parent))
from territories import TERRITORIES

BASE_URL   = "https://nlr.ru"
SEARCH_URL = "https://nlr.ru/rlin/kartogr18.php"

# Список расширен: вместо 4 губерний теперь 49 территорий (с уездами)
GEO_TERMS = TERRITORIES

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": SEARCH_URL,
    "Content-Type": "application/x-www-form-urlencoded",
}


@dataclass
class RnbKartRecord:
    record_num: str = ""       # отображаемый номер (313, 329, …)
    shelfmark: str = ""        # шифр РНБ К 1-Росс 2/15а
    description: str = ""     # полное библиографическое описание
    year_from: int | None = None
    year_to: int | None = None
    rusmarc_url: str = ""      # URL карточки в RUSMARC
    geo_query: str = ""        # запрос, по которому найдено
    url: str = SEARCH_URL
    library_id: str = "rnb_kart"
    library_name: str = "РНБ — Сводный каталог карт XVIII в."


def _encode_post(fields: list[tuple[str, str]]) -> bytes:
    """Кодирует список пар (name, value) в windows-1251 URL-encoded."""
    parts = []
    for k, v in fields:
        parts.append(
            f"{k}={requests.utils.quote(v.encode('windows-1251'), safe='')}"
        )
    return "&".join(parts).encode("ascii")


def _build_search_fields(geo: str) -> list[tuple[str, str]]:
    return [
        ("field0", "SE1"), ("znach0", geo), ("operator0", "начало строки"),
        ("log1", "AND"),
        ("field1", "SE5"), ("znach1", ""), ("operator1", "начало строки"),
        ("log2", "AND"),
        ("field2", "SE4"), ("znach2", ""), ("operator2", "начало строки"),
        ("log3", "AND"),
        ("field3", "SE6"), ("znach3", ""), ("operator3", "начало строки"),
        ("log4", "AND"),
        ("field4", "SE8"), ("znach4", ""), ("operator4", "начало строки"),
        ("log5", "AND"),
        ("field5", "SE12"), ("znach5", ""), ("operator5", "начало строки"),
        ("database", "karpgr18"),
        ("basename", "Сводный каталог русских печатных карт XVIII века"),
        ("basesize", "518"),
        ("baseupdate", "2007-12-25 16:33:24 "),
        ("search", ""),
        ("Poisk.x", "10"),
        ("Poisk.y", "10"),
    ]


def _extract_hidden_fields(html: str) -> dict[str, str]:
    """
    Парсит все hidden-поля из HTML страницы результатов.
    Возвращает словарь name→value (уже декодировано из windows-1251).
    """
    fields: dict[str, str] = {}
    for m in re.finditer(
        r'<input[^>]+type=["\']?hidden["\']?[^>]*>', html, re.I
    ):
        tag = m.group(0)
        name_m  = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
        value_m = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
        if name_m:
            fields[name_m.group(1)] = value_m.group(1) if value_m else ""
    return fields


def _has_next_page(html: str) -> bool:
    return bool(re.search(r'name="Next_poisk"', html, re.I))


def _parse_years(text: str) -> tuple[int | None, int | None]:
    # Игнорируем годы после 1920 (библиографические ссылки типа "1961")
    nums = re.findall(r"\b(1[5-9]\d{2})\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _parse_records(html: str, geo: str, debug: bool = False) -> list[RnbKartRecord]:
    """Парсит HTML страницы результатов → список записей."""
    if debug:
        print("\n─── HTML (первые 4000 символов) ───")
        print(html[:4000])
        print("─── конец ───\n")

    records: list[RnbKartRecord] = []
    soup = BeautifulSoup(html, "lxml")

    # Каждая запись: <FONT COLOR="RED">NNN</FONT> ... <hr>
    # Ищем все <tr> с <font color="RED">
    for td in soup.find_all("td"):
        font = td.find("font", color=re.compile(r"RED", re.I))
        if not font:
            continue

        rec_num = font.get_text(strip=True)
        if not rec_num.strip().isdigit():
            continue

        # Весь текст ячейки — это описание
        raw_text = td.get_text(separator="\n", strip=True)
        lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]

        # Первая строка после номера — шифр
        shelfmark = ""
        desc_start = 0
        for i, ln in enumerate(lines):
            if ln == rec_num:
                if i + 1 < len(lines):
                    shelfmark = lines[i + 1]
                desc_start = i + 2
                break

        description = " ".join(lines[desc_start:]).replace("Rusmarc", "").strip()

        # Ссылка Rusmarc → numer
        rusmarc_url = ""
        rusmarc_a = td.find("a", href=re.compile(r"rusmarc", re.I))
        if rusmarc_a:
            href = rusmarc_a.get("href", "")
            m = re.search(r"numer=(\d+)", href)
            if m:
                rusmarc_url = f"{BASE_URL}/rlin/rusmarc.php?numer={m.group(1)}&database=karpgr18"

        y_from, y_to = _parse_years(description)

        records.append(RnbKartRecord(
            record_num=rec_num,
            shelfmark=shelfmark,
            description=description[:600],
            year_from=y_from,
            year_to=y_to,
            rusmarc_url=rusmarc_url,
            geo_query=geo,
        ))

    return records


def search_geo(session: requests.Session, geo: str,
               debug: bool = False) -> Iterator[RnbKartRecord]:
    """Поиск по географическому заголовку (поле SE1)."""
    # Первый запрос
    body = _encode_post(_build_search_fields(geo))
    try:
        resp = session.post(SEARCH_URL, data=body, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"[РНБ карты] Ошибка поиска {geo!r}: {e}")
        return

    html = resp.content.decode("windows-1251")

    m = re.search(r"Найдено\s+записей[:\s]+(\d+)", html, re.I)
    total = int(m.group(1)) if m else "?"
    print(f"[РНБ карты] {geo!r}: {total} записей")

    page = 1
    while True:
        records = _parse_records(html, geo, debug=(debug and page == 1))
        for rec in records:
            yield rec

        if not _has_next_page(html):
            break

        # Пагинация: берём все hidden-поля из страницы результатов
        hidden = _extract_hidden_fields(html)
        next_fields = list(hidden.items()) + [
            ("Next_poisk.x", "10"),
            ("Next_poisk.y", "10"),
        ]

        time.sleep(2.0)
        page += 1
        print(f"[РНБ карты] Страница {page}…")
        body = _encode_post(next_fields)
        try:
            resp = session.post(SEARCH_URL, data=body, timeout=20)
            resp.raise_for_status()
            html = resp.content.decode("windows-1251")
        except Exception as e:
            print(f"[РНБ карты] Ошибка стр.{page}: {e}")
            break


def search(geo: str = "", debug: bool = False) -> Iterator[RnbKartRecord]:
    session = requests.Session()
    session.headers.update(HEADERS)
    if geo:
        yield from search_geo(session, geo, debug)
    else:
        seen: set[str] = set()
        for term in GEO_TERMS:
            time.sleep(2.0)
            for rec in search_geo(session, term, debug):
                key = rec.record_num
                if key not in seen:
                    seen.add(key)
                    yield rec


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск в РНБ Сводном каталоге карт XVIII в."
    )
    parser.add_argument("--geo", default="",
                        help="Географический заголовок (Калуж / Перм / Смолен / Яросла)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    results = list(search(args.geo, args.debug))
    print(f"\n[РНБ карты] Итого: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  #{r.record_num:<6} {yr:<12} [{r.shelfmark}]")
        print(f"             {r.description[:80]}")
        if r.rusmarc_url:
            print(f"             {r.rusmarc_url}")


if __name__ == "__main__":
    main()
