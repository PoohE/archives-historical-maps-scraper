"""А10: найти ВСЕ фонды землеустроительных комиссий, уже представленные в каталоге.

Поводом служит ошибка исходной гипотезы: ГАПК ф. 279 и ГАЯО ф. 455 оказались
межевыми архивами (чертёжными), а не комиссиями, тогда как в ГАСО комиссий
сразу несколько (ф. 334 губернская, ф. 237 Сычевская, ф. 428 Ельнинская).
Поэтому фонды ищем не по заранее названным номерам, а по фондообразователю
и по характерным формулировкам в любом поле записи.

  python a10_find_zk_funds.py [путь_к_baseline.jsonl]
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
OUT = ROOT / "a10_zemleustroystvo"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"

ZK = re.compile(
    r"землеустроительн\w*\s+комисси"
    r"|землеустроительн\w*\s+комисси"
    r"|поземельно-?устроительн"
    r"|землеустроительн\w*\s+отряд"
    r"|уездн\w*\s+землеустроительн",
    re.IGNORECASE,
)
# фондообразователь пишется в «Примечания» строкой «Фондообразователь: …»
FO = re.compile(r"Фондообразователь:\s*([^\n]+)")


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT

    funds: dict[tuple[str, str], Counter] = defaultdict(Counter)
    counts: Counter = Counter()
    rows: list[dict] = []
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        f = rec.get("fields") or {}
        blob = " ".join(
            str(f.get(k) or "")
            for k in ("Название источника", "Описание", "Примечания", "Серия")
        )
        if not ZK.search(blob):
            continue
        arch = (f.get("Архив [авто]") or "?").strip()
        fond = str(f.get("Фонд") or "")
        key = (arch, fond)
        counts[key] += 1
        m = FO.search(str(f.get("Примечания") or ""))
        funds[key][m.group(1).strip() if m else "(фондообразователь не указан)"] += 1
        rows.append(
            {
                "page_id": rec.get("id") or "",
                "arch": arch,
                "fond": fond,
                "opis": str(f.get("Опись") or ""),
                "delo": str(f.get("Единица хранения") or ""),
                "name": (f.get("Название источника") or "")[:200],
                "year_lo": f.get("Год создания (нижняя)"),
                "fo": m.group(1).strip() if m else "",
            }
        )

    print(f"записей с упоминанием землеустроительной комиссии: {len(rows)}\n")
    print("ФОНДЫ (архив, фонд) → фондообразователи:")
    for key, c in counts.most_common(40):
        print(f"\n  {key[0]} ф. {key[1]} — {c} зап.")
        for fo, k in funds[key].most_common(6):
            print(f"      {k:5d}  {fo}")

    p = OUT / "zk_mentions.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n→ {p} ({len(rows)})")


if __name__ == "__main__":
    main()
