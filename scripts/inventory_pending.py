"""Сводная ревизия: ВСЁ, что накоплено к внесению за работу с серийными данными.

Запрос пользователя 10.11.2026 перед заливкой: проверить, что собрано воедино всё
найденное, а не только последние три пакета. Накопление шло несколькими дорожками
и в разные дни, часть пакетов старше недели.

Скрипт обходит output/ и считает каждый найденный пакет: сколько записей, сколько
уже лежит в каталоге (по page_id либо по шифру), сколько действительно новых.

  python inventory_pending.py
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
BASELINE = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"

#: где искать пакеты: маска → как называется
GLOBS = [
    "*/package*.jsonl", "*/*package*.jsonl", "work_*/*.jsonl",
    "*/ours.jsonl", "*/link_set.jsonl", "*/union.jsonl",
    "package_*/*.jsonl", "*/pakety/*.jsonl",
]
SKIP = ("baseline", "scale_prov", "preflight", "review_", "year_", "foreign_",
        "territory_map", "host_probe", "catalog_check", "opisi_rows", "fund_ids",
        "target_funds", "defects/")


def shelf_of(r: dict) -> str | None:
    for k in ("shelf", "code", "fund_code"):
        if r.get(k):
            return re.sub(r"\s+", "", str(r[k])).lower()
    f, o, d = r.get("fond"), r.get("opis"), r.get("delo")
    if f and d:
        return re.sub(r"\s+", "", f"{r.get('arch','')}ф{f}оп{o}д{d}").lower()
    return None


def main() -> None:
    fix_stdout()
    # что уже в каталоге
    cat_ids: set[str] = set()
    cat_shelf: set[str] = set()
    for line in BASELINE.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        f = rec.get("fields") or {}
        pid = rec.get("page_id") or rec.get("id")
        if pid:
            cat_ids.add(pid)
        sh = shelf_of({"arch": f.get("Архив [авто]"), "fond": f.get("Фонд"),
                       "opis": f.get("Опись"), "delo": f.get("Единица хранения")})
        if sh:
            cat_shelf.add(sh)
    print(f"в каталоге: {len(cat_ids)} записей, {len(cat_shelf)} опознаваемых шифров\n")

    seen_files: set[Path] = set()
    rows_out = []
    for g in GLOBS:
        for p in sorted(ROOT.glob(g)):
            if p in seen_files or any(s in str(p).replace("\\", "/") for s in SKIP):
                continue
            seen_files.add(p)
            try:
                rows = [json.loads(ln) for ln in p.open(encoding="utf-8") if ln.strip()]
            except (json.JSONDecodeError, OSError):
                continue
            if not rows:
                continue
            have_id = sum(1 for r in rows if r.get("page_id") in cat_ids)
            have_sh = sum(
                1 for r in rows
                if not r.get("page_id") and shelf_of(r) in cat_shelf
            )
            new = len(rows) - have_id - have_sh
            rows_out.append({
                "file": str(p.relative_to(ROOT)),
                "rows": len(rows), "in_catalog": have_id + have_sh, "new": new,
            })

    rows_out.sort(key=lambda x: -x["new"])
    print(f"{'файл':62s} {'строк':>7s} {'в каталоге':>11s} {'НОВЫХ':>7s}")
    tot_new = 0
    for r in rows_out:
        if r["rows"] < 5:
            continue
        print(f"  {r['file']:60s} {r['rows']:7d} {r['in_catalog']:11d} {r['new']:7d}")
        tot_new += r["new"]
    print(f"\nвсего потенциально новых записей: {tot_new}")
    print(f"файлов-пакетов просмотрено: {len(rows_out)}")

    out = ROOT / "defects" / "inventory_pending.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows_out, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
