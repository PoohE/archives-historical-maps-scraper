"""
РОССИЙСКАЯ ГОСУДАРСТВЕННАЯ БИБЛИОТЕКА (РГБ)
Электронный каталог: https://search.rsl.ru

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (получено из DevTools 2026-07-07)
══════════════════════════════════════════════════════════════

API:
  URL:    https://search.rsl.ru/site/ajax-search?language=ru
  Метод:  POST (form-data)
  Ответ:  JSON с полем content (HTML-строка, ~78 kB)

Параметры POST (Form Data):
  SearchFilterForm[search]        — поисковый запрос
  SearchFilterForm[fulltext]      — полнотекстовый поиск (пусто = по заголовку/автору)
  SearchFilterForm[page]          — номер страницы (1-based)
  SearchFilterForm[sortby]        — сортировка (default / date / ...)
  SearchFilterForm[pubyearfrom]   — год издания от
  SearchFilterForm[pubyearto]     — год издания до
  SearchFilterForm[accessFree]    — 1 = только свободный доступ (15 187 записей)
  SearchFilterForm[accessLimited] — 0/1
  SearchFilterForm[elfunds]       — 0 (фильтр по фонду — уточнить)
  SearchFilterForm[nofile]        — 0
  SearchFilterForm[inDodRoom]     — 0
  SearchFilterForm[updatedFields] — search (служебное)

Ответ JSON:
  TotalHits         — общее кол-во результатов
  MaxDisplayPage    — максимум 100 страниц (1000 записей) на один запрос
  PageSize          — 10 записей на странице
  content           — HTML-строка со списком записей (парсить BeautifulSoup)
  filterAmounts     — {accessFree: N, accessLimited: N, ...}
  SearchFacetResult — фасеты

══════════════════════════════════════════════════════════════
СТРАТЕГИЯ ПОИСКА
══════════════════════════════════════════════════════════════

Проблема: "карта калужская" → 106 471 результат, MaxDisplayPage=100 → только 1000 доступны.

Решение:
1. Узкие запросы: "карта Калужской губернии", "план Пермского наместничества" и т.д.
2. Фильтр accessFree=1 + диапазон лет → резко сокращает выборку
3. Постфильтрация по шифру хранения KGR* (картографический фонд РГБ)

Шифры КГ РГБ:
  KGR — картографический фонд (Карты) ← ПРИОРИТЕТ
  KGR Ko — общегеографические карты
  KGR Kb — топографические карты
  KGR Ka — атласы

══════════════════════════════════════════════════════════════
СТРУКТУРА HTML ЗАПИСИ (из content)
══════════════════════════════════════════════════════════════

Каждая запись в HTML:
  <div class="row"> или <div class="result-item">
    Заголовок:     <a href="/ru/record/...">Название</a>
    Шифр:          текст после «Шифр хранения»
    Тема:          текст после «Тема»
    Общ. примечания: текст после «Общие примечания»
    Содержание:    текст после «Содержание»
    Ссылка:        /ru/record/{id}/ — карточка

Кнопка «больше» раскрывает скрытый div с полными данными —
они УЖЕ есть в HTML (display:none), дополнительный запрос не нужен.

Карточка документа:
  URL: https://search.rsl.ru/ru/record/{id}/
  Содержит полное библ. описание + ссылку на оцифровку

══════════════════════════════════════════════════════════════
ИЗВЕСТНЫЕ ОГРАНИЧЕНИЯ
══════════════════════════════════════════════════════════════

1. MaxDisplayPage=100 → максимум 1000 записей на запрос. При широком запросе
   часть записей недоступна. Делать узкие запросы (ключевое слово + территория).

2. Оцифровано 106 001, НЕ оцифровано 470. accessFree=1 даёт 15 187 — это только
   свободный доступ. Часть карт доступна только в читальном зале (inReadingRoom=29109).
   Для каталога важны обе группы — можно запускать с accessFree=0 тоже.

3. POST-запрос, не GET — стандартный requests работает через session с cookies.
   При ошибке 403 — добавить заголовок Referer: https://search.rsl.ru/

4. Скорость: ~78 kB HTML на страницу × 100 страниц = ~7.8 MB за запрос. Не быстро.
   Ставить задержку ≥ 2 сек.

5. Дубли с НЭБ возможны — НЭБ агрегирует из РГБ. Проверять по заголовку + году.

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_rsl.py "карта Калужской губернии"
  python searcher_rsl.py "карта Калужской губернии" --free-only
  python searcher_rsl.py --all-queries --year-from 1700 --year-to 1917
  python searcher_rsl.py "план Пермского наместничества" --debug
"""

import re
import sys
import time
import argparse
import csv
from dataclasses import dataclass, field
from typing import Iterator

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://search.rsl.ru/site/ajax-search"
CARD_BASE  = "https://search.rsl.ru/ru/record"

KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж"]
TERRITORIES = [
    # Калужская
    "Калужской губернии", "Калужского наместничества", "Калужская губерния",
    # Пермская
    "Пермской губернии", "Пермского наместничества", "Пермская губерния",
    # Смоленская
    "Смоленской губернии", "Смоленского наместничества", "Смоленская губерния",
    # Ярославская
    "Ярославской губернии", "Ярославского наместничества", "Ярославская губерния",
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://search.rsl.ru/ru/search",
    "Origin": "https://search.rsl.ru",
}


@dataclass
class RslRecord:
    title: str = ""
    author: str = ""
    year_from: int | None = None
    year_to: int | None = None
    shelfmark: str = ""          # Шифр хранения (KGR Ko 102/IX-114)
    subject: str = ""            # Тема (иерархия УДК)
    notes: str = ""              # Общие примечания (масштаб, проекция и т.д.)
    content_note: str = ""       # Содержание (доп. карты)
    url: str = ""                # https://search.rsl.ru/ru/record/{id}/
    access: str = ""             # free / limited / reading_room
    library_id: str = "rsl"
    library_name: str = "Российская государственная библиотека"


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        r = s.get("https://search.rsl.ru/ru/search", timeout=15)
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', r.text)
        if m:
            token = m.group(1)
            # Yii2 принимает CSRF и через заголовок, и через поле формы
            s.headers["X-Csrf-Token"] = token
            s._csrf_token = token  # сохраняем для подстановки в data
    except Exception:
        pass
    return s


