"""Сверка состояния страниц пакета 4.1 по НОМЕРУ страницы, а не по выборке из базы.

Зачем именно так. 22.11 выяснилось, что оба обычных способа узнать «что в каталоге» врут
каждый по-своему:

  * **журнал заливки неполон** — запись `lib.permkrai.ru/node/14035` лежит в базе
    (создана 12:01), а строки в `created_pages.jsonl` на неё нет: прогон убит системой
    между созданием страницы и записью в журнал;
  * **фильтрованный запрос к базе теряет записи** — выборка «создано 22.11 и позже»
    дважды вернула 1 120 страниц, причём четыре страницы, созданные в 11:35, в неё не
    попали, хотя нижняя граница выборки — те же 11:35, и прямой запрос каждой из них
    отвечает `in_trash: false`. Сортировка по времени создания картину не меняет, то есть
    это не race пагинации, а отставание индекса. Та же грабля с другой стороны:
    `feedback_notion-query-caps-at-10000` и правило «не найдено ≠ нет в базе».

Надёжен только `GET /v1/pages/{id}`: он отвечает за доли секунды и показывает фактическое
состояние. Поэтому берём ОБЪЕДИНЕНИЕ всех известных нам номеров страниц (журнал заливки +
обе выборки) и спрашиваем каждую поштучно. Уже снятые в корзину (журнал trashed_pages.jsonl)
не опрашиваем — их состояние мы задали сами и проверили выборочно.

Выход: `output/upload_2026-11-22-series/pages_state.jsonl` — по строке на страницу
(page_id, url, in_trash). Прогон возобновляемый: опрошенные номера читаются из выхода
и пропускаются.

  python scripts/verify_pages_by_id_2026_11_22.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# Папка прогона задаётся аргументом: приёмка по номерам страниц нужна после КАЖДОЙ
# заливки, а не только после набора 4.1 (23.11.2026 — второй прогон, пакет разбора 318).
_RUN = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") \
    else "upload_2026-11-22-series"
W = ROOT / "output" / _RUN
OUT = W / "pages_state.jsonl"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
SOURCES = [
    (W / "review_run" / "created_pages.jsonl", "page_id"),
    (W / "probe_run" / "created_pages.jsonl", "page_id"),
    (W / "live_today.jsonl", "page_id"),
    (W / "live_today_sorted.jsonl", "page_id"),
]
RETRIES = 5


def ids_from(path: Path, key: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for ln in path.open(encoding="utf-8"):
        if not ln.strip():
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        pid = rec.get(key)
        if pid:
            out[pid] = rec.get("url") or out.get(pid, "")
    return out


def get_page(pid: str, token: str) -> dict:
    req = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{pid}",
        headers={"Authorization": f"Bearer {token}", "Notion-Version": "2025-09-03"})
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"_missing": True}
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(2 ** attempt * 0.4)
    raise last  # type: ignore[misc]


def main() -> None:
    fix_stdout()
    known: dict[str, str] = {}
    for path, key in SOURCES:
        known.update(ids_from(path, key))
    trashed = ids_from(W / "decisions" / "trashed_pages.jsonl", "page_id")
    done = ids_from(OUT, "page_id")
    todo = [p for p in known if p not in trashed and p not in done]
    print(f"известных номеров страниц: {len(known)}")
    print(f"  снято в корзину нами ранее: {len(trashed)}")
    print(f"  уже опрошено: {len(done)}")
    print(f"  к опросу: {len(todo)}")

    load_env(ENV_PATH)
    token = env("NOTION_TOKEN")
    live = gone = missing = 0
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        for n, pid in enumerate(todo, 1):
            p = get_page(pid, token)
            if p.get("_missing"):
                missing += 1
                state = {"page_id": pid, "url": known[pid], "in_trash": None,
                         "note": "страница не найдена (404)"}
            else:
                it = bool(p.get("in_trash") or p.get("archived"))
                url = ((p.get("properties") or {}).get("Ссылка на онлайн-архив") or {}).get("url")
                state = {"page_id": pid, "url": url or known[pid], "in_trash": it,
                         "created": p.get("created_time")}
                live += 0 if it else 1
                gone += 1 if it else 0
            f.write(json.dumps(state, ensure_ascii=False) + "\n")
            f.flush()
            if n % 100 == 0:
                print(f"  опрошено {n}/{len(todo)} | живых {live} | в корзине {gone}")
    print(f"\nживых: {live} | в корзине: {gone} | не найдено: {missing}")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
