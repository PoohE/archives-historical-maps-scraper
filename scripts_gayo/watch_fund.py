"""Ждать, пока не будут дочитаны все описи указанного фонда, и выйти с отчётом.

Читает только локальные файлы состояния — к порталу не обращается, на квоту не влияет.
Выходит, когда фонд закрыт, когда прогон умер или по истечении срока.

Запуск: python -u -B scripts_gayo/watch_fund.py 455
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "output" / "gayo" / "dela_state.json"
OPISI = ROOT / "output" / "gayo" / "opisi_ordered.jsonl"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    fund = sys.argv[1] if len(sys.argv) > 1 else "455"
    hours = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

    ops = [json.loads(ln) for ln in OPISI.read_text(encoding="utf-8").splitlines() if ln.strip()]
    mine = [o["inv_id"] for o in ops if str(o["fund_num"]) == fund]
    if not mine:
        print(f"у фонда {fund} описей не найдено")
        return 1

    deadline = time.time() + hours * 3600
    while time.time() < deadline:
        st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        done = [i for i in mine if st.get(i, {}).get("done")]
        rows = sum(st.get(i, {}).get("rows", 0) for i in mine)
        if len(done) >= len(mine):
            print(f"Ф.{fund} ЗАКРЫТ: {len(mine)} описей, {rows} дел")
            return 0
        time.sleep(300)
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    done = [i for i in mine if st.get(i, {}).get("done")]
    rows = sum(st.get(i, {}).get("rows", 0) for i in mine)
    print(f"срок наблюдения вышел: Ф.{fund} — {len(done)}/{len(mine)} описей, {rows} дел")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
