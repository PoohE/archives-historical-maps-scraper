"""
Интерактивная проверка сомнительных источников после поиска.

Запуск:
  python review.py                   # открыть последний review.csv
  python review.py output/20260703/  # конкретная папка запуска

Читает review.csv, показывает по одному. Пользователь вводит:
  [Enter]   — включить (да, это карта)
  n         — исключить (не карта)
  s         — пропустить (решить позже)
  q         — выйти (прогресс сохраняется)

После сессии:
  - подтверждённые добавляются в results.csv
  - статистика новых триггер-слов — в trigger_proposals.txt
  - прогресс сохраняется: повторный запуск продолжает с того же места
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).parent / "output"


def find_latest_run() -> Path | None:
    runs = sorted(BASE.glob("20*"))
    for d in reversed(runs):
        if (d / "review.csv").exists():
            return d
    return None


def load_progress(run_dir: Path) -> set[str]:
    """URLs уже просмотренных записей."""
    p = run_dir / "review_progress.json"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return set(json.load(f).get("seen", []))
    return set()


def save_progress(run_dir: Path, seen: set[str]) -> None:
    p = run_dir / "review_progress.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"seen": list(seen)}, f, ensure_ascii=False)


def append_to_results(run_dir: Path, rows: list[list]) -> None:
    """Добавляет подтверждённые записи в results.csv."""
    results_path = run_dir / "results.csv"
    mode = "a" if results_path.exists() else "w"
    with open(results_path, mode, newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if mode == "w":
            writer.writerow(["Источник", "Территория", "Ключевое слово",
                             "Название", "Год от", "Год до", "URL", "Описание"])
        writer.writerows(rows)


def extract_words(titles: list[str]) -> Counter:
    """Извлекает слова из заголовков для анализа триггеров."""
    stopwords = {"и", "в", "на", "по", "за", "из", "от", "до", "об", "к",
                 "с", "у", "а", "но", "или", "не", "для", "при", "под"}
    counter: Counter = Counter()
    for title in titles:
        words = re.findall(r"[а-яёА-ЯЁ]{4,}", title.lower())
        for w in words:
            if w not in stopwords:
                counter[w] += 1
    return counter


def propose_triggers(confirmed_titles: list[str], rejected_titles: list[str],
                     run_dir: Path) -> None:
    """Анализирует паттерны и предлагает новые триггер-слова."""
    from triggers import ALL_POSITIVE, DOUBTFUL

    conf_words  = extract_words(confirmed_titles)
    reject_words = extract_words(rejected_titles)

    # Слова, которых нет в триггерах, но встречаются ≥3 раза в подтверждённых
    existing = set(w for kw in ALL_POSITIVE for w in [kw])
    existing |= set(w for kw in DOUBTFUL for w in [kw])

    proposals = {
        w: cnt for w, cnt in conf_words.items()
        if cnt >= 3 and not any(w.startswith(ex) or ex.startswith(w) for ex in existing)
    }

    out_path = run_dir / "trigger_proposals.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Предлагаемые новые триггер-слова (встречаются ≥3 раза в подтверждённых)\n\n")
        if proposals:
            for w, cnt in sorted(proposals.items(), key=lambda x: -x[1]):
                f.write(f"{cnt:3d}×  {w}\n")
        else:
            f.write("(нет новых кандидатов)\n")

        if rejected_titles:
            f.write("\n# Слова из ОТКЛОНЁННЫХ (ложные срабатывания)\n\n")
            for w, cnt in reject_words.most_common(20):
                f.write(f"{cnt:3d}×  {w}\n")

    print(f"\n  Предложения по триггерам → {out_path.name}")
    if proposals:
        print("  Топ-5 кандидатов для добавления в triggers.py:")
        for w, cnt in sorted(proposals.items(), key=lambda x: -x[1])[:5]:
            print(f"    {cnt}× {w}")


def main() -> None:
    # Определяем папку запуска
    if len(sys.argv) > 1:
        run_dir = Path(sys.argv[1])
        if not run_dir.is_absolute():
            run_dir = BASE / run_dir
    else:
        run_dir = find_latest_run()
        if not run_dir:
            print("Нет папок с review.csv в output/. Сначала запусти run_search.py.")
            sys.exit(1)

    review_path = run_dir / "review.csv"
    if not review_path.exists():
        print(f"Файл не найден: {review_path}")
        sys.exit(1)

    print(f"\n{'═'*60}")
    print(f"ПРОВЕРКА СОМНИТЕЛЬНЫХ ИСТОЧНИКОВ")
    print(f"Папка: {run_dir.name}")
    print(f"{'═'*60}")
    print("  [Enter] — карта (включить)  |  n — не карта  |  s — пропустить  |  q — выйти")
    print()

    # Загружаем все сомнительные
    seen = load_progress(run_dir)
    with open(review_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    pending = [r for r in all_rows if r.get("URL", "") not in seen]
    total   = len(all_rows)
    done    = total - len(pending)

    print(f"  Всего: {total}  |  Уже проверено: {done}  |  Осталось: {len(pending)}")
    if not pending:
        print("\nВсе записи проверены!")
        return

    confirmed_titles: list[str] = []
    rejected_titles:  list[str] = []
    confirmed_rows:   list[list] = []

    for i, row in enumerate(pending, start=done + 1):
        url   = row.get("URL", "")
        title = row.get("Название", "")
        src   = row.get("Источник", "")
        terr  = row.get("Территория", "")
        yr    = f"{row.get('Год от', '')}–{row.get('Год до', '')}"
        desc  = row.get("Описание", "")[:120]

        print(f"\n[{i}/{total}]  {src.upper()} | {terr}")
        print(f"  Название: {title}")
        if yr.strip("–"):
            print(f"  Год:     {yr}")
        if desc:
            print(f"  Описание: {desc}")
        print(f"  URL:     {url}")

        ans = input("→ ").strip().lower()

        if ans == "q":
            print("\nВыход. Прогресс сохранён.")
            break
        elif ans == "n":
            rejected_titles.append(title)
            seen.add(url)
        elif ans == "s":
            pass  # не добавляем в seen — вернёмся
        else:  # Enter = подтвердить
            confirmed_titles.append(title)
            confirmed_rows.append([
                src, terr, row.get("Ключевое слово", ""),
                title, row.get("Год от", ""), row.get("Год до", ""),
                url, row.get("Описание", ""),
            ])
            seen.add(url)

        save_progress(run_dir, seen)

    # Сохранить подтверждённые в results.csv
    if confirmed_rows:
        append_to_results(run_dir, confirmed_rows)
        print(f"\n  ✓ Добавлено в results.csv: {len(confirmed_rows)} записей")

    print(f"\n  Отклонено: {len(rejected_titles)}  |  Пропущено: —")

    # Анализ триггеров
    if confirmed_titles or rejected_titles:
        propose_triggers(confirmed_titles, rejected_titles, run_dir)

    print(f"\n{'═'*60}")
    print("Сессия проверки завершена.")
    total_reviewed = total - len([r for r in all_rows if r.get("URL", "") not in seen])
    print(f"Проверено: {total_reviewed}/{total}")


if __name__ == "__main__":
    main()
