"""Третий очаг дефекта года: ГАПК ф. 716 оп. 1 — 84 дела с годом 1785–1917.

Найдено 10.11.2026 при доведении дефекта года до конца. Прошлый прогон эти записи
не увидел, потому что искал оговорку «по крайним датам описи» в примечаниях, а здесь
её НЕТ — крайние даты описи просто подставлены в поля года молча.

Признак тот же, что у исправленных 1 847: у 84 дел из 86 стоит одинаковый интервал
**1785–1917** (132 года), при совершенно разном содержании — план участка с каменным
домом, план лавки, план кирпичных сараев, план усадебного места. Это не датировка,
а крайние даты описи.

Правило версии 2 (согласовано 09.11.2026): крайние даты описи датой дела не являются,
в поля года не пишутся, остаются в примечаниях; выставляется признак
«Год: источник значения» = «по крайним датам описи».

  python year_fix_gapk716.py            # показать план
  python year_fix_gapk716.py --apply    # применить
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
BASELINE = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects" / "year_fix_gapk716.jsonl"
LOCK = Path(__file__).resolve().parent / ".year_gapk716.lock"
OTHER = [Path(__file__).resolve().parent / ".scale_prov.lock"]
YEAR_PROP = "Год: источник значения"
#: интервал, подставленный из крайних дат описи
OPIS_RANGE = (1785, 1917)
NOTE_ADD = ("Год снят 10.11.2026: 1785–1917 — это крайние даты ОПИСИ ф. 716 оп. 1, "
            "а не дата дела (один интервал у 84 дел разного содержания). "
            "Датируется в пределах 1785–1917 по описи.")


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rows = []
    for line in BASELINE.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        f = rec.get("fields") or {}
        if (str(f.get("Архив [авто]") or ""), str(f.get("Фонд") or ""),
                str(f.get("Опись") or "")) != ("ГАПК", "716", "1"):
            continue
        lo, hi = f.get("Год создания (нижняя)"), f.get("Год создания (верхняя)")
        if (lo, hi) != OPIS_RANGE:
            continue
        rows.append({
            "pid": rec.get("page_id") or rec.get("id") or "",
            "delo": str(f.get("Единица хранения") or ""),
            "name": (f.get("Название источника") or "")[:120],
            "note": str(f.get("Примечания") or ""),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + chr(10))
    print(f"записей с годом {OPIS_RANGE[0]}–{OPIS_RANGE[1]}: {len(rows)}")
    for r in rows[:6]:
        print(f"  д.{r['delo']:>5s} | {r['name'][:95]}")
    print(f"→ {OUT}")

    if not args.apply:
        print("\nбез --apply ничего не изменено")
        return
    busy = [p.name for p in OTHER if p.exists()]
    if busy:
        sys.exit("идёт другой прогон записи: " + ", ".join(busy) + " — жду")
    if LOCK.exists():
        sys.exit(f"уже идёт прогон ({LOCK.name})")

    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))
    LOCK.write_text("year_gapk716", encoding="utf-8")
    try:
        n = 0
        for r in rows:
            if not r["pid"]:
                continue
            note = (r["note"] + chr(10) + NOTE_ADD).strip() if r["note"] else NOTE_ADD
            retry(lambda pid=r["pid"], note=note: c.pages.update(
                page_id=pid,
                properties={
                    "Год создания (нижняя)": {"number": None},
                    "Год создания (верхняя)": {"number": None},
                    "Год источника": {"number": None},
                    YEAR_PROP: {"select": {"name": "по крайним датам описи"}},
                    "Примечания": {"rich_text": [
                        {"type": "text", "text": {"content": note[:1900]}}]},
                },
            ))
            n += 1
            if n % 20 == 0:
                print(f"  обработано {n}/{len(rows)}", flush=True)
        print(f"ИТОГО исправлено: {n}")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
