"""Приёмка правок каталога: сверка ПО САМОМУ NOTION, а не по журналам прогонов.

Журнал скрипта говорит, что вызов был сделан; он не говорит, что значение стоит
в карточке. Поэтому берём случайную выборку и читаем поля прямо из Notion.

Проверяет три вещи:
  1) «Масштаб: источник значения» — выставлен ли и совпадает ли с ожидаемым;
  2) «Год: источник значения» и сам год — очищен ли там, где год шёл по описи,
     и стоит ли интервал там, где он выведен из датировки серии;
  3) привязка к сериям 23 и 24 — на месте ли отношение.

  python verify_fixes.py [--n 40]
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
SCALE_PLAN = ROOT / "defects" / "scale_prov_plan_ours.jsonl"
SCALE_APPLIED = ROOT / "defects" / "scale_prov_applied.txt"
YEAR_PLAN = ROOT / "defects" / "year_fix_plan.jsonl"
SCALE_PROP = "Масштаб: источник значения"
YEAR_PROP = "Год: источник значения"


def sel_name(page: dict, prop: str) -> str | None:
    v = (page.get("properties") or {}).get(prop) or {}
    s = v.get("select")
    return s.get("name") if s else None


def number(page: dict, prop: str):
    v = (page.get("properties") or {}).get(prop) or {}
    return v.get("number")


def relations(page: dict, prop: str = "Серия / массив") -> int:
    v = (page.get("properties") or {}).get(prop) or {}
    return len(v.get("relation") or [])


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()
    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))
    rnd = random.Random(20261110)

    # --- 1. масштаб: выборка из уже применённых
    applied = [
        x.strip() for x in SCALE_APPLIED.read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    want = {}
    for ln in SCALE_PLAN.open(encoding="utf-8"):
        if ln.strip():
            r = json.loads(ln)
            want[r["page_id"]] = r["v"]
    sample = rnd.sample(applied, min(args.n, len(applied)))
    got: Counter = Counter()
    mism = []
    for pid in sample:
        pg = retry(lambda pid=pid: c.pages.retrieve(page_id=pid))
        v = sel_name(pg, SCALE_PROP)
        got[v or "— пусто —"] += 1
        if pid in want and v != want[pid]:
            mism.append((pid, want[pid], v))
    print(f"МАСШТАБ — проверено карточек: {len(sample)} из {len(applied)} применённых")
    for k, n in got.most_common():
        print(f"  {n:4d}  {k}")
    print(f"  расхождений с планом: {len(mism)}")
    for pid, w, g in mism[:5]:
        print(f"    {pid}: ждали «{w}», стоит «{g}»")

    # --- 2. год
    yplan = [json.loads(ln) for ln in YEAR_PLAN.open(encoding="utf-8") if ln.strip()]
    by_kind: dict[str, list] = {}
    for r in yplan:
        by_kind.setdefault(r["kind"], []).append(r)
    print(f"\nГОД — план: {len(yplan)}; " + ", ".join(
        f"{k} {len(v)}" for k, v in by_kind.items()))
    bad = 0
    checked = 0
    for kind, rows in by_kind.items():
        take = rnd.sample(rows, min(12, len(rows)))
        for r in take:
            pg = retry(lambda pid=r["pid"]: c.pages.retrieve(page_id=pid))
            prov = sel_name(pg, YEAR_PROP)
            lo = number(pg, "Год создания (нижняя)")
            checked += 1
            ok = prov == kind
            if kind == "по крайним датам описи":
                ok = ok and lo is None
            else:
                ok = ok and lo == r["lo"]
            if not ok:
                bad += 1
                if bad <= 5:
                    print(f"  ✗ {kind}: признак «{prov}», нижний год {lo} "
                          f"(ждали {r['lo']})")
    print(f"  проверено {checked}, расхождений {bad}")

    # --- 3. привязка к сериям
    for name, path in (
        ("серия 23", ROOT / "a10_zemleustroystvo" / "link_set.jsonl"),
        ("серия 24", ROOT / "ural_gornozavod" / "ours.jsonl"),
    ):
        ids = [
            json.loads(ln)["page_id"]
            for ln in path.open(encoding="utf-8")
            if ln.strip() and json.loads(ln).get("page_id")
        ]
        take = rnd.sample(ids, min(15, len(ids)))
        linked = 0
        for pid in take:
            pg = retry(lambda pid=pid: c.pages.retrieve(page_id=pid))
            if relations(pg):
                linked += 1
        print(f"\n{name}: из {len(take)} проверенных связаны {linked} "
              f"(всего в наборе {len(ids)})")


if __name__ == "__main__":
    main()
