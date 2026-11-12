"""А11: сводные описи РГИА ф. 380 (38–41) — есть ли в них наши губернии.

Поводом служит ошибка в файле кандидатов: позиция А11 описана как «РГИА ф. 380
оп. 1190, 42 556 ед. хр.». Такой описи у фонда НЕТ — фонд имеет 41 опись,
а 42 556/42 563 — это объём фонда целиком. Описание «карты и планы казённых
земель и лесов ПО ВСЕМ ГУБЕРНИЯМ» соответствует сводной **оп. 39**.

Прежняя выборка по нашим губерниям (`rgia380_extract_ours.py`) брала только
погубернские описи 10 (Калужская), 21 (Пермская), 28 (Смоленская),
37 (Черниговская–Ярославская). СВОДНЫЕ описи 38–41 в неё не входили:
  оп. 38 — хронологические и систематические каталоги казённых земель и лесов;
  оп. 39 — карты и планы казённых и частных земель и лесов по ВСЕМ губерниям;
  оп. 40 — карты и планы водных систем, чертежи гидротехнических сооружений;
  оп. 41 — чертежи зданий промышленных и сельскохозяйственных заведений.
Проверка 09.11.2026 показала, что пробел УЖЕ был закрыт отдельным прогоном
08.10.2026 (`output/rgia_fund380_opisi38_41_retag_20261008/`): 2 616 дел описей
38–41 переразмечены, по нашим губерниям отобрано 3 дела, и все три в каталоге
есть. Скрипт оставлен как независимая проверка этого вывода по состояниям описей.
⚠️ Каталог состояний — `rgia_fund380_20261003_v3_1` (полный прогон). В каталоге
`..._20261002_v2` лежит ранний частичный дамп (727 узлов, по ~20 на опись) —
считать по нему нельзя, даст ложный ноль.

  python a11_rgia380_svodnye_opisi.py
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

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "output" / "rgia_fund380_20261003_v3_1" / "fund380_opis_state"
OUT = ROOT / "output" / "a11_rgia380_svodnye"
SVODNYE = {38, 39, 40, 41}
DELO = re.compile(r"Ф\.\s*380\s*Оп\.\s*(\d+)\s*Д\.\s*(\S+)")


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    if not STATE.exists():
        sys.exit(f"нет состояний описей: {STATE}")

    files = sorted(STATE.glob("*.json"))
    print(f"файлов состояния: {len(files)}")

    inventory: list[tuple[int, int, str]] = []
    rows: list[dict] = []
    totals = Counter()
    for p in files:
        o = json.loads(p.read_text(encoding="utf-8"))
        raw = o.get("opis_number")
        # в состояниях v3_1 номер описи лежит СТРОКОЙ — без приведения
        # к int сравнение с множеством сводных описей молча даёт ноль
        try:
            num = int(str(raw))
        except (TypeError, ValueError):
            num = raw
        meta = o.get("node_metadata") or {}
        inventory.append((num, len(meta), o.get("territory") or ""))
        totals["узлов всего"] += len(meta)
        if num not in SVODNYE:
            continue
        for nid, m in meta.items():
            code = str(m.get("fund_code") or "")
            title = str(m.get("title") or "")
            blob = f"{code} {title}"
            gub = our_gubernii(blob)
            if not gub:
                continue
            mm = DELO.search(code)
            rows.append(
                {
                    "node_id": nid,
                    "opis": num,
                    "delo": mm.group(2) if mm else "",
                    "code": code,
                    "title": title[:400],
                    "gub": gub,
                    "scope": classify(blob),
                    "dates": str(m.get("dates") or m.get("date") or ""),
                }
            )

    print("\nСОСТАВ ФОНДА (опись → узлов → территория описи):")
    for num, n, terr in sorted(inventory, key=lambda x: (x[0] is None, x[0])):
        mark = "  ← СВОДНАЯ" if num in SVODNYE else ""
        print(f"  оп. {num:>3}  {n:>6} узлов   {terr[:38]:38s}{mark}")
    print(f"\nвсего узлов в фонде: {totals['узлов всего']}")
    print(f"⚠️ описи с номером 1190 в фонде нет; описей всего: {len(files)}")

    print(f"\nВ СВОДНЫХ ОПИСЯХ 38–41 по нашим губерниям: {len(rows)}")
    for num, c in sorted(Counter(r["opis"] for r in rows).items()):
        print(f"  оп. {num}: {c}")
    gc: Counter = Counter()
    for r in rows:
        for g in r["gub"]:
            gc[g] += 1
    print("  по губерниям: " + ", ".join(f"{g} {c}" for g, c in gc.most_common()))
    print("  по вердикту гейта: " + str(dict(Counter(r["scope"] for r in rows))))

    print("\nПРИМЕРЫ (до 15):")
    for r in rows[:15]:
        print(f"  [{','.join(r['gub'])}] {r['code']} — {r['title'][:130]}")

    p = OUT / "svodnye_ours.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n→ {p} ({len(rows)})")

    pi = OUT / "fund_inventory.json"
    pi.write_text(
        json.dumps(
            [{"opis": n, "nodes": k, "territory": t} for n, k, t in inventory],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"→ {pi}")


if __name__ == "__main__":
    main()
