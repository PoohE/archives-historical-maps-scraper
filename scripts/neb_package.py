"""Пакет НЭБ под внесение: добавить признак происхождения масштаба и границы года.

Сырой файл `harvested_neb.jsonl` — это свидетельство прогона, его не правим.
Пакет собирается отдельно, по образцу `harvest_rgo_clean.py`.

Повод — проверка `preflight_upload.py` 10.11.2026: у 15 записей НЭБ масштаб есть,
а признака происхождения значения нет, и по правилу проекта такую запись вносить
нельзя. Масштаб у НЭБ берётся из контекста карточки (поле `scale_ctx`), то есть
происхождение — «из карточки НЭБ», а не эвристика.

  python neb_package.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from territory_gate import our_gubernii  # noqa: E402

DIR = Path(__file__).resolve().parents[1] / "output" / "work_2026-11-08"
SRC = DIR / "harvested_neb.jsonl"
OUT = DIR / "neb_package.jsonl"
YEAR = re.compile(r"1[5-9]\d{2}|20\d{2}")


def main() -> None:
    fix_stdout()
    if not SRC.exists():
        sys.exit(f"нет {SRC}")
    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8") if ln.strip()]
    ok = [r for r in rows if r.get("status") == "добрано"]

    pack = []
    for r in ok:
        title = (r.get("zagolovok_polnyi") or r.get("zagolovok") or "").strip()
        raw_year = str(r.get("god_text") or "")
        yrs = sorted({int(x) for x in YEAR.findall(raw_year)})
        blob = " ".join(
            str(r.get(k) or "") for k in ("zagolovok_polnyi", "zagolovok", "seriya")
        )
        pack.append({
            "key": r.get("key"),
            "url": r.get("url"),
            "title": title or None,
            "series": r.get("seriya") or None,
            "holder": r.get("hranitel") or None,
            "source_card": r.get("istochnik_kartochki") or None,
            "year_raw": raw_year or None,
            "year_lo": yrs[0] if yrs else None,
            "year_hi": yrs[-1] if yrs else None,
            "year_src": "из карточки НЭБ" if yrs else "нет",
            "scale": r.get("scale"),
            # масштаб у НЭБ читается из контекста карточки, а не выводится по типу
            "scale_src": "из карточки НЭБ" if r.get("scale") else None,
            "scale_ctx": r.get("scale_ctx"),
            "sheets": r.get("polya") or None,
            "gub": our_gubernii(blob),
        })

    with OUT.open("w", encoding="utf-8") as f:
        for p in pack:
            f.write(json.dumps(p, ensure_ascii=False) + chr(10))

    print(f"карточек в пакете: {len(pack)}")
    print(f"  с названием: {sum(1 for p in pack if p['title'])}")
    print(f"  с годом: {sum(1 for p in pack if p['year_lo'])}")
    print(f"  с масштабом (из карточки): {sum(1 for p in pack if p['scale'])}")
    ours = [p for p in pack if p["gub"]]
    print(f"\n  по нашим четырём губерниям: {len(ours)}")
    gc: Counter = Counter()
    for p in ours:
        for g in p["gub"]:
            gc[g] += 1
    for g, c in gc.most_common():
        print(f"    {c:4d}  {g}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
