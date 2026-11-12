"""А10: что на самом деле лежит в фондах-лидерах выдачи.

Проверка перед тем как называть фонд «землеустроительным»: 8 713 записей
ГАПК ф. 279 и 1 767 ГАЯО ф. 455 слишком много для одной комиссии — надо
посмотреть названия дел, годы и описи своими глазами.

  python a10_inspect_funds.py [N_примеров]
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

SRC = (
    Path(__file__).resolve().parents[1]
    / "output"
    / "a10_zemleustroystvo"
    / "union.jsonl"
)
TOP = [
    ("ГАПК", "279"),
    ("ГАЯО", "455"),
    ("ГАСО", "237"),
    ("ГАСО", "428"),
    ("ГАСО", "334"),
    ("ГАСО", "814"),
    ("ГАКО", "485"),
    ("ГАКО", "575"),
    ("РГИА", "380"),
]


def main() -> None:
    fix_stdout()
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8") if ln.strip()]

    for arch, fond in TOP:
        sel = [
            r
            for r in rows
            if arch in (r["arch"] or "")
            and fond in str(r["fond"] or "")
        ]
        print("=" * 78)
        print(f"{arch} ф. {fond} — {len(sel)} записей")
        if not sel:
            print("  (в выдаче нет)")
            continue
        op = Counter(r["opis"] for r in sel)
        print(f"  описи: {dict(op.most_common(12))}")
        yl = [r["year_lo"] for r in sel if isinstance(r["year_lo"], (int, float))]
        if yl:
            print(f"  годы: {int(min(yl))}–{int(max(yl))}")
        print(f"  уровень: {dict(Counter(r['lvl'] for r in sel).most_common(5))}")
        print(f"  причина попадания: {dict(Counter(r['why'] for r in sel))}")
        print("  примеры:")
        for r in sel[:k]:
            print(
                f"    оп.{r['opis']} д.{r['delo']} [{r['year_lo']}] {r['name'][:150]}"
            )


if __name__ == "__main__":
    main()
