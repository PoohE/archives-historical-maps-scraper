"""
Оркестратор полного поиска по 4 губерниям гранта ИГИС.

Запуск:
  python run_search.py --dry-run          # только показать, не писать в Notion
  python run_search.py                    # полный поиск → Notion
  python run_search.py --source rgo,gpib  # только конкретные источники
  python run_search.py --resume           # продолжить с последней контрольной точки

Результаты: output/search_YYYYMMDD_HHMMSS.csv
Контрольная точка: output/search_checkpoint.json
"""
import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "modules"))
sys.stdout.reconfigure(encoding="utf-8")

from territories import GUBERNIA_QUERIES, UYEZD_QUERIES
from triggers import PRIMARY

# ── Параметры поиска (согласованы с пользователем) ───────────────────────────
YEAR_FROM = 1700
YEAR_TO   = 1980

# Основные ключевые слова — достаточно широко, _is_cart() отфильтрует дальше
KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж", "топографическая"]

# Только настоящие архивы и библиотеки с оригинальными документами
# (ресурсы без ссылок на первоисточник — в отдельной таблице «Геопорталы»)
SOURCE_PRIORITY = [
    "gpib",         # ГПИБ России — электронная библиотека (elib.shpl.ru)
    "prlib",        # Президентская библиотека
    "nlr_cart",     # РНБ, отдел карт
    "permkrai",     # Пермская краевая библиотека
    "kaluga_lib",   # Калужская библиотека им. Белинского
    "smolensk_lib", # Смоленская ОУНБ им. Твардовского
    "yaroslavl_lib",# Ярославская ОУНБ / Ярославика
]

# Временно отключены (searcher требует переработки):
# "rgo"    — нет текстового поиска, нужен обход каталога
# "aonb"   — не проверен

# Перенесены в таблицу «Геопорталы» — просмотрщики без ссылки на архив:
# "runivers"   — портал-просмотрщик
# "retromap"   — портал-просмотрщик
# "southklad"  — портал-просмотрщик
# "qmap"       — портал-просмотрщик
# "etomesto"   — геопортал, не архив

# ── Генерация списка территорий ───────────────────────────────────────────────
def build_territories() -> list[tuple[str, str]]:
    """
    Возвращает [(query_territory, label), ...] для всех 4 губерний и уездов.
    query_territory — строка для передачи в searcher (напр. 'Калужская губерния')
    label — для логов
    """
    result: list[tuple[str, str]] = []
    for gub_key in ("калужская", "пермская", "смоленская", "ярославская"):
        # Губерния + историческое название (наместничество)
        for gub_name in GUBERNIA_QUERIES[gub_key]:
            result.append((gub_name, gub_key.title()))
        # Уезды
        for uyezd in UYEZD_QUERIES[gub_key]:
            result.append((uyezd, gub_key.title()))
    return result


# ── Контрольная точка ─────────────────────────────────────────────────────────
_CHECKPOINT_PATH: Path | None = None  # устанавливается в main() после создания run_dir

def load_checkpoint(run_dir: Path) -> set[str]:
    """Возвращает множество уже выполненных комбинаций из чекпоинта в run_dir."""
    cp = run_dir / "checkpoint.json"
    if cp.exists():
        with open(cp, encoding="utf-8") as f:
            return set(json.load(f).get("done", []))
    return set()

def save_checkpoint(done: set[str], run_dir: Path) -> None:
    cp = run_dir / "checkpoint.json"
    with open(cp, "w", encoding="utf-8") as f:
        json.dump({"done": list(done), "updated": datetime.now().isoformat()}, f,
                  ensure_ascii=False, indent=2)