def _post_with_retry(session: requests.Session, data: dict,
                     attempts: int = 2) -> requests.Response:
    """POST с ограниченной повторной попыткой при временном сбое TLS/сети."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.post(
                SEARCH_URL,
                params={"language": "ru"},
                data=data,
                timeout=30,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts:
                wait = 5 * attempt
                print(f"[РГБ] Временная ошибка POST; повтор через {wait} с")
                time.sleep(wait)
    raise last_error or RuntimeError("неизвестная ошибка POST РГБ")


def _parse_years(text: str) -> tuple[int | None, int | None]:
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _is_kgr(shelfmark: str) -> bool:
    """Проверяет что шифр принадлежит картографическому фонду РГБ."""
    s = shelfmark.upper()
    return s.startswith("KGR") or s.startswith("КГР")


def _parse_content_html(html: str, debug: bool = False) -> list[RslRecord]:
    """Парсит HTML из поля content JSON-ответа."""
    if debug:
        print("\n─── content HTML (первые 5000 символов) ───")
        print(html[:5000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    records: list[RslRecord] = []

    # Каждая запись — блок с заголовком-ссылкой на /ru/record/
    record_re = re.compile(r"^/ru/record/")
    seen_urls: set[str] = set()

    # В актуальной выдаче ссылка /ru/record/... называется «Описание»,
    # а заголовок находится в соседнем блоке .rsl-item-nocover-descr.
    # Поэтому сначала поднимаемся к контейнеру всей записи, а не к блоку
    # кнопок (старый селектор class_=row ошибочно выбирал именно его).
    for title_link in soup.find_all("a", href=record_re):
        url = "https://search.rsl.ru" + title_link["href"].rstrip("/") + "/"
        if url in seen_urls:
            continue
        seen_urls.add(url)

        container = title_link.find_parent(
            "div", class_=lambda value: value and "search-container" in value
        )
        if not container:
            container = title_link.find_parent(
                "div", class_=lambda value: value and "search-item" in value
            )
        if not container:
            container = title_link.find_parent("li") or title_link.find_parent("div")

        title_node = container.select_one(".rsl-item-nocover-descr, .js-item-maininfo") if container else None
        title = title_node.get_text(" ", strip=True) if title_node else title_link.get_text(" ", strip=True)

        text = container.get_text("\n", strip=True) if container else title

        # В актуальной выдаче значения полей находятся в паре блоков
        # .rsl-item-otherinfo-item-name / .rsl-item-otherinfo-item-value.
        # Извлечение по подписи не даёт соседним полям попасть в шифр.
        def field_value(label: str) -> str:
            if not container:
                return ""
            for block in container.select(".rsl-item-otherinfo-item"):
                name = block.select_one(".rsl-item-otherinfo-item-name")
                value = block.select_one(".rsl-item-otherinfo-item-value")
                if name and value and name.get_text(" ", strip=True) == label:
                    return value.get_text(" ", strip=True)
            return ""

        shelfmark = field_value("Шифр хранения")

        # Только картографический фонд
        # Без шифра нельзя подтвердить принадлежность к картографическому
        # фонду: широкая выдача РГБ содержит книги, журналы и справочники.
        if not _is_kgr(shelfmark):
            continue

        # Тема
        subject = field_value("Тема")

        # Общие примечания
        notes = field_value("Общие примечания")

        # Содержание
        content_note = field_value("Содержание")

        # Год
        y_from, y_to = _parse_years(text)

        # Доступ
        access = ""
        if "свободный" in text.lower():
            access = "free"
        elif "читальный зал" in text.lower():
            access = "reading_room"
        elif "ограниченный" in text.lower():
            access = "limited"

        records.append(RslRecord(
            title=title,
            author=(container.select_one(".js-item-authorinfo").get_text(" ", strip=True)
                    if container and container.select_one(".js-item-authorinfo") else ""),
            year_from=y_from,
            year_to=y_to,
            shelfmark=shelfmark,
            subject=subject,
            notes=notes,
            content_note=content_note,
            url=url,
            access=access,
        ))

    return records


def search_query(session: requests.Session,
                 query: str,
                 year_from: int | None = None,
                 year_to: int | None = None,
                 free_only: bool = False,
                 debug: bool = False) -> Iterator[RslRecord]:
    """
    Поиск по одному запросу. Обходит до MaxDisplayPage=100 страниц.
    Исключения пробрасываются наверх.
    """
    max_pages = 100
    found_total = 0
    seen_urls: set[str] = set()

    for page in range(1, max_pages + 1):
        data = {
            "_csrf":                           getattr(session, "_csrf_token", ""),
            "SearchFilterForm[pubyearfrom]":   str(year_from) if year_from else "",
            "SearchFilterForm[pubyearto]":     str(year_to)   if year_to   else "",
            "SearchFilterForm[sortby]":        "default",
            "SearchFilterForm[page]":          str(page),
            "SearchFilterForm[search]":        query,
            "SearchFilterForm[fulltext]":      "0",
        }
        # Yii2/jQuery сериализует updatedFields как массив. Передача строки
        # (как в старой версии) приводит к 400 или к пустой выдаче.
        data["SearchFilterForm[updatedFields][]"] = "search"
        if free_only:
            data["SearchFilterForm[accessFree]"] = "1"

        time.sleep(2.0)
        try:
            resp = _post_with_retry(session, data)
        except requests.RequestException as exc:
            print(f"[РГБ] Прогон прерван после страницы {page - 1}: {exc}")
            break
        j = resp.json()

        total_hits = j.get("TotalHits", 0)
        max_display = j.get("MaxDisplayPage", 100)
        content_html = j.get("content", "")

        if page == 1:
            print(f"[РГБ] {query!r}: {total_hits} результатов, "
                  f"доступно страниц: {min(max_display, 100)}")

        if not content_html or content_html.strip() == "":
            break

        records = _parse_content_html(content_html, debug=(debug and page == 1))

        for rec in records:
            if rec.url in seen_urls:
                continue
            seen_urls.add(rec.url)
            # Постфильтр по годам (если year_from/to не переданы в запрос)
            if year_from and rec.year_to and rec.year_to < year_from:
                continue
            if year_to and rec.year_from and rec.year_from > year_to:
                continue
            found_total += 1
            yield rec

        print(f"[РГБ]   стр.{page}: {len(records)} карт (KGR), итого {found_total}")

        if page >= min(max_display, 100):
            break


def search(query: str,
           year_from: int | None = None,
           year_to: int | None = None,
           free_only: bool = False,
           debug: bool = False) -> Iterator[RslRecord]:
    """Поиск по РГБ. Исключения пробрасываются наверх."""
    session = _make_session()
    yield from search_query(session, query, year_from, year_to, free_only, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Поиск карт в каталоге РГБ (search.rsl.ru)"
    )
    parser.add_argument("query", nargs="?", default="",
                        help="Поисковый запрос")
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to",   type=int, default=1920, dest="year_to")
    parser.add_argument("--free-only", action="store_true", dest="free_only",
                        help="Только свободный доступ (accessFree=1)")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries",
                        help="Все ключевые слова × территории")
    parser.add_argument("--debug", action="store_true",
                        help="Дамп HTML первой страницы")
    parser.add_argument("--csv", default="",
                        help="Записать структурированный результат в CSV")
    args = parser.parse_args()

    if args.all_queries:
        session = _make_session()
        seen: set[str] = set()
        total = 0
        for kw in KEYWORDS:
            for territory in TERRITORIES:
                q = f"{kw} {territory}"
                for rec in search_query(session, q, args.year_from, args.year_to,
                                        args.free_only):
                    if rec.url not in seen:
                        seen.add(rec.url)
                        total += 1
                        yr = f"{rec.year_from or '?'}–{rec.year_to or '?'}"
                        print(f"  {yr:<12} [{rec.shelfmark[:15]}] {rec.title[:55]}")
        print(f"\n[РГБ] Итого уникальных карт KGR: {total}")
        return

    if not args.query:
        parser.error("Укажите запрос или --all-queries")

    results = list(search(args.query, args.year_from, args.year_to,
                          args.free_only, args.debug))
    if args.csv:
        fields = ["title", "author", "year_from", "year_to", "shelfmark",
                  "subject", "notes", "content_note", "url", "access",
                  "library_id", "library_name"]
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for rec in results:
                writer.writerow({name: getattr(rec, name) for name in fields})
        print(f"[РГБ] CSV: {args.csv}")
    print(f"\n[РГБ] Карт KGR: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} [{r.shelfmark[:18]}] {r.title[:50]}")
        print(f"             {r.url}")
        if r.notes:
            print(f"             {r.notes[:80]}")


if __name__ == "__main__":
    main()
