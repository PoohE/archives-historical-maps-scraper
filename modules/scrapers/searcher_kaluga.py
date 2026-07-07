"""
КАЛУЖСКАЯ ОБЛАСТНАЯ НАУЧНАЯ БИБЛИОТЕКА им. В.Г. БЕЛИНСКОГО
Электронный каталог: http://217.15.203.140:81/cgi-bin/irbis64r_plus/irbis_webcgi.exe

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
══════════════════════════════════════════════════════════════

Система:   IRBIS64 (irbis64r_plus) — стандартная АБИС для российских библиотек
Адрес:     http://217.15.203.140:81  (IP без домена — геоблок маловероятен)
CGI:       /cgi-bin/irbis64r_plus/irbis_webcgi.exe

БАЗЫ ДАННЫХ:
  KR   — основной краеведческий каталог (поиск "карта калужская" → 234 результата)
  RK   — «Редкая книга» (37 ед.) — приоритет, там исторические карты
  (возможны другие: EC — Экология, PZ — Природопользование и т.д.)

ПОИСК (параметры IRBIS64):
  C21COM=S            — команда поиска
  P21DBN=KR           — база данных
  S21FMT=brief        — краткий формат результатов
  S21STN=1            — начальный номер записи (пагинация)
  S21ALL=             — поисковый запрос
  S21CNT=20           — количество записей на странице

ФИЛЬТР ПО РУБРИКАМ:
  В результатах есть поле «Рубрики: Карты» — ключевой фильтр.
  Способ 1: поиск через S21ALL с ограничением по рубрике (ББК К или Рубрика=Карты)
  Способ 2: постфильтрация по тексту «Рубрики: Карты» в HTML результатов
  Рекомендуется Способ 2 — он точнее (Способ 1 зависит от конфигурации IRBIS).

ЭКСПОРТ:
  Кнопка «Печать/Сохранение результатов поиска» → «все найденные» → выгрузка
  всех найденных записей в одном запросе. Параметр: C21COM=R (report/print).
  Формат вывода: plain text или RTF с полными библ. описаниями.
  ПРИОРИТЕТ: использовать экспорт, а не постраничный обход — быстрее и надёжнее.

СТРУКТУРА ЗАПИСИ (из HTML):
  - Шифр (ББК):          К 26.18, К о (=6) и т.д.
  - Заглавие:            ссылка на полное описание
  - Рубрики:             Карты / Деревни–История / ...
  - Аннотация:           текстовое поле
  - Год издания:         из библ. описания
  - «Прямая ссылка на документ» — формируется кнопкой, не прямой href

ПАГИНАЦИЯ:
  S21STN=1, 6, 11, 16, ... (шаг = S21CNT, по умолчанию 5)
  Последняя страница: S21STN > total_found → пустой список

══════════════════════════════════════════════════════════════
ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ И ПРАВИЛА
══════════════════════════════════════════════════════════════

1. ЛОЖНЫЕ СРАБАТЫВАНИЯ: запрос «карта калужская» даёт 234 результата, из которых
   большинство — книги или статьи, упоминающие слово «карта» в тексте.
   Фильтровать обязательно по полю «Рубрики: Карты».

2. ОТДЕЛЬНАЯ БАЗА «Редкая книга» (P21DBN=RK или аналог) — проверять отдельно,
   там 37 документов, среди которых высока вероятность исторических карт.

3. IRBIS может ограничивать запросы по IP при частых обращениях — ставить
   задержку ≥ 2 сек между запросами.

4. URL содержит IP (не домен) — может смениться при переезде сервера.
   При ошибке подключения проверить актуальный адрес через belinkaluga.ru.

5. ПРЯМАЯ ССЫЛКА на документ формируется кнопкой JavaScript — не является
   статичным href. Для получения: парсить атрибут data-href или
   использовать отдельный запрос C21COM=R с номером записи.

6. КЛЮЧЕВЫЕ СЛОВА для поиска: только географические имена губерний и уездов.
   Слово «карта» включать в запрос — иначе слишком много шума.
   Примеры: «карта Калужская», «план Калужской губернии», «атлас Калужский».

══════════════════════════════════════════════════════════════
ПРОВЕРОЧНЫЕ URL
══════════════════════════════════════════════════════════════

Поиск «карта калужская» в KR:
  http://217.15.203.140:81/cgi-bin/irbis64r_plus/irbis_webcgi.exe
  ?C21COM=S&P21DBN=KR&S21FMT=brief&S21ALL=карта+калужская&S21STN=1

«Редкая книга»:
  ?C21COM=S&P21DBN=RK&S21FMT=brief&S21ALL=карта&S21STN=1

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_kaluga.py "карта Калужская губерния"   # один запрос
  python searcher_kaluga.py --all-queries                # все 4 губернии + ключевые слова
  python searcher_kaluga.py --debug                      # дамп HTML первой страницы
  python searcher_kaluga.py --db RK                      # только «Редкая книга»
"""

