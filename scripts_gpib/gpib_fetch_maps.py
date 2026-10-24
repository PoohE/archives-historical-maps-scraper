"""ГПИБ: добор САМИХ КАРТ — узлы внутри разделов «Карты».

⚠️ ЗАЧЕМ. Прогон 21.10 прочитал 854 узла и дал в пакет лишь ОДНУ настоящую карту.
Причина вскрылась по ссылке пользователя на `/ru/nodes/88747` («Карта Калужской
губернии», лист 3945×2960): у ГПИБ карты лежат на ТРЕТЬЕМ уровне —

    издание → том → раздел «Карты» → сама карта

а узел-раздел называется одним словом «Карты», без губернии и уезда. Обход спускался
только в узлы, где территория уже названа, поэтому в разделы «Карты» он НЕ заходил.
Из 2353 упомянутых дочерних узлов остались непрочитанными 1877, и среди них 120 с
картографической подписью — это и есть пропущенные карты.

Скрипт: берёт прочитанные узлы, находит среди их детей разделы «Карты/Планы/Атлас»,
читает их и их содержимое, вытаскивает лист (page_id, размер, ссылка на зум 8).

Запуск:
    python -B scripts_gpib/gpib_fetch_maps.py --limit 5
    python -B scripts_gpib/gpib_fetch_maps.py
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
sys.path.insert(0, str(ROOT / "scripts_gpib"))
sys.path.insert(0, str(ROOT / "scripts_review"))
from gpib_fetch_cards import get, parse  # noqa: E402
from scope_rules import territories  # noqa: E402

OUT = ROOT / "output" / "gpib_yandex_20261021"
SRC = OUT / "gpib_nodes.jsonl"
DST = OUT / "gpib_maps.jsonl"
HOST = "http://elib.shpl.ru"
DELAY = 1.0
MAX_ZOOM = 8

# Узел-раздел с картами: называется одним словом, территории в названии нет
MAP_SECTION = re.compile(r"^\s*(?:карты|карта|планы|план|атлас\w*|чертежи|"
                         r"картографические\s+материалы)\s*$", re.I)


def scan_info(doc: str) -> dict:
    """page_id, размер оригинала и ссылка на максимальный зум."""
    m = re.search(r'"pages":(\[.*?\])', doc)
    if not m:
        return {}
    try:
        pages = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return {}
    if not pages:
        return {}
    first = pages[0]
    zooms = re.search(r'"zooms":\[([\d,\s]+)\]', doc)
    zs = [int(x) for x in zooms.group(1).split(",")] if zooms else []
    zmax = min(MAX_ZOOM, len(zs) - 1) if zs else MAX_ZOOM
    return {
        "stranic": len(pages),
        "page_id": first.get("id", ""),
        "original_px": f"{first.get('w','')}x{first.get('h','')}",
        "zoom_px": zs[zmax] if zs else "",
        "url_skana": f"{HOST}/pages/{first['id']}/zooms/{zmax}" if first.get("id") else "",
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8")]
    # разделы «Карты» среди детей прочитанных узлов + контекст родителя
    # ⚠️ Берём разделы «Карты» И СРЕДИ ДЕТЕЙ, И СРЕДИ УЖЕ ПРОЧИТАННЫХ УЗЛОВ.
    # Первая версия брала только непрочитанные разделы — и пропустила 33 раздела,
    # которые второй проход открыл, но внутрь не заходил: там осталось 128 карт,
    # включая «Карту Калужской губернии» (node 88747) из раздела 55766.
    sections: dict[str, dict] = {}
    for r in rows:
        if MAP_SECTION.match((r.get("zaglavie") or r.get("zagolovok") or "")):
            sections[r["node_id"]] = {
                "razdel_id": r["node_id"],
                "roditel_id": r["node_id"],
                "roditel": (r.get("roditelskoe") or "")[:200],
                "roditel_izdanie": (r.get("roditelskoe") or "")[:200],
            }
        for d in r.get("deti", []):
            if MAP_SECTION.match(d.get("zagolovok", "")) and d["node_id"] not in sections:
                sections[d["node_id"]] = {
                    "razdel_id": d["node_id"],
                    "roditel_id": r["node_id"],
                    "roditel": (r.get("zaglavie") or r.get("zagolovok") or "")[:200],
                    "roditel_izdanie": (r.get("roditelskoe") or "")[:200],
                }
    secs = list(sections.values())
    if args.limit:
        secs = secs[: args.limit]
    print(f"разделов «Карты» к обходу: {len(secs)}")

    done: set[str] = set()
    if DST.exists():
        for ln in DST.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["node_id"])
            except Exception:  # noqa: BLE001, S112
                continue

    found = 0
    with DST.open("a", encoding="utf-8") as fh:
        for i, s in enumerate(secs, 1):
            doc = get(f"{HOST}/ru/nodes/{s['razdel_id']}")
            if not doc:
                print(f"  {i:>4}/{len(secs)} раздел {s['razdel_id']} — не открылся", flush=True)
                continue
            sec = parse(s["razdel_id"], doc)
            kids = sec.get("deti", [])
            time.sleep(DELAY)
            # сами карты — дети раздела
            for k in kids:
                nid = k["node_id"]
                if nid in done or nid == s["razdel_id"]:
                    continue
                kdoc = get(f"{HOST}/ru/nodes/{nid}")
                if not kdoc:
                    continue
                card = parse(nid, kdoc)
                blob = " ".join(str(card.get(x, "")) for x in
                                ("zaglavie", "zagolovok", "bibl_opisanie")) + " " + s["roditel"]
                rec = {
                    "node_id": nid,
                    "zagolovok": (card.get("zaglavie") or card.get("zagolovok") or
                                  k.get("zagolovok", ""))[:300],
                    "razdel": s["razdel_id"],
                    "iz_izdaniya": s["roditel"],
                    "izdanie_verhnee": s["roditel_izdanie"],
                    "god": card.get("god", ""),
                    "bibl_opisanie": (card.get("bibl_opisanie") or "")[:500],
                    "territoriya": "; ".join(territories(blob)),
                    "url": f"{HOST}/ru/nodes/{nid}",
                    **scan_info(kdoc),
                    "istochnik": "ГПИБ",
                }
                rec.pop("deti", None)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                done.add(nid)
                found += 1
                print(f"  {i:>4}/{len(secs)} {nid:>8} {rec.get('original_px','—'):<12} "
                      f"[{rec['territoriya'] or '—'}] {rec['zagolovok'][:50]}", flush=True)
                time.sleep(DELAY)

    out_rows = [json.loads(ln) for ln in DST.open(encoding="utf-8")]
    if out_rows:
        cols = sorted({k for r in out_rows for k in r})
        with (OUT / "gpib_maps.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(out_rows)
    mine = sum(1 for r in out_rows if r.get("territoriya"))
    print(f"\nкарт собрано: {len(out_rows)} | по 4 губерниям: {mine}")
    print(f"→ {OUT / 'gpib_maps.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
