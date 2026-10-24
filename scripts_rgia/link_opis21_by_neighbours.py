"""Оп. 21 ф. 380: привязка оставшихся записей к делам по соседям в сплошной нумерации.

Задача: у 295 записей описи 21 не был прочитан карандашный сквозной номер (= номер дела).
Разбор 18.10 показал, что 207 из них привязывать и не нужно: 101 помечены «ВЫБЫЛО»
(таким номер не ставился), 78 зачёркнуты/переданы, 28 — позднейшие землеустроительные
дела вне описи. Остаются 88.

Механика, подтверждённая чтением сканов 23 и 26 Vision:
карандашный номер ставится у ПЕРВОЙ строки группы, а следующие строки той же группы
(«сшивка» — одно дело из нескольких планов) своего номера не получают. Контроль по уже
привязанным записям сошёлся точно: кат. 9700 → дело 147, 9704 → 148, 9705 → 149,
9711 → 150, 9717 → 151 — и на скане эти номера стоят ровно у этих строк.

Отсюда правило: запись без номера принадлежит делу ближайшей ПРЕДЫДУЩЕЙ привязанной
записи, если следующая привязанная продолжает нумерацию без разрыва (prev+1). Разрыв
означает, что между ними есть собственные номера, которых мы не видели, — такие случаи
в автоматическую привязку не идут, их помечаем на дочитывание скана.

Порядок записей в описи восстанавливается по (лист, № каталога): оба растут по ходу описи.

Выход: opis21_linked_by_neighbours.csv — привязанные, и opis21_still_unlinked.csv — остаток.

Запуск:
    python -B scripts_rgia/link_opis21_by_neighbours.py output/rgia_f380_op21_handoff_20261011
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path


def list_key(s: str) -> tuple[int, int]:
    """«18об» → (18, 1), «19» → (19, 0): оборот идёт после лицевой стороны."""
    m = re.match(r"(\d+)\s*(об)?", (s or "").strip())
    if not m:
        return (10**6, 0)
    return (int(m.group(1)), 1 if m.group(2) else 0)


def num(s: str) -> int:
    m = re.search(r"\d+", (s or ""))
    return int(m.group(0)) if m else 10**9


# Начало описи (листы 1-4) соседями не берётся: предыдущей привязанной записи нет.
# Прочитано Vision со сканов 5-8 (18.10). Номер стоит у строки, выбывшие его не получают,
# поэтому чернильный «№ по порядку» и карандашный номер дела разошлись на единицу уже
# на первом листе: кат. 13063 «Учетная карта» со штампом «ВЫБЫЛО» номера не получила.
MANUAL = {
    "39827": ("1", "скан 5, л.1: карандашный № 1 у строки (кат. 13063 выше — «ВЫБЫЛО», без номера)"),
    "39830": ("2", "скан 5, л.1: карандашный № 2"),
    "39831": ("3", "скан 5, л.1: карандашный № 3"),
    "40471": ("4", "скан 5, л.1: карандашный № 4"),
    "40472": ("5", "скан 5, л.1: карандашный № 5"),
    "46036": ("7", "скан 6, л.2: карандашный № 7 (кат. 44855 и 44861 — «ВЫБЫЛО», без номера)"),
    "46229": ("8", "скан 6, л.2: карандашный № 8"),
    "9976": ("9", "скан 7, л.3, рубрика «Рекогносцировки»: карандашный № 9"),
    # ⚠️ В описи есть ЛИТЕРНЫЕ номера дел (269б, 269в, 270а, 270б, 271а, 271б, 271в) —
    # рубрика «Предположения и проекты», лит. Ж. Первое чтение их не распознало, отсюда
    # мнимые «разрывы нумерации» 269→273. Прочитано со скана 56 (л. 51об-52).
    "10025": ("270б", "скан 56, л.52: карандашный № 270-б (литерный)"),
    "10026": ("271а", "скан 56, л.52: карандашный № 271-а (литерный)"),
}
# Записи без номера каталога — опознаются по началу заголовка.
MANUAL_BY_TITLE = {
    "Чертеж Мехонских дач: села Мехонского под № 38":
        ("6", "скан 6, л.1об: карандашный № 6"),
    "Уменьшенный поверочный план дачи, состоящей в уезд":
        ("10", "скан 8, л.4 «Карты из дополнительной описи»: карандашный № 10"),
    "Чертеж Мехонских дач: села Мехонского с деревнями":
        ("6", "скан 8, л.4: отдельного номера нет, в примечании описи «См. ед. хр. № 6»"),
}


def manual(r: dict) -> tuple[str, str] | None:
    k = (r.get("katalog") or "").strip()
    if k in MANUAL:
        return MANUAL[k]
    t = (r.get("title") or "").strip()
    for pref, v in MANUAL_BY_TITLE.items():
        if t.startswith(pref[:40]):
            return v
    return None


def skip_reason(r: dict) -> str | None:
    note = (r.get("note") or "") + " " + (r.get("needs_human_reason") or "")
    if r.get("vybylo") == "да" or "ЫБЫЛО" in note or "Выбыло" in note:
        return "выбыло — карандашный номер не ставился"
    if "передано" in note or "зачёркнут" in note:
        return "зачёркнуто/передано"
    if "землеустроительн" in note:
        return "позднее землеустроительное дело вне описи"
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    args = ap.parse_args()
    pkg = Path(args.package)

    linked = list(csv.DictReader((pkg / "opis21_records_linked.csv").open(encoding="utf-8-sig")))
    free = list(csv.DictReader((pkg / "opis21_records_without_delo.csv").open(encoding="utf-8-sig")))

    # общий порядок описи: лист, затем номер каталога
    for r in linked:
        r["_src"] = "linked"
    for r in free:
        r["_src"] = "free"
    allrows = sorted(linked + free, key=lambda r: (list_key(r.get("list", "")),
                                                   num(r.get("katalog", ""))))

    out, rest = [], []
    verdict: Counter[str] = Counter()
    for i, r in enumerate(allrows):
        if r["_src"] != "free":
            continue
        man = manual(r)
        if man:
            r["delo_no"], r["link_verdict"] = man[0], "привязано"
            r["link_why"] = f"прочитано со скана: {man[1]}"
            verdict["привязано (чтением скана)"] += 1
            out.append(r)
            continue
        why = skip_reason(r)
        if why:
            verdict["привязка не нужна"] += 1
            r["link_verdict"], r["link_why"] = "не нужна", why
            rest.append(r)
            continue
        prev = next((x for x in reversed(allrows[:i]) if x["_src"] == "linked"), None)
        nxt = next((x for x in allrows[i + 1:] if x["_src"] == "linked"), None)
        pno, nno = (num(prev["delo_no"]) if prev else None), (num(nxt["delo_no"]) if nxt else None)
        if prev and nxt and nno == pno + 1:
            r["delo_no"] = prev["delo_no"]
            r["link_verdict"] = "привязано"
            r["link_why"] = (f"сшивка: номер у первой строки группы (кат. {prev.get('katalog')}"
                             f" → дело {prev['delo_no']}), следующее дело {nxt['delo_no']}"
                             f" продолжает нумерацию без разрыва")
            verdict["привязано"] += 1
            out.append(r)
        else:
            gap = f"{pno}→{nno}" if pno and nno else "край описи"
            r["link_verdict"] = "нужно дочитать скан"
            r["link_why"] = f"разрыв нумерации соседей ({gap}): между ними есть свои номера"
            verdict["нужно дочитать скан"] += 1
            rest.append(r)

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        fields = [k for k in data[0] if not k.startswith("_")]
        with (pkg / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)

    dump("opis21_linked_by_neighbours", out)
    dump("opis21_still_unlinked", rest)

    print(f"записей без дела: {len(free)}")
    for k, v in verdict.most_common():
        print(f"  {v:>4}  {k}")
    if out:
        print("\nпримеры привязки:")
        for r in out[:8]:
            print(f"  кат.{r.get('katalog'):>7} л.{r.get('list'):>6} → дело № {r['delo_no']}"
                  f" | {r['title'][:52]}")
    print(f"\n→ {pkg / 'opis21_linked_by_neighbours.csv'}")
    print(f"→ {pkg / 'opis21_still_unlinked.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
