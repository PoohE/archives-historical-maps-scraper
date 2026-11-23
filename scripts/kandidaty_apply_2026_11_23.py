"""Запись статусов кандидатов в Notion по itog.csv (23.11.2026, команда владельца «записывай»).

Вход: output/kandidaty_proverka_2026-11-23/itog.csv (page_id, решение, причина) — итог
выборочной проверки по слоям и правил владельца (см. kandidaty_reshenie_2026_11_23.py).
  «принять»   → Статус приёмки = принято (одна правка, без чтения страницы);
  «отклонить» → читаем живую страницу, ставим «отклонено», причину ДОПИСЫВАЕМ в «Примечания».
Страница, которая уже не «кандидат» (её поменял кто-то другой), не трогается.
Журнал построчно — output/kandidaty_proverka_2026-11-23/apply_journal.jsonl; повторный запуск
пропускает записанное. Приёмка — опросом по номерам страниц, не по журналу.

  python scripts/kandidaty_apply_2026_11_23.py --limit 20      # проба
  python scripts/kandidaty_apply_2026_11_23.py                 # всё
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "output" / "kandidaty_proverka_2026-11-23"
JOURNAL = DIR / "apply_journal.jsonl"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
MARK = "Проверка кандидатов 23.11.2026 (выборка по слоям, решение владельца): отклонено — "
RPS = 2.7
_lock = threading.Lock()
_last = [0.0]


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(7):
        with _lock:                                  # общий темп на все потоки
            wait = 1 / RPS - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        req = urllib.request.Request(
            f"https://api.notion.com/v1{path}", data=data, method=method,
            headers={"Authorization": f"Bearer {token}", "Notion-Version": "2025-09-03",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"_missing": True}
            if e.code not in (409, 429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            pass
        time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"{method} {path}: исчерпаны попытки")


def plain(prop: dict | None) -> str:
    return "".join(x.get("plain_text", "") for x in (prop or {}).get("rich_text", []))


def work(row: dict, token: str) -> dict:
    pid, d = row["page_id"], row["решение"]
    if d == "принять":
        p = api("PATCH", f"/pages/{pid}", token,
                {"properties": {"Статус приёмки": {"select": {"name": "принято"}}}})
        return {"page_id": pid, "решение": d, "итог": "missing" if p.get("_missing") else "ok"}
    p = api("GET", f"/pages/{pid}", token)
    if p.get("_missing") or p.get("in_trash"):
        return {"page_id": pid, "решение": d, "итог": "missing"}
    props = p["properties"]
    st = ((props.get("Статус приёмки") or {}).get("select") or {}).get("name")
    if st != "кандидат":
        return {"page_id": pid, "решение": d, "итог": f"пропущено: статус уже «{st}»"}
    note = plain(props.get("Примечания")).rstrip()
    add = MARK + row["причина"]
    new = (note + "\n" + add).strip() if note else add
    api("PATCH", f"/pages/{pid}", token, {"properties": {
        "Статус приёмки": {"select": {"name": "отклонено"}},
        "Примечания": {"rich_text": [{"type": "text", "text": {"content": new[:2000]}}]}}})
    return {"page_id": pid, "решение": d, "итог": "ok"}


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    rows = list(csv.DictReader(open(DIR / "itog.csv", encoding="utf-8-sig")))
    done = set()
    if JOURNAL.exists():
        done = {json.loads(x)["page_id"] for x in JOURNAL.open(encoding="utf-8") if x.strip()}
    # отклонения первыми: их меньше, и они важнее для чистоты подсчётов
    todo = sorted((r for r in rows if r["page_id"] not in done), key=lambda r: r["решение"] != "отклонить")
    if args.limit:
        todo = todo[: args.limit // 2] + [r for r in todo if r["решение"] == "принять"][: args.limit - args.limit // 2]
    print(f"всего {len(rows)} | записано ранее {len(done)} | к записи {len(todo)}", flush=True)
    load_env(ENV_PATH)
    token = env("NOTION_TOKEN")
    n = err = 0
    with JOURNAL.open("a", encoding="utf-8", newline="\n") as f, ThreadPoolExecutor(3) as ex:
        futs = {ex.submit(work, r, token): r for r in todo}
        for fu in futs:
            r = futs[fu]
            try:
                res = fu.result()
            except Exception as e:  # noqa: BLE001
                err += 1
                print(f"  ОШИБКА {r['page_id']}: {type(e).__name__}: {e}", flush=True)
                continue
            res["date"] = "2026-11-23"
            with _lock:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                f.flush()
            n += 1
            if n % 500 == 0:
                print(f"  {n}/{len(todo)} | ошибок {err}", flush=True)
    print(f"готово: записано {n}, ошибок {err}; журнал {JOURNAL}", flush=True)


if __name__ == "__main__":
    main()
