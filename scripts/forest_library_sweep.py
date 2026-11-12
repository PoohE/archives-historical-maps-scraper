"""Прогон по ЛЕСНОЙ серии: четыре губернии × лесные термины × каталоги и архивы.

Переиспользует движок `series_library_sweep` (Yandex Search API, вежливый обход,
возобновление по списку выполненных запросов) — новый здесь только набор запросов
и список сайтов: к библиотечным каталогам добавлены архивные порталы.

Зачем отдельный набор. Прежние прогоны искали серии по НАЗВАНИЮ («Специальная карта
западной части…»), а у лесоустройства названия серии нет вовсе: единица — комплект
по даче. Поэтому ищем по связке «лесной термин + наша губерния».

  python forest_library_sweep.py plan
  python forest_library_sweep.py run            # возобновляемый
  python forest_library_sweep.py run --limit 20
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from series_library_sweep import RECORD_RE, run_query  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "forest_sweep"

GUB = ["Калужской", "Смоленской", "Ярославской", "Пермской"]

# Лесные термины — как они звучат в заголовках дел и карточках изданий.
PHRASES = [
    "лесоустройство {g} губернии",
    "планы лесных дач {g} губернии",
    "план лесонасаждений {g} губернии",
    "лесная дача {g} губернии план",
    "лесничество {g} губернии план карта",
    "карта лесов {g} губернии",
    "таксационное описание лесов {g} губернии",
    "казенные леса {g} губернии отчетная карта",
    "удельные леса {g} губернии план",
    "лесоустроительный планшет {g} губернии",
    "лесхоз {g} области план лесонасаждений",
]

SITES = [
    # библиотеки
    "search.rsl.ru",
    "nlr.ru",
    "primo.nlr.ru",
    "rusneb.ru",
    "prlib.ru",
    "elib.rgo.ru",
    "kp.rusneb.ru",
    "elib.shpl.ru",
    "catalog.shpl.ru",
    # архивные порталы
    "fgurgia.ru",
    "online.archives.ru",
    "goskatalog.ru",
    "rgada.info",
    "rgae.ru",
]

EXTRA_RECORD_RE = dict(RECORD_RE)
EXTRA_RECORD_RE.update(
    {
        "fgurgia.ru": re.compile(r"fgurgia\.ru/object/(\d+)"),
        "online.archives.ru": re.compile(r"online\.archives\.ru/\S*?(\d{10,})"),
        "goskatalog.ru": re.compile(r"goskatalog\.ru/portal/#/collections\?id=(\d+)"),
    }
)


def queries() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for g in GUB:
        for ph in PHRASES:
            text = ph.format(g=g)
            for site in SITES:
                out.append((f"лес — {g}", f"site:{site} {text}"))
    return out


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="plan", choices=["plan", "run"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    qs = queries()
    if args.mode == "plan":
        print(f"запросов: {len(qs)} = {len(GUB)} губерний × {len(PHRASES)} фраз × {len(SITES)} сайтов")
        for s, q in qs[:12]:
            print(f"  [{s}] {q}")
        print(f"  … ещё {len(qs) - 12}")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    hits_path = OUT / "hits.jsonl"
    seen_path = OUT / "queries_done.txt"
    seen = set(seen_path.read_text(encoding="utf-8").splitlines()) if seen_path.exists() else set()
    todo = [(s, q) for s, q in qs if q not in seen]
    if args.limit:
        todo = todo[: args.limit]
    print(f"к выполнению: {len(todo)} из {len(qs)} (уже сделано {len(seen)})")

    total = 0
    with hits_path.open("a", encoding="utf-8") as hf, seen_path.open("a", encoding="utf-8") as sf:
        for i, (group, q) in enumerate(todo, 1):
            res = run_query(q, results=30)
            for r in res:
                url = r.get("url") or ""
                host = next((h for h in EXTRA_RECORD_RE if h in url), "")
                rec_id = ""
                if host:
                    m = EXTRA_RECORD_RE[host].search(url)
                    rec_id = m.group(1) if m else ""
                hf.write(
                    json.dumps(
                        {
                            "group": group,
                            "query": q,
                            "host": host or url.split("/")[2] if "//" in url else "",
                            "rec_id": rec_id,
                            "title": r.get("title") or "",
                            "url": url,
                            "snippet": (r.get("snippet") or "")[:300],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            hf.flush()
            sf.write(q + "\n")
            sf.flush()
            total += len(res)
            if i % 10 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} запросов, находок всего {total}", flush=True)
    print(f"готово: {total} находок → {hits_path}")


if __name__ == "__main__":
    main()
