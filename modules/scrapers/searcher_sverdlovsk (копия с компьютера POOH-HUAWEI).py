"""
СВЕРДЛОВСКАЯ ОБЛАСТНАЯ УНИВЕРСАЛЬНАЯ НАУЧНАЯ БИБЛИОТЕКА им. В. Г. БЕЛИНСКОГО
OPAC-Global (ДИТ-М) — электронный каталог
http://79.110.251.73/cgiopac/opacg/opac.exe

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

Система:   OPAC-Global v2.4.0 (ДИТ-М), CGI на Apache
Адрес:     http://79.110.251.73  (IP без домена)
CGI:       /cgiopac/opacg/opac.exe
Только без VPN (российский IP; с VPN — таймаут)

БАЗЫ ДАННЫХ:
  UNIF  — Единый каталог (все базы; использовать по умолчанию)
  BOOKS — Книги (СОУНБ им. В. Г. Белинского)
  STAT  — Статьи

ПОИСКОВЫЙ ЗАПРОС (профессиональный синтаксис OPAC-Global):
  ((SH карта)) AND (PY LE '1917')
  SH = предметная рубрика (Subject Heading)
  PY = год публикации (Publication Year)
  LE = меньше или равно
  TI = заглавие

СЕССИЯ (ГОСТЕВОЙ ВХОД):
  POST /cgiopac/opacg/opac.exe
    arg0=GUEST
    arg1=GUESTE
    TypeAccess=PayAccess
  Referer: https://book.uraic.ru/library/catalog.php
  Это стандартный публичный гостевой доступ (без регистрации).
  Источник: форма на https://book.uraic.ru/library/catalog.php (кнопка «Электронный каталог»)

ПАРАМЕТРЫ ПОИСКА (расширенный, ACT=SRCH2):
  Поле 1: I1=SH  V1=карта         (предмет)
  Поле 2: I2=PY  V2=1917  O2=LE   (год ≤ 1917)
  BASE=UNIF, FMT=brief, NUM=1 (стр. пагинации), ONPAGE=20

ПАГИНАЦИЯ:
  NUM=1, 21, 41, … (шаг = ONPAGE)
  Конец: пустой список или NUM > всего найдено

СТРУКТУРА ЗАПИСИ (из скрина):
  — Номер записи (1, 2, 3…)
  — Тип: «Однотомник. Книга.» / «Статья.» / «Дореволюционное издание.»
  — Автор, Заголовок, Выходные данные (место, год)
  — Библиотека: «Свердловская ОУНБ; Отдел: ДХ; Формат: С; Инв. номер: …»
  — Аннотация (курсив)
  — «Входит в…» ссылка

ФИЛЬТРАЦИЯ:
  Поиск по SH=карта возвращает и «карты трудового процесса» —
  постфильтровать по наличию географических слов в заголовке.

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_sverdlovsk.py                   # все 4 губернии (фильтр в заголовке)
  python searcher_sverdlovsk.py --geo Перм        # одна губерния
  python searcher_sverdlovsk.py --year-to 1800    # только XVIII век
  python searcher_sverdlovsk.py --debug           # дамп HTML первой страницы
  python searcher_sverdlovsk.py --check-ses       # проверить получение сессии
"""

import re
import sys
import time
import argparse
from dataclasses import dataclass, field
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE_URL   = "http://79.110.251.73"
CGI        = "/cgiopac/opacg/opac.exe"
SEARCH_URL = BASE_URL + CGI

GEO_TERMS = ["Калуж", "Перм", "Смолен", "Яросла"]

# Географические фильтры для постфильтрации результатов
GEO_MAP = {
    "Калуж": ["Калуж", "калуж"],
    "Перм":  ["Перм", "перм", "Уральск"],
    "Смолен": ["Смолен", "смолен"],
    "Яросла": ["Яросла", "яросла"],
}

