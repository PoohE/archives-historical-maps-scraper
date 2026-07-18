"""
catalog_search.py — поиск историко-географических источников и запись в Notion.

Режим A (онлайн-каталоги):
  python catalog_search.py --query "межевые планы" --year_from 1765 --year_to 1842 \
      --archive РГАДА --territory "Тульская губерния" --type A1

Режим B (PDF/текст):
  python catalog_search.py --pdf путь/к/файлу.pdf --territory "Тульская губерния"

Флаги:
  --dry-run   только показать найденное, не записывать в Notion
  --max-pages число страниц поиска (по умолч. 3)
  --source    neb|ebid|archives|all (по умолч. all)
"""
import argparse
import importlib.util
import logging
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# Общие модули (field_mapper, pdf_extractor, notion_writer) лежат в соседней папке
_shared = Path(__file__).parent.parent / "Каталогизация"
sys.path.insert(0, str(_shared))

# .env хранится там же
load_dotenv(_shared / ".env")

# Searcher-модули — в локальной папке modules/ этой папки
def _load_searcher(name: str):
    path = Path(__file__).parent / "modules" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

searcher_neb       = _load_searcher("searcher_neb")
searcher_ebid      = _load_searcher("searcher_ebid")
searcher_archives  = _load_searcher("searcher_archives")
searcher_libraries = _load_searcher("searcher_libraries")

from modules import field_mapper, pdf_extractor
from modules.notion_writer import NotionWriter

