"""
РОССИЙСКИЙ ГОСУДАРСТВЕННЫЙ ИСТОРИЧЕСКИЙ АРХИВ (РГИА)
Электронный каталог: https://fgurgia.ru

══════════════════════════════════════════════════════════════
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ (из скринов 2026-07-10)
══════════════════════════════════════════════════════════════

РЕЖИМ 1 — Предметный указатель (тематические группы карт):
  URL:  GET https://fgurgia.ru/search
  Параметры:
    type=custom
    searchObjectType=SUBINDEX
    customSearchUnique=d
    p0.v=карта       ← поисковый термин
    p0.t=0           ← смещение (offset)
    p0.d=0
    p0.c=128         ← предположительно, ID коллекции или кол-во на странице
  Результат: список наименований (КАРТА ГАТЧИНСКОГО УЕЗДА, КАРТА МЕСТНОСТИ...)
  каждое — ссылка на объект → fgurgia.ru/object/{id}
  Пагинация: << < 1 из N > >> (параметр смещения для перебора)

РЕЖИМ 2 — Общий поиск (полнотекстовый по заголовкам дел):
  URL:  GET https://fgurgia.ru/search
  Параметры:
    type=simple
    p0.v=карта+Пермская   ← запрос
    p0.i=n                ← регистронезависимый поиск (n=no case)
    p0.d=0                ← смещение в результатах
    p0.c=128
    p0.t=0
  Результат: дела (Шифр, Заголовок, Крайние даты)
  Указывает на fgurgia.ru/object/{id}

Карточка объекта (fgurgia.ru/object/{id}):
  Наименование, Наименование группы, Библиографический источник,
  Примечание, Постоянная ссылка
  Раздел «Дела»:
    Шифр хранения (Ф. NNN Оп. NNN Д. NNN)
    Заголовок дела
    Крайние даты

══════════════════════════════════════════════════════════════
СТРАТЕГИЯ ПОИСКА
══════════════════════════════════════════════════════════════

ПРЕДМЕТНЫЙ УКАЗАТЕЛЬ — для систематического обхода картографических материалов:
  Запросы: "карта", "план", "атлас" → список десятков/сотен тематических групп
  Далее фильтруем по территории в заголовке (Калужская, Пермская и т.д.)

ОБЩИЙ ПОИСК — для прицельного поиска по губернии:
  Запросы: "карта Калужской", "план Пермской" и т.д.
  Возвращает конкретные дела с шифрами.

══════════════════════════════════════════════════════════════
ЗАПУСК
══════════════════════════════════════════════════════════════

  python searcher_rgia.py "карта Калужской"
  python searcher_rgia.py "карта Пермской" --debug
  python searcher_rgia.py --mode subindex --term карта
  python searcher_rgia.py --all-queries
"""

import re
import time
import argparse
import csv
from dataclasses import dataclass, field
from typing import Iterator

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://fgurgia.ru"
SEARCH_URL = "https://fgurgia.ru/search"
TREE_URL = BASE_URL + "/ajax/tree/{}"

TERRITORIES = [
    "Калужской",
    "Калужского",
    "Калужская",
    "Пермской",
    "Пермского",
    "Пермская",
    "Смоленской",
    "Смоленского",
    "Смоленская",
    "Ярославской",
    "Ярославского",
    "Ярославская",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://fgurgia.ru/",
}

# Шаг пагинации — кол-во записей на странице (уточнить после теста)
PAGE_SIZE = 20
SIMPLE_COMPONENT_ID = "72425"
TREE_PAGE_SIZE = 12