import re
import sys
import time
import argparse
from dataclasses import dataclass, field
from typing import Iterator
from urllib.parse import urlencode, quote

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://217.15.203.140:81"
CGI = "/cgi-bin/irbis64r_plus/irbis_webcgi.exe"
SEARCH_URL = BASE_URL + CGI

# Все базы данных для проверки
DATABASES = {
    "KR": "Краеведение (основная)",
    "RK": "Редкая книга",
}

# Ключевые слова + территории для полного обхода
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
HEADERS = {"User-Agent": UA}


@dataclass
class KalugaRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    bbk: str = ""                # шифр ББК
    rubrics: str = ""            # рубрики
    annotation: str = ""
    url: str = ""
    db: str = ""                 # база данных (KR / RK)
    library_id: str = "kaluga_lib"
    library_name: str = "Калужская ОНБИБ им. В.Г. Белинского"


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


def _is_map_record(rubrics: str, bbk: str) -> bool:
    """Проверяет является ли запись картографическим материалом."""
    text = (rubrics + " " + bbk).lower()
    return (
        "карт" in text
        or "план" in text
        or "атлас" in text
        or "к 26" in text   # ББК: К 26 = картография
        or "к о" in text    # ББК: К о = краеведение (общий)
    )


def _parse_results_page(soup: BeautifulSoup, db: str,
                        debug: bool = False) -> tuple[list[KalugaRecord], int]:
    """
    Парсит страницу результатов IRBIS64.
    Возвращает (список записей, всего найдено).
    """
    if debug:
        print("\n─── HTML (первые 6000 символов) ───")
        print(soup.prettify()[:6000])
        print("─── конец HTML ───\n")

    # Определяем общее количество найденных
    total = 0
    total_match = re.search(r"Найденных документов.*?:\s*(\d+)", soup.get_text())
    if not total_match:
        total_match = re.search(r"найдено.*?(\d+)", soup.get_text(), re.I)
    if total_match:
        total = int(total_match.group(1))

    records: list[KalugaRecord] = []

    # IRBIS64 brief format: каждая запись в отдельном блоке
    # Пробуем разные варианты разметки
    items = soup.select("table.brief_result, div.result_item, .brief")
    if not items:
        # Fallback: ищем блоки с ББК (характерный признак IRBIS записи)
        items = []
        for el in soup.find_all(string=re.compile(r"ББК\s+[А-ЯA-Z]")):
            parent = el.find_parent("td") or el.find_parent("div") or el.find_parent("p")
            if parent and parent not in items:
                items.append(parent)

    if not items:
        # Последний вариант: парсить весь текст как блоки
        full_text = soup.get_text("\n")
        blocks = re.split(r"\n{3,}", full_text)
        for block in blocks:
            if "ББК" in block or "Рубрики" in block:
                # Извлекаем поля из текста
                title_m = re.search(r"^(.+?)\n", block.strip())
                title = title_m.group(1).strip() if title_m else ""
                bbk_m = re.search(r"ББК\s+([^\n]+)", block)
                bbk = bbk_m.group(1).strip() if bbk_m else ""
                rub_m = re.search(r"Рубрики:\s*([^\n]+)", block)
                rubrics = rub_m.group(1).strip() if rub_m else ""
                ann_m = re.search(r"Аннотация:\s*([^\n]+(?:\n[^\n]+)*)", block)
                annotation = ann_m.group(1).strip()[:300] if ann_m else ""

                if not _is_map_record(rubrics, bbk):
                    continue

                y_from, y_to = _parse_years(block)
                records.append(KalugaRecord(
                    title=title,
                    year_from=y_from,
                    year_to=y_to,
                    bbk=bbk,
                    rubrics=rubrics,
                    annotation=annotation,
                    db=db,
                ))
        return records, total

    # Парсинг найденных HTML-элементов
    for item in items:
        text = item.get_text("\n", strip=True)

        # Заголовок — первая ссылка
        title_el = item.find("a")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        href = title_el.get("href", "") if title_el else ""
        url = href if href.startswith("http") else (BASE_URL + href if href else "")

        # ББК
        bbk_m = re.search(r"ББК\s+([^\n\r<]+)", text)
        bbk = bbk_m.group(1).strip() if bbk_m else ""

        # Рубрики
        rub_m = re.search(r"Рубрики:\s*([^\n\r<]+)", text)
        rubrics = rub_m.group(1).strip() if rub_m else ""

        # Аннотация
        ann_m = re.search(r"Аннотация:\s*([^\n\r<]{10,})", text)
        annotation = ann_m.group(1).strip()[:300] if ann_m else ""

        if not title:
            continue
        if not _is_map_record(rubrics, bbk):
            continue

        y_from, y_to = _parse_years(text)
        records.append(KalugaRecord(
            title=title,
            year_from=y_from,
            year_to=y_to,
            bbk=bbk,
            rubrics=rubrics,
            annotation=annotation,
            url=url,
            db=db,
        ))

    return records, total