# --- Логирование ---
log_dir = Path(__file__).parent / "output"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"catalog_{date.today()}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def _check_env() -> bool:
    """Проверяет наличие обязательных переменных окружения."""
    required = ["NOTION_TOKEN", "NOTION_DB_SOURCES", "NOTION_DB_ARCHIVES",
                "NOTION_DB_TYPES", "NOTION_DB_SERIES"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        log.error(f"Отсутствуют переменные в .env: {', '.join(missing)}")
        return False
    return True


def _write_record(writer: NotionWriter, rec: field_mapper.SourceRecord,
                  dry_run: bool) -> bool:
    """Записывает одну запись. Возвращает True если добавлена."""
    if dry_run:
        log.info(f"[DRY-RUN] {rec.title[:80]} | {rec.archive_name} | {rec.year_from}-{rec.year_to}")
        return True
    try:
        page_id = writer.write(rec)
        if page_id is None:
            log.info(f"Дубликат, пропущен: {rec.title[:60]}")
            return False
        log.info(f"Добавлен: {rec.title[:60]} → {page_id}")
        return True
    except Exception as e:
        log.error(f"Ошибка записи в Notion: {e} | {rec.title[:60]}")
        return False


def run_online(args, writer: NotionWriter) -> tuple[int, int]:
    """Режим A: поиск в онлайн-каталогах. Возвращает (найдено, добавлено)."""
    found = 0
    added = 0
    sources = args.source.lower().split(",")

    # НЭБ
    if "neb" in sources or "all" in sources:
        log.info("=== Поиск в НЭБ (rusneb.ru) ===")
        for raw in searcher_neb.search(
                args.query,
                year_from=args.year_from,
                year_to=args.year_to,
                max_pages=args.max_pages):
            rec = field_mapper.from_neb(raw)
            if args.territory:
                rec.territory = args.territory
            if args.type:
                rec.source_type_code = args.type
            found += 1
            if _write_record(writer, rec, args.dry_run):
                added += 1

    # ЭБИД
    if "ebid" in sources or "all" in sources:
        log.info("=== Поиск в ЭБИД (docs.historyrussia.org) ===")
        for raw in searcher_ebid.search(
                args.query,
                year_from=args.year_from,
                year_to=args.year_to,
                territory=args.territory or "",
                max_pages=args.max_pages):
            rec = field_mapper.from_ebid(raw)
            if args.type:
                rec.source_type_code = args.type
            found += 1
            if _write_record(writer, rec, args.dry_run):
                added += 1

    # Росархив-онлайн
    if "archives" in sources or "all" in sources:
        log.info("=== Поиск в Росархив-онлайн (online.archives.ru) ===")
        for raw in searcher_archives.search(
                args.query,
                year_from=args.year_from,
                year_to=args.year_to,
                archive=args.archive or "",
                territory=args.territory or "",
                max_pages=args.max_pages):
            rec = field_mapper.from_archives(raw)
            if args.type:
                rec.source_type_code = args.type
            found += 1
            if _write_record(writer, rec, args.dry_run):
                added += 1

    # Онлайн-коллекции библиотек
    if "libraries" in sources or "all" in sources:
        libs = getattr(args, "libraries", "all")
        log.info(f"=== Поиск в онлайн-коллекциях библиотек [{libs}] ===")
        for raw in searcher_libraries.search(
                args.query,
                year_from=args.year_from,
                year_to=args.year_to,
                libraries=libs,
                max_pages=args.max_pages):
            rec = field_mapper.from_library(raw)
            if args.territory:
                rec.territory = args.territory
            if args.type:
                rec.source_type_code = args.type
            found += 1
            if _write_record(writer, rec, args.dry_run):
                added += 1

    return found, added


def run_pdf(args, writer: NotionWriter) -> tuple[int, int]:
    """Режим B: извлечение из PDF/текстового файла."""
    log.info(f"=== Извлечение из файла: {args.pdf} ===")
    try:
        records = pdf_extractor.extract(args.pdf, territory=args.territory or "")
    except FileNotFoundError as e:
        log.error(str(e))
        return 0, 0
    except Exception as e:
        log.error(f"Ошибка обработки файла: {e}")
        return 0, 0

    found = len(records)
    added = 0
    for rec in records:
        if args.type:
            rec.source_type_code = args.type
        if _write_record(writer, rec, args.dry_run):
            added += 1
    return found, added


def main():
    parser = argparse.ArgumentParser(
        description="Поиск историко-географических источников → Notion")

    # Режим A: онлайн-поиск
    parser.add_argument("--query", help="Поисковый запрос (ключевые слова)")
    parser.add_argument("--year_from", type=int, help="Год создания (нижняя граница)")
    parser.add_argument("--year_to", type=int, help="Год создания (верхняя граница)")
    parser.add_argument("--archive", help="Фильтр по архиву (напр. РГАДА)")
    parser.add_argument("--territory", help="Территория охвата (напр. 'Тульская губерния')")
    parser.add_argument("--type", help="Код типа источника A1–C5 (переопределяет авто-определение)")
    parser.add_argument("--source", default="all",
                        help="Источники поиска: neb, ebid, archives, libraries или all (по умолч. all)")
    parser.add_argument("--libraries", default="all",
                        help=(f"Конкретные библиотеки (используется если --source включает libraries): "
                              f"{', '.join(searcher_libraries.LIBRARY_IDS)} или all (по умолч. all)"))
    parser.add_argument("--max-pages", type=int, default=3,
                        dest="max_pages", help="Макс. страниц поиска (по умолч. 3)")

    # Режим B: PDF
    parser.add_argument("--pdf", help="Путь к PDF или текстовому файлу (Режим B)")

    # Общее
    parser.add_argument("--dry-run", action="store_true",
                        help="Показать результаты без записи в Notion")

    args = parser.parse_args()

    if not args.query and not args.pdf:
        parser.error("Укажите --query (режим A) или --pdf (режим B)")

    if not _check_env():
        sys.exit(1)

    writer = NotionWriter()

    if args.pdf:
        found, added = run_pdf(args, writer)
    else:
        found, added = run_online(args, writer)

    mode = "DRY-RUN" if args.dry_run else "записано"
    log.info(f"Итого: найдено {found}, {mode} {added}")
    log.info(f"Лог: {log_file}")


if __name__ == "__main__":
    main()
