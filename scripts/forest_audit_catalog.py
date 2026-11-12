"""Лес в КАТАЛОГЕ Notion: что уже внесено, по каким архивам и губерниям.

Вопрос пользователя 09.11.2026: «а почему ты считаешь что только в РГИА?»
Проверка по `найденные_источники.sqlite` ответа не дала: там 36 274 из 39 637
записей — РГИА, а региональные архивы (ГАПК, ГАКО, ГАСО, ГАЯО) в эту базу не
попадали, они вносились в Notion напрямую. Поэтому считаем по выгрузке каталога.

Вход: output/notion_catalog_<дата>_baseline.jsonl (112 202 записи, 487 МБ) —
читается потоком, в память целиком не поднимается.

Считает: лесные записи по словарю терминов, разрез «архив x административный
уровень x фонд», отдельно — по нашим четырём губерниям (территория берётся
из поля «Охватываемая территория», а при его пустоте — своим гейтом по заголовку).

  python forest_audit_catalog.py [путь_к_baseline.jsonl]
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from forest_audit_store import FALSE, FOREST  # noqa: E402
from territory_gate import our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
OUT = ROOT / "forest_audit"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"


def text_of(f: dict) -> str:
    return " ".join(
        str(f.get(k) or "")
        for k in ("Название источника", "Описание", "Примечания")
    )


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not src.exists():
        sys.exit(f"нет выгрузки: {src}")

    n = 0
    forest: list[dict] = []
    all_arch = Counter()
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        rec = json.loads(line)
        f = rec.get("fields") or {}
        arch = f.get("Архив [авто]") or "?"
        all_arch[arch] += 1
        t = text_of(f)
        if FOREST.search(t) and not FALSE.search(t):
            forest.append(
                {
                    "arch": arch,
                    "fond": str(f.get("Фонд") or ""),
                    "opis": str(f.get("Опись") or ""),
                    "lvl": f.get("Административный уровень") or "",
                    "name": (f.get("Название источника") or "")[:140],
                    "year": f.get("Год создания (нижняя)"),
                    "gub": our_gubernii(t),
                    "status": f.get("Статус приёмки") or "",
                }
            )
    print(f"записей в выгрузке: {n}")
    print(f"лесных по словарю: {len(forest)}\n")

    by_arch = Counter(r["arch"] for r in forest)
    print("ЛЕС ПО АРХИВАМ (и всего записей архива в каталоге):")
    for a, c in by_arch.most_common(20):
        print(f"  {a:<34} лес {c:>6}  из {all_arch[a]:>7}")
    zero = [a for a in all_arch if a not in by_arch and all_arch[a] >= 50]
    if zero:
        print(f"\n  ⚠️ архивы с 50+ записями, но БЕЗ леса: {', '.join(sorted(zero))}")

    gubs = ["Калужская", "Смоленская", "Ярославская", "Пермская"]
    grid: dict[str, Counter] = defaultdict(Counter)
    ours = [r for r in forest if r["gub"]]
    for r in ours:
        for g in r["gub"]:
            grid[r["arch"]][g] += 1
    print(f"\nлесных записей с нашей губернией в заголовке: {len(ours)}")
    print(f"\n{'архив':<34}" + "".join(f"{g:>13}" for g in gubs))
    for a in sorted(grid, key=lambda x: -sum(grid[x].values())):
        print(f"{a:<34}" + "".join(f"{grid[a].get(g, 0):>13}" for g in gubs))

    top_fonds = Counter(
        f"{r['arch']} ф.{r['fond']}" + (f" оп.{r['opis']}" if r["opis"] else "")
        for r in forest
        if r["fond"]
    )
    print("\nТОП фондов по лесу:")
    for k, c in top_fonds.most_common(15):
        print(f"  {c:>6}  {k}")

    rep = ["# Лес в каталоге Notion: что уже внесено\n"]
    rep.append(
        f"Собрано `forest_audit_catalog.py` 09.11.2026 по выгрузке `{src.name}` "
        f"({n} записей). Лесных по словарю — **{len(forest)}**, из них с нашей "
        f"губернией в заголовке — **{len(ours)}**.\n"
    )
    rep.append("## По архивам\n")
    rep.append("| Архив | Лесных | Всего записей архива |")
    rep.append("|---|---|---|")
    for a, c in by_arch.most_common():
        rep.append(f"| {a} | {c} | {all_arch[a]} |")
    if zero:
        rep.append(
            f"\n⚠️ Архивы с 50+ записями в каталоге и **нулём** по лесу: "
            f"{', '.join(sorted(zero))}. Это и есть адреса для прогона.\n"
        )
    rep.append("\n## Разрез: архив x наша губерния\n")
    rep.append("| Архив | " + " | ".join(gubs) + " |")
    rep.append("|---|" + "---|" * len(gubs))
    for a in sorted(grid, key=lambda x: -sum(grid[x].values())):
        rep.append(f"| {a} | " + " | ".join(str(grid[a].get(g, 0)) for g in gubs) + " |")
    rep.append("\n## Топ фондов по лесу\n")
    rep.append("| Записей | Фонд |")
    rep.append("|---|---|")
    for k, c in top_fonds.most_common(40):
        rep.append(f"| {c} | {k} |")
    rep.append("\n## Лесные записи по нашим губерниям\n")
    rep.append("| Архив | Фонд/Опись | Губерния | Год | Название |")
    rep.append("|---|---|---|---|---|")
    for r in sorted(ours, key=lambda x: (x["arch"], x["name"])):
        fo = f"ф.{r['fond']}" + (f"/оп.{r['opis']}" if r["opis"] else "")
        rep.append(
            f"| {r['arch']} | {fo} | {'; '.join(r['gub'])} | {r['year'] or ''} | {r['name']} |"
        )

    path = OUT / "ОБЗОР_лес_в_каталоге.md"
    path.write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"\nотчёт: {path}")


if __name__ == "__main__":
    main()
