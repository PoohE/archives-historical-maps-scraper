"""
Быстрая проверка отдельного источника: 1 запрос, до 5 записей.

Запуск:
  python check_source.py rsl               # проверить РГБ
  python check_source.py rosarchive        # проверить Росархив-онлайн
  python check_source.py rgia              # проверить РГИА (fgurgia.ru)
  python check_source.py ebid              # проверить ЭБИД
  python check_source.py goskatalog        # проверить Госкаталог (SPA — особый режим)
  python check_source.py neb               # проверить НЭБ
  python check_source.py gpib              # проверить ГПИБ
  python check_source.py kaluga_lib        # проверить Калугу (нужен рос. IP)
  python check_source.py smolensk_lib      # проверить Смоленск
  python check_source.py permkrai          # проверить Пермь (нужен рос. IP)
  python check_source.py all               # проверить все доступные (медленно)

Цель: быстро понять, отвечает ли сайт и есть ли там карты.
Не записывает в Notion. Не сохраняет в файл.
"""

import sys
import time
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).parent / "modules"))
sys.stdout.reconfigure(encoding="utf-8")

# Тестовый запрос и фильтры — достаточно широкие чтобы что-то найти
TEST_QUERY   = "карта Калужской губернии"
TEST_QUERY2  = "карта калужская"       # для архивов с другим форматом
YEAR_FROM    = 1700
YEAR_TO      = 1920
LIMIT        = 5                       # показать не более N записей


# ── Вспомогательные функции ───────────────────────────────────────────────────

def _take(gen: Iterator, n: int) -> list:
    result = []
    for item in gen:
        result.append(item)
        if len(result) >= n:
            break
    return result


def _print_header(source_id: str, label: str, url: str) -> None:
    print()
    print("=" * 70)
    print(f"  {source_id.upper():<15} {label}")
    print(f"  {url}")
    print("=" * 70)


def _print_records(records: list, fields_fn) -> None:
    if not records:
        print("  ⚠  Записей не найдено (проверь соединение и --debug вручную)")
        return
    for r in records:
        print(f"  ✓  {fields_fn(r)}")


def _ok_or_fail(count: int) -> str:
    return "✅ OK" if count > 0 else "❌ FAIL (нет записей)"


# ── Проверки по источникам ────────────────────────────────────────────────────

def check_rsl() -> int:
    _print_header("rsl", "Российская государственная библиотека", "https://search.rsl.ru")
    from scrapers import searcher_rsl as m
    gen = m.search(TEST_QUERY, year_from=YEAR_FROM, year_to=YEAR_TO, free_only=True)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"[{r.shelfmark[:18]}] {r.title[:45]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_neb() -> int:
    _print_header("neb", "Национальная электронная библиотека", "https://rusneb.ru")
    from scrapers import searcher_neb as m
    gen = m.search(TEST_QUERY, year_from=YEAR_FROM, year_to=YEAR_TO)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"{r.title[:55]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_gpib() -> int:
    _print_header("gpib", "ГПИБ России", "http://elib.shpl.ru")
    import registry
    gen = registry.search("gpib", TEST_QUERY, year_from=YEAR_FROM, year_to=YEAR_TO, max_pages=1)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"{r.title[:55]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_kaluga_lib() -> int:
    _print_header("kaluga_lib", "Калужская ОНБИБ (IRBIS64, нужен рос. IP)",
                  "http://217.15.203.140:81")
    from scrapers import searcher_kaluga as m
    gen = m.search(TEST_QUERY, year_from=YEAR_FROM, year_to=YEAR_TO)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"{r.title[:55]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_smolensk_lib() -> int:
    _print_header("smolensk_lib", "Смоленская ОУНБ (обход коллекции)",
                  "http://www.smolensklib.ru")
    from scrapers import searcher_smolensk as m
    gen = m.search(year_from=YEAR_FROM, year_to=YEAR_TO, max_pages=1)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"{r.title[:55]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_permkrai() -> int:
    _print_header("permkrai", "Пермская краевая библиотека (нужен рос. IP)",
                  "https://lib.permkrai.ru")
    from scrapers import searcher_permkrai as m
    gen = m.search("карта Пермской губернии", year_from=YEAR_FROM, year_to=YEAR_TO)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"{r.title[:55]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_rosarchive() -> int:
    _print_header("rosarchive", "Росархив Онлайн (РГАДА, РГВИА, РГИА, ГАРФ)",
                  "http://online.archives.ru")
    from scrapers import searcher_rosarchive as m
    gen = m.search(TEST_QUERY2, year_from=YEAR_FROM, year_to=YEAR_TO)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"{r.title[:55]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_rgia() -> int:
    _print_header("rgia", "РГИА — электронный каталог (fgurgia.ru)",
                  "https://fgurgia.ru")
    from scrapers import searcher_rgia as m
    gen = m.search(TEST_QUERY, year_from=YEAR_FROM, year_to=YEAR_TO)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"[{r.fund_code[:18]}] {r.title[:40]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_ebid() -> int:
    _print_header("ebid", "ЭБИД / ИнфоРост (docs.historyrussia.org)",
                  "https://docs.historyrussia.org")
    from scrapers import searcher_ebid as m
    gen = m.search(TEST_QUERY, year_from=YEAR_FROM, year_to=YEAR_TO, max_pages=3)
    recs = _take(gen, LIMIT)
    _print_records(recs, lambda r: (
        f"{(str(r.year_from or '?') + '–' + str(r.year_to or '?')):<12}"
        f"[{r.archive[:15]}] {r.title[:45]}"
    ))
    print(f"\n  Результат: {_ok_or_fail(len(recs))} ({len(recs)} из {LIMIT})")
    return len(recs)


