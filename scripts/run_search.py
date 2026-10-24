"""
Оркестратор полного поиска по 4 губерниям гранта ИГИС.

Запуск:
  python scripts/run_search.py --dry-run          # только показать, не писать в Notion
  python scripts/run_search.py                    # полный поиск → Notion
  python scripts/run_search.py --source rgo,gpib  # только конкретные источники
  python scripts/run_search.py --resume           # продолжить с последней контрольной точки

Результаты: output/search_YYYYMMDD_HHMMSS.csv
Контрольная точка: output/search_checkpoint.json
"""
import argparse
from collections import Counter
import csv
import json
import os
import sys
import time
import signal
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "modules"))
sys.stdout.reconfigure(encoding="utf-8")
# This legacy flag limits GPIB secondary edition fetches. PRLIB detail extraction
# is mandatory and is configured independently in searcher_libraries.
os.environ.setdefault("IGIS_BULK_MODE", "0")

from territories import GUBERNIA_QUERIES, UYEZD_QUERIES
from triggers import PRIMARY
from prlib_run_state import atomic_json, existing_outputs, identity, iter_query, query_path, completed_query
import registry  # единый движок источников (modules/registry.py)
from notion_export import export as export_notion_candidates
import scope_gate

# ── Параметры поиска (согласованы с пользователем) ───────────────────────────
YEAR_FROM = None
YEAR_TO = None
SCOPE_RULES = Path(__file__).resolve().parents[1] / "ПРАВИЛА_ОТБОРА_источников.md"
SCOPE_RULES_SHA256 = "a44615d5f9b42f129b81ac29e42b7d3719d416626e5d640de81cd3c141f4aa9e"

# Основные ключевые слова — достаточно широко, _is_cart() отфильтрует дальше
KEYWORDS = ["карта", "план", "атлас", "съёмка", "чертёж", "топографическая"]

# Только настоящие архивы и библиотеки с оригинальными документами
# (ресурсы без ссылок на первоисточник — в отдельной таблице «Геопорталы»)
SOURCE_PRIORITY = [
    "gpib",         # ✅ ГПИБ России — электронная библиотека (elib.shpl.ru)
    "prlib",        # ✅ Президентская библиотека
    "nlr_cart",     # ✅ РНБ, отдел карт (картографический каталог)
    "neb",          # ✅ НЭБ — агрегатор (дубли с РГБ/ГПИБ → dedup)
    "rsl",          # ✅ РГБ — search.rsl.ru (POST API, фильтр KGR)
    "permkrai",     # ⚠️ Пермская краевая библиотека (ELiS, AJAX)
    "kaluga_lib",   # ⚠️ Калужская библиотека им. Белинского (IRBIS64)
    "smolensk_lib", # ⚠️ Смоленская ОУНБ (walk-источник, обход коллекции)
]

# Недоступные источники (не включаются в поиск):
# "yaroslavl_lib" — rlib.yar.ru/search не работает (2026-07), каталог недоступен
# "rgo"           — геопортал РГО, нет текстового поиска, требуется обход каталога
# "aonb"          — Архангельская ОНБ, не проверена

# Примечание:
# - Источники переупорядочены по готовности (✅ готовые → ⚠️ частичные)
# - Запускать ✅ готовые в первую очередь
# - ⚠️ частичные требуют отладки DevTools анализом

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
    atomic_json(cp, {"done": sorted(done), "updated": datetime.now().isoformat()})


