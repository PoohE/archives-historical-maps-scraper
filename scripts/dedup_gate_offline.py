"""Блокирующий дедуп-гейт перед заливкой: пакет против каталога, офлайн.

Почему офлайн, а не 2 939 запросов к живой базе: фильтр `url equals` на каталоге из
112 тыс. записей отвечает с задержкой и отдаёт 504, то есть «не найдено» не означает
«нет в базе» (память feedback_upload-acceptance-by-page-id-journal), а сплошной запрос
обрывается на 10 000 записях (feedback_notion-query-caps-at-10000).

Источники истины о том, что уже в каталоге:
  1. последняя офлайн-выгрузка каталога (`*_baseline.jsonl`, поле «Ссылка на онлайн-архив»);
  2. ВСЕ журналы заливок, сделанных после даты выгрузки (`created_pages.jsonl`,
     `created.jsonl`) — иначе месячный разрыв между выгрузкой и сегодняшним днём
     пропустит свежевнесённое.

Сверка идёт по нормализованному URL: схема и www отбрасываются, хвостовой слэш снимается,
регистр хоста опускается. Иначе `http://` против `https://` и `/nodes/16157` против
`/nodes/16157/` дадут ложное «нет в базе».

  python scripts/dedup_gate_offline.py output/upload_2026-11-22-series/review_run/notion_import.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
URL_COL = "Ссылка на онлайн-архив"


def norm(url: str) -> str:
    """URL к сравнимому виду: без схемы, без www, без хвостового слэша."""
    u = (url or "").strip()
    if not u:
        return ""
    p = urlparse(u if "//" in u else "//" + u)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "").rstrip("/")
    q = f"?{p.query}" if p.query else ""
    return f"{host}{path}{q}"


def load_baseline(path: Path) -> set[str]:
    seen: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            val = (rec.get("fields") or {}).get(URL_COL)
            if isinstance(val, str) and val.strip():
                seen.add(norm(val))
    return seen


def load_journals(after: str) -> tuple[set[str], list[tuple[str, int]]]:
    """URL из всех журналов заливок. after — дата выгрузки, только для отчёта."""
    seen: set[str] = set()
    found: list[tuple[str, int]] = []
    pats = ["*/created_pages.jsonl", "*/*/created_pages.jsonl",
            "*/created.jsonl", "*/*/created.jsonl"]
    for pat in pats:
        for p in sorted(OUT.glob(pat)):
            n = 0
            for line in p.open(encoding="utf-8"):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                u = rec.get("url") or rec.get(URL_COL) or ""
                if u:
                    seen.add(norm(u))
                    n += 1
            if n:
                found.append((str(p.relative_to(OUT)), n))
    return seen, found


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("package", help="CSV пакета заливки")
    ap.add_argument("--baseline", default=None, help="выгрузка каталога; по умолчанию свежайшая")
    ap.add_argument("--write-clean", action="store_true",
                    help="записать рядом notion_import_clean.csv без дублей")
    args = ap.parse_args()

    pkg_path = Path(args.package)
    if not pkg_path.exists():
        sys.exit(f"нет пакета: {pkg_path}")

    if args.baseline:
        base_path = Path(args.baseline)
    else:
        cands = sorted(OUT.glob("notion_catalog_*_baseline.jsonl"))
        if not cands:
            sys.exit("не найдена офлайн-выгрузка каталога (*_baseline.jsonl)")
        base_path = max(cands, key=lambda p: p.stat().st_size)

    print(f"выгрузка каталога: {base_path.name} "
          f"({base_path.stat().st_size / 1e6:.0f} МБ, {base_path.stat().st_mtime_ns // 10**9})")
    base = load_baseline(base_path)
    print(f"  URL в выгрузке: {len(base)}")

    jrn, found = load_journals(base_path.name)
    print(f"  журналов заливок найдено: {len(found)}, URL в них: {len(jrn)}")
    for name, n in found:
        print(f"    {n:5d}  {name}")

    known = base | jrn
    print(f"  всего известных URL: {len(known)}")

    rows = list(csv.DictReader(pkg_path.open(encoding="utf-8-sig")))
    dup_base, dup_jrn, inner, clean = [], [], [], []
    seen_pkg: set[str] = set()
    for r in rows:
        k = norm(r.get(URL_COL, ""))
        if not k:
            continue
        if k in seen_pkg:
            inner.append(r)
            continue
        seen_pkg.add(k)
        if k in base:
            dup_base.append(r)
        elif k in jrn:
            dup_jrn.append(r)
        else:
            clean.append(r)

    print(f"\nПАКЕТ: {len(rows)} строк")
    print(f"  уже в каталоге (по выгрузке):      {len(dup_base)}")
    print(f"  уже внесено после выгрузки:        {len(dup_jrn)}")
    print(f"  дубль внутри пакета:               {len(inner)}")
    print(f"  К ЗАЛИВКЕ (нет нигде):             {len(clean)}")

    for label, lst in (("уже в каталоге", dup_base), ("внесено после выгрузки", dup_jrn)):
        if lst:
            print(f"\nпримеры — {label}:")
            for r in lst[:5]:
                print(f"  {r[URL_COL]}\n     {r['Название источника'][:80]}")

    if args.write_clean:
        dest = pkg_path.with_name("notion_import_clean.csv")
        with dest.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(clean)
        print(f"\n-> {dest} ({len(clean)} строк)")

    print("\nГЕЙТ: " + ("ЧИСТО, дублей нет" if not (dup_base or dup_jrn or inner)
                        else f"НАЙДЕНЫ ДУБЛИ — {len(dup_base) + len(dup_jrn) + len(inner)}"))


if __name__ == "__main__":
    main()
