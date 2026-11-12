"""Что лежит в каталоге под характерными военными масштабами (3, 4, 5, 10 вёрст).

  python scale_series_breakdown.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

BASELINE = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\текущий_baseline.jsonl"
)
OUT = Path(
    r"C:\Users\admin\AppData\Local\Temp\claude"
    r"\D--IG-Dropbox-Andy-PoohV-Project-Claude"
    r"\7fbfb943-dfbd-4420-95d7-a7e98d81798e\scratchpad\scale_breakdown.md"
)

TARGET = {126000: "3 версты", 168000: "4 версты", 210000: "5 вёрст", 420000: "10 вёрст",
          252000: "6 вёрст"}
GUB = re.compile(r"калужск|смоленск|ярославск|пермск", re.I)


def main() -> None:
    fix_stdout()
    buckets: dict[int, list[dict]] = {k: [] for k in TARGET}

    with BASELINE.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            fl = rec.get("fields", {})
            sc = fl.get("Масштаб (знаменатель)")
            try:
                sc = int(sc)
            except (TypeError, ValueError):
                continue
            if sc not in TARGET:
                continue
            name = str(fl.get("Название источника") or "")
            buckets[sc].append(
                {
                    "name": name[:150],
                    "год": fl.get("Год источника") or fl.get("Год создания (нижняя)"),
                    "архив": fl.get("Архив [авто]") or fl.get("Место хранения"),
                    "фонд": fl.get("Фонд"),
                    "опись": fl.get("Опись"),
                    "дело": fl.get("Единица хранения"),
                    "наша_губ": bool(GUB.search(name)),
                    "серия": bool(fl.get("Серия / массив")),
                    "page_id": rec.get("page_id"),
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as w:
        w.write("# Каталог: записи с характерными военными масштабами\n\n")
        for sc, label in TARGET.items():
            rows = buckets[sc]
            ours = [r for r in rows if r["наша_губ"]]
            linked = sum(1 for r in rows if r["серия"])
            print(f"1:{sc} ({label}): {len(rows)} записей, "
                  f"по нашим губерниям {len(ours)}, привязано к серии {linked}")
            arch = Counter(str(r["архив"]) for r in rows)
            print("    архивы: " + ", ".join(f"{a} {n}" for a, n in arch.most_common(5)))
            w.write(f"\n## 1:{sc} — {label} — {len(rows)} записей "
                    f"(по нашим губерниям {len(ours)}, привязано к серии {linked})\n\n")
            w.write("Архивы: " + ", ".join(f"{a} — {n}" for a, n in arch.most_common()) + "\n\n")
            w.write("### По нашим губерниям\n\n")
            for r in ours[:200]:
                w.write(f"- **{r['name']}** | {r['год']} | {r['архив']} "
                        f"ф. {r['фонд']} оп. {r['опись']} д. {r['дело']} | `{r['page_id']}`\n")
            if not ours:
                w.write("_нет_\n")
            w.write("\n### Прочие (первые 60)\n\n")
            for r in [x for x in rows if not x["наша_губ"]][:60]:
                w.write(f"- {r['name']} | {r['год']} | {r['архив']} "
                        f"ф. {r['фонд']} оп. {r['опись']} д. {r['дело']}\n")
    print(f"\nподробности: {OUT}")


if __name__ == "__main__":
    main()
