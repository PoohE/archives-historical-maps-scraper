"""ГПИБ: скачать сканы одностраничных карт для распознавания.

По правилу пользователя (21.10): карточка-КАРТА (один лист) — скачиваем скан и
распознаём с него масштаб, год и отображаемые объекты; карточка-ТЕКСТ (том во много
листов) — только ссылка и число листов, распознавание не ведётся.

Берёт `gpib_maps.jsonl`, отбирает записи по 4 губерниям с одним листом и качает
максимальный доступный зум (`/pages/<page_id>/zooms/8`).

Запуск:
    python -B scripts_gpib/gpib_download_maps.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "output" / "gpib_yandex_20261021" / "gpib_maps.jsonl"
DST = Path(r"C:/Users/admin/AppData/Local/Temp/claude"
           r"/D--IG-Dropbox-Andy-PoohV-Project-Claude"
           r"/ae4394c8-cb3d-46e4-9d8e-1d9425a44bd7/scratchpad/gpib_maps")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DELAY = 1.0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    DST.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8")]
    maps = [r for r in rows
            if r.get("territoriya") and r.get("stranic") == 1 and r.get("url_skana")]
    if args.limit:
        maps = maps[: args.limit]
    print(f"одностраничных карт по 4 губерниям: {len(maps)}")

    index = []
    for i, r in enumerate(maps, 1):
        out = DST / f"{r['node_id']}.jpg"
        if not out.exists():
            try:
                req = urllib.request.Request(
                    r["url_skana"], headers={"User-Agent": UA,
                                             "Referer": r.get("url", "http://elib.shpl.ru/")})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    out.write_bytes(resp.read())
                time.sleep(DELAY)
            except urllib.error.HTTPError as e:
                print(f"  {i:>3}/{len(maps)} {r['node_id']} — HTTP {e.code}")
                continue
            except Exception as e:  # noqa: BLE001
                print(f"  {i:>3}/{len(maps)} {r['node_id']} — {type(e).__name__}")
                continue
        kb = out.stat().st_size // 1024
        index.append({"node_id": r["node_id"], "file": str(out),
                      "zagolovok": r["zagolovok"], "territoriya": r["territoriya"],
                      "original_px": r.get("original_px", ""),
                      "iz_izdaniya": r.get("iz_izdaniya", ""),
                      "url": r.get("url", "")})
        print(f"  {i:>3}/{len(maps)} {r['node_id']:>8} {kb:>5} КБ  {r['zagolovok'][:54]}")

    (DST / "_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nскачано: {len(index)} → {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
