"""Убрать из JSONL страницы с неразобранным ответом, чтобы движок прогнал их заново.

Движки (`extract_opis_vision.py`, `extract_opis_batch.py`) считают готовой любую страницу,
уже записанную в JSONL, — в том числе ту, где ответ обрезался по лимиту токенов. Этот
скрипт снимает такие страницы, после чего повторный прогон их переделает.

Запуск:
    python -B scripts_gaso/drop_unparsed_pages.py C:\\arch\\output\\gaso_vision_20261013
    python -B scripts_gaso/drop_unparsed_pages.py <папка> --also-empty   # и пустые страницы
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--also-empty", action="store_true",
                    help="снимать и страницы без записей (осторожно: обложки реально пусты)")
    args = ap.parse_args()

    total = 0
    for jsonl in sorted(Path(args.folder).glob("*.jsonl")):
        rows = [json.loads(ln) for ln in jsonl.open(encoding="utf-8") if ln.strip()]
        bad = [r["page"] for r in rows
               if r.get("raw") or (args.also_empty and not r["rows"])]
        if not bad:
            print(f"{jsonl.stem:<16} чисто")
            continue
        keep = [r for r in rows if r["page"] not in set(bad)]
        with jsonl.open("w", encoding="utf-8") as fh:
            for r in keep:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        total += len(bad)
        print(f"{jsonl.stem:<16} снято {len(bad)}: {sorted(bad)}")
    print(f"\nвсего снято страниц: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
