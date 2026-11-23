# -*- coding: utf-8 -*-
"""РГИА, фонды 379, 387 и 515 — прицельный прогон (позиции А1–А3 реестра добора).

Зачем отдельный прогон. Полный проход по РГИА 02.10.2026 (24 запроса, 4 губернии × 6 слов)
искал картографическими словами и эти три фонда не достал: у них своя лексика —
государственные имущества, лесной департамент, удельные имения и лесные дачи.
Фонды выявлены 09.11.2026 при лесном прогоне и с тех пор не прогонялись (хост доступен).

Что делаем: общий полнотекстовый поиск `fgurgia.ru` тематическими словами этих фондов
× четыре губернии, затем **отбор по шифру** — оставляем только дела Ф. 379, 387 и 515.
Шифр в выдаче есть (`fund_code`), поэтому отбор точный, а не по догадке.

Автоматически в каталог ничего не идёт: выход — пакет на разбор приёмщиком.

  python rgia_funds_379_387_515.py --probe    # проба: 3 запроса, показать что приходит
  python rgia_funds_379_387_515.py            # полный прогон
"""

import argparse
import json
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "modules" / "scrapers"))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout, log  # noqa: E402

# ⚠️ `common.log` — ФАБРИКА логгеров, а не print: вызов log("текст") создавал
# логгер с таким именем и не печатал ничего. Из-за этого прогон добора полей
# 15.11.2026 отработал 71 минуту с ПУСТЫМ логом — следить было не за чем.
LOG = log("rgia_funds_379_387_515")
from searcher_rgia import _make_session, search_simple  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "rgia_funds_379_387_515"
GUB = ["Калужской", "Смоленской", "Ярославской", "Пермской"]
# Лексика самих фондов, а не картографическая — именно её не хватало прогону 02.10.
TERMS = [
    "государственных имуществ",
    "лесного департамента",
    "удельных имений",
    "лесных дач",
    "описные книги",
]
WANT = re.compile(r"\bФ\.?\s*0*(379|387|515)\b", re.I)


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="3 запроса для проверки формата")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    queries = [f"{t} {g}" for t in TERMS for g in GUB]
    if args.probe:
        queries = queries[:3]

    seen_path = OUT / "queries_done.txt"
    seen = set(seen_path.read_text(encoding="utf-8").splitlines()) if seen_path.exists() else set()
    hits_path = OUT / "hits.jsonl"
    kept_path = OUT / "fund_379_387_515.jsonl"

    total = kept = 0
    with (hits_path.open("a", encoding="utf-8") as hf,
          kept_path.open("a", encoding="utf-8") as kf,
          seen_path.open("a", encoding="utf-8") as sf):
        session = _make_session()
        for i, q in enumerate(queries, 1):
            if q in seen:
                continue
            n = k = 0
            try:
                for rec in search_simple(session, q):
                    d = asdict(rec)
                    d.pop("raw_detail", None)          # страховочный JSON тут не нужен
                    d["запрос"] = q
                    hf.write(json.dumps(d, ensure_ascii=False) + "\n")
                    n += 1
                    if WANT.search(d.get("fund_code") or ""):
                        kf.write(json.dumps(d, ensure_ascii=False) + "\n")
                        k += 1
            except Exception as e:                      # noqa: BLE001 — прогон не ронять
                LOG.info(f"[{i}/{len(queries)}] {q}: ошибка {type(e).__name__}")
                continue
            hf.flush()
            kf.flush()
            sf.write(q + "\n")
            sf.flush()
            total += n
            kept += k
            LOG.info(f"[{i}/{len(queries)}] {q[:48]} → дел {n}, из них Ф.379/387/515: {k}")
            time.sleep(2.0)

    LOG.info(f"всего дел в выдаче: {total}; отобрано по шифру: {kept}")
    LOG.info(f"выход: {kept_path}")


if __name__ == "__main__":
    main()
