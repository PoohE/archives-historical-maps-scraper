"""А13–А15: горнозаводской картографический комплекс Урала в каталоге Notion.

Три позиции списка кандидатов — карты лесных дач Камышловского уезда (А13),
заводские лесные дачи и лесоустройство горнозаводских округов (А14), планы
горнозаводских округов, дач, рудников и приисков (А15) — разбираются одним
блоком: у них общий фондообразователь-уровень (горная администрация), общая
нормативная линия (инструкция Канкрина 1830 → 1891 → 1896) и общий пробел
(Государственный архив Свердловской области в прогоны не входил).

Считаем сплошным офлайн-проходом выгрузки каталога (живой запрос Notion режет
на 10 000 — память `feedback_notion-query-caps-at-10000`).

Четыре слоя отбора, они пересекаются и считаются раздельно:
  ЗАВОД   — завод, заводская дача, куренная дача, горнозаводской округ;
  РУДНИК  — рудник, прииск, шахта, копь, отвод, месторождение, маркшейдерский;
  ЛЕС_ГЗ  — лесной слой ИМЕННО горнозаводской (лес + заводской контекст);
  ОКРУГ   — горный округ как единица.

  python ural_gornozavod_audit.py [путь_к_baseline.jsonl]
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from territory_gate import our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
OUT = ROOT / "ural_gornozavod"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"

ZAVOD = re.compile(
    r"завод|заводск\w*\s+дач|куренн|горнозаводск|горн\w*\s+округ"
    r"|домен|железоделат|медеплавил|чугунолит|железн\w*\s+промысл",
    re.IGNORECASE,
)
RUDNIK = re.compile(
    r"рудник|прииск|шахт|копь|копи\b|месторожден|маркшейдер"
    r"|золотоносн|платинон|горн\w*\s+работ|отвод\w*\s+(?:площад|земл)",
    re.IGNORECASE,
)
LES = re.compile(r"лес|дровян|таксац|лесничеств|лесосек|лесонасажден", re.IGNORECASE)
OKRUG = re.compile(r"горнозаводск\w*\s+округ|горн\w*\s+округ|заводск\w*\s+округ", re.I)

# омонимы: «завод» как учреждение не горное
FALSE = re.compile(
    r"конск\w*\s+завод|конный\s+завод|сахарн\w*\s+завод|кирпичн\w*\s+завод"
    r"|винокуренн|стекольн\w*\s+завод|лесопильн\w*\s+завод",
    re.IGNORECASE,
)


def text_of(f: dict) -> str:
    return " ".join(
        str(f.get(k) or "")
        for k in ("Название источника", "Описание", "Примечания", "Серия")
    )


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not src.exists():
        sys.exit(f"нет выгрузки: {src}")

    n = 0
    rows: list[dict] = []
    layers: Counter = Counter()
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        rec = json.loads(line)
        f = rec.get("fields") or {}
        t = text_of(f)

        z = bool(ZAVOD.search(t)) and not FALSE.search(t)
        r = bool(RUDNIK.search(t))
        lz = bool(LES.search(t)) and z
        o = bool(OKRUG.search(t))
        if not (z or r):
            continue
        tags = []
        if z:
            tags.append("ЗАВОД")
        if r:
            tags.append("РУДНИК")
        if lz:
            tags.append("ЛЕС_ГЗ")
        if o:
            tags.append("ОКРУГ")
        for tg in tags:
            layers[tg] += 1
        rows.append(
            {
                "page_id": rec.get("page_id") or rec.get("id") or "",
                "tags": tags,
                "arch": f.get("Архив [авто]") or "?",
                "fond": str(f.get("Фонд") or ""),
                "opis": str(f.get("Опись") or ""),
                "delo": str(f.get("Единица хранения") or ""),
                "lvl": f.get("Административный уровень") or "",
                "name": (f.get("Название источника") or "")[:220],
                "year_lo": f.get("Год создания (нижняя)"),
                "scale": f.get("Масштаб (знаменатель)"),
                "gub": our_gubernii(t),
                "seriya": f.get("Серия") or "",
            }
        )

    print(f"записей в выгрузке: {n}")
    print(f"горнозаводской слой (завод ИЛИ рудник): {len(rows)}")
    print("по слоям (пересекаются): " + ", ".join(f"{k} {v}" for k, v in layers.most_common()))

    ours = [x for x in rows if x["gub"]]
    perm = [x for x in rows if "Пермская" in (x["gub"] or [])]
    print(f"\nпо нашим губерниям: {len(ours)}; из них Пермская: {len(perm)}")
    gc: Counter = Counter()
    for x in rows:
        for g in x["gub"] or ["(не определена)"]:
            gc[g] += 1
    for g, c in gc.most_common():
        print(f"  {c:6d}  {g}")

    print("\nПО АРХИВАМ (только наши губернии):")
    for a, c in Counter(x["arch"] for x in ours).most_common(12):
        print(f"  {c:6d}  {a}")

    print("\nПО ФОНДАМ (только наши губернии, топ-15):")
    for k, c in Counter(f"{x['arch']} ф. {x['fond']}" for x in ours).most_common(15):
        print(f"  {c:6d}  {k}")

    print("\nМАСШТАБЫ (знаменатель, наши губернии, топ-12):")
    for s, c in Counter(
        str(x["scale"]) for x in ours if x["scale"]
    ).most_common(12):
        print(f"  {c:6d}  1:{s}")
    print(f"  без масштаба: {sum(1 for x in ours if not x['scale'])}")

    print("\nГОДЫ (наши губернии, по десятилетиям):")
    dec: Counter = Counter()
    for x in ours:
        y = x["year_lo"]
        if isinstance(y, (int, float)):
            dec[int(y) // 10 * 10] += 1
    for d in sorted(dec):
        print(f"  {d}-е: {dec[d]}")

    print("\nУЖЕ ПРИВЯЗАНО К КАКОЙ-ТО СЕРИИ (наши губернии):")
    ser = Counter(str(x["seriya"])[:60] or "(нет)" for x in ours)
    for s, c in ser.most_common(8):
        print(f"  {c:6d}  {s}")

    by_tag: dict[str, list[dict]] = defaultdict(list)
    for x in ours:
        for tg in x["tags"]:
            by_tag[tg].append(x)
    for tg in ("ЛЕС_ГЗ", "ОКРУГ", "РУДНИК"):
        print(f"\nПРИМЕРЫ {tg} (до 8):")
        for x in by_tag[tg][:8]:
            sc = f"1:{x['scale']}" if x["scale"] else "масштаб ?"
            print(f"  {x['arch']} ф.{x['fond']} оп.{x['opis']} [{x['year_lo']}] {sc} — {x['name'][:120]}")

    for name, data in (("all.jsonl", rows), ("ours.jsonl", ours)):
        p = OUT / name
        with p.open("w", encoding="utf-8") as fh:
            for x in data:
                fh.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(f"\n→ {p} ({len(data)})")


if __name__ == "__main__":
    main()
