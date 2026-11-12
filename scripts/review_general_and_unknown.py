"""Разбор записей с вердиктом «общая» и «нет территории».

Второй пункт приёмки 10.11.2026. Первый (19 «чужих») показал, что вердикт гейта
надо проверять, а не принимать: две записи из девятнадцати оказались нашими.

Здесь задача обратная — найти НАШИ записи, которые гейт не опознал. В примерах
аудита были видны фонды РГАДА с заголовками вида «…по КАЛУЖСКОЙ губернии»
(капслок) — то есть, вероятно, системная промашка, а не разнородный шум.

Скрипт не решает за человека: он группирует записи по узнаваемым образцам,
показывает размер каждой группы и выписывает всё в файл для просмотра.

  python review_general_and_unknown.py [путь_к_baseline.jsonl]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from territory_gate import classify, our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects"

#: наши губернии в любом регистре и падеже — для проверки «гейт промахнулся?»
OURS_LOOSE = re.compile(
    r"калужск|смоленск|ярославск|пермск|перм\b", re.IGNORECASE
)


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT

    buckets: dict[str, list[dict]] = {"общая": [], "нет": [], "нет текста": []}
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        f = rec.get("fields") or {}
        blob = " ".join(
            str(f.get(k) or "")
            for k in ("Название источника", "Описание", "Примечания")
        )
        v = classify(blob)[0] if blob.strip() else "нет текста"
        if v not in buckets:
            continue
        buckets[v].append({
            "page_id": rec.get("page_id") or rec.get("id") or "",
            "arch": f.get("Архив [авто]") or "?",
            "fond": str(f.get("Фонд") or ""),
            "opis": str(f.get("Опись") or ""),
            "title": (f.get("Название источника") or "")[:220],
            "status": str(f.get("Статус приёмки") or ""),
            "verdict": v,
            "loose_hit": bool(OURS_LOOSE.search(blob)),
            "gate_gub": our_gubernii(blob),
        })

    for name, rows in buckets.items():
        print(f"\n=== «{name}»: {len(rows)} записей")
        if not rows:
            continue
        miss = [r for r in rows if r["loose_hit"] and not r["gate_gub"]]
        print(f"  ⚠️ упоминают нашу губернию, но гейт её не взял: {len(miss)}")
        print("  по архивам: " + str(dict(Counter(r["arch"] for r in rows).most_common(8))))
        if miss:
            print("  по фондам среди промахов: " + str(
                dict(Counter(f"{r['arch']} ф.{r['fond']}" for r in miss).most_common(6))))
            print("  примеры промахов:")
            for r in miss[:6]:
                print(f"    {r['arch']} ф.{r['fond']} оп.{r['opis']} | {r['title'][:120]}")
        rest = [r for r in rows if not r["loose_hit"]]
        if rest:
            print(f"  наших губерний не упоминают вовсе: {len(rest)}")
            for r in rest[:5]:
                print(f"    {r['arch']}: {r['title'][:120]}")

    for name, rows in buckets.items():
        p = OUT / f"review_{name.replace(' ', '_')}.jsonl"
        with p.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
        print(f"\n→ {p} ({len(rows)})")


if __name__ == "__main__":
    main()