# Картографические признаки для фильтрации нережографических «карт»
MAP_WORDS = ["губерни", "наместничеств", "уезд", "план города", "топограф",
             "атлас", "географич", "карта Росс", "межев", "генеральн",
             "Урал", "область", "край", "территори"]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": BASE_URL + "/opacg/",
}


@dataclass
class SverdRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    doc_type: str = ""          # Однотомник.Книга / Статья / Дореволюционное издание
    location: str = ""          # Отдел, инв. номер
    annotation: str = ""
    url: str = SEARCH_URL
    geo_query: str = ""
    library_id: str = "sverdlovsk"
    library_name: str = "Свердловская ОУНБ им. В. Г. Белинского"


# ── Сессия ────────────────────────────────────────────────────────────────────

def get_session(s: requests.Session, debug: bool = False) -> str:
    """
    Гостевой вход в OPAC-Global.
    Эмулирует нажатие кнопки «Электронный каталог» на book.uraic.ru/library/catalog.php
    POST arg0=GUEST, arg1=GUESTE, TypeAccess=PayAccess
    Возвращает SES-строку или '' если не удалось.
    """
    s.headers["Referer"] = "https://book.uraic.ru/library/catalog.php"

    try:
        r = s.post(SEARCH_URL,
                   data={"arg0": "GUEST", "arg1": "GUESTE", "TypeAccess": "PayAccess"},
                   timeout=20)
        txt = r.content.decode("windows-1251", errors="replace")

        if debug:
            print(f"[СО] Вход: {r.status_code}, {len(txt)} bytes")
            print(txt[:500])

        # Ищем SES в ответе
        m = re.search(r"SES=([A-Za-z0-9+/=_-]+)", txt)
        if m:
            ses = m.group(1)
            if debug:
                print(f"[СО] SES получен из HTML: {ses[:30]}...")
            return ses

        # Из cookies
        for name in ("SES", "ses", "SESID", "session"):
            if name in s.cookies:
                ses = s.cookies[name]
                if debug:
                    print(f"[СО] SES из куки {name}: {ses[:30]}...")
                return ses

        if debug:
            print(f"[СО] SES не найден в ответе. HTML: {txt[:400]}")

    except Exception as e:
        if debug:
            print(f"[СО] Ошибка входа: {e}")
        raise

    return ""


# ── Поиск ─────────────────────────────────────────────────────────────────────

def _build_query(geo: str, year_to: int) -> str:
    """Строит профессиональный запрос OPAC-Global."""
    return f"((SH карта)) AND (PY LE '{year_to}')"


def _search_page(s: requests.Session, ses: str, query: str,
                 num: int, onpage: int, base: str = "UNIF",
                 debug: bool = False) -> requests.Response:
    """Один запрос к CGI — страница результатов поиска."""
    # Пробуем профессиональный поиск (ACT=SRCH3, FIND=query)
    params: dict = {
        "ACT":    "SRCH3",
        "LNG":    "RUS",
        "BASE":   base,
        "FIND":   query,
        "FMT":    "brief",
        "NUM":    str(num),
        "ONPAGE": str(onpage),
    }
    if ses:
        params["SES"] = ses

    r = s.get(SEARCH_URL, params=params, timeout=20)
    r.raise_for_status()

    # Если пришёл пустой ответ или ошибка «Не хватает входных данных» — пробуем POST
    if "Не хватает" in r.text or len(r.text) < 300:
        if debug:
            print(f"[СО] GET не сработал, пробуем POST расширенный (ACT=SRCH2)")
        # Расширенный поиск через поля формы
        # SH = карта, PY LE year_to → разбираем из query
        year_match = re.search(r"PY LE '(\d+)'", query)
        year = year_match.group(1) if year_match else "1917"
        data: dict = {
            "ACT":    "SRCH2",
            "LNG":    "RUS",
            "BASE":   base,
            "I1":     "SH",
            "V1":     "карта",
            "I2":     "PY",
            "V2":     year,
            "O2":     "LE",
            "C2":     "AND",
            "FMT":    "brief",
            "NUM":    str(num),
            "ONPAGE": str(onpage),
        }
        if ses:
            data["SES"] = ses
        r = s.post(SEARCH_URL, data=data, timeout=20)
        r.raise_for_status()

    return r


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2})\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _is_geo_map(title: str, annotation: str, geo: str) -> bool:
    """Проверяет что запись — географическая карта нужной губернии."""
    text = (title + " " + annotation).lower()
    # Фильтр по территории
    terms = GEO_MAP.get(geo, [geo.lower()])
    if not any(t.lower() in text for t in terms):
        # Если нет привязки к конкретной губернии — проверяем общие гео-слова
        # (карта могла быть каталогизирована без указания региона)
        if not any(w in text for w in [w.lower() for w in MAP_WORDS[:4]]):
            return False
    # Исключаем явно не географические «карты»
    skip = ["трудового процесса", "технологическ", "качества", "учёта"]
    if any(s in text for s in skip):
        return False
    return True


