"""Выгрузка по одному уезду из набора ф. 380 РГИА — срез для просмотра человеком.

Зачем: пользователь просит «всё, что нашлось по губернии X, уезд Y». Ищем по ВСЕМ частям
пакета (clean / review / out_of_scope), чтобы срез был честным, а не только по принятому.
Масштаб парсится из заголовка тем же способом, что в `triage_fund380_review_queue.py`
(1 верста в дюйме = 1:42 000, 1 сажень = 1:84).

Запуск:
    python -B scripts_rgia/extract_uezd_slice.py --uezd "мещ[оеё]в" --label мещовский
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "output" / "rgia_fund380_handoff_package_20261008"
PARTS = {
    "clean": PKG / "records_clean.csv",
    "review": PKG / "review_queue.csv",
    "out_of_scope": PKG / "out_of_scope.csv",
}
NUM = r"(\d+(?:[.,]\d+)?)"
SCALE_PATTERNS = [
    (re.compile(r"1\s*/\s*(\d[\d\s]{3,9})"), "direct"),
    (re.compile(rf"{NUM}\s*саж[еня]*\w*", re.I), "sazhen"),
    (re.compile(rf"{NUM}\s*верст\w*", re.I), "versta"),
    (re.compile(rf"{NUM}\s*вер\.", re.I), "versta"),
]
# Колонки среза: сначала то, что читает человек, потом служебное
COLS = ["part", "fund_code", "opis", "delo", "uezd_role", "doc_kind", "title", "date_raw",
        "year_from", "year_to", "sheets", "scale_denominator", "scale_source", "territory",
        "territory_evidence", "territory_source", "subject_evidence", "level_evidence",
        "needs_human", "url"]

# Заголовки ф. 380 строятся как «<губерния>. <уезд>. <предмет>» — предмет берём из третьей части
DOC_KINDS = [
    (re.compile(r"юридическ\w*\s+документ", re.I), "юридические документы дачи"),
    (re.compile(r"отчетн\w*\s+карт", re.I), "отчётная карта уезда"),
    (re.compile(r"план\w*\s+крестьянск\w*\s+земел", re.I), "план крестьянских земель"),
    (re.compile(r"план\w*\s+земел\w*\s+общего", re.I), "план земель общего и чересполосного владения"),
    (re.compile(r"казенн\w*\s+оброчн\w*\s+стат", re.I), "план казённой оброчной статьи"),
    (re.compile(r"\bплан\w*\b", re.I), "план (прочий)"),
    (re.compile(r"\bкарт\w*\b", re.I), "карта (прочая)"),
]


def doc_kind(title: str) -> str:
    for rx, name in DOC_KINDS:
        if rx.search(title or ""):
            return name
    return "не определён"


def uezd_role(title: str, rx: re.Pattern) -> str:
    """Свой уезд записи или лишь упоминание в тексте заголовка.

    У ф. 380 уезд стоит во ВТОРОЙ части заголовка после губернии. Если совпадение
    только дальше по тексту — дело относится к соседнему уезду, а наш назван как
    смежная территория («пустоши: Раменного леса…» в деле Мосальского уезда).
    """
    parts = [p.strip() for p in (title or "").split(".")]
    head = ". ".join(parts[:3])          # архив + губерния + уезд
    return "own" if rx.search(head) else "mention"


def parse_scale(title: str) -> tuple[int | None, str]:
    t = title or ""
    m = re.search(r"[Мм]асштаб\w*\s*([^.;]{1,60})", t)
    tail = m.group(1) if m else t
    for rx, kind in SCALE_PATTERNS:
        mm = rx.search(tail)
        if not mm:
            continue
        raw = mm.group(1).replace(" ", "").replace(",", ".")
        try:
            val = float(raw)
        except ValueError:
            continue
        if val <= 0:
            continue
        if kind == "direct":
            return int(val), "в заголовке прямо (1/N)"
        if kind == "sazhen":
            return int(round(val * 84)), f"{raw} саж. в дюйме → 1 саж. = 1:84"
        return int(round(val * 42000)), f"{raw} вер. в дюйме → 1 вер. = 1:42 000"
    return None, ""


def split_code(code: str) -> tuple[str, str]:
    """«Ф. 380 Оп. 10 Д. 1» → («10», «1»)."""
    o = re.search(r"Оп\.?\s*([\w/]+)", code or "")
    d = re.search(r"Д\.?\s*([\w\s./-]+?)\s*$", code or "")
    return (o.group(1) if o else ""), (d.group(1).strip() if d else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uezd", required=True, help="регулярка названия уезда, напр. мещ[оеё]в")
    ap.add_argument("--label", required=True, help="метка для имени файла")
    ap.add_argument("--out", default=str(ROOT / "output"))
    args = ap.parse_args()
    rx = re.compile(args.uezd, re.I)

    rows: list[dict] = []
    counts: dict[str, int] = {}
    for part, path in PARTS.items():
        src = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        hit = [r for r in src if any(rx.search(str(v or "")) for v in r.values())]
        counts[part] = len(hit)
        print(f"{part:<13} {len(src):>5} записей → совпало {len(hit)}")
        for r in hit:
            opis, delo = split_code(r.get("fund_code", ""))
            den, how = parse_scale(r.get("title", ""))
            rows.append({
                "part": part,
                "fund_code": r.get("fund_code", ""),
                "opis": opis,
                "delo": delo,
                "uezd_role": uezd_role(r.get("title", ""), rx),
                "doc_kind": doc_kind(r.get("title", "")),
                "title": r.get("title", ""),
                "date_raw": r.get("date_raw", ""),
                "year_from": r.get("year_from", ""),
                "year_to": r.get("year_to", ""),
                "sheets": r.get("sheets", ""),
                "scale_denominator": den or "",
                "scale_source": how,
                "territory": r.get("territory", ""),
                "territory_evidence": r.get("territory_evidence", ""),
                "territory_source": r.get("territory_source", ""),
                "subject_evidence": r.get("subject_evidence", ""),
                "level_evidence": r.get("level_evidence", ""),
                "needs_human": r.get("needs_human", ""),
                "url": r.get("url", ""),
            })

    def sort_key(r: dict) -> tuple:
        return (r["opis"], int(re.sub(r"\D", "", r["delo"]) or 0), r["title"])

    rows.sort(key=sort_key)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d")
    csv_path = out_dir / f"rgia_f380_{args.label}_uezd_{stamp}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    with_scale = [r for r in rows if r["scale_denominator"]]
    years = sorted({r["year_from"] for r in rows if r["year_from"]})
    rep = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "pattern": args.uezd,
        "source_package": str(PKG),
        "counts_by_part": counts,
        "total": len(rows),
        "with_scale": len(with_scale),
        "years_span": [years[0], years[-1]] if years else None,
        "by_opis": {o: sum(1 for r in rows if r["opis"] == o)
                    for o in sorted({r["opis"] for r in rows})},
        "by_uezd_role": {k: sum(1 for r in rows if r["uezd_role"] == k)
                         for k in ("own", "mention")},
        "by_doc_kind": {k: sum(1 for r in rows if r["doc_kind"] == k)
                        for k in sorted({r["doc_kind"] for r in rows})},
    }
    (out_dir / f"rgia_f380_{args.label}_uezd_{stamp}_REPORT.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nвсего {len(rows)}; с масштабом {len(with_scale)}; "
          f"годы {rep['years_span']}; по описям {rep['by_opis']}")
    print(f"файл: {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
