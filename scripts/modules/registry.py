"""
Единый реестр источников — движок парсинга архивов.

Задача: run_search.py (и любой другой оркестратор) работает с ЛЮБЫМ источником
через один интерфейс, не зная деталей конкретного скрапера:

    import registry
    for rec in registry.search("kaluga_lib", "карта Калужская губерния",
                               year_from=1700, year_to=1980, max_pages=5):
        ...  # rec — всегда LibraryRecord

Реестр объединяет два поколения кода:
  1. Легаси-функции из searcher_libraries.py (gpib, prlib, nlr_cart, ...)
  2. Автономные скраперы из modules/scrapers/ (kaluga IRBIS64, НЭБ, РГБ, ...)
     — у каждого своя сигнатура search() и свой Record; адаптеры приводят
     их к LibraryRecord.

Новые скраперы ПЕРЕКРЫВАЮТ одноимённые легаси-источники (kaluga_lib,
smolensk_lib, permkrai) — легаси-версии были написаны «вслепую» по общему
шаблону регионального сайта, новые — по фактической структуре каталогов.

Режимы источника (mode):
  query — обычный поиск по строке запроса (перебор территория × слово)
  walk  — обход коллекции целиком, запрос игнорируется (запускать ОДИН раз
          за прогон, не перебирать комбинации)

Добавление нового источника = один SourceSpec в SOURCES + адаптер-функция.
Новый отдельный скрипт писать НЕ нужно, если сайт укладывается в query/walk.
"""
from dataclasses import dataclass
from typing import Callable, Iterator

import searcher_libraries
from searcher_libraries import LibraryRecord


@dataclass(frozen=True)
class SourceSpec:
    id: str
    name: str
    mode: str                                   # "query" | "walk"
    searcher: Callable[..., Iterator[LibraryRecord]]
    note: str = ""                              # ограничения (геоблок и т.п.)


# ── адаптеры легаси-источников (searcher_libraries.py) ───────────────────────

def _legacy(lib_id: str) -> Callable[..., Iterator[LibraryRecord]]:
    def _fn(query: str, year_from: int | None, year_to: int | None,
            max_pages: int) -> Iterator[LibraryRecord]:
        fn = searcher_libraries._SEARCHERS[lib_id]
        yield from fn(query, year_from, year_to, max_pages)
    return _fn


# ── адаптеры новых скраперов (modules/scrapers/) ─────────────────────────────

def _from_kaluga(query: str, year_from: int | None, year_to: int | None,
                 max_pages: int) -> Iterator[LibraryRecord]:
    from scrapers import searcher_kaluga as m
    for r in m.search(query, year_from=year_from, year_to=year_to):
        desc = "; ".join(p for p in (
            f"Рубрики: {r.rubrics}" if r.rubrics else "",
            f"ББК {r.bbk}" if r.bbk else "",
            r.annotation,
        ) if p)
        yield LibraryRecord(
            title=r.title, author=r.author,
            year_from=r.year_from, year_to=r.year_to,
            description=desc, url=r.url,
            library_id="kaluga_lib", library_name=r.library_name,
            extra={"db": r.db},
        )


def _from_permkrai(query: str, year_from: int | None, year_to: int | None,
                   max_pages: int) -> Iterator[LibraryRecord]:
    from scrapers import searcher_permkrai as m
    for r in m.search(query, year_from=year_from, year_to=year_to):
        yield LibraryRecord(
            title=r.title,
            year_from=r.year_from, year_to=r.year_to,
            description=r.description, url=r.url,
            library_id="permkrai", library_name=r.library_name,
            extra={"url_source": r.url_source, "owner": r.owner,
                   "open_access": r.open_access, "tags": r.tags},
        )


def _from_smolensk(query: str, year_from: int | None, year_to: int | None,
                   max_pages: int) -> Iterator[LibraryRecord]:
    # Обход коллекции (311 док., 32 стр.) — query игнорируется,
    # max_pages фиксирован размером коллекции, а не пагинацией поиска
    from scrapers import searcher_smolensk as m
    for r in m.search(year_from=year_from, year_to=year_to, max_pages=32):
        desc = "; ".join(p for p in (r.subject, r.publication) if p)
        yield LibraryRecord(
            title=r.title, author=r.author,
            year_from=r.year_from, year_to=r.year_to,
            description=desc, url=r.url,
            library_id="smolensk_lib", library_name=r.library_name,
            extra={"pdf_url": r.pdf_url, "organization": r.organization},
        )