def _parse_results(html: str, geo: str, debug: bool = False) -> tuple[list[SverdRecord], int]:
    """
    Парсит HTML страницы результатов OPAC-Global.
    Возвращает (список записей, всего найдено).
    """
    if debug:
        print("\n─── HTML (первые 5000 символов) ───")
        print(html[:5000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text(" ", strip=True)

    # Всего найдено
    total = 0
    m = re.search(r"Количество\s+записей[:\s]*(\d+)", full_text, re.I)
    if not m:
        m = re.search(r"Найдено[:\s]*(\d+)", full_text, re.I)
    if m:
        total = int(m.group(1))

    records: list[SverdRecord] = []

    # Каждая запись — нумерованный блок. Пробуем несколько вариантов разметки.
    # Вариант A: таблица с нумерованными строками
    rows = soup.select("table tr")
    # Вариант B: div.record / div.result / li
    if not rows:
        rows = soup.select("div.result_item, div.record, li.result")

    # Вариант C: ищем блоки по числовым меткам
    if not rows:
        # Разбиваем текст на блоки по номерам записей
        blocks = re.split(r"\n\s*(\d{1,4})\s*\n", full_text)
        for i in range(1, len(blocks) - 1, 2):
            num_str = blocks[i]
            content = blocks[i + 1] if i + 1 < len(blocks) else ""
            if not num_str.isdigit():
                continue
            title_m = re.search(r"([А-ЯA-Z][^.\n]{10,})", content)
            title = title_m.group(1).strip() if title_m else ""
            y_from, y_to = _parse_years(content)
            ann_m = re.search(r"([А-Яа-я][^.]{30,}\.$)", content)
            annotation = ann_m.group(1).strip()[:300] if ann_m else ""
            if title and (not geo or _is_geo_map(title, annotation, geo)):
                records.append(SverdRecord(
                    title=title[:200],
                    year_from=y_from,
                    year_to=y_to,
                    annotation=annotation,
                    geo_query=geo,
                ))
        return records, total

    for row in rows:
        text = row.get_text("\n", strip=True)
        if len(text) < 30:
            continue

        # Тип документа
        doc_type = ""
        for dt in ["Однотомник", "Многотомник", "Статья", "Дореволюционное", "Аналитика"]:
            if dt in text:
                doc_type = dt
                break

        # Заголовок — первая ссылка или первая строка с большой буквы
        title_el = row.find("a")
        if title_el:
            title = title_el.get_text(" ", strip=True)
        else:
            lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 10]
            title = lines[0] if lines else ""

        # Исключаем навигационные строки
        if not title or title.lower().startswith(("база данных", "формат", "отдел:")):
            continue

        # Автор
        author_m = re.search(r"^([А-Я][а-я]+\s+[А-Я]\.[А-Я]?\.?)", text, re.M)
        author = author_m.group(1).strip() if author_m else ""

        # Аннотация (обычно в <i> или <em>)
        ann_el = row.find(["i", "em"])
        annotation = ann_el.get_text(" ", strip=True)[:300] if ann_el else ""

        # Местонахождение
        loc_m = re.search(r"(Свердловская[^;]*;[^;]*;[^;]*Инв\.\s*номер[^<\n]*)", text, re.I)
        location = loc_m.group(1).strip()[:120] if loc_m else ""

        y_from, y_to = _parse_years(text)

        if not title:
            continue

        # Постфильтрация по географии и типу карты
        if geo and not _is_geo_map(title, annotation, geo):
            continue

        records.append(SverdRecord(
            title=title[:200],
            author=author,
            year_from=y_from,
            year_to=y_to,
            doc_type=doc_type,
            location=location,
            annotation=annotation,
            geo_query=geo,
        ))

    return records, total


def search_geo(s: requests.Session, ses: str, geo: str,
               year_to: int = 1917, base: str = "UNIF",
               debug: bool = False) -> Iterator[SverdRecord]:
    """Поиск карт по одной губернии."""
    query = _build_query(geo, year_to)
    onpage = 20
    num = 1
    total = None

    print(f"[СО] Запрос: {query!r} (база {base})")

    while True:
        try:
            r = _search_page(s, ses, query, num, onpage, base, debug=(debug and num == 1))
        except Exception as e:
            print(f"\n[СО] Ошибка стр.{num}: {e}")
            break

        html = r.content.decode("windows-1251", errors="replace")
        records, found_total = _parse_results(html, geo, debug=(debug and num == 1))

        if total is None:
            total = found_total
            if total == 0:
                print(f"[СО] 0 результатов")
                return
            pages = (total + onpage - 1) // onpage
            print(f"[СО] Всего: {total}, страниц: {pages}")

        print(f"[СО] Стр.{num//onpage + 1}: {len(records)} карт-записей")
        for rec in records:
            yield rec

        num += onpage
        if num > total:
            break
        time.sleep(2.0)


def search(geo: str = "", year_to: int = 1917,
           debug: bool = False) -> Iterator[SverdRecord]:
    """Поиск по всем 4 губерниям или одной конкретной."""
    s = requests.Session()
    s.headers.update(HEADERS)

    ses = get_session(s, debug=debug)

    terms = [geo] if geo else GEO_TERMS
    seen: set[str] = set()

    for term in terms:
        time.sleep(2.0)
        for rec in search_geo(s, ses, term, year_to=year_to, debug=debug):
            key = rec.title + str(rec.year_from)
            if key not in seen:
                seen.add(key)
                yield rec


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск карт в Свердловской ОУНБ им. Белинского (OPAC-Global)"
    )
    parser.add_argument("--geo", default="",
                        help="Губерния (Калуж / Перм / Смолен / Яросла) — без флага все 4")
    parser.add_argument("--year-to", type=int, default=1917, dest="year_to",
                        help="Год публикации ≤ (по умолчанию 1917)")
    parser.add_argument("--debug", action="store_true",
                        help="Дамп HTML первой страницы + подробный лог")
    parser.add_argument("--check-ses", action="store_true", dest="check_ses",
                        help="Только проверить получение сессии и выйти")
    args = parser.parse_args()

    if args.check_ses:
        s = requests.Session()
        s.headers.update(HEADERS)
        ses = get_session(s, debug=True)
        print(f"\n[СО] SES = {ses!r}")
        print("[СО] Cookies:", dict(s.cookies))
        return

    results = list(search(args.geo, args.year_to, debug=args.debug))
    print(f"\n[СО] Итого уникальных карт: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} [{r.doc_type[:12]}] {r.title[:65]}")
        if r.location:
            print(f"               {r.location[:80]}")


if __name__ == "__main__":
    main()
