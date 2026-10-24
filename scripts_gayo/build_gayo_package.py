"""ГАЯО: собрать дела портала в пакет каталога и прогнать общим гейтом отбора.

Гейт переиспользуется целиком из `scripts_gaso/build_gaso_package.py`: правила отбора
общие для всех источников (`ПРАВИЛА_ОТБОРА_источников.md` §1.1, §1.1-бис), расхождение
между архивами было бы дефектом, а не особенностью. Так же сделано по ГАКО.

Запуск:
    python -B scripts_gayo/build_gayo_package.py output/gayo/dela.jsonl \
        --out output/gayo_package_20261014
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts_gaso"))
from build_gaso_package import OUT_FIELDS, apply_gate, norm_sign  # noqa: E402
from parse_focr_opisi import OBJ  # noqa: E402

YEAR = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")

# Класс документа. Губернский межевой архив отложился сплошным массивом генерального
# межевания, и «межевая книга» — сильный признак гейта — даёт десятки тысяч ТЕКСТОВЫХ
# актов (румбы, меры, смежества), а не карт. Для приёмки это надо различать: книга
# неразрывна с планом своей дачи и ценна, но картой не является.
GRAPHIC = re.compile(
    r"геометрическ\w*\s+(?:специальн|генеральн)\w*\s+план|\bплан\b|выкопировк|\bкарт[аыуе]\b"
    r"|чертеж|чертёж|атлас|съемк|съёмк|топограф|профил", re.I)
TEXT_ACT = re.compile(r"^\s*межевая книга|^\s*геодезическ\w*\s+описани|^\s*полев\w*\s+(?:записк|журнал)"
                      r"|^\s*описание границ|^\s*полюбовн\w*\s+сказк", re.I)
PAPERWORK = re.compile(r"^\s*дел[оа]\b|^\s*указ|^\s*рапорт|^\s*переписк|^\s*ведомост"
                       r"|^\s*прошени|^\s*журнал\b|^\s*реестр", re.I)


def klass_of(title: str) -> str:
    if GRAPHIC.search(title):
        return "графический"
    if TEXT_ACT.search(title):
        return "межевой акт (текст)"
    if PAPERWORK.search(title):
        return "делопроизводство"
    return "не определён"


def years(s: str) -> tuple[str | None, str | None]:
    """Крайние даты дела: портал отдаёт «1874 — 1913», «15 дек 1880», «[середина ХІХ в.]»."""
    yy = YEAR.findall(s or "")
    if not yy:
        return None, None
    return yy[0], (yy[-1] if yy[-1] != yy[0] else None)


def opis_label(row: dict) -> str:
    """Номер описи: в карточке фонда он в первой ячейке строки, иначе — внутренний id."""
    cells = [c for c in (row.get("inv_cells") or []) if c]
    if cells:
        m = re.search(r"\d+[А-Яа-яT]*", cells[0])
        if m:
            return m.group(0)
    return f"id{row.get('inv_id', '')}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src, out = Path(args.jsonl), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    # дела в dela.jsonl могут повторяться: при обрыве захода страница перечитывается
    # с начала и строки дописываются снова (18.10 — 4937 лишних строк, все идентичные).
    # Ключ дедупа — unit_id, идентификатор дела на портале.
    seen: set[str] = set()
    dups = 0
    for ln in src.open(encoding="utf-8"):
        if not ln.strip():
            continue
        r = json.loads(ln)
        title = (r.get("title") or "").strip()
        if not title:
            continue
        uid = r.get("unit_id") or ""
        if uid:
            if uid in seen:
                dups += 1
                continue
            seen.add(uid)
        d1, d2 = years(r.get("dates", ""))
        note = [r.get("fund_title", "")]
        if r.get("digitized"):
            note.append(f"оцифровано: {r['digitized']}")
        if r.get("dates") and not d1:
            note.append(f"даты: {r['dates']}")
        rows.append({
            "fund": r.get("fund_num", ""), "opis": opis_label(r),
            "n_delo": r.get("unit_num", ""), "zagolovok": title,
            "data_nachato": d1, "data_okoncheno": d2,
            "listov": r.get("sheets") or None,
            "obyekt": "; ".join(dict.fromkeys(OBJ.findall(title))) or None,
            "kartograficheskiy_priznak": norm_sign(None, title),
            "primechanie": "; ".join(x for x in note if x) or None,
            "sposob": "portal", "page": None,
            "flags": f"arc{r.get('arc')};unit{r.get('unit_id', '')}",
            "klass": klass_of(title),
        })
    for r in rows:
        r["gate"], r["gate_reason"] = apply_gate(r)

    fields = [*OUT_FIELDS, "klass"]

    def dump(name: str, data: list[dict]) -> None:
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps({k: r.get(k) for k in fields}, ensure_ascii=False) + "\n")

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]
    dump("gayo_all_records", rows)
    dump("gayo_accepted", acc)
    dump("gayo_needs_human", nh)
    dump("gayo_scope_drops", drop)

    print(f"записей: {len(rows)} (снято повторов по unit_id: {dups})")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо фондам (принято):")
    for fund, n in Counter(r["fund"] for r in acc).most_common(25):
        print(f"  ф. {fund:<8} {n}")
    print("\nкласс у принятых (для сортировки на приёмке):")
    for k, n in Counter(r["klass"] for r in acc).most_common():
        print(f"  {k:<24} {n}")
    print("\nпризнаки у принятых:")
    for k, n in Counter(r["kartograficheskiy_priznak"] for r in acc).most_common(12):
        print(f"  {k:<30} {n}")
    print(f"\nпакет: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
