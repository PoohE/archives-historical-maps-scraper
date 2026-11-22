"""Снятие 484 дублирующих страниц пакета 4.1 в корзину Notion (решение владельца 22.11.2026).

Откуда дубли. Мост заливки на одной записи делал запрос создания дважды: первый ответ не
доходил по таймауту, мост повторял, а страница к тому времени уже была создана. В журнале
`created_pages.jsonl` это видно как две строки с РАЗНЫМИ page_id и одной ссылкой, идущие
подряд (у 474 пар из 484 разрыв — одна строка). Ещё 10 пар — наложение двух прогонов.

Почему корзина, а не «Статус приёмки = отклонено», как в dedupe_true_duplicates.py: там
дубль это две РАЗНЫЕ строки каталога на одно дело, и решение о них надо сохранить видимым.
Здесь — побайтово одинаковые копии, созданные сбоем транспорта; в каталоге документировать
нечего. Решение всё равно воспроизводимо: журнал пар лежит в
decisions/dubli_k_udaleniyu.csv, факт снятия — в decisions/trashed_pages.jsonl.

Оставляем ту страницу пары, что создана первой (меньший автономер каталога). Сверка одной
пары по страницам в Notion показала полное совпадение полей и всех трёх связей (архив,
территория, современный регион), то есть выбор внутри пары безразличен.

Возобновляемость: уже снятые page_id читаются из trashed_pages.jsonl и пропускаются —
прерванный прогон продолжается тем же вызовом, ничего не снимается дважды.

  python scripts/trash_dubli_2026_11_22.py --dry-run
  python scripts/trash_dubli_2026_11_22.py --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env  # noqa: E402

from notion_client import Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEC = ROOT / "output" / "upload_2026-11-22-series" / "decisions"
PAIRS = DEC / "dubli_k_udaleniyu.csv"
JOURNAL = DEC / "trashed_pages.jsonl"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
RETRIES = 6
COL_DROP = "УДАЛИТЬ page_id"
COL_KEEP = "оставляем page_id"


def call_retry(func, **kwargs):
    """Транспортные сбои httpx/VPN — не отказ операции: повторяем с нарастающей паузой."""
    last = None
    for attempt in range(RETRIES):
        try:
            return func(**kwargs)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 ** attempt * 0.5)
    raise last


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = list(csv.DictReader(PAIRS.open(encoding="utf-8-sig")))
    pairs = [(r[COL_DROP], r[COL_KEEP], r["Ссылка на онлайн-архив"]) for r in rows]

    done: set[str] = set()
    if JOURNAL.exists():
        for ln in JOURNAL.open(encoding="utf-8"):
            if ln.strip():
                done.add(json.loads(ln)["page_id"])
    todo = [p for p in pairs if p[0] not in done]

    print(f"пар в списке: {len(pairs)} | уже снято: {len(done)} | к снятию: {len(todo)}")
    # контроль: снимаемый id не должен совпасть с оставляемым ни в одной паре
    collide = [p for p in pairs if p[0] == p[1]]
    keep_ids = {p[1] for p in pairs}
    overlap = {p[0] for p in pairs} & keep_ids
    print(f"совпадение снимаемого с оставляемым внутри пары: {len(collide)} (должно быть 0)")
    print(f"снимаемый id встречается как оставляемый в другой паре: {len(overlap)} (должно быть 0)")
    if collide or overlap:
        sys.exit("ОСТАНОВ: список дублей противоречив, ничего не снято")

    if args.dry_run:
        for drop, keep, url in todo[:5]:
            print(f"  снял бы {drop}\n     остаётся {keep}\n     {url}")
        print(f"\n(проба: ничего не снято; всего сняло бы {len(todo)})")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))
    ok = err = 0
    with JOURNAL.open("a", encoding="utf-8", newline="\n") as jf:
        for n, (drop, keep, url) in enumerate(todo, 1):
            try:
                call_retry(client.pages.update, page_id=drop, archived=True)
            except Exception as exc:  # noqa: BLE001
                err += 1
                print(f"  [{n}/{len(todo)}] ОШИБКА {drop}: {type(exc).__name__}: {exc}")
                continue
            ok += 1
            jf.write(json.dumps({"page_id": drop, "kept": keep, "url": url,
                                 "date": "2026-11-22"}, ensure_ascii=False) + "\n")
            jf.flush()
            if n % 50 == 0:
                print(f"  снято {n}/{len(todo)}")
    print(f"\nснято в корзину: {ok} | ошибок: {err}")
    print(f"журнал: {JOURNAL}")


if __name__ == "__main__":
    main()
