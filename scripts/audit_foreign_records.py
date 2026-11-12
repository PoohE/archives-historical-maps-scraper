"""Что за записи в каталоге НЕ попали под фильтр «наши губернии».

Повод — вопрос пользователя 10.11.2026: «что делают в нашем каталоге записи по чужим
губерниям, они же должны были отсеяться при приёмке?»

Проверка нужна потому, что в прогонах признака масштаба фильтр `--only-ours` работал
по ТЕКСТУ ЗАГОЛОВКА (территориальный гейт), а у каталога есть собственное поле
«Охватываемая территория» — связь со справочником территорий. Это разные вещи, и
«не прошло по заголовку» ≠ «чужая губерния».

Считает разрез: поле территории заполнено или нет × вердикт гейта по заголовку ×
статус приёмки. Отдельно — какие именно территории стоят в поле.

  python audit_foreign_records.py [путь_к_baseline.jsonl]
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from territory_gate import classify  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects" / "foreign_audit.json"

TERR = "Охватываемая территория"
REG = "Современные регионы"
STATUS = "Статус приёмки"


def main() -> None:
    fix_stdout()
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not src.exists():
        sys.exit(f"нет выгрузки: {src}")

    n = 0
    has_terr = Counter()
    verdict = Counter()
    cross = Counter()
    status = Counter()
    no_terr_examples: list[str] = []
    foreign_examples: list[str] = []

    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        f = (json.loads(line).get("fields") or {})
        t = f.get(TERR)
        filled = bool(t) and t != "[]"
        has_terr["поле территории заполнено" if filled else "поле территории ПУСТО"] += 1
        blob = " ".join(
            str(f.get(k) or "") for k in ("Название источника", "Описание", "Примечания")
        )
        v = classify(blob)[0] if blob.strip() else "нет текста"
        verdict[v] += 1
        cross[(("поле есть" if filled else "поля нет"), v)] += 1
        status[str(f.get(STATUS) or "— не задан —")] += 1
        name = (f.get("Название источника") or "")[:110]
        if not filled and len(no_terr_examples) < 8:
            no_terr_examples.append(f"{f.get('Архив [авто]') or '?'}: {name}")
        if v == "чужая" and len(foreign_examples) < 10:
            foreign_examples.append(f"{f.get('Архив [авто]') or '?'}: {name}")

    print(f"записей в каталоге: {n}\n")
    print("ПОЛЕ «Охватываемая территория»:")
    for k, c in has_terr.most_common():
        print(f"  {c:7d}  {k}  ({c * 100 // n} %)")

    print("\nВЕРДИКТ ГЕЙТА ПО ЗАГОЛОВКУ (это НЕ то же самое, что поле):")
    for k, c in verdict.most_common():
        print(f"  {c:7d}  {k}  ({c * 100 // n} %)")

    print("\nПЕРЕСЕЧЕНИЕ:")
    for (a, b), c in sorted(cross.items(), key=lambda x: -x[1]):
        print(f"  {c:7d}  поле: {a:10s} | гейт: {b}")

    print("\nСТАТУС ПРИЁМКИ:")
    for k, c in status.most_common(8):
        print(f"  {c:7d}  {k}")

    print("\nПРИМЕРЫ «чужая» по гейту:")
    for s in foreign_examples:
        print(f"  {s}")
    print("\nПРИМЕРЫ с ПУСТЫМ полем территории:")
    for s in no_terr_examples:
        print(f"  {s}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "всего": n,
        "поле территории": dict(has_terr),
        "вердикт гейта": dict(verdict),
        "пересечение": {f"{a}|{b}": c for (a, b), c in cross.items()},
        "статус приёмки": dict(status),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