def search_db(query: str, db: str = "KR",
              year_from: int | None = None,
              year_to: int | None = None,
              debug: bool = False) -> Iterator[KalugaRecord]:
    """
    Поиск в одной базе данных IRBIS64.
    Исключения пробрасываются наверх.
    """
    page_size = 20
    start = 1

    # Первый запрос — узнаём сколько всего
    params = {
        "C21COM": "S",
        "P21DBN": db,
        "S21FMT": "brief",
        "S21ALL": query,
        "S21STN": start,
        "S21CNT": page_size,
    }

    print(f"[КОНБ/{db}] Запрос: {query!r}", end=" ... ")
    resp = _get(SEARCH_URL, params=params)  # исключение наверх при ошибке
    soup = BeautifulSoup(resp.text, "lxml")
    records, total = _parse_results_page(soup, db, debug=debug)

    if total == 0:
        print("0 результатов")
        return

    print(f"всего {total}, стр. 1", end="")

    for rec in records:
        if year_from and rec.year_to and rec.year_to < year_from:
            continue
        if year_to and rec.year_from and rec.year_from > year_to:
            continue
        yield rec

    # Остальные страницы
    for start in range(1 + page_size, total + 1, page_size):
        print(f", стр. {start // page_size + 1}", end="")
        params["S21STN"] = start
        try:
            resp = _get(SEARCH_URL, params=params)
        except Exception as e:
            print(f"\n[КОНБ/{db}] Ошибка стр.{start}: {e}")
            break
        soup = BeautifulSoup(resp.text, "lxml")
        page_records, _ = _parse_results_page(soup, db)
        if not page_records:
            break
        for rec in page_records:
            if year_from and rec.year_to and rec.year_to < year_from:
                continue
            if year_to and rec.year_from and rec.year_from > year_to:
                continue
            yield rec

    print()  # перевод строки после всех страниц


def search(query: str,
           year_from: int | None = None,
           year_to: int | None = None,
           databases: list[str] | None = None,
           debug: bool = False) -> Iterator[KalugaRecord]:
    """
    Поиск по всем базам данных. Исключения пробрасываются наверх.
    """
    dbs = databases or list(DATABASES.keys())
    for db in dbs:
        yield from search_db(query, db=db, year_from=year_from,
                             year_to=year_to, debug=debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск карт в Калужской ОНБИБ (IRBIS64, 217.15.203.140:81)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос (напр. 'карта Калужская губерния')")
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--db", default="",
                        help=f"База данных: {', '.join(DATABASES)} (по умолч. все)")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries",
                        help="Перебрать все ключевые слова × территории (полный обход)")
    parser.add_argument("--debug", action="store_true",
                        help="Вывести HTML первой страницы (для отладки структуры)")
    args = parser.parse_args()

    dbs = [args.db] if args.db else list(DATABASES.keys())

    if args.all_queries:
        all_results: list[KalugaRecord] = []
        seen: set[str] = set()
        for kw in KEYWORDS:
            for territory in TERRITORIES:
                q = f"{kw} {territory}"
                for rec in search(q, args.year_from, args.year_to,
                                  databases=dbs, debug=False):
                    key = rec.title + str(rec.year_from)
                    if key not in seen:
                        seen.add(key)
                        all_results.append(rec)
        print(f"\n[КОНБ] Итого уникальных карт: {len(all_results)}")
        for r in all_results:
            yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
            print(f"  [{r.db}] {yr:<12} {r.title[:65]}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to,
                          databases=dbs, debug=args.debug))
    print(f"\n[КОНБ] Найдено карт: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  [{r.db}] {yr:<12} {r.bbk:<12} {r.title[:55]}")
        if r.rubrics:
            print(f"              Рубрики: {r.rubrics}")


if __name__ == "__main__":
    main()
