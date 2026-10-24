"""ГПИБ: добор ссылок на сканы (и размеров страниц) для карточек пакета.

⚠️ КАК УСТРОЕН ДОСТУП К СКАНАМ (разобрано 21.10.2026, без этого ссылки не собрать):
  * карточка `/ru/nodes/<id>` публично отдаёт только МИНИАТЮРУ первой страницы —
    `/system/pages/.../images/small/<hash>.jpg`, это 328×359 px при оригинале
    3086×3386; пути `original`, `large`, `medium` отвечают 404, а в конфиге
    просмотрщика стоит `"downloadUrl": null` — скачивание оригинала отключено;
  * НО в конфиге карточки лежит список страниц с их размерами:
    `"pages":[{"id":1360417,"w":3086,"h":3386,"downloadUrl":null}]`,
    и `"zooms":[82,164,328,492,656,818,984,1146,1966]` — ширины девяти уровней;
  * сам просмотрщик строит адрес по формуле из `application-*.js`:
        pageUrl(pageId, z) = links_z0/z1/z2[pageId]  при z < 3
                             «/pages/<pageId>/zooms/<z>»  при z >= 3
    Проверено: `/pages/1360417/zooms/8` → 1966×2157 px, 891 КБ. С этого размера
    читаются выходные данные, линейная шкала и подписи волостей — то есть с него
    и снимаются масштаб, год и объекты.

Скрипт берёт node_id из пакета, вытаскивает page_id каждой страницы и пишет ссылку
на максимальный доступный зум.

Запуск:
    python -B scripts_gpib/gpib_fetch_scans.py --only-carto
    python -B scripts_gpib/gpib_fetch_scans.py
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "output" / "gpib_package_20261021"
OUT = ROOT / "output" / "gpib_yandex_20261021"
HOST = "http://elib.shpl.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
DELAY = 1.0
MAX_ZOOM = 8


def get(url: str, tries: int = 3) -> str | None:
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
        except Exception:  # noqa: BLE001
            pass
        time.sleep(2 + 3 * n)
    return None


def scans_of(node_id: str) -> dict:
    """Страницы карточки: id, размер оригинала, ссылка на максимальный зум."""
    doc = get(f"{HOST}/ru/nodes/{node_id}")
    if not doc:
        return {}
    m = re.search(r'"pages":(\[.*?\])', doc)
    zooms = re.search(r'"zooms":\[([\d,\s]+)\]', doc)
    if not m:
        return {}
    try:
        pages = json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return {}
    zs = [int(x) for x in zooms.group(1).split(",")] if zooms else []
    zmax = min(MAX_ZOOM, len(zs) - 1) if zs else MAX_ZOOM
    first = pages[0] if pages else {}
    return {
        "stranic": len(pages),
        "page_id": first.get("id", ""),
        "original_px": f"{first.get('w','')}x{first.get('h','')}" if first else "",
        "zoom_px": zs[zmax] if zs else "",
        # ссылка на максимальный доступный зум первой страницы
        "url_skana": (f"{HOST}/pages/{first['id']}/zooms/{zmax}" if first.get("id") else ""),
        "page_ids": ";".join(str(p.get("id", "")) for p in pages[:50]),
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-carto", action="store_true",
                    help="только картографические карточки и тома с картой в приложении")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    src = PKG / "гпиб_accepted.jsonl"
    rows = [json.loads(ln) for ln in src.open(encoding="utf-8")]
    todo = [r for r in rows
            if not args.only_carto
            or r.get("klass") in ("картография", "межевые книги")
            or r.get("prilozhenie_karta")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"карточек в пакете {len(rows)}, в работе {len(todo)}")

    dst = OUT / "gpib_scans.jsonl"
    done: dict[str, dict] = {}
    if dst.exists():
        for ln in dst.open(encoding="utf-8"):
            try:
                r = json.loads(ln)
                done[r["node_id"]] = r
            except Exception:  # noqa: BLE001, S112
                continue

    with dst.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(todo, 1):
            nid = str(r["node_id"])
            if nid in done:
                continue
            s = scans_of(nid)
            rec = {"node_id": nid, "zagolovok": r["zagolovok"][:200], **s}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            done[nid] = rec
            print(f"  {i:>4}/{len(todo)} {nid:>8} стр.{s.get('stranic','?'):<4} "
                  f"{s.get('original_px','—'):<12} → {s.get('url_skana','—')}", flush=True)
            time.sleep(DELAY)

    rows_out = list(done.values())
    if rows_out:
        cols = sorted({k for r in rows_out for k in r})
        with (OUT / "gpib_scans.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_out)
    print(f"\nкарточек со сканом: {sum(1 for r in rows_out if r.get('url_skana'))} из {len(rows_out)}")
    print(f"→ {OUT / 'gpib_scans.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