@dataclass
class RgiaRecord:
    title: str = ""
    fund_code: str = ""  # Шифр: Ф.NNN Оп.NNN Д.NNN
    fund_name: str = ""
    sheets: str = ""
    date_raw: str = ""
    subject_group: str = ""  # Наименование группы (в предметном указателе)
    year_from: int | None = None
    year_to: int | None = None
    bib_source: str = ""  # Библиографический источник
    notes: str = ""
    card_text: str = ""  # complete saved source-card text
    # JSON ответ /ajax/obj сохраняется отдельно в JSONL: это страховка от
    # потери полей карточки при последующих изменениях адаптера.
    raw_detail: dict[str, object] = field(default_factory=dict)
    url_download: str = ""  # data.downloadLink, when supplied by RGIA
    url_image: str = ""  # data.imageUrl, when supplied by RGIA
    url: str = ""  # fgurgia.ru/object/{id}
    library_id: str = "rgia"
    library_name: str = "РГИА (fgurgia.ru)"


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _parse_years(text: str) -> tuple[int | None, int | None]:
    normalized = text.casefold().replace("ё", "е")
    if re.search(
        r"конец\s+(?:xix|19)\s*(?:-|–|—)\s*начал\w*\s+(?:xx|20)\s+век",
        normalized,
    ):
        return 1900, 1900
    nums = re.findall(r"\b(1[5-9]\d{2}|20[012]\d)\b", text)
    if not nums:
        return None, None
    ys = [int(n) for n in nums]
    return min(ys), max(ys)


