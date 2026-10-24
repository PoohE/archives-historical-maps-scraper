"""Добор хвоста ГАЯО: пропущенные страницы описи и проверка описи с нулём дел.

Ночной прогон упёрся на двух описях из 157 и крутился вхолостую:
  * оп. 10000290076 (ф.455) — страницы 24–32 пропущены при сбоях, записаны в `missed`;
    основное чтение идёт с первой непрочитанной (72-й), к пропущенным не возвращается;
  * оп. 10000081447 (ф.1441) — портал отдал 0 дел, а при нуле `done` выставить нельзя.

Скрипт читает ровно пропущенные страницы, дописывает дела в тот же dela.jsonl и
закрывает описи в состоянии. Нулевую опись перепроверяет и, если дел действительно
нет, помечает `done` с пометкой `empty`.

Запуск:
    python -u -B scripts_gayo/fix_tail.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import gayo_harvest as G  # noqa: E402

OUT = ROOT / "output" / "gayo" / "dela.jsonl"
STATE = ROOT / "output" / "gayo" / "dela_state.json"
OPISI = ROOT / "output" / "gayo" / "opisi_ordered.jsonl"


def row_payload(op: dict, key: str, cells: list[str]) -> dict:
    href = G.HREF.search(cells[1])
    cam = G.CAM.search(cells[4]) if len(cells) > 4 else None
    return {
        "arc": op["arc"], "fund_num": op["fund_num"], "fund_title": op["title"],
        "inv_id": key, "inv_cells": op.get("inv_cells", []),
        "unit_num": G.clean(cells[0]), "title": G.clean(cells[1]),
        "dates": G.clean(cells[2]),
        "sheets": G.clean(cells[3]) if len(cells) > 3 else "",
        "unit_id": href.group(1).rsplit("/", 1)[-1] if href else "",
        "digitized": G.clean(cam.group(1)) if cam else "",
    }


def once() -> int:
    """Один заход. Возвращает число описей, оставшихся незакрытыми."""
    state = json.loads(STATE.read_text(encoding="utf-8"))
    opisi = {str(o["inv_id"]): o for o in
             (json.loads(x) for x in OPISI.read_text(encoding="utf-8").splitlines() if x.strip())}

    todo = [(k, v) for k, v in state.items() if not v.get("done")]
    print(f"описей в работе: {len(todo)}")

    with OUT.open("a", encoding="utf-8") as f:
        for key, st in todo:
            op = opisi.get(key)
            if not op:
                print(f"оп.{key}: нет в очереди описей, пропускаю")
                continue
            base = f"https://{G.HOST}/archive{op['arc']}/inventory/{key}"
            missed = sorted(set(st.get("missed") or []))

            if not missed and not st.get("total"):
                # опись с нулём дел: перепроверяем и закрываем, если и правда пусто
                html = G.fetch(base)
                if html is None:
                    print(f"оп.{key}: страница не получена (капча?) — оставляю как есть")
                    continue
                tot = G.total_of(html)
                rows = [c for c in G.grid_rows(html) if len(c) >= 3]
                if tot == 0 and not rows:
                    st["done"], st["empty"] = True, True
                    print(f"оп.{key} (ф.{op['fund_num']}): дел на портале нет — закрыта как пустая")
                else:
                    st["total"] = tot
                    print(f"оп.{key}: портал отдал {tot} дел — оставляю обычному прогону")
                continue

            got = 0
            still: list[int] = []
            taken: list[int] = []
            for p in missed:
                html = G.fetch(f"{base}?page={p}")
                rows = [c for c in G.grid_rows(html)] if html else []
                # страница-капча приходит как обычный html (≈28 КБ) с пустой таблицей:
                # пустой грид на странице внутри описи = НЕ взято, иначе опись закрывается
                # с недобором (поймано 18.10 — оп.290076 закрылась, потеряв 180 дел)
                if html is None or not rows:
                    still.append(p)
                    print(f"  оп.{key} стр.{p}: не получена"
                          f"{' (пустая таблица — похоже на капчу)' if html else ''}")
                    if G.CAPTCHA_HIT or html:
                        break
                    continue
                for cells in rows:
                    if len(cells) < 3:
                        continue
                    f.write(json.dumps(row_payload(op, key, cells), ensure_ascii=False) + "\n")
                    got += 1
                f.flush()
                taken.append(p)
            # всё, что не прочитано в этот заход (включая оборванное на break), остаётся в missed
            still = sorted(set(missed) - set(taken))
            st["rows"] = st.get("rows", 0) + got
            st["missed"] = still
            if not still:
                st["done"] = True
            pages_total = max(1, -(-int(st.get("total") or 0) // G.PER_PAGE))
            print(f"оп.{key} (ф.{op['fund_num']}): добрано {got} дел, "
                  f"не взято страниц {len(still)}, всего строк {st['rows']}/{st.get('total')} "
                  f"({pages_total} стр.)")

    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    done = sum(1 for v in state.values() if v.get("done"))
    rows = sum(v.get("rows", 0) for v in state.values())
    print(f"итог: описей {done}/{len(state)}, дел {rows}", flush=True)
    G.SESSION and G.SESSION.close()
    G.SESSION = None
    return len(state) - done


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--every", type=int, default=10, help="минут между заходами")
    args = ap.parse_args()

    for c in range(1, args.cycles + 1):
        print(f"\n[{time.strftime('%H:%M')}] заход {c}/{args.cycles}", flush=True)
        try:
            left = once()
        except Exception as e:  # noqa: BLE001
            print(f"  заход прерван ({type(e).__name__}: {e})", flush=True)
            left = -1
        if left == 0:
            print("хвост дочитан — останавливаюсь", flush=True)
            return 0
        if c < args.cycles:
            time.sleep(args.every * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