# ── Основной поиск ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Поиск по 4 губерниям ИГИС")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать результаты, не писать в Notion")
    parser.add_argument("--source", default="all",
                        help=f"Источники через запятую: {', '.join(SOURCE_PRIORITY)} или all")
    parser.add_argument("--resume", action="store_true",
                        help="Продолжить с контрольной точки")
    parser.add_argument("--max-pages", type=int, default=5, dest="max_pages",
                        help="Макс. страниц поиска на источник (по умолч. 5)")
    parser.add_argument("--max-combos", type=int, default=0, dest="max_combos",
                        help="Остановиться после N комбинаций (0 = без лимита, для GitHub Actions)")
    parser.add_argument("--run-dir", default="", dest="run_dir_override",
                        help="Фиксированная папка запуска (для облака: output/cloud)")
    args = parser.parse_args()

    # Импортируем searcher и health-монитор после добавления modules/ в путь
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "searcher_libraries",
        Path(__file__).parent / "modules" / "searcher_libraries.py"
    )
    searcher_lib = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(searcher_lib)

    from archive_health import ArchiveHealth
    health = ArchiveHealth()

    # Список источников
    if args.source == "all":
        sources = SOURCE_PRIORITY
    else:
        sources = [s.strip() for s in args.source.split(",")]

    # Территории и ключевые слова
    territories = build_territories()
    total_combos = len(territories) * len(KEYWORDS) * len(sources)

    # Папка запуска: --run-dir (фиксированная, для облака) → --resume → новая
    base_out = Path(__file__).parent / "output"
    base_out.mkdir(exist_ok=True)
    if args.run_dir_override:
        run_dir = base_out / args.run_dir_override
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"[Облако] Фиксированная папка: output/{args.run_dir_override}/")
    elif args.resume:
        existing_runs = sorted(base_out.glob("20*"))  # папки YYYYMMDD_HHMMSS
        if existing_runs:
            run_dir = existing_runs[-1]
            print(f"[Резюме] Продолжаем запуск: {run_dir.name}")
        else:
            print("[Резюме] Предыдущих запусков нет — начинаем новый")
            run_dir = base_out / datetime.now().strftime("%Y%m%d_%H%M%S")
            run_dir.mkdir(exist_ok=True)
    else:
        run_dir = base_out / datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir.mkdir(exist_ok=True)

    # Контрольная точка (грузим при --resume или фиксированной папке облака)
    done = load_checkpoint(run_dir) if (args.resume or args.run_dir_override) else set()
    if done:
        print(f"[Резюме] Уже выполнено: {len(done)} комбинаций")
        # Показать прогресс по источникам
        combos_per_source = len(territories) * len(KEYWORDS)
        for src in sources:
            src_done = sum(1 for k in done if k.endswith(f"|{src}"))
            pct = int(src_done / combos_per_source * 100)
            status = "✓ завершён" if src_done == combos_per_source else f"{src_done}/{combos_per_source} ({pct}%)"
            print(f"  {src:<15} {status}")
        print()
    out_file    = run_dir / "results.csv"       # уверенные источники
    review_file = run_dir / "review.csv"        # сомнительные → для review.py

    print(f"\n{'='*60}")
    print(f"ПОИСК ИГИС: 4 губернии, {YEAR_FROM}–{YEAR_TO}")
    print(f"Территорий: {len(territories)}  |  Ключевых слов: {len(KEYWORDS)}")
    print(f"Источников: {len(sources)}  |  Всего комбинаций: {total_combos}")
    print(f"Режим: {'DRY-RUN (без записи в Notion)' if args.dry_run else 'ПОЛНЫЙ (запись в Notion)'}")
    print(f"Папка:     output/{run_dir.name}/")
    print(f"{'='*60}\n")

    total_found = 0
    combo_n = 0
    new_combos_done = 0     # комбинации выполненные в ЭТОМ запуске (для --max-combos)
    max_combos_reached = False

    from triggers import classify

    # Дописываем к существующим файлам, если продолжаем (иначе теряем прошлые результаты)
    files_exist = out_file.exists() and done
    file_mode = "a" if files_exist else "w"

    with (open(out_file, file_mode, newline="", encoding="utf-8-sig") as csvf,
          open(review_file, file_mode, newline="", encoding="utf-8-sig") as rvf):

        writer  = csv.writer(csvf)
        rv_writer = csv.writer(rvf)
        COLS = ["Источник", "Территория", "Ключевое слово",
                "Название", "Год от", "Год до", "URL", "Описание"]
        # Заголовок пишем только для нового файла
        if file_mode == "w":
            writer.writerow(COLS)
            rv_writer.writerow(COLS + ["Решение", "Комментарий"])  # заполнит review.py

        MAX_EMPTY = 3  # после стольких пустых ответов подряд — пропускаем источник

        for source_id in sources:
            if max_combos_reached:
                break
            print(f"\n{'─'*50}")
            print(f"Источник: {source_id.upper()}")
            print(f"{'─'*50}")

            consecutive_empty = 0
            skip_source = False

            for territory, gub_label in territories:
                if skip_source or max_combos_reached:
                    break
                for keyword in KEYWORDS:
                    combo_key = f"{territory}|{keyword}|{source_id}"
                    combo_n += 1

                    if combo_key in done:
                        continue

                    query = f"{keyword} {territory}"
                    print(f"[{combo_n}/{total_combos}] {source_id} | {query[:60]}", end=" ... ")

                    if args.dry_run:
                        print("(dry-run, пропуск)")
                        done.add(combo_key)
                        continue

                    try:
                        pos = doubtful = 0
                        for rec in searcher_lib.search(
                            query,
                            year_from=YEAR_FROM,
                            year_to=YEAR_TO,
                            libraries=source_id,
                            max_pages=args.max_pages,
                        ):
                            row = [
                                source_id, territory, keyword,
                                rec.title, rec.year_from, rec.year_to,
                                rec.url, (rec.description or "")[:200],
                            ]
                            verdict = classify(rec.title)
                            if verdict == "positive":
                                writer.writerow(row)
                                csvf.flush()
                                pos += 1
                            else:  # doubtful (negative уже отфильтрован в searcher)
                                rv_writer.writerow(row + ["", ""])
                                rvf.flush()
                                doubtful += 1
                            total_found += 1

                        if pos + doubtful > 0:
                            health.ok(source_id)
                            consecutive_empty = 0
                        else:
                            consecutive_empty += 1
                            if consecutive_empty >= MAX_EMPTY:
                                print(f"\n[{source_id}] {MAX_EMPTY} пустых ответа подряд — пропускаем источник")
                                health.issue(source_id,
                                    f"0 результатов на первых {MAX_EMPTY} запросах — источник не отвечает на ключевые слова")
                                skip_source = True
                                done.add(combo_key)
                                save_checkpoint(done, run_dir)
                                break
                        print(f"{pos} уверенных, {doubtful} сомнительных")
                    except Exception as e:
                        err_msg = str(e)
                        health.issue(source_id, f"Запрос: {query!r} → {err_msg}")
                        print(f"ОШИБКА: {err_msg}")

                    done.add(combo_key)
                    save_checkpoint(done, run_dir)
                    new_combos_done += 1
                    if args.max_combos > 0 and new_combos_done >= args.max_combos:
                        print(f"\n[GitHub Actions] Лимит {args.max_combos} комбинаций достигнут — останавливаемся")
                        max_combos_reached = True
                        break
                    time.sleep(0.5)  # небольшая пауза между комбинациями

    # Сохраняем статусы доступности источников в Notion
    if not args.dry_run:
        health.save()

    print(f"\n{'='*60}")
    print(f"ИТОГО: найдено {total_found} записей")
    print(f"Папка: {run_dir}")
    if args.dry_run:
        print("Режим DRY-RUN — в Notion не записано")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
