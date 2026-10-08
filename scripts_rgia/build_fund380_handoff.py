"""Сборка итогового пакета фонда 380 РГИА для передачи в каталог.

Делит выход прогона на три части, не изменяя исходный `records.csv`:
  * `records_clean.csv`  — записи с подтверждённой территорией (идут в каталог);
  * `review_queue.csv`   — территория не названа в заголовке, но запись может быть нашей
                           (определяется только по карточке дела или положению в описи);
  * `out_of_scope.csv`   — мотивированный отсев: чужие губернии, надрегиональные карты,
                           каталоги карт (описи описей).

Почему так: описи 10/21/28 губернские (территория в каждом заголовке), а 38-41 — сводные
каталоги Планового архива по всей империи, где дела сгруппированы по губерниям и название
губернии стоит в заголовке РАЗДЕЛА описи, а не дела. Поэтому 2616 записей из 2633 пришли
без территории и попали в набор как `territory_not_resolved` (keep + needs_human).

Запуск из корня проекта:
    python -B scripts_rgia/build_fund380_handoff.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path("C:/arch/output/rgia_fund380_20261003_v3_1")
RETAG = ROOT / "output" / "rgia_fund380_opisi38_41_retag_20261008" / "retag.jsonl"
OUT = ROOT / "output" / f"rgia_fund380_handoff_package_{time.strftime('%Y%m%d')}"

GUB_OPISI = {"fund380_opis_10": "Калужская губерния",
             "fund380_opis_21": "Пермская губерния",
             "fund380_opis_28": "Смоленская губерния"}
OUT_OF_SCOPE = {"foreign_only", "catalog", "supra_regional"}


def norm_terr(value: str) -> str:
    """Привести к единому виду: «Калужская» и «Калужская губерния» — одно и то же."""
    parts = [p.strip() for p in (value or "").split(";") if p.strip()]
    out = []
    for p in parts:
        p = p if p.endswith("губерния") else f"{p} губерния"
        if p not in out:
            out.append(p)
    return "; ".join(out)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    args = ap.parse_args()
    src = Path(args.src)

    with (src / "records.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    verdicts = {}
    if RETAG.exists():
        for ln in RETAG.open(encoding="utf-8"):
            j = json.loads(ln)
            verdicts[j.get("url", "")] = j
    print(f"записей в прогоне: {len(rows)}; вердиктов разбора 38-41: {len(verdicts)}")

    clean, review, dropped = [], [], []
    for r in rows:
        kw = r.get("keyword", "")
        terr = (r.get("territory") or "").strip()
        if kw in GUB_OPISI:
            r = dict(r, territory=norm_terr(terr) or GUB_OPISI[kw],
                     territory_source="опись губернская: " + GUB_OPISI[kw])
            clean.append(r)
            continue
        v = verdicts.get(r.get("url", ""))
        if terr:
            clean.append(dict(r, territory=norm_terr(terr),
                              territory_source="территория в заголовке дела"))
        elif v and v.get("decision") == "ours":
            clean.append(dict(r, territory=norm_terr(v["territory"]),
                              territory_source="разбор 08.10: " + v["evidence"]))
        elif v and v.get("decision") in OUT_OF_SCOPE:
            dropped.append(dict(r, drop_reason=v["decision"], drop_evidence=v["evidence"]))
        else:
            review.append(dict(r, review_reason=(v or {}).get("evidence",
                                                              "территория не названа")))

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "records_clean.csv", clean)
    write_csv(OUT / "review_queue.csv", review)
    write_csv(OUT / "out_of_scope.csv", dropped)

    by_terr: dict[str, int] = {}
    for r in clean:
        by_terr[r.get("territory", "—")] = by_terr.get(r.get("territory", "—"), 0) + 1
    by_opis: dict[str, int] = {}
    for r in clean:
        k = r.get("keyword", "").replace("fund380_opis_", "оп.")
        by_opis[k] = by_opis.get(k, 0) + 1

    rep = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "source_run": str(src),
        "network": "not_run",
        "input_records": len(rows),
        "clean": len(clean),
        "review_queue": len(review),
        "out_of_scope": len(dropped),
        "conservation_delta": len(rows) - (len(clean) + len(review) + len(dropped)),
        "clean_by_territory": by_terr,
        "clean_by_opis": by_opis,
        "ready_for_import": False,
        "note": "Схема сборочная (не 65 колонок). Мэппинг и дедуп — на стороне каталога.",
    }
    (OUT / "PACKAGE_REPORT.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nчисто:        {len(clean)}")
    print(f"на проверку:  {len(review)}")
    print(f"вне охвата:   {len(dropped)}")
    print(f"delta:        {rep['conservation_delta']}")
    print(f"\nпо территориям: {by_terr}")
    print(f"по описям:      {by_opis}")
    print(f"\nвыход: {OUT}")
    return 0 if rep["conservation_delta"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