def check_goskatalog() -> int:
    _print_header("goskatalog", "Госкаталог.РФ (SPA — нужна API-разведка)",
                  "https://goskatalog.ru/portal/")
    print("  ⚠  Госкаталог использует SPA (#-роутинг).")
    print("     Для API-разведки: открой DevTools → Network → поищи «карта Калужская»")
    print("     → найди XHR-запрос к /portal/api/ или /api/")
    print("     Запиши URL и передай мне — допишу searcher_goskatalog.py")
    print("\n  Пропускаем автоматическую проверку.")
    return -1  # -1 = не реализовано, пропускаем


# ── Диспетчер ─────────────────────────────────────────────────────────────────

CHECKS = {
    "rsl":          check_rsl,
    "neb":          check_neb,
    "gpib":         check_gpib,
    "kaluga_lib":   check_kaluga_lib,
    "smolensk_lib": check_smolensk_lib,
    "permkrai":     check_permkrai,
    "rosarchive":   check_rosarchive,
    "rgia":         check_rgia,
    "ebid":         check_ebid,
    "goskatalog":   check_goskatalog,
}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Быстрая проверка архива: 1 запрос, до 5 записей"
    )
    parser.add_argument("source",
                        help=f"ID источника или 'all'. Доступно: {', '.join(CHECKS)}")
    args = parser.parse_args()

    if args.source == "all":
        summary: list[tuple[str, int]] = []
        for src_id, fn in CHECKS.items():
            try:
                n = fn()
                summary.append((src_id, n))
            except Exception as e:
                print(f"\n  ❌ ОШИБКА: {e}")
                summary.append((src_id, -2))
            time.sleep(3)  # пауза между архивами

        print("\n\n" + "=" * 70)
        print("  ИТОГИ ПРОВЕРКИ")
        print("=" * 70)
        for src_id, n in summary:
            if n == -1:
                status = "⏭  пропущен (нужна API-разведка)"
            elif n == -2:
                status = "💥 ошибка"
            elif n == 0:
                status = "❌ 0 записей"
            else:
                status = f"✅ {n} записей"
            print(f"  {src_id:<18} {status}")
        return

    if args.source not in CHECKS:
        print(f"Неизвестный источник: {args.source!r}")
        print(f"Доступно: {', '.join(CHECKS)}")
        sys.exit(1)

    try:
        CHECKS[args.source]()
    except Exception as e:
        print(f"\n  ❌ ОШИБКА: {e}")
        print("  Запусти вручную с --debug чтобы увидеть HTML:")
        print(f"  python modules/scrapers/searcher_{args.source}.py --debug ...")
        sys.exit(1)


if __name__ == "__main__":
    main()
