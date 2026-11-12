"""А10: вытащить ОФИЦИАЛЬНЫЕ названия фондов-лидеров из выгрузки каталога.

Фонд-лидер ГАПК ф. 279 охватывает 1736–1923 — значит это не одна комиссия,
а сборный фонд; ГАЯО ф. 455 попал только по терминам, его название тоже надо
установить. Названия ищем в полях записи (их имена заранее не известны —
печатаем весь набор полей по одному примеру на фонд).

  python a10_fund_names.py [путь_к_baseline.jsonl]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"

WANT = [
    ("ГАПК", "279"),
    ("ГАЯО", "455"),
    ("ГАСО", "237"),
    ("ГАСО", "428"),
    ("ГАСО", "334"),
    ("ГАКО", "485"),
    ("ГАКО", "575"),
    ("ГАПК", "716"),
]


def main() -> None:
    fix_stdout()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    samples: dict[tuple[str, str], dict] = {}
    opis_names: dict[tuple[str, str], Counter] = {}
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        f = (json.loads(line).get("fields") or {})
        arch = (f.get("Архив [авто]") or "").strip()
        fond = re.sub(r"\D", "", str(f.get("Фонд") or ""))
        for a, n in WANT:
            if a in arch and fond == n:
                samples.setdefault((a, n), f)
                oc = opis_names.setdefault((a, n), Counter())
                oc[str(f.get("Опись") or "")] += 1

    for key in WANT:
        f = samples.get(key)
        print("=" * 78)
        print(f"{key[0]} ф. {key[1]}")
        if not f:
            print("  в каталоге нет ни одной записи")
            continue
        for k, v in f.items():
            s = str(v)
            if s and s not in ("None", "[]", "{}"):
                print(f"  {k}: {s[:260]}")
        print(f"  --- описи: {dict(opis_names[key].most_common(15))}")


if __name__ == "__main__":
    main()