# ── Основной поиск ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Поиск по 4 губерниям ИГИС")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать результаты, не писать в Notion")
    parser.add_argument("--no-notion", action="store_true",
                        help="Выполнить поиск и сохранить в CSV, но НЕ писать в Notion")
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
    if not args.no_notion and not args.dry_run:
        parser.error('Сбор отделён от публикации: используйте --no-notion. Импорт требует ручной приёмки.')

    # Самодиагностика: проверяем что результаты не уйдут в gitignored-папку
    if args.run_dir_override and args.run_dir_override.startswith("20"):
        print(f"[ОШИБКА] --run-dir '{args.run_dir_override}' начинается с '20' — "
              f"такие папки попадают в .gitignore. Используй 'cloud' или другое имя.")
        sys.exit(1)
    if not args.run_dir_override and not args.resume and not args.dry_run:
        print("[ПРЕДУПРЕЖДЕНИЕ] Без --run-dir и --resume результаты пойдут в папку с датой "
              "(gitignored). Для облака добавь --run-dir cloud.")

    if args.dry_run:
        class DryRunHealth:
            def ok(self, library_id: str) -> None:
                pass

            def issue(self, library_id: str, problem: str) -> None:
                pass

            def save(self) -> None:
                pass

        health = DryRunHealth()
    else:
        from archive_health import ArchiveHealth
        health = ArchiveHealth()

    # Список источников — все проходят через реестр движка
    if args.source == "all":
        sources = SOURCE_PRIORITY
    else:
        sources = [s.strip() for s in args.source.split(",")]
    unknown = [s for s in sources if s not in registry.SOURCES]
    if unknown:
        print(f"[ОШИБКА] Неизвестные источники: {', '.join(unknown)}")
        print(f"Доступны: {', '.join(registry.available())}")
        sys.exit(1)

    # Территории и ключевые слова
    # walk-источники (обход коллекции) — 1 комбинация вместо территория×слово
    territories = build_territories()
    combos_per_query_source = len(territories) * len(KEYWORDS)
    total_combos = sum(1 if registry.is_walk(s) else combos_per_query_source
                       for s in sources)

    # Папка запуска: --run-dir (фиксированная, для облака) → --resume → новая
    base_out = Path(__file__).resolve().parent.parent / "output"
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
        for src in sources:
            src_total = 1 if registry.is_walk(src) else combos_per_query_source
            src_done = sum(1 for k in done if k.endswith(f"|{src}"))
            pct = int(src_done / src_total * 100)
            status = "✓ завершён" if src_done >= src_total else f"{src_done}/{src_total} ({pct}%)"
            print(f"  {src:<15} {status}")
        print()
    out_file    = run_dir / "search_audit.csv"  # техническая выдача, не импорт
    review_file = run_dir / "review.csv"        # сомнительные → для review.py
    if (run_dir / 'results.csv').exists():
        raise ValueError('Старый формат запуска: выберите новый --run-dir; исходные CSV не мигрируются автоматически')

    print(f"\n{'='*60}")
    print("ПОИСК ИГИС: 4 губернии, без автоматической отсечки по году")
    print(f"Территорий: {len(territories)}  |  Ключевых слов: {len(KEYWORDS)}")
    print(f"Источников: {len(sources)}  |  Всего комбинаций: {total_combos}")
    mode = (
        "DRY-RUN (без записи в Notion)" if args.dry_run
        else "ПОИСК + CSV (без записи в Notion)" if args.no_notion
        else "ПОЛНЫЙ (запись в Notion)"
    )
    print(f"Режим: {mode}")
    print(f"Папка:     output/{run_dir.name}/")
    print(f"{'='*60}\n")

    total_found = 0
    combo_n = 0
    new_combos_done = 0     # комбинации выполненные в ЭТОМ запуске (для --max-combos)
    max_combos_reached = False

    from triggers import classify
    selection = scope_gate.load_policy(SCOPE_RULES, expected_sha256=SCOPE_RULES_SHA256)

    # Дописываем к существующим файлам, если продолжаем (иначе теряем прошлые результаты)
    if "prlib" in sources:
        files_exist, persisted_keys = existing_outputs(run_dir)
        # Historical done flags without final per-query coverage are unverified.
        done = {key for key in done if not key.endswith("|prlib") or (
            completed_query(run_dir,key,YEAR_FROM,YEAR_TO))}
    else:
        files_exist = out_file.exists() and done
        persisted_keys = set()
    file_mode = "a" if files_exist else "w"
    if files_exist and (run_dir / "records_full.jsonl").exists():
        for previous in (run_dir / "records_full.jsonl").read_text(encoding="utf-8").splitlines():
            if previous.strip() and not (json.loads(previous).get("record", {}).get("extra") or {}).get("scope_verdict"):
                raise ValueError("Legacy records lack scope verdict; use a new run directory")
    drop_path = run_dir / "scope_drops.jsonl"
    if files_exist and drop_path.exists():
        for prior_drop in drop_path.read_text(encoding="utf-8").splitlines():
            if prior_drop.strip() and "prlib" in sources:
                persisted_keys.add(tuple(json.loads(prior_drop)["record_key"]))

    # Full records preserve linked editions/images for the Notion exporter.
    # Exclusive creation protects previous raw material when not resuming.
    with (open(run_dir / "records_full.jsonl", "a" if file_mode == "a" else "x", encoding="utf-8") as rawf,
          open(out_file, file_mode, newline="", encoding="utf-8-sig") as csvf,
          open(review_file, file_mode, newline="", encoding="utf-8-sig") as rvf,
          open(drop_path, "a" if file_mode == "a" else "x", encoding="utf-8") as dropf):

        writer  = csv.writer(csvf)
        rv_writer = csv.writer(rvf)
        COLS = ["Источник", "Территория", "Ключевое слово",
                "Название", "Год от", "Год до", "URL", "Описание"]
        # Заголовок пишем только для нового файла
        if file_mode == "w":
            writer.writerow(COLS)
            rv_writer.writerow(COLS + ["Решение", "Комментарий"])  # заполнит review.py

        def process_records(rec_iter, source_id, territory, keyword):
            """Раскладывает записи по results/review. Возвращает (pos, doubtful)."""
            pos = doubtful = 0
            for rec in rec_iter:
                record_key = identity(source_id, territory, keyword, rec.url)
                if source_id == "prlib" and record_key in persisted_keys:
                    continue
                verdict = scope_gate.check(rec, source=source_id, amendments=selection)
                record_data = asdict(rec)
                if not verdict.keep:
                    dropf.write(json.dumps({"source": source_id, "territory": territory,
                        "keyword": keyword, "record_key": record_key, "record": record_data,
                        "scope_drop_reason": verdict.reason, "scope_verdict": verdict.asdict()},
                        ensure_ascii=False) + "\n")
                    dropf.flush()
                    os.fsync(dropf.fileno())
                    if source_id == "prlib":
                        persisted_keys.add(record_key)
                    continue
                extra = record_data.get("extra")
                if not isinstance(extra, dict):
                    extra = {"prior_extra": extra} if extra is not None else {}
                extra.update(scope_verdict=verdict.asdict(), ready_for_import=False)
                record_data["extra"] = extra
                rawf.write(json.dumps({"source": source_id, "territory": territory,
                                       "keyword": keyword, "record": record_data},
                                      ensure_ascii=False) + "\n")
                rawf.flush()
                row = [
                    source_id, territory, keyword,
                    rec.title, rec.year_from, rec.year_to,
                    rec.url, (rec.description or ""),
                ]
                if classify(rec.title) == "positive" and not verdict.needs_human:
                    writer.writerow(row)
                    csvf.flush()
                    pos += 1
                else:  # doubtful (negative уже отфильтрован в searcher)
                    rv_writer.writerow(row + ["scope_needs_human" if verdict.needs_human else "", ""])
                    rvf.flush()
                    doubtful += 1
                if source_id == "prlib":
                    for handle in (rawf,csvf,rvf):
                        handle.flush()
                        os.fsync(handle.fileno())
                    persisted_keys.add(record_key)
            return pos, doubtful

        MAX_EMPTY = 5   # пустых ответов подряд в одной территории → пропуск источника
        MAX_ERRORS = 5  # сетевых ошибок подряд (timeout/connection) → пропуск источника

        for source_idx, source_id in enumerate(sources, 1):
            if max_combos_reached:
                print(f"\n✅ max_combos ({args.max_combos}) достигнут — все остальные источники пропускаются")
                break

            print(f"\n{'─'*50}")
            print(f"[{source_idx}/{len(sources)}] Источник: {source_id.upper()}")
            print(f"{'─'*50}")
            sys.stdout.flush()  # гарантировать вывод перед выполнением

            # Проверка инициализации источника
            try:
                print(f"[{source_id}] Инициализация...")
                if source_id != "prlib":
                    test_result = next(registry.search(source_id, "test", max_pages=1), None)
                # PRLIB access is checked by its actual query, never a stray "test" request.
                print(f"[{source_id}] ✅ Инициализирован успешно")
            except Exception as e:
                print(f"[{source_id}] ❌ ОШИБКА инициализации: {e}")
                health.issue(source_id, f"Инициализация: {e}")
                continue  # пропустить этот источник и перейти к следующему
            sys.stdout.flush()

            # walk-источник: один обход коллекции вместо перебора комбинаций
            if registry.is_walk(source_id):
                combo_key = f"__walk__|{source_id}"
                combo_n += 1
                if combo_key in done:
                    print(f"[{source_id}] обход уже выполнен (чекпоинт)")
                    continue
                print(f"[{combo_n}/{total_combos}] {source_id} | обход коллекции", end=" ... ")
                if args.dry_run:
                    print("(dry-run, пропуск)")
                    done.add(combo_key)
                    continue
                try:
                    pos, doubtful = process_records(
                        registry.search(source_id, "",
                                        year_from=YEAR_FROM, year_to=YEAR_TO,
                                        max_pages=args.max_pages),
                        source_id, "(вся коллекция)", "(обход)")
                    total_found += pos + doubtful
                    if pos + doubtful > 0:
                        health.ok(source_id)
                    else:
                        health.issue(source_id, "Обход коллекции: 0 записей")
                    print(f"{pos} уверенных, {doubtful} сомнительных")
                except Exception as e:
                    health.issue(source_id, f"Обход коллекции → {e}")
                    print(f"ОШИБКА: {e}")
                done.add(combo_key)
                save_checkpoint(done, run_dir)
                new_combos_done += 1
                if args.max_combos > 0 and new_combos_done >= args.max_combos:
                    print(f"\n[GitHub Actions] Лимит {args.max_combos} комбинаций достигнут — останавливаемся")
                    max_combos_reached = True
                continue

            skip_source = False
            consecutive_errors = 0  # счётчик сетевых ошибок (отдельно от пустых)

            print(f"[{source_id}] Начинаем поиск по {len(territories)} территориям")

            for territory, gub_label in territories:
                consecutive_empty = 0  # сбрасываем при смене территории
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

                    query_coverage = {}
                    try:
                        try:
                            if source_id == "prlib":
                                search_results = iter_query(run_dir,combo_key,query,
                                    YEAR_FROM,YEAR_TO,args.max_pages,query_coverage)
                            else:
                                search_results = registry.search(source_id, query,
                                    year_from=YEAR_FROM, year_to=YEAR_TO,max_pages=args.max_pages)
                            try:
                                pos, doubtful = process_records(search_results, source_id, territory, keyword)
                            finally:
                                if source_id == "prlib":
                                    search_results.close()
                        except StopIteration:
                            pos, doubtful = 0, 0  # пустой результат — нормально

                        total_found += pos + doubtful

                        if pos + doubtful > 0:
                            health.ok(source_id)
                            consecutive_empty = 0
                        else:
                            consecutive_empty += 1
                            if source_id != "prlib" and consecutive_empty >= MAX_EMPTY:
                                print(f"\n[{source_id}] {MAX_EMPTY} пустых ответа подряд — пропускаем источник")
                                health.issue(source_id,
                                    f"0 результатов на первых {MAX_EMPTY} запросах — источник не отвечает на ключевые слова")
                                skip_source = True
                                done.add(combo_key)
                                save_checkpoint(done, run_dir)
                                break
                        print(f"{pos} уверенных, {doubtful} сомнительных")
                    except KeyboardInterrupt:
                        raise  # Ctrl+C — пробросить выше
                    except Exception as e:
                        err_msg = str(e)[:100]  # обрезать длинные ошибки
                        health.issue(source_id, f"Запрос: {query!r} → {err_msg}")
                        print(f"ОШИБКА: {err_msg}")
                        consecutive_errors += 1
                        if consecutive_errors >= MAX_ERRORS:
                            print(f"\n[{source_id}] {MAX_ERRORS} ошибок подряд — пропускаем источник")
                            health.issue(source_id, f"Источник недоступен: {MAX_ERRORS} ошибок подряд")
                            skip_source = True
                            if source_id != "prlib":
                                done.add(combo_key)
                            save_checkpoint(done, run_dir)
                            break
                    else:
                        consecutive_errors = 0  # сбрасываем при успешном запросе

                    if source_id != "prlib" or query_coverage.get("status") == "reported_end":
                        done.add(combo_key)
                    else:
                        done.discard(combo_key)
                    save_checkpoint(done, run_dir)
                    new_combos_done += 1
                    if args.max_combos > 0 and new_combos_done >= args.max_combos:
                        print(f"\n[GitHub Actions] Лимит {args.max_combos} комбинаций достигнут — останавливаемся")
                        max_combos_reached = True
                        break
                    time.sleep(0.5)  # небольшая пауза между комбинациями

            print(f"[{source_id}] Завершили источник (skip_source={skip_source}, max_combos_reached={max_combos_reached})")

    drop_counts = Counter()
    for dropped in drop_path.read_text(encoding="utf-8").splitlines():
        if dropped.strip():
            drop_counts[json.loads(dropped)["scope_drop_reason"]] += 1
    needs_human = sum(bool((json.loads(line).get("record", {}).get("extra") or {})
                           .get("scope_verdict", {}).get("needs_human"))
                      for line in (run_dir / "records_full.jsonl").read_text(encoding="utf-8").splitlines()
                      if line.strip())
    atomic_json(run_dir / "scope_REPORT.json", {
        "rules_sha256": selection.rules_sha256,
        "scope_drop_counts": dict(drop_counts),
        "candidate_needs_human": needs_human,
        "year_filter": None,
        "ready_for_import": False,
    })

    # A versioned candidate package is produced for every run, including resumes.
    # It contains all raw records; trigger classification is not human approval.
    export_dir = run_dir / ('notion_candidates_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    report = export_notion_candidates(run_dir / 'records_full.jsonl', export_dir)
    print(f"[CSV Notion] {report['rows']} строк; {report['columns']} полей; ручная приёмка ожидается: {export_dir}")
    print(f"\n[ИТОГО] Обработано источников: {source_idx}/{len(sources)}")
    # Сохраняем статусы доступности источников в Notion
    if not args.dry_run and not args.no_notion:
        health.save()
    elif args.no_notion:
        print("[--no-notion] Пропуск записи в Notion (CSV сохранён)")

    print(f"\n{'='*60}")
    print(f"ИТОГО: найдено {total_found} записей")
    print(f"Папка: {run_dir}")
    if args.dry_run:
        print("Режим DRY-RUN — в Notion не записано")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