def _from_neb(query: str, year_from: int | None, year_to: int | None,
              max_pages: int) -> Iterator[LibraryRecord]:
    from scrapers import searcher_neb as m
    for r in m.search(query, year_from=year_from, year_to=year_to):
        desc = "; ".join(p for p in (
            r.description,
            f"Фондодержатель: {r.source_lib}" if r.source_lib else "",
            f"Доступ: {r.access}" if r.access else "",
        ) if p)
        yield LibraryRecord(
            title=r.title, author=r.author,
            year_from=r.year_from, year_to=r.year_to,
            place=r.place, description=desc, url=r.url,
            library_id="neb", library_name=r.library_name,
            extra={"url_viewer": r.url_viewer, "publisher": r.publisher,
                   "collections": r.collections, "access": r.access,
                   "source_lib": r.source_lib},
        )


def _from_rsl(query: str, year_from: int | None, year_to: int | None,
              max_pages: int) -> Iterator[LibraryRecord]:
    from scrapers import searcher_rsl as m
    for r in m.search(query, year_from=year_from, year_to=year_to):
        desc = "; ".join(p for p in (r.subject, r.notes, r.content_note) if p)
        yield LibraryRecord(
            title=r.title, author=r.author,
            year_from=r.year_from, year_to=r.year_to,
            description=desc, url=r.url,
            library_id="rsl", library_name=r.library_name,
            extra={"shelfmark": r.shelfmark, "access": r.access},
        )


# ── реестр ────────────────────────────────────────────────────────────────────
# Геопорталы-просмотрщики (etomesto, retromap, southklad, qmap, runivers)
# не регистрируются — см. .claude/rules/search-sources.md

SOURCES: dict[str, SourceSpec] = {s.id: s for s in (
    # новые скраперы (перекрывают легаси-версии с теми же id)
    SourceSpec("kaluga_lib",   "Калужская ОНБИБ им. Белинского (IRBIS64)",
               "query", _from_kaluga,
               note="IP 217.15.203.140:81; задержка ≥2 c"),
    SourceSpec("permkrai",     "Пермская краевая библиотека (ELiS)",
               "query", _from_permkrai,
               note="геоблок с нероссийских IP"),
    SourceSpec("smolensk_lib", "Смоленская ОУНБ (elib, обход коллекции)",
               "walk", _from_smolensk,
               note="311 документов, 32 страницы; поиска нет"),
    SourceSpec("neb",          "Национальная электронная библиотека",
               "query", _from_neb,
               note="агрегатор — возможны дубли с РГБ/ГПИБ"),
    SourceSpec("rsl",          "Российская государственная библиотека",
               "query", _from_rsl,
               note="POST API; фильтр шифра KGR"),
    # легаси из searcher_libraries.py
    SourceSpec("gpib",         "ГПИБ России (elib.shpl.ru)",
               "query", _legacy("gpib")),
    SourceSpec("prlib",        "Президентская библиотека",
               "query", _legacy("prlib"),
               note="rate-limit: перезапускать при блокировке"),
    SourceSpec("nlr_cart",     "РНБ, каталог карт",
               "query", _legacy("nlr_cart")),
    SourceSpec("yaroslavl_lib", "Ярославская ОУНБ / Ярославика",
               "query", _legacy("yaroslavl_lib"),
               note="rlib.yar.ru/search не работает (2026-07)"),
    SourceSpec("rgo",          "Геопортал РГО",
               "query", _legacy("rgo"),
               note="отключён: нет текстового поиска"),
    SourceSpec("aonb",         "Архангельская ОНБ «Русский Север»",
               "query", _legacy("aonb"),
               note="не проверен"),
)}


# ── публичный интерфейс движка ────────────────────────────────────────────────

def available() -> list[str]:
    return list(SOURCES)


def is_walk(source_id: str) -> bool:
    return SOURCES[source_id].mode == "walk"


def search(source_id: str, query: str = "",
           year_from: int | None = None, year_to: int | None = None,
           max_pages: int = 5) -> Iterator[LibraryRecord]:
    """
    Единая точка входа. Исключения скраперов пробрасываются наверх —
    оркестратор различает сетевую ошибку и пустой результат.
    """
    if source_id not in SOURCES:
        raise KeyError(
            f"Неизвестный источник {source_id!r}. Доступны: {', '.join(SOURCES)}")
    yield from SOURCES[source_id].searcher(query, year_from, year_to, max_pages)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"{'id':<15} {'режим':<6} название")
    print("─" * 78)
    for s in SOURCES.values():
        line = f"{s.id:<15} {s.mode:<6} {s.name}"
        if s.note:
            line += f"  [{s.note}]"
        print(line)
