"""ГАСО-Урал: скачать сканы описей целевых фондов.

Портал публикует сканы описей простыми JPEG по предсказуемому пути:
`/upload/images/lists_auto/<фонд>_<опись>/NNN.jpg` (нумерация с 001).
Проверено 09.11.2026 на ф. 773 оп. 1 — 32 скана.

Объём по целевым фондам (из `target_funds.json`): всего **13 006** сканов, из них
ф. 59 — 7 285 и ф. 24 — 4 883. Поэтому по умолчанию качаются только МАЛЫЕ фонды:
они дёшевы и закрывают сразу три позиции реестра (А25 — землеустроительные комиссии
восточных уездов Пермской губернии, А29 — съёмки Бержье и Аллори, А13/А30 —
карты лесных дач Камышловского уезда).

  python gaso_ural_fetch_scans.py                 # малые фонды (≈196 сканов)
  python gaso_ural_fetch_scans.py --funds 59,24   # конкретные фонды
  python gaso_ural_fetch_scans.py --all           # все целевые (13 006 — долго)
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

BASE = "https://opisi.gaso-ural.ru"
ROOT = Path(__file__).resolve().parents[1] / "output" / "gaso_ural"
SCANS = ROOT / "scans"
TARGETS = ROOT / "target_funds.json"
LOCK = Path(__file__).resolve().parent / ".gaso_scans.lock"
UA = {
    "User-Agent": "Mozilla/5.0 (research; IGRAS RNF 26-17-00347; contact down.pooh@gmail.com)",
    "Referer": BASE + "/",
}
DELAY = 0.6
#: малые фонды: дёшево и закрывают позиции реестра целиком
SMALL = ["773", "64", "374", "713", "148", "9", "160", "14"]


def fetch_bytes(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=60
        ) as r:
            return r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--funds", default="")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if LOCK.exists():
        sys.exit(f"уже идёт прогон ({LOCK.name})")
    if not TARGETS.exists():
        sys.exit(f"нет {TARGETS} — сначала gaso_ural_targets.py")
    tf = json.loads(TARGETS.read_text(encoding="utf-8"))

    if args.funds:
        want = [x.strip() for x in args.funds.split(",") if x.strip()]
    elif args.all:
        want = [k for k, v in tf.items() if v.get("opisi")]
    else:
        want = [k for k in SMALL if tf.get(k, {}).get("opisi")]

    plan: list[tuple[str, str, int]] = []
    for num in want:
        for o in tf[num].get("opisi") or []:
            plan.append((num, o["opis"], o["scans"]))
    total = sum(n for _, _, n in plan)
    print(f"фондов: {len(want)} | описей: {len(plan)} | сканов к загрузке: {total}")
    for num, op, n in plan:
        print(f"  ф. {num} оп. {op}: {n}")

    LOCK.write_text("gaso_scans", encoding="utf-8")
    got = skipped = dead = 0
    try:
        for num, op, n in plan:
            d = SCANS / f"{num}_{op}"
            d.mkdir(parents=True, exist_ok=True)
            for i in range(1, n + 1):
                name = f"{i:03d}.jpg"
                dst = d / name
                if dst.exists() and dst.stat().st_size > 2000:
                    skipped += 1
                    continue
                url = f"{BASE}/upload/images/lists_auto/{num}_{op}/{name}"
                blob = fetch_bytes(url)
                if not blob or len(blob) < 2000:
                    dead += 1
                    print(f"    ⛔ {num}_{op}/{name}: нет или пусто", flush=True)
                else:
                    dst.write_bytes(blob)
                    got += 1
                time.sleep(DELAY)
            print(f"  ф. {num} оп. {op}: готово (скачано {got}, было {skipped}, "
                  f"провалов {dead})", flush=True)
    finally:
        LOCK.unlink(missing_ok=True)
    print(f"\nИТОГО скачано {got}, уже было {skipped}, не получено {dead}")
    print(f"→ {SCANS}")


if __name__ == "__main__":
    main()
