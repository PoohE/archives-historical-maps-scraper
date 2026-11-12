"""Слияние улова прогона со старым пакетом + отсев того, что уже в каталоге.

Шаг плана: единый поток на добор вместо двух пересекающихся списков.

Ключ дедупликации — держатель + идентификатор карточки, причём идентификатор НЭБ
000199_000009_NNNNNNNNN сводится к записи РГБ 01NNNNNNNNN (это один документ,
см. память reference_neb-id-maps-to-rgb-record). Без этого одна карточка попадёт
в работу дважды под разными хостами.

  python build_work_list.py index    # один раз: индекс ключей, уже лежащих в каталоге
  python build_work_list.py build    # собрать work.jsonl
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HITS = ROOT / "output" / "series_library_sweep" / "hits.jsonl"
PKG = ROOT / "output" / "series_package_20261107"
OUTDIR = ROOT / "output" / "work_2026-11-08"
INDEX = OUTDIR / "catalog_keys.txt"
WORK = OUTDIR / "work.jsonl"

BASELINE = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\текущий_baseline.jsonl"
)

PATTERNS = (
    ("РГБ", re.compile(r"000199_000009_(\d{9})")),            # НЭБ-идентификатор РГБ
    ("РГБ", re.compile(r"search\.rsl\.ru/ru/record/0?1?(\d{9})")),
    ("ПБ", re.compile(r"prlib\.ru/item/(\d+)")),
    ("РГО", re.compile(r"elib\.rgo\.ru/handle/123456789/(\d+)")),
    ("НЭБ", re.compile(r"rusneb\.ru/catalog/([0-9A-Za-z_]+)")),
    ("КП", re.compile(r"kp\.rusneb\.ru/[^\"'\s]*?(\d{5,})")),
)


def key_of(url: str) -> str | None:
    if not url:
        return None
    for holder, pat in PATTERNS:
        m = pat.search(url)
        if m:
            return f"{holder}:{m.group(1)}"
    return None


def build_index() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    keys: set[str] = set()
    n = 0
    with BASELINE.open(encoding="utf-8") as f:
        for line in f:
            n += 1
            for m in re.finditer(r"https?://[^\"'\s\\]+", line):
                k = key_of(m.group(0))
                if k:
                    keys.add(k)
    INDEX.write_text("\n".join(sorted(keys)), encoding="utf-8")
    print(f"просмотрено записей каталога: {n}")
    print(f"ключей карточек, уже имеющихся в каталоге: {len(keys)}")
    print(f"файл: {INDEX}")


def build_work() -> None:
    have = set(INDEX.read_text(encoding="utf-8").splitlines()) if INDEX.exists() else set()
    print(f"ключей в каталоге: {len(have)}")

    work: dict[str, dict] = {}
    src: Counter = Counter()

    # 1. улов прогона
    for ln in HITS.open(encoding="utf-8"):
        r = json.loads(ln)
        if not r.get("каталожный"):
            continue
        k = key_of(r["url"])
        if not k:
            continue
        if k in work:
            s = work[k]["seriya"]
            if r["серия"] not in s:
                work[k]["seriya"] = f"{s}; {r['серия']}"
            continue
        work[k] = {"key": k, "url": r["url"].rstrip("/"), "seriya": r["серия"],
                   "zagolovok": r.get("title", ""), "istochnik": "прогон 08.11"}
        src["прогон"] += 1

    # 2. старый пакет (готовые и требующие человека; отложенные серии не берём)
    for name in ("package_ready.jsonl", "package_still_human.jsonl"):
        p = PKG / name
        if not p.exists():
            continue
        for ln in p.open(encoding="utf-8"):
            r = json.loads(ln)
            k = key_of(r.get("record_url", ""))
            if not k:
                continue
            if k in work:
                work[k].setdefault("zagolovok_polnyi", r.get("zagolovok_polnyi", ""))
                work[k]["istochnik"] = "прогон 08.11 + пакет 07.11"
                src["совпало с пакетом"] += 1
                continue
            work[k] = {"key": k, "url": r["record_url"].rstrip("/"), "seriya": r["seriya"],
                       "zagolovok": r.get("zagolovok", ""),
                       "zagolovok_polnyi": r.get("zagolovok_polnyi", ""),
                       "istochnik": "пакет 07.11"}
            src["только пакет"] += 1

    already = [k for k in work if k in have]
    for k in already:
        work.pop(k)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    with WORK.open("w", encoding="utf-8") as f:
        for r in work.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nиз прогона уникальных карточек: {src['прогон']}")
    print(f"из пакета совпало с прогоном:    {src['совпало с пакетом']}")
    print(f"из пакета только там:            {src['только пакет']}")
    print(f"отсеяно (уже в каталоге):        {len(already)}")
    print(f"\nК ДОБОРУ: {len(work)} карточек → {WORK}")
    by = Counter(r["seriya"] for r in work.values())
    for s, n in by.most_common(25):
        print(f"  {n:>5}  {s[:70]}")


if __name__ == "__main__":
    fix_stdout()
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    (build_index if mode == "index" else build_work)()
