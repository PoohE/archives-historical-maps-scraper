"""А10: есть ли в каталоге фонды землеустроительных комиссий, названные разбором.

Deep research дал номера, которых в нашей выдаче не было: ГАКО ф. 575,
ГАЯО ф. 476, ГАПК ф. 277 (губернская комиссия — не 279!), уездные ГАПК
ф. 282/318/331 и восточно-уездные в ГАСО-Урал ф. 374/713/761.
Проверяем сплошным проходом, что из этого в каталоге уже есть.

  python a10_check_named_funds.py [путь_к_baseline.jsonl]
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
    ("ГАКО", "575", "Калужская губернская ЗК"),
    ("ГАКО", "485", "Калужская уездная ЗК"),
    ("ГАЯО", "476", "Ярославская губернская ЗК (по публикации)"),
    ("ГАПК", "277", "Пермская губернская ЗК"),
    ("ГАПК", "282", "Осинская уездная ЗК"),
    ("ГАПК", "318", "Камышловская уездная ЗК"),
    ("ГАПК", "331", "Соликамская уездная ЗК"),
    ("ГАСО", "560", "Гжатская уездная ЗК (Смоленск)"),
    ("ГАСО", "374", "Красноуфимская уездная ЗК (Свердловск!)"),
    ("ГАСО", "713", "Ирбитская уездная ЗК (Свердловск!)"),
    ("ГАСО", "761", "Верхотурская уездная ЗК (Свердловск!)"),
]


def main() -> None:
    fix_stdout()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    cnt: Counter = Counter()
    sample: dict[tuple[str, str], str] = {}
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        f = (json.loads(line).get("fields") or {})
        arch = (f.get("Архив [авто]") or "").strip()
        fond = re.sub(r"\D", "", str(f.get("Фонд") or ""))
        for a, n, _ in WANT:
            if a in arch and fond == n:
                cnt[(a, n)] += 1
                sample.setdefault((a, n), (f.get("Название источника") or "")[:150])
    for a, n, label in WANT:
        c = cnt[(a, n)]
        mark = "ЕСТЬ" if c else "НЕТ "
        print(f"  [{mark}] {a} ф. {n:4s} {c:6d}  — {label}")
        if c:
            print(f"            пример: {sample[(a, n)]}")


if __name__ == "__main__":
    main()
