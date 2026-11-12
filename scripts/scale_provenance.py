"""Шаг 1 устранения дефекта масштаба: признак «Масштаб: источник значения».

Решение пользователя 09.11.2026 — вариант (а): догадка сохраняется, но становится
машиночитаемо отличимой от измеренного значения. Причина — память
`feedback_guess-in-numeric-field-poisons-analysis`: числовое поле «Масштаб
(знаменатель)» заполнялось эвристикой по типу источника, и подсчёты её молча
использовали (ложный вывод «в горнозаводском слое доминирует 1:8 400»).

Значения признака (select):
  «с листа»             — масштаб прочитан с самого листа или из карточки архива;
  «из заголовка описи»  — назван в заголовке дела («Масштаб 200 саженей»);
  «по типу источника»   — ЭВРИСТИКА, в анализ не брать;
  «не установлен»       — числового значения нет и догадки не делалось.

Правило вывода (детерминированное, по уже имеющимся полям):
  есть «приближ»/«по типу» в «Оригинальный масштаб»            → по типу источника
  «Оригинальный масштаб» заполнен без этих слов                → с листа
  числовое поле есть, пояснения нет, масштаб назван в заголовке → из заголовка описи
  числовое поле есть, пояснения нет, в заголовке нет           → не установлен (⚠️ сирота)
  числового значения нет                                        → не установлен

  python scale_provenance.py                 # сухой прогон: что будет выставлено
  python scale_provenance.py --create-prop   # создать свойство в схеме каталога
  python scale_provenance.py --apply [--only-ours] [--limit N]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

from territory_gate import our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
BASELINE = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "defects"
LOCK = Path(__file__).resolve().parent / ".scale_prov.lock"
#: журнал уже выставленных страниц. Нужен потому, что выгрузка каталога — снимок
#: от 30.10 и признака в ней нет: без журнала повторный запуск переделывал бы всё
#: заново. 09.11.2026 прогон убит нехваткой памяти на 2 400 из 14 833 — журнал
#: позволяет продолжить с места, а не с начала.
APPLIED = ROOT / "defects" / "scale_prov_applied.txt"
OTHER_LOCKS = [
    Path(__file__).resolve().parent / ".series23.lock",
    Path(__file__).resolve().parent / ".series24.lock",
]
CATALOG_DS = "decdf63c-6f64-4852-ada2-65e72c79d9bc"
PROP = "Масштаб: источник значения"
OPTIONS = ["с листа", "из заголовка описи", "по типу источника", "не установлен"]

HEUR = re.compile(r"приближ|по типу", re.IGNORECASE)
SCALE_IN_TITLE = re.compile(
    r"\d{1,4}\s*саж(?:ен\w*|\.)|\d{1,3}\s*(?:верст\w*|в\.)\s*(?:в\s*дюйм|/\s*дюйм)"
    r"|\bм-\s*\d{1,3}\s*в\b|1\s*:\s*\d{3,9}",
    re.IGNORECASE,
)


def verdict(f: dict) -> str:
    orig = str(f.get("Оригинальный масштаб") or "").strip()
    num = f.get("Масштаб (знаменатель)")
    if orig:
        return "по типу источника" if HEUR.search(orig) else "с листа"
    if num:
        text = f"{f.get('Название источника') or ''} {f.get('Описание') or ''}"
        return "из заголовка описи" if SCALE_IN_TITLE.search(text) else "не установлен"
    return "не установлен"


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--create-prop", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--only-ours",
        action="store_true",
        help="только записи, территориально привязанные к нашим четырём губерниям",
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--skip-unset",
        action="store_true",
        help="не писать «не установлен»: значение неинформативно (отсутствие "
        "признака и так читается как «не установлен»), а это 67 тыс. вызовов API",
    )
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))

    if args.create_prop:
        ds = retry(lambda: c.data_sources.retrieve(data_source_id=CATALOG_DS))
        if PROP in ds["properties"]:
            print(f"свойство уже есть: {PROP}")
        else:
            retry(
                lambda: c.data_sources.update(
                    data_source_id=CATALOG_DS,
                    properties={
                        PROP: {
                            "select": {
                                "options": [{"name": o} for o in OPTIONS]
                            }
                        }
                    },
                )
            )
            print(f"свойство создано: {PROP} ({', '.join(OPTIONS)})")

    if not BASELINE.exists():
        sys.exit(f"нет выгрузки: {BASELINE}")

    applied: set[str] = set()
    if APPLIED.exists():
        applied = {
            x.strip() for x in APPLIED.read_text(encoding="utf-8").splitlines()
            if x.strip()
        }
        print(f"уже выставлено ранее (по журналу): {len(applied)}")

    plan: list[dict] = []
    stats: Counter = Counter()
    for line in BASELINE.open(encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        f = rec.get("fields") or {}
        v = verdict(f)
        stats[v] += 1
        if f.get(PROP) == v:
            stats["уже выставлено"] += 1
            continue
        if (rec.get("page_id") or rec.get("id") or "") in applied:
            stats["уже выставлено"] += 1
            continue
        text = f"{f.get('Название источника') or ''} {f.get('Описание') or ''}"
        ours = bool(our_gubernii(text))
        if args.only_ours and not ours:
            continue
        if args.skip_unset and v == "не установлен":
            continue
        plan.append(
            {
                "page_id": rec.get("page_id") or rec.get("id") or "",
                "v": v,
                "ours": ours,
                "arch": f.get("Архив [авто]") or "",
                "num": f.get("Масштаб (знаменатель)"),
            }
        )
        if args.limit and len(plan) >= args.limit:
            break

    print("РАСКЛАД ПО ВСЕМУ КАТАЛОГУ:")
    for k in OPTIONS:
        print(f"  {stats[k]:7d}  {k}")
    print(f"\nк выставлению в этом прогоне: {len(plan)}")
    print(f"  из них по нашим губерниям: {sum(1 for r in plan if r['ours'])}")
    print("  по значению: " + str(dict(Counter(r["v"] for r in plan))))

    p = OUT / ("scale_prov_plan_ours.jsonl" if args.only_ours else "scale_prov_plan.jsonl")
    with p.open("w", encoding="utf-8") as fh:
        for r in plan:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"→ {p}")

    # ⚠️ сироты: число есть, но откуда — неизвестно
    orphans = [r for r in plan if r["v"] == "не установлен" and r["num"]]
    print(f"\n⚠️ число в поле есть, происхождение неизвестно: {len(orphans)}")

    if not args.apply:
        print("\nбез --apply ничего не записано")
        return

    if LOCK.exists():
        sys.exit(f"уже идёт прогон ({LOCK.name})")
    busy = [q.name for q in OTHER_LOCKS if q.exists()]
    if busy:
        sys.exit("идёт другой прогон записи в Notion: " + ", ".join(busy) + " — жду")

    LOCK.write_text("scale_prov", encoding="utf-8")
    APPLIED.parent.mkdir(parents=True, exist_ok=True)
    try:
        n = 0
        # журнал пишется ПОСТРОЧНО и сбрасывается на диск: прогон может быть убит
        # в любой момент (09.11.2026 — нехваткой памяти), и продолжить надо с места
        with APPLIED.open("a", encoding="utf-8") as jf:
            for i, r in enumerate(plan, 1):
                if not r["page_id"]:
                    continue
                retry(
                    lambda r=r: c.pages.update(
                        page_id=r["page_id"],
                        properties={PROP: {"select": {"name": r["v"]}}},
                    )
                )
                jf.write(r["page_id"] + chr(10))
                jf.flush()
                n += 1
                if i % 200 == 0:
                    print(f"  {i}/{len(plan)}: выставлено {n}", flush=True)
        print(f"ИТОГО выставлено: {n}")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
