"""Выборочная сверка прогона-теггера: случайная выборка записей из журнала.

Сплошная сверка 76 400 записей съедает память и время. Для приёмки достаточно случайной
выборки: при 300 проверенных записях и нуле расхождений доля ошибок с вероятностью 95 %
не превышает 1 %.

  python verify_tag_sample.py --run gayo455_full --n 300
"""

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261107)
    args = ap.parse_args()

    done = ROOT / "output" / f"mezh_tag_{args.run}" / "done.jsonl"
    # читаем построчно, не держим файл в памяти: нужны page_id и намерение прогона.
    # rel_after == [] и kind «…не межевание» означают СОЗНАТЕЛЬНЫЙ отказ от привязки —
    # это не сбой, и сверка обязана их различать.
    ids: list[str] = []
    intent: dict[str, str] = {}
    with done.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            pid = rec.get("page_id") or rec.get("id")
            if not pid:
                continue
            ids.append(pid)
            intent[pid] = "привязка" if rec.get("rel_after") else "без привязки намеренно"
    print(f"записей в журнале: {len(ids)}")
    print(f"  из них с намеренной привязкой: "
          f"{sum(1 for v in intent.values() if v == 'привязка')}")
    print(f"  намеренно без привязки: "
          f"{sum(1 for v in intent.values() if v != 'привязка')}")

    random.seed(args.seed)
    sample = random.sample(ids, min(args.n, len(ids)))
    print(f"проверяем выборку: {len(sample)}\n")

    client = Client(auth=env("NOTION_TOKEN"))
    stats: Counter = Counter()
    bad: list[str] = []
    for i, pid in enumerate(sample, 1):
        try:
            props = retry(lambda pid=pid: client.pages.retrieve(pid))["properties"]
        except Exception as exc:  # noqa: BLE001 - фиксируем и идём дальше
            stats["ошибка чтения"] += 1
            bad.append(f"{pid}: {exc}")
            continue
        rel = props.get("Серия / массив", {}).get("relation", [])
        want = intent.get(pid) == "привязка"
        if rel and want:
            stats["серия проставлена, как и планировалось"] += 1
        elif not rel and not want:
            stats["серии нет — и прогон её не ставил (верно)"] += 1
        elif rel and not want:
            stats["серия есть, хотя прогон её не ставил (была раньше)"] += 1
        else:
            stats["РАСХОЖДЕНИЕ: прогон ставил, в базе нет"] += 1
            bad.append(pid)
        if i % 50 == 0:
            print(f"  {i}/{len(sample)}")
        time.sleep(0.2)

    print("\nитог выборки:")
    for k, v in stats.most_common():
        print(f"  {v:>5}  {k}")
    if bad:
        print(f"\nпроблемных: {len(bad)} (первые 10)")
        for b in bad[:10]:
            print("   ", b)
    else:
        print("\nрасхождений нет")


if __name__ == "__main__":
    main()
