"""Пересмотр записей, снятых сломанным движком (дефекты 19-20.11.2026).

Берёт список url с прежним «плохим» статусом (не ответил / хост недоступен /
заслон / карточка пуста) и перезапрашивает их уже исправленным движком:
404 больше не выключает площадку, одна «стена» не хоронит остальные карточки,
reCAPTCHA в разметке не считается заслоном, у РГО свой парсер DSpace.

Запуск: python scripts/dobor_pereprover.py [--limit N]
Вход:   output/pereprover_kandidaty_2026-11-21.jsonl
Выход:  output/dobor_pereprover_2026-11-21.jsonl (возобновляемый)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
IN = ROOT / "output" / "pereprover_kandidaty_2026-11-21.jsonl"
OUT = ROOT / "output" / "dobor_pereprover_2026-11-21.jsonl"


def engine():
    spec = importlib.util.spec_from_file_location("h", ROOT / "scripts" / "harvest_cards.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    m = engine()
    todo = [json.loads(ln) for ln in IN.open(encoding="utf-8") if ln.strip()]
    done = set()
    if OUT.exists():
        for ln in OUT.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["url"])
            except Exception:
                continue
    todo = [r for r in todo if r["url"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"к пересмотру {len(todo)} (уже пройдено {len(done)})", flush=True)

    got = empty = dead = 0
    with OUT.open("a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            url = r["url"]
            rec = {"url": url, "прежний_статус": r.get("прежний_статус", "")}
            src = m.route({"key": f"x:{url}", "url": url})
            if not src:
                rec["статус"] = m.blocked_reason(url) or "нет маршрута"
                dead += 1
            else:
                body = m.fetch(src)
                if not body:
                    rec["статус"] = "не ответил"
                    dead += 1
                elif m.is_wall(body):
                    rec["статус"] = "заслон"
                    dead += 1
                else:
                    rec.update(m.parse_for(src, body))
                    rec["istochnik_kartochki"] = src
                    if rec.get("zagolovok_polnyi"):
                        rec["статус"] = "добрано"
                        got += 1
                    else:
                        rec["статус"] = "карточка пуста"
                        empty += 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} — добрано {got}, пусто {empty}, нет {dead}", flush=True)
    print(f"\nитог: добрано {got}, карточка пуста {empty}, не вышло {dead} → {OUT}")


if __name__ == "__main__":
    main()
