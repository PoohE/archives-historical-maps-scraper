"""ГАКО: собрать дела в пакет каталога и прогнать тем же гейтом, что ГАСО.

Гейт переиспользуется целиком из `scripts_gaso/build_gaso_package.py` — правила отбора
общие для всех источников (`ПРАВИЛА_ОТБОРА_источников.md` §1.1, §1.1-бис), и расхождение
между источниками здесь было бы дефектом, а не особенностью.

Запуск:
    python -B scripts_gako/build_gako_package.py C:\\arch\\output\\gako_harvest_20261013\\gako_dela.jsonl \
        --out C:\\arch\\output\\gako_package_20261013
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts_gaso"))
from build_gaso_package import OUT_FIELDS, apply_gate, norm_sign  # noqa: E402
from parse_focr_opisi import OBJ  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.jsonl)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for ln in src.open(encoding="utf-8"):
        if not ln.strip():
            continue
        r = json.loads(ln)
        title = (r.get("zagolovok") or "").strip()
        if not title:
            continue
        rows.append({
            "fund": r["fund"], "opis": r["opis"], "n_delo": r["n_delo"],
            "zagolovok": title,
            "data_nachato": None, "data_okoncheno": None, "listov": None,
            "obyekt": "; ".join(dict.fromkeys(OBJ.findall(title))) or None,
            "kartograficheskiy_priznak": norm_sign(None, title),
            "primechanie": r.get("opis_label"),
            "sposob": "portal", "page": None, "flags": None,
        })
    for r in rows:
        r["gate"], r["gate_reason"] = apply_gate(r)

    def dump(name: str, data: list[dict]) -> None:
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=OUT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps({k: r.get(k) for k in OUT_FIELDS}, ensure_ascii=False) + "\n")

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]
    dump("gako_all_records", rows)
    dump("gako_accepted", acc)
    dump("gako_needs_human", nh)
    dump("gako_scope_drops", drop)

    print(f"записей: {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо фондам (принято):")
    for fund, n in Counter(r["fund"] for r in acc).most_common():
        print(f"  ф. {fund:<8} {n}")
    print("\nпризнаки у принятых:")
    for k, n in Counter(r["kartograficheskiy_priznak"] for r in acc).most_common(10):
        print(f"  {k:<28} {n}")
    print(f"\nпакет: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