def _parse_object_page(html: str, obj_url: str, debug: bool = False) -> RgiaRecord:
    """Парсит карточку объекта fgurgia.ru/object/{id}."""
    if debug:
        print("\n─── object HTML (первые 3000 символов) ───")
        print(html[:3000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")

    # The detail panel uses labelled dataLine blocks, not table or dl rows.
    detail_fields = {}
    rows = soup.select(".dataLine[id]") or soup.select(".dataLine")
    for row in rows:
        label = row.select_one(".dataLabel")
        value = row.select_one(".dataWrap")
        if label is not None and value is not None:
            key = " ".join(label.get_text(" ", strip=True).split()).rstrip(":")
            detail_fields[key] = " ".join(value.get_text(" ", strip=True).split())
    if detail_fields.get("Шифр") and detail_fields.get("Заголовок"):
        date_raw = detail_fields.get("Крайние даты", "")
        year_from, year_to = _parse_years(date_raw)
        return RgiaRecord(
            title=detail_fields["Заголовок"],
            fund_code=detail_fields["Шифр"],
            fund_name=detail_fields.get("Название фонда", ""),
            sheets=detail_fields.get("Количество листов", ""),
            date_raw=date_raw,
            year_from=year_from,
            year_to=year_to,
            bib_source=detail_fields.get("Библиографический источник", ""),
            notes=detail_fields.get("Примечание", ""),
            card_text=_detail_card_text(detail_fields),
            url=obj_url,
        )

    # Заголовок
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        title_el = soup.select_one(".title, .name, .heading")
        if title_el:
            title = title_el.get_text(strip=True)

    fields: dict[str, str] = {}

    # Поля — возможны варианты разметки
    # Вариант 1: dl/dt/dd
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            fields[dt.get_text(strip=True).rstrip(":")] = dd.get_text(" ", strip=True)

    # Вариант 2: таблица
    if not fields:
        for row in soup.select("table tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                val = cells[1].get_text(" ", strip=True)
                if key:
                    fields[key] = val

    # Вариант 3: div-пары
    if not fields:
        for el in soup.select(".field, .prop"):
            label = el.select_one(".label, .name")
            value = el.select_one(".value, .val")
            if label and value:
                fields[label.get_text(strip=True).rstrip(":")] = value.get_text(
                    " ", strip=True
                )

    # Шифр хранения из раздела «Дела»
    fund_code = ""
    cases_section = soup.find(string=re.compile(r"Дела", re.I))
    if cases_section:
        parent = cases_section.find_parent(["div", "section", "ul"])
        if parent:
            # Ищем шифр в виде «Ф. NNN Оп. NNN Д. NNN»
            code_m = re.search(
                r"Ф\.\s*[\d\-]+\s+Оп\.\s*[\d\-]+[^<\n]*Д\.\s*[\d\-]+", parent.get_text()
            )
            if code_m:
                fund_code = code_m.group(0).strip()

    # Даты
    date_text = (
        fields.get("Крайние даты", "") + " " + fields.get("Дата", "") + " " + title
    )
    y_from, y_to = _parse_years(date_text)

    return RgiaRecord(
        title=title or fields.get("Наименование", ""),
        fund_code=fund_code or fields.get("Шифр", ""),
        subject_group=fields.get("Наименование группы", ""),
        year_from=y_from,
        year_to=y_to,
        bib_source=fields.get("Библиографический источник", "")[:200],
        notes=fields.get("Примечание", "")[:200],
        card_text=_detail_card_text(fields),
        url=obj_url,
    )


def classify_detail_object(data: dict) -> dict[str, object]:
    """Classify an AJAX detail without inventing a case identity.

    The jstree node set can include non-case objects. A catalog runner must
    preserve their provenance for review instead of treating a missing title or
    F/Op/D code as a parser exception.
    """
    attrs = {
        str(a.get("name", "")).strip(): str(a.get("text", "")).strip()
        for a in data.get("attributes", [])
        if a.get("name")
    }
    title = (
        str(data.get("title") or "").strip()
        or attrs.get("Наименование", "")
        or attrs.get("Название", "")
        or attrs.get("Заголовок", "")
    ).strip()
    code = attrs.get("Шифр", "").strip()
    independent_case = bool(
        title
        and re.fullmatch(r"Ф\.\s*\d+\s+Оп\.\s*\d+\s+Д\.\s*\d+(?:-\d+)?", code)
    )
    return {
        "kind": "archival_case" if independent_case else "noncase_review",
        "reason": "case_identity_missing" if not independent_case else "case_identity_present",
        "title_present": bool(title),
        "fund_code_present": bool(code),
        "attribute_names": sorted(attrs),
        "object_type": str(data.get("objectTypeName") or ""),
    }


def _detail_card_text(attrs: dict[str, str]) -> str:
    """Preserve all non-empty labelled fields from an RGIA detail card."""
    return "\n".join(f"{name}: {value}" for name, value in attrs.items() if value)


def _detail_url(data: dict, key: str) -> str:
    """Return a public detail URL only when the endpoint supplies a string."""
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def _parse_object_json(data: dict, obj_url: str) -> RgiaRecord:
    """Парсит актуальный JSON, который выдаёт /ajax/obj/{id}/{index}."""
    attrs = {
        str(a.get("name", "")).strip(): str(a.get("text", "")).strip()
        for a in data.get("attributes", [])
        if a.get("name")
    }
    title = (
        data.get("title")
        or attrs.get("Наименование")
        or attrs.get("Название")
        or attrs.get("Заголовок")
        or ""
    ).strip()
    start = attrs.get("Начальный год документов", "")
    end = attrs.get("Конечный год документов", "")
    y_from, _ = _parse_years(start)
    _, y_to = _parse_years(end)
    if y_from is None and y_to is None:
        y_from, y_to = _parse_years(attrs.get("Крайние даты", ""))
    number = attrs.get("Номер фонда", "")
    fund_code = attrs.get("Шифр", "") or (f"Ф. {number}" if number else "")
    return RgiaRecord(
        title=title,
        fund_code=fund_code,
        fund_name=attrs.get("Название фонда", ""),
        sheets=attrs.get("Количество листов", ""),
        date_raw=attrs.get("Крайние даты", "")
        or " ".join(x for x in (start, end) if x),
        subject_group=str(data.get("objectTypeName") or attrs.get("Вид фонда", "")),
        year_from=y_from,
        year_to=y_to,
        bib_source=attrs.get("Библиографический источник", ""),
        notes=attrs.get("Примечание", "") or attrs.get("Аннотация", ""),
        card_text=_detail_card_text(attrs),
        raw_detail=dict(data),
        url_download=_detail_url(data, "downloadLink"),
        url_image=_detail_url(data, "imageUrl"),
        url=obj_url,
    )


def _parse_result_links(html: str, debug: bool = False) -> list[str]:
    """
    Извлекает ссылки на объекты из страницы результатов поиска.
    Возвращает: ['/object/NNN', ...]  (абсолютные URL)
    """
    if debug:
        print("\n─── search results HTML (первые 4000 символов) ───")
        print(html[:4000])
        print("─── конец ───\n")

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()

    # Навигация сайта содержит множество /object/... без title. В выдаче
    # результатов title заполнен описанием объекта, поэтому фильтруем по нему.
    for a in soup.find_all("a", href=re.compile(r"/object/\d+"), title=True):
        href: str = a["href"]
        url = BASE_URL + href if href.startswith("/") else href
        if url not in seen:
            seen.add(url)
            links.append(url)

    return links


def _extract_search_index(html: str) -> str:
    m = re.search(r'data-search-index="(\d+)"', html)
    return m.group(1) if m else ""


def _fetch_object(
    session: requests.Session, obj_url: str, search_index: str, debug: bool = False
) -> RgiaRecord:
    """Получает карточку через JSON endpoint, с HTML fallback."""
    obj_id_m = re.search(r"/object/(\d+)", obj_url)
    if search_index and obj_id_m:
        api_url = f"{BASE_URL}/ajax/obj/{obj_id_m.group(1)}/{search_index}"
        r = session.get(api_url, params={"children": "false"}, timeout=20)
        r.raise_for_status()
        try:
            return _parse_object_json(r.json(), obj_url)
        except ValueError:
            pass
    r = session.get(obj_url, timeout=20)
    r.raise_for_status()
    return _parse_object_page(r.text, obj_url, debug=debug)


def _count_total_pages(html: str) -> int:
    """Извлекает общее число страниц из пагинатора «1 из N»."""
    m = re.search(r"из\s+(\d+)", html)
    return int(m.group(1)) if m else 1


def _rgia_search_terms(query: str) -> str:
    """Use the stemmed territorial terms accepted by the live simple search."""
    territory_stems = {
        "калуж": "калужск",
        "перм": "пермск",
        "смолен": "смоленск",
        "ярослав": "ярославск",
    }
    administrative_words = {"губерния", "губернии", "уезд", "уезда", "область"}
    terms = []
    found_territory = False
    for word in re.findall(r"[А-Яа-яЁёA-Za-z0-9-]+", query.lower()):
        replacement = next(
            (
                stem
                for prefix, stem in territory_stems.items()
                if word.startswith(prefix)
            ),
            None,
        )
        if replacement:
            if replacement not in terms:
                terms.append(replacement)
            found_territory = True
        elif not (found_territory and word in administrative_words):
            terms.append(word)
    return " ".join(terms)


def _tree_params(page: int, node_id: str | int = 0) -> dict[str, str]:
    """Mirror the public jstree request made by nonstatic/scripts/treework.js."""
    return {
        "page": "1",
        "nPage": str(page),
        "size": "",
        "id": str(node_id),
        "parentId": "",
        "objectType": "",
        "orderNumber": "0",
        "showPageList": "true",
        "count": "0",
        "alphabet": "",
        "tabId": "0",
        "completeWorkId": "-1",
    }


def _fetch_tree(session: requests.Session, search_index: str, page: int, node_id=0):
    response = session.get(
        TREE_URL.format(search_index),
        params=_tree_params(page, node_id),
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("RGIA /ajax/tree response is not a JSON list")
    return payload


def _cases_root(nodes: list[dict]) -> str:
    for node in nodes:
        if (
            "дела"
            in BeautifulSoup(str(node.get("text", "")), "lxml")
            .get_text(" ", strip=True)
            .lower()
        ):
            node_id = str(node.get("id", ""))
            if node_id and node_id != "None":
                return node_id
    return ""


def _tree_page_count(nodes: list[dict]) -> int:
    for node in nodes:
        if str(node.get("id", "")) == "None":
            parts = str(node.get("text", "")).split(",")
            if len(parts) >= 5 and parts[4].strip().isdigit():
                return int(parts[4].strip())
    return 1


def _case_node_ids(nodes: list[dict]) -> list[str]:
    return [str(node["id"]) for node in nodes if str(node.get("id", "")).isdigit()]


def _fetch_object_by_id(
    session: requests.Session, object_id: str, search_index: str
) -> RgiaRecord:
    obj_url = f"{BASE_URL}/object/{object_id}"
    response = session.get(
        f"{BASE_URL}/ajax/obj/{object_id}/{search_index}",
        params={"children": "false"},
        timeout=20,
    )
    response.raise_for_status()
    return _parse_object_json(response.json(), obj_url)


def search_simple(
    session: requests.Session,
    query: str,
    year_from: int | None = None,
    year_to: int | None = None,
    debug: bool = False,
) -> Iterator[RgiaRecord]:
    """Search cases through the public jstree JSON route, not /ajax/pages."""
    search_terms = _rgia_search_terms(query)
    if not search_terms:
        return

    try:
        response = session.get(
            SEARCH_URL,
            params={
                "p0.v": search_terms,
                "type": "simple",
                "p0.c": str(TREE_PAGE_SIZE),
                "p0.a": SIMPLE_COMPONENT_ID,
            },
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"[РГИА] Ошибка search: {exc}")
        return

    search_index = _extract_search_index(response.text)
    if not search_index:
        print("[РГИА] data-search-index не найден; список дел не запрашивался")
        return

    seen_ids: set[str] = set()
    max_pages = 1
    page = 1
    while page <= max_pages:
        try:
            time.sleep(3.0)
            roots = _fetch_tree(session, search_index, page)
            root_id = _cases_root(roots)
            if not root_id:
                print(f"[РГИА] Дела не найдены на странице {page}")
                return
            time.sleep(3.0)
            nodes = _fetch_tree(session, search_index, page, root_id)
        except Exception as exc:
            print(f"[РГИА] Ошибка jstree page={page}: {exc}")
            return

        max_pages = max(max_pages, _tree_page_count(nodes))
        object_ids = [
            object_id
            for object_id in _case_node_ids(nodes)
            if object_id not in seen_ids
        ]
        if debug:
            print(
                f"[РГИА] {query!r} -> {search_terms!r}: "
                f"страница {page}/{max_pages}, дел={len(object_ids)}"
            )
        if not object_ids and page == 1:
            return

        for object_id in object_ids:
            seen_ids.add(object_id)
            try:
                time.sleep(3.0)
                record = _fetch_object_by_id(session, object_id, search_index)
            except Exception as exc:
                print(f"[РГИА] Ошибка дела {object_id}: {exc}")
                continue

            if year_from and record.year_to and record.year_to < year_from:
                continue
            if year_to and record.year_from and record.year_from > year_to:
                continue
            yield record
        page += 1


def search_subindex(
    session: requests.Session,
    term: str = "карта",
    territory_filter: str = "",
    year_from: int | None = None,
    year_to: int | None = None,
    debug: bool = False,
) -> Iterator[RgiaRecord]:
    """
    Предметный указатель РГИА (searchObjectType=SUBINDEX).
    Возвращает тематические группы карт и их дела.
    """
    offset = 0

    while True:
        params = {
            "type": "custom",
            "searchObjectType": "SUBINDEX",
            "customSearchUnique": "d",
            "p0.v": term,
            "p0.d": str(offset),
        }
        time.sleep(2.0)
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"[РГИА/предм.] Ошибка offset={offset}: {e}")
            break

        if offset == 0:
            total_pages = _count_total_pages(resp.text)
            print(f"[РГИА/предм.] term={term!r}: {total_pages} стр. в указателе")

        links = _parse_result_links(resp.text, debug=(debug and offset == 0))
        if not links:
            break

        for obj_url in links:
            # Фильтр по территории на уровне URL перед загрузкой — не применяем,
            # чтобы не пропустить нестандартные названия; фильтруем по тексту карточки.
            time.sleep(1.5)
            try:
                r = session.get(obj_url, timeout=20)
                r.raise_for_status()
            except Exception as e:
                print(f"[РГИА/предм.] Ошибка {obj_url}: {e}")
                continue

            rec = _parse_object_page(r.text, obj_url, debug=(debug and offset == 0))

            if territory_filter:
                searchable = (rec.title + rec.subject_group + rec.notes).lower()
                if territory_filter.lower() not in searchable:
                    continue

            if year_from and rec.year_to and rec.year_to < year_from:
                continue
            if year_to and rec.year_from and rec.year_from > year_to:
                continue

            yield rec

        offset += PAGE_SIZE
        if offset >= _count_total_pages(resp.text) * PAGE_SIZE:
            break


def search(
    query: str,
    year_from: int | None = None,
    year_to: int | None = None,
    debug: bool = False,
) -> Iterator[RgiaRecord]:
    """Поиск через общий режим."""
    session = _make_session()
    yield from search_simple(session, query, year_from, year_to, debug)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Поиск карт в РГИА (fgurgia.ru)")
    parser.add_argument(
        "query", nargs="?", default="", help="Поисковый запрос (для --mode simple)"
    )
    parser.add_argument(
        "--mode",
        choices=["simple", "subindex"],
        default="simple",
        help="simple = общий поиск; subindex = предметный указатель",
    )
    parser.add_argument(
        "--term",
        default="карта",
        help="Термин для предметного указателя (по умолчанию: карта)",
    )
    parser.add_argument(
        "--territory", default="", help="Фильтр по территории для режима subindex"
    )
    parser.add_argument("--year-from", type=int, default=1500, dest="year_from")
    parser.add_argument("--year-to", type=int, default=1920, dest="year_to")
    parser.add_argument("--all-queries", action="store_true", dest="all_queries")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--csv", default="", help="Записать структурированный результат в CSV"
    )
    args = parser.parse_args()

    session = _make_session()

    if args.mode == "subindex" or not args.query:
        results = list(
            search_subindex(
                session,
                args.term,
                args.territory,
                args.year_from,
                args.year_to,
                args.debug,
            )
        )
    elif args.all_queries:
        seen: set[str] = set()
        results = []
        for ter in TERRITORIES:
            for kw in ("карта", "план", "атлас"):
                q = f"{kw} {ter}"
                for rec in search_simple(session, q, args.year_from, args.year_to):
                    if rec.url not in seen:
                        seen.add(rec.url)
                        results.append(rec)
    else:
        results = list(
            search_simple(session, args.query, args.year_from, args.year_to, args.debug)
        )

    if args.csv:
        fields = [
            "title",
            "fund_code",
            "fund_name",
            "sheets",
            "date_raw",
            "subject_group",
            "year_from",
            "year_to",
            "bib_source",
            "notes",
            "url",
            "library_id",
            "library_name",
        ]
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for rec in results:
                writer.writerow({name: getattr(rec, name) for name in fields})
        print(f"[РГИА] CSV: {args.csv}")

    print(f"\n[РГИА] Итого: {len(results)}")
    for r in results:
        yr = f"{r.year_from or '?'}–{r.year_to or '?'}"
        print(f"  {yr:<12} [{r.fund_code[:20]}] {r.title[:55]}")
        print(f"             {r.url}")
        if r.bib_source:
            print(f"             Источник: {r.bib_source[:70]}")


if __name__ == "__main__":
    main()
