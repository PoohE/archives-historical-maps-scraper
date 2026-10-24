"""Картфонд РГО (онлайн — Геопортал): пакет каталога.

⚠️ ОТБОР ИДЁТ ПО ПОЛЮ «Территориальный охват», НЕ ПО ЗАГОЛОВКУ. Карточки геопортала —
это отдельные ЛИСТЫ атласов, и названия у них вида «Лист 11», «X.», «Planche 1»,
«Обложка», «№ 15», «Аннотация»: по заголовку не видно ничего. Совпадения дают именно
охваты: «Лист 10 → Ярославская область», «X. Рязанско-Уральская… → Калужская область».

⚠️ ОХВАТ ДАН В СОВРЕМЕННЫХ РЕГИОНАХ (область / край / республика), а проект работает
с ГУБЕРНИЯМИ. Поэтому:
  * прямые соответствия (Калужская, Смоленская, Ярославская области, Пермский край)
    → принимаются;
  * регионы, которые были ЧАСТЬЮ Пермской губернии (Свердловская область целиком
    выросла из Екатеринбургского, Верхотурского, Ирбитского, Камышловского уездов;
    Шадринский уезд ушёл в Курганскую область; север — Коми-Пермяцкий округ) →
    `needs_human`: лист может лежать и за пределами губернии, это решает человек;
  * всё остальное → отсев по охвату.

⚠️ Полнота фонда этим пакетом НЕ закрывается: онлайн выложено ≈ 4 % собрания
(2 112 карточек при ~48 тыс. единиц Картфонда), преимущественно листы атласов.

Шифр: архивного/библиотечного шифра карточка не даёт. Идентификатор — номер записи
геопортала (`record_id`) + URL; фондообразователь — Картографический фонд РГО.
⚠️ Геопортал объединяет материалы не только РГО, но и организаций-партнёров —
поле `istochnik_rgo` («Источник» карточки) переносится как есть, чтобы чужое
собрание не ушло в каталог как РГО.

Запуск:
    python -B scripts_rgo/build_rgo_package.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from false_carto import alien_hit, is_false_carto  # noqa: E402
from scope_rules import CARTO, LIMIT, YEAR, territories  # noqa: E402

# Современный регион → губерния проекта (прямое соответствие)
REGION_DIRECT = {
    "Калужская": r"Калужск\w*\s+(?:област|обл)",
    "Смоленская": r"Смоленск\w*\s+(?:област|обл)",
    "Ярославская": r"Ярославск\w*\s+(?:област|обл)",
    "Пермская": r"Пермск\w*\s+(?:кра|обл)|Коми-Пермяцк",
}
# Регионы, выросшие из Пермской губернии — решает человек
REGION_PARTIAL = re.compile(r"Свердловск\w*\s+(?:област|обл)|Курганск\w*\s+(?:област|обл)"
                            r"|Челябинск\w*\s+(?:област|обл)", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "output" / "rgo_geoportal_20261021"
                                        / "rgo_records.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "output" / "rgo_package_20261021"))
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for ln in src.open(encoding="utf-8"):
        try:
            c = json.loads(ln)
        except Exception:  # noqa: BLE001, S112
            continue
        ter_rgo = (c.get("territoriya_rgo") or "").strip()
        title = (c.get("zagolovok") or "").strip()
        blob = " ".join(str(c.get(k, "")) for k in
                        ("zagolovok", "razdel", "podrazdel", "kollekciya", "tip"))
        gub = [g for g, p in REGION_DIRECT.items() if re.search(p, ter_rgo, re.I)]
        # заголовок тоже может называть губернию прямо («Карта Калужской губернии»)
        gub = sorted(set(gub) | set(territories(title)))
        partial = bool(REGION_PARTIAL.search(ter_rgo))
        # ⚠️ Год на геопортале записан с пометкой: «датировано 1862», «около 1840».
        # В каталог нужен год числом, но саму формулировку сохраняем: «около» и
        # «датировано» — это сведения о точности датировки, их нельзя потерять.
        god_raw = str(c.get("god", "") or "").strip()
        m_god = re.search(r"(1[5-9]\d{2}|20[0-2]\d)", god_raw)
        god = m_god.group(1) if m_god else ""
        god_num = int(god) if god else None
        if not god:
            yy = YEAR.findall(" ".join(str(c.get(k, "")) for k in ("zagolovok", "tip")))
            god = max(yy) if yy else ""
            god_num = int(god) if god else None
        rec = {
            "record_id": c.get("record_id", ""),
            "zagolovok": title,
            "razdel": c.get("razdel", ""),
            "podrazdel": c.get("podrazdel", ""),
            "god": god,
            "god_formulirovka": god_raw,
            "tip": c.get("tip", ""),
            "masshtab": c.get("masshtab", ""),
            "avtor": c.get("avtor", ""),
            "izdatel": c.get("izdatel", ""),
            "territoriya_rgo": ter_rgo,
            "territoriya": "; ".join(gub),
            "kollekciya": c.get("kollekciya", ""),
            "istochnik_rgo": c.get("istochnik", ""),
            "url": c.get("url", ""),
            "istochnik": "Картографический фонд РГО (Геопортал)",
        }
        fc = is_false_carto(title)
        al = alien_hit(title)
        if fc:
            rec["gate"], rec["gate_reason"] = "отсев", f"ложный картографический признак: «{fc}»"
        elif not ter_rgo and not gub:
            rec["gate"], rec["gate_reason"] = "needs_human", "территориальный охват в карточке пуст"
        elif gub and god_num and god_num > LIMIT:
            rec["gate"], rec["gate_reason"] = "needs_human", f"издание {god_num} > {LIMIT}"
        elif gub:
            rec["gate"] = "принято"
            rec["gate_reason"] = "территориальный охват — губерния проекта"
            if al:
                rec["gate_reason"] += f" (в заголовке также «{al}» — проверить)"
        elif partial:
            rec["gate"] = "needs_human"
            rec["gate_reason"] = ("охват — регион, выросший из Пермской губернии "
                                  f"(«{ter_rgo[:60]}»): лист может быть и вне губернии")
        else:
            rec["gate"], rec["gate_reason"] = "отсев", f"охват вне проекта: «{ter_rgo[:60]}»"
        # сохраняем картографический признак для сведения
        rec["est_carto_priznak"] = "да" if CARTO.search(blob) else ""
        rows.append(rec)

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("rgo_accepted", acc)
    dump("rgo_needs_human", nh)
    dump("rgo_scope_drops", drop)

    print(f"Картфонд РГО: карточек {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print("\nразделы принятых:")
    for g, n in Counter(r["razdel"] for r in acc).most_common(8):
        print(f"  {n:>4}  {g}")
    print(f"\nс масштабом: {sum(1 for r in acc if r['masshtab'])} из {len(acc)}")
    print(f"с годом:     {sum(1 for r in acc if r['god'])}")
    print("\nисточник в карточке (принято):")
    for g, n in Counter(r["istochnik_rgo"][:40] for r in acc).most_common(5):
        print(f"  {n:>4}  {g or '—'}")
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
