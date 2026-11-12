"""А10: итоговый набор записей каталога под привязку к серии 23.

Гипотеза «ГАПК ф. 279 = Пермская губернская землеустроительная комиссия»
опровергнута (это сборная коллекция планов чертёжной, межевой комиссии и
поземельно-устроительного отряда, 1675–1917), поэтому фонд целиком в серию
не берётся — только записи, прошедшие по терминам.

Берём:
  A) все записи ПОДТВЕРЖДЁННЫХ фондов землеустроительных комиссий
     (фондообразователь прочитан в поле «Примечания» каталога);
  B) записи любых других фондов, прошедшие по терминам столыпинского
     землеустройства И привязанные к одной из наших четырёх губерний.

  python a10_build_link_set.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "a10_zemleustroystvo"

# подтверждённые фонды землеустроительных комиссий (архив, фонд) -> название
ZK_CONFIRMED = {
    ("ГАСО", "334"): "Смоленская губернская землеустроительная комиссия",
    ("ГАСО", "237"): "Сычевская уездная землеустроительная комиссия",
    ("ГАСО", "428"): "Ельнинская уездная землеустроительная комиссия",
    ("ГАСО", "1027"): "Велижская уездная землеустроительная комиссия",
    ("ГАСО", "458"): "Рославльская уездная землеустроительная комиссия",
    ("ГАСО", "89"): "Краснинская уездная землеустроительная комиссия",
    ("ГАСО", "560"): "Гжатская уездная землеустроительная комиссия",
    ("ГАКО", "Ф-485"): "Калужская уездная землеустроительная комиссия",
}


def main() -> None:
    fix_stdout()
    rows = [
        json.loads(ln)
        for ln in (OUT / "union.jsonl").open(encoding="utf-8")
        if ln.strip()
    ]

    sel: dict[str, dict] = {}
    for r in rows:
        key = (r["arch"], str(r["fond"]))
        zk = ZK_CONFIRMED.get(key)
        take = None
        if zk:
            take = f"фонд ЗК: {zk}"
        elif "термин" in r["why"] and r["gub"]:
            take = "термин + наша губерния"
        if not take:
            continue
        rr = dict(r)
        rr["basis"] = take
        pid = r["page_id"] or f"{r['arch']}|{r['fond']}|{r['opis']}|{r['name']}"
        sel[pid] = rr

    final = list(sel.values())
    print(f"под привязку к серии 23: {len(final)}\n")
    print("по основанию:")
    for b, c in Counter(r["basis"] for r in final).most_common():
        print(f"  {c:6d}  {b}")
    print("\nпо архивам:")
    for a, c in Counter(r["arch"] for r in final).most_common():
        print(f"  {c:6d}  {a}")
    print("\nпо фондам:")
    for k, c in Counter(
        f"{r['arch']} ф. {r['fond']}" for r in final
    ).most_common(20):
        print(f"  {c:6d}  {k}")
    print("\nпо губерниям:")
    gc: Counter = Counter()
    for r in final:
        for g in r["gub"] or ["(не определена)"]:
            gc[g] += 1
    for g, c in gc.most_common():
        print(f"  {c:6d}  {g}")
    nopid = [r for r in final if not r["page_id"]]
    print(f"\nбез page_id (привязать нельзя): {len(nopid)}")

    p = OUT / "link_set.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in final:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"→ {p}")


if __name__ == "__main__":
    main()
