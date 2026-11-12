"""А10: землеустроительные комиссии (1906–1917) в КАТАЛОГЕ Notion.

Задача пользователя по А10: «полный разбор, собрать всю информацию, внести
всюду, после найти и привязать существующие или добавить в доп поиск».
Этот скрипт закрывает «найти существующие»: сплошной офлайн-проход по выгрузке
каталога (Notion API режет живой запрос на 10 000 записях — считать только
офлайн, память `feedback_notion-query-caps-at-10000`).

Ищет по двум независимым признакам:
  1) ТЕРМИНЫ столыпинского землеустройства (разверстание, отруб, хутор,
     чересполосица, выдел к одному месту, единоличное владение, землеустроит*);
  2) НОМЕРА ФОНДОВ землеустроительных комиссий, известные по разбору:
     ГАКО ф. 575 и ф. 485, ГАСО ф. 334, ГАПК ф. 279.

Выход: output/a10_zemleustroystvo/ — три jsonl (термины, фонды, объединение)
и сводка на экран.

  python a10_zemleustroystvo_audit.py [путь_к_baseline.jsonl]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from territory_gate import our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output"
OUT = ROOT / "a10_zemleustroystvo"
DEFAULT = ROOT / "notion_catalog_20261030_023643_baseline.jsonl"

# --- признак 1: терминология столыпинского землеустройства -----------------
# СИЛЬНЫЕ термины — однозначно столыпинское землеустройство.
STRONG = re.compile(
    r"землеустро|земл\w*\s*устро"
    r"|разверстан|разверстк"
    r"|отруб(?!\w*\s*(?:дерев|ствол|бревн))"
    r"|чересполосиц|многополос|узкополос"
    r"|выдел\w*\s+(?:на|к)\s+(?:одно|един)"
    r"|единоличн\w*\s+(?:владен|землепольз|хозяйств|участ)"
    r"|укреплени\w*\s+надел"
    r"|выход\w*\s+из\s+общин"
    r"|хуторск\w*\s+(?:участ|надел|план|устройств|хозяйств|земл)"
    r"|(?:участ|надел|план)\w*\s+(?:под\s+)?хутор"
    r"|крестьянск\w*\s+поземельн\w*\s+банк"
    r"|Крестьянск\w*\s+земельн\w*\s+банк",
    re.IGNORECASE,
)
# СЛАБЫЙ термин — «хутор» сам по себе: в межевых книгах XVIII–XIX вв. это тип
# населённого пункта, а не столыпинский участок. Берём только в годах реформы.
WEAK = re.compile(r"хутор", re.IGNORECASE)
WEAK_YEARS = (1906, 1925)

# отсев очевидных омонимов: «хутор» как тип населённого пункта в названии
# уездов юга, «отруб» в лесном деле (отруб = срез ствола)
FALSE = re.compile(
    r"отруб\w*\s*(?:дерев|ствол|бревн)"
    r"|хуторск\w*\s+казач"
    r"|Донск|Кубанск|Терск|Оренбургск\w*\s+казач",
    re.IGNORECASE,
)

# --- признак 2: фонды землеустроительных комиссий --------------------------
# Только ПОДТВЕРЖДЁННЫЕ фондообразователем. ГАПК ф. 279 из списка исключён:
# это сборная коллекция планов чертёжной, межевой комиссии и поземельно-
# устроительного отряда (1675–1917), а не фонд комиссии.
ZU_FUNDS = {
    "ГАКО": {"575", "485"},
    "ГАСО": {"334", "237", "428", "1027", "458", "89", "560"},
}
# Ярославская: фонда комиссии в каталоге нет (ф. 476 по публикации —
# в доп. поиск); её планы лежат в ф. 455 «Ярославский губернский межевой
# архив» и отбираются терминами.


def text_of(f: dict) -> str:
    return " ".join(
        str(f.get(k) or "")
        for k in ("Название источника", "Описание", "Примечания", "Серия")
    )


def row(rec: dict, f: dict, why: str) -> dict:
    return {
        "page_id": rec.get("id") or rec.get("page_id") or "",
        "why": why,
        "arch": f.get("Архив [авто]") or "?",
        "fond": str(f.get("Фонд") or ""),
        "opis": str(f.get("Опись") or ""),
        "delo": str(f.get("Дело") or ""),
        "lvl": f.get("Административный уровень") or "",
        "name": (f.get("Название источника") or "")[:200],
        "year_lo": f.get("Год создания (нижняя)"),
        "year_hi": f.get("Год создания (верхняя)"),
        "gub": our_gubernii(text_of(f)),
        "seriya": f.get("Серия") or "",
        "status": f.get("Статус приёмки") or "",
        "url": f.get("Ссылка") or f.get("URL") or "",
    }


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not src.exists():
        sys.exit(f"нет выгрузки: {src}")

    n = 0
    by_terms: list[dict] = []
    by_fund: list[dict] = []
    for line in src.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        rec = json.loads(line)
        f = rec.get("fields") or {}
        t = text_of(f)

        y = f.get("Год создания (нижняя)")
        in_years = isinstance(y, (int, float)) and (
            WEAK_YEARS[0] <= y <= WEAK_YEARS[1]
        )
        hit_terms = not FALSE.search(t) and (
            bool(STRONG.search(t)) or (in_years and bool(WEAK.search(t)))
        )
        arch = (f.get("Архив [авто]") or "").strip()
        fond = re.sub(r"\D", "", str(f.get("Фонд") or ""))
        hit_fund = False
        for a, funds in ZU_FUNDS.items():
            if a in arch and fond in funds:
                hit_fund = True
                break

        if hit_terms:
            by_terms.append(row(rec, f, "термин"))
        if hit_fund:
            by_fund.append(row(rec, f, "фонд"))

    print(f"записей в выгрузке: {n}")
    print(f"по терминам землеустройства: {len(by_terms)}")
    print(f"по фондам землеустр. комиссий: {len(by_fund)}\n")

    seen: dict[str, dict] = {}
    for r in by_terms + by_fund:
        key = r["page_id"] or f"{r['arch']}|{r['fond']}|{r['opis']}|{r['name']}"
        if key in seen:
            if r["why"] not in seen[key]["why"]:
                seen[key]["why"] += "+" + r["why"]
        else:
            seen[key] = dict(r)
    union = list(seen.values())
    print(f"объединение (уникальных): {len(union)}\n")

    print("ПО АРХИВАМ:")
    for a, c in Counter(r["arch"] for r in union).most_common(25):
        print(f"  {c:6d}  {a}")

    print("\nПО НАШИМ ГУБЕРНИЯМ:")
    gc = Counter()
    for r in union:
        for g in r["gub"] or ["(не определена)"]:
            gc[g] += 1
    for g, c in gc.most_common():
        print(f"  {c:6d}  {g}")

    ours = [r for r in union if r["gub"]]
    print(f"\nиз них привязано к нашим губерниям: {len(ours)}")

    print("\nФОНДЫ (топ-25 по объединению):")
    for k, c in Counter(
        f"{r['arch']} ф. {r['fond']}" for r in union
    ).most_common(25):
        print(f"  {c:6d}  {k}")

    print("\nГОДЫ (1906–1917 и окрестности):")
    inperiod = [
        r
        for r in union
        if isinstance(r["year_lo"], (int, float)) and 1900 <= r["year_lo"] <= 1925
    ]
    print(f"  записей с нижним годом 1900–1925: {len(inperiod)}")
    for y, c in sorted(Counter(int(r["year_lo"]) for r in inperiod).items()):
        print(f"    {y}: {c}")

    for name, data in (
        ("by_terms.jsonl", by_terms),
        ("by_fund.jsonl", by_fund),
        ("union.jsonl", union),
        ("ours.jsonl", ours),
    ):
        p = OUT / name
        with p.open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n→ {p} ({len(data)})")


if __name__ == "__main__":
    main()
