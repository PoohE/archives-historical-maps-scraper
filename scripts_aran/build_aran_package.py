"""СПбФ АРАН: пакет каталога из двух наборов (описи + географический указатель).

Что и откуда:
 * `aran_inventory_cases.jsonl` — перечни дел описей ф. 3 «Географические известия
   по городам и местностям» (оп. 10а и оп. 10б) и «Научно-организационные материалы
   Географического департамента». Это главный массив.
 * `aran_cases.jsonl` — дела, найденные через географический указатель `/geo`
   (8 наших пунктов). Нужен как контроль: часть дел указателя есть и в описях,
   дедуп идёт по ШИФРУ.

⚠️ Класс материала здесь — «пространственное описание», НЕ картография. «Географические
известия по г. N и его уезду при доношении из N-ской воеводской канцелярии» (1760–1768) —
это ответы на академическую географическую анкету: описания городов, уездов, рек, дорог,
мостов. Карт в описи нет, и выдавать их за картографию нельзя.

⚠️ Территория определяется по ГОРОДУ, а не по губернии: на 1761 год Калужской и
Ярославской губерний ещё не существовало (учреждены 1776 и 1777), дела идут по
воеводским канцеляриям — Козельской, Лихвинской, Малоярославской, Романовской,
Пошехонской. Поэтому `scope_rules.territories()` с перечнями уездных городов здесь
работает, а поиск по слову «губерния» дал бы ноль.

Запуск:
    python -B scripts_aran/build_aran_package.py
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
from false_carto import alien_hit, not_a_place  # noqa: E402
from scope_rules import CARTO, MEZHEVYE, territories  # noqa: E402

SRC_DIR = ROOT / "output" / "aran_20261021"
GEO_DESC = re.compile(
    r"географическ\w+\s+извести|географическ\w+\s+ответ|топографическ\w+\s+опис"
    r"|ведомост|реестр|описани|анкет|рапорт\w*\s+из|доношени\w*\s+из", re.I)
# Личная переписка — основное содержимое указателя, в каталог не идёт
PEREPISKA = re.compile(r"письм[оа]|письма|переписк|телеграмм|открытк\w*\s*\d*\s*п\.", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "output" / "aran_package_20261021"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    rows = []
    for fname, origin in (("aran_inventory_cases.jsonl", "перечень дел описи"),
                          ("aran_cases.jsonl", "географический указатель")):
        f = SRC_DIR / fname
        if not f.exists():
            continue
        for ln in f.open(encoding="utf-8"):
            try:
                c = json.loads(ln)
            except Exception:  # noqa: BLE001, S112
                continue
            shifr = (c.get("shifr") or "").strip()
            title = (c.get("zagolovok") or "").strip()
            if not shifr or shifr in seen:
                continue
            seen.add(shifr)
            blob = f"{title} {c.get('geo', '')} {c.get('opis', '')}"
            gub = territories(blob)
            is_desc = bool(GEO_DESC.search(title))
            is_mail = bool(PEREPISKA.search(title))
            rec = {
                "shifr": shifr,
                "zagolovok": title,
                "hron": c.get("hron", ""),
                "listov": c.get("listov", ""),
                "opis": c.get("opis", "") or "ф. 3, по географическому указателю",
                "geo_ukazatel": c.get("geo", ""),
                "territoriya": "; ".join(gub),
                "klass": ("межевые книги" if MEZHEVYE.search(title) else
                          "картография" if CARTO.search(title) and not is_desc else
                          "пространственное описание" if is_desc else ""),
                "otkuda": origin,
                "url": c.get("url", ""),
                "istochnik": "СПбФ АРАН",
            }
            nap = not_a_place(blob)
            al = alien_hit(title)
            if is_mail and not is_desc:
                rec["gate"], rec["gate_reason"] = "отсев", "личная переписка, не описание территории"
            elif not rec["klass"]:
                rec["gate"], rec["gate_reason"] = "отсев", "не описание территории и не картография"
            elif not gub:
                rec["gate"], rec["gate_reason"] = "needs_human", "территория проекта в заголовке не названа"
            elif nap:
                rec["gate"], rec["gate_reason"] = "needs_human", f"название губернии — не топоним: «{nap}»"
            elif al:
                rec["gate"], rec["gate_reason"] = "needs_human", f"названа чужая территория «{al}»"
            else:
                rec["gate"] = "принято"
                rec["gate_reason"] = rec["klass"] + " + территория проекта"
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

    dump("aran_accepted", acc)
    dump("aran_needs_human", nh)
    dump("aran_scope_drops", drop)

    print(f"СПбФ АРАН: дел всего {len(rows)} (дедуп по шифру)")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print("\nпринятые дела:")
    for r in acc:
        print(f"   {r['shifr']:<24} {r['hron'][:18]:<20} {r['zagolovok'][:72]}")
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
