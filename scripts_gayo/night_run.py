"""Ночной фоновый добор ГАЯО: малыми порциями с длинными паузами.

Замер 14.10: после прохождения проверки портал отдаёт ~80 страниц подряд, затем короткий
хвост и снова reCAPTCHA. Плотные заходы упираются в заслон, поэтому ночью идём редко и
понемногу — по 40 запросов раз в полчаса, чтобы окно успевало восстановиться само и
участие человека почти не требовалось.

Каждый цикл: одна пробная страница. Свободно — запускаем порцию; стоит проверка —
ничего не делаем до следующего цикла (одна проба в полчаса, а не долбёжка).

Запуск:
    python -u -B scripts_gayo/night_run.py --batch 40 --every 30 --cycles 24
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATE = ROOT / "output" / "gayo" / "dela_state.json"
PROBE = "https://af.yar-archives.ru/archive5/funds"  # самый маленький архив


def progress() -> tuple[int, int]:
    if not STATE.exists():
        return 0, 0
    st = json.loads(STATE.read_text(encoding="utf-8"))
    return (sum(1 for v in st.values() if v.get("done")),
            sum(v.get("rows", 0) for v in st.values()))


def session_free() -> bool:
    code = (
        "import sys; sys.path.insert(0, r'%s'); import gayo_harvest as G; "
        "h = G.fetch('%s', tries=1); "
        "print('FREE' if h and G.fund_rows(h, 5) else 'BLOCKED'); "
        "G.SESSION and G.SESSION.close()" % (HERE, PROBE)
    )
    try:
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:  # noqa: BLE001
        # зависшая проба — это не авария цикла: считаем окно закрытым и ждём следующего.
        # Без этого TimeoutExpired убивал весь ночной прогон (поймано 16.10, 22:02).
        print(f"    проба не ответила ({type(e).__name__}), считаю окно закрытым", flush=True)
        return False
    return "FREE" in (r.stdout or "")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=40)
    ap.add_argument("--every", type=int, default=30, help="минут между циклами")
    ap.add_argument("--cycles", type=int, default=24)
    ap.add_argument("--delay", type=float, default=8.0)
    ap.add_argument("--opisi", default=str(ROOT / "output" / "gayo" / "opisi_ordered.jsonl"))
    args = ap.parse_args()

    total_opisi = sum(1 for ln in Path(args.opisi).read_text(encoding="utf-8").splitlines()
                      if ln.strip())
    for c in range(1, args.cycles + 1):
        stamp = time.strftime("%H:%M")
        if not session_free():
            done, rows = progress()
            print(f"[{stamp}] цикл {c}/{args.cycles}: стоит проверка, пропускаю "
                  f"(собрано {rows} дел, описей {done}/{total_opisi})", flush=True)
        else:
            try:
                r = subprocess.run(
                    [sys.executable, "-u", "-B", str(HERE / "gayo_harvest.py"),
                     "--dela", args.opisi, "--delay", str(args.delay),
                     "--max-requests", str(args.batch)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=args.batch * max(args.delay, 1) * 4 + 600)
            except Exception as e:  # noqa: BLE001
                # заход завис — пишем и идём к следующему циклу; прогресс уже на диске
                print(f"[{stamp}] цикл {c}/{args.cycles}: заход прерван "
                      f"({type(e).__name__})", flush=True)
                if c < args.cycles:
                    time.sleep(args.every * 60)
                continue
            tail = [x for x in (r.stdout or "").splitlines()
                    if "запросов за заход" in x or "дел собрано" in x or "КАПЧА" in x]
            done, rows = progress()
            print(f"[{stamp}] цикл {c}/{args.cycles}: {' | '.join(tail[-3:])} "
                  f"→ описей {done}/{total_opisi}, дел {rows}", flush=True)
            if done >= total_opisi:
                print("все описи дочитаны — останавливаюсь", flush=True)
                return 0
        if c < args.cycles:
            time.sleep(args.every * 60)
    done, rows = progress()
    print(f"\nитог ночи: описей {done}/{total_opisi}, дел {rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
