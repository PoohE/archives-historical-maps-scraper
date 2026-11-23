# -*- coding: utf-8 -*-
"""РГИА: фондовый прогон по статистическим и ведомственным фондам раздела Г.

Фонды выявлены при разборе статистико-экономических серий 14–15.11.2026 и записаны в
`РЕЕСТР_отложенного_добора.md` (строки А33–А39). Ни один из них в прогоны проекта не входил;
главный — ф. 1290, узел почти всех статистических серий ЦСК.

Механика та же, что в `rgia_funds_379_387_515.py` (обкатан 14.11: 20 запросов, 4 324 дела
выдачи, 270 отобрано по шифру): общий полнотекстовый поиск `fgurgia.ru` тематическими
словами фондов × четыре губернии, затем ОТБОР ПО ШИФРУ — оставляем только дела нужных
фондов. Отбор точный, а не по догадке.

  python rgia_stat_funds.py --probe   # 3 запроса, проверить формат
  python rgia_stat_funds.py           # полный прогон (возобновляемый)
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
LOG = log("rgia_stat_funds")
from searcher_rgia import _make_session, search_simple  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "rgia_stat_funds"
GUB = ["Калужской", "Смоленской", "Ярославской", "Пермской"]

# Фонд → лексика самого фонда (картографические слова бесполезны: эти фонды текстовые)
FUNDS = {
    "1290": ["статистического комитета", "статистические сведения", "волостей и селений",
             "о народонаселении"],
    "573": ["окладных сборов", "о продаже земель", "оценки недвижимых имуществ"],
    "593": ["дворянского земельного банка", "залог имения"],
    "733": ["народного просвещения", "о начальных училищах"],
    "744": ["учебных заведений ведомости"],
    "20": ["торговли и мануфактур", "о фабриках и заводах"],
    "23": ["торговли и промышленности", "фабричной инспекции"],
    "37": ["горного департамента", "о горных заводах"],
    "44": ["горного учёного комитета", "горнозаводской промышленности"],
    "350": ["планы и чертежи путей сообщения", "о железной дороге план"],
}
WANT = re.compile(r"\bФ\.?\s*0*(" + "|".join(FUNDS) + r")\b", re.I)


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    queries = [f"{term} {g}" for terms in FUNDS.values() for term in terms for g in GUB]
    if args.probe:
        queries = queries[:3]
    LOG.info(f"план: {len(queries)} запросов по {len(FUNDS)} фондам")

    seen_path = OUT / "queries_done.txt"
    seen = set(seen_path.read_text(encoding="utf-8").splitlines()) if seen_path.exists() else set()
    total = kept = 0
    with ((OUT / "hits.jsonl").open("a", encoding="utf-8") as hf,
          (OUT / "fund_hits.jsonl").open("a", encoding="utf-8") as kf,
          seen_path.open("a", encoding="utf-8") as sf):
        session = _make_session()
        for i, q in enumerate(queries, 1):
            if q in seen:
                continue
            n = k = 0
            try:
                for rec in search_simple(session, q):
                    d = asdict(rec)
                    d.pop("raw_detail", None)
                    d["запрос"] = q
                    hf.write(json.dumps(d, ensure_ascii=False) + "\n")
                    n += 1
                    if WANT.search(d.get("fund_code") or ""):
                        kf.write(json.dumps(d, ensure_ascii=False) + "\n")
                        k += 1
            except Exception as e:  # noqa: BLE001 — прогон не ронять на одном запросе
                LOG.info(f"[{i}/{len(queries)}] {q[:48]}: ошибка {type(e).__name__}")
                continue
            hf.flush()
            kf.flush()
            sf.write(q + "\n")
            sf.flush()
            total += n
            kept += k
            LOG.info(f"[{i}/{len(queries)}] {q[:46]} → дел {n}, по нашим фондам {k}")
            time.sleep(2.0)

    LOG.info(f"всего дел выдачи: {total}; отобрано по шифру: {kept}")


if __name__ == "__main__":
    main()
