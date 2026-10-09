"""Собрать пакет передачи по Президентской библиотеке: Notion-импорт по трём классам.

Вход: `release_candidates/notion_import.csv` пакета v8.1 (451 запись, 65 колонок) и
вердикты предметного гейта (`output/prlib_subject_gate_<дата>/`). Сопоставление по
ссылке на онлайн-архив.

Выход (`output/prlib_handoff_<дата>/`):
  notion_import_cartographic.csv  — карты, планы, атласы: вносить в каталог
  notion_import_spatial_data.csv  — топографические и статистические описания
  review_subject_unconfirmed.csv  — предмет не подтверждён: НЕ вносить
  dropped.csv                     — отсеяно с причиной
  HANDOFF.md                      — что передаётся и на каких правилах

Запуск:
    python -B scripts_review/build_prlib_handoff.py
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path("C:/arch/output/prlib_catalog_full_20261008_v8_1")
GATE = ROOT / "output" / f"prlib_subject_gate_{time.strftime('%Y%m%d')}"
OUT = ROOT / "output" / f"prlib_handoff_{time.strftime('%Y%m%d')}"
URL_COL = "Ссылка на онлайн-архив"


def read_csv(path: Path) -> list[dict]:
    if not path.exists() or not path.read_text(encoding="utf-8-sig").strip():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], cols: list[str] | None = None) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    if cols is None:
        cols = []
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
    ap.add_argument("--gate", default=str(GATE))
    args = ap.parse_args()
    src, gate = Path(args.src), Path(args.gate)

    notion = read_csv(src / "release_candidates" / "notion_import.csv")
    by_url = {(r.get(URL_COL) or "").strip(): r for r in notion}
    cols = list(notion[0]) if notion else []
    print(f"notion_import: {len(notion)} строк, уникальных ссылок {len(by_url)}")

    parts = {
        "cartographic": read_csv(gate / "keep_cartographic.csv"),
        "spatial": read_csv(gate / "keep_spatial_data.csv"),
        "review": read_csv(gate / "review_subject_unconfirmed.csv"),
        "dropped": read_csv(gate / "dropped.csv"),
    }
    OUT.mkdir(parents=True, exist_ok=True)

    stats: dict[str, dict] = {}
    for name, rows in parts.items():
        matched, missing = [], []
        for r in rows:
            n = by_url.get((r.get("url") or "").strip())
            if n is None:
                missing.append(r.get("title", ""))
                continue
            extra = {k: v for k, v in r.items()
                     if k in ("gate_reason", "gate_evidence", "subject_evidence",
                              "review_reason", "territory")}
            matched.append(dict(n, **{f"gate::{k}": v for k, v in extra.items()}))
        stats[name] = {"gate_rows": len(rows), "matched": len(matched),
                       "unmatched": len(missing), "unmatched_titles": missing[:5]}
        print(f"  {name:<14} гейт {len(rows):>4} → сопоставлено {len(matched):>4}"
              f"{'  ⚠ без ссылки: ' + str(len(missing)) if missing else ''}")
        fname = {"cartographic": "notion_import_cartographic.csv",
                 "spatial": "notion_import_spatial_data.csv",
                 "review": "review_subject_unconfirmed.csv",
                 "dropped": "dropped.csv"}[name]
        write_csv(OUT / fname, matched,
                  cols + [f"gate::{k}" for k in ("territory", "subject_evidence",
                                                 "gate_reason", "gate_evidence",
                                                 "review_reason")])

    (OUT / "HANDOFF_REPORT.json").write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "source_package": str(src),
        "gate_output": str(gate),
        "notion_import_rows": len(notion),
        "parts": stats,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nвыход: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
