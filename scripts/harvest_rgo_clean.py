"""Чистка полей добора РГО и сборка пакета под внесение.

Парсер `harvest_rgo.py` режет текст карточки по списку известных подписей, но у РГО
встречаются и подписи вне списка («Источник публикации / электронной копии»,
«Дата загрузки ресурса», «Располагается в коллекциях»). Из-за этого в поле «Шифр
хранения» попадал хвост соседней подписи:
    «AIII 2/16 Источник публикации / электронной копии : Картографический фонд…»
Перекачивать 462 карточки ради этого не нужно — хвост детерминированно отрезается.

Заодно собирает пакет: что реально добыто и чего не хватает для карточки каталога.

  python harvest_rgo_clean.py
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

DIR = Path(__file__).resolve().parents[1] / "output" / "work_2026-11-08"
SRC = DIR / "harvested_rgo.jsonl"
OUT = DIR / "rgo_package.jsonl"

#: подписи, которые могут оказаться ПОСЛЕ нужного значения и должны его обрезать
TAIL_LABELS = (
    "Источник публикации",
    "Дата загрузки ресурса",
    "Располагается в коллекциях",
    "Файлы ресурса",
    "URI",
    "Заглавие/название",
    "Дата публикации",
    "Библиографическое описание",
    "Шифр хранения",
    "Авторы",
    "Аннотация",
)
SCALE = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})")


def cut(val: str | None) -> str | None:
    if not val:
        return None
    s = str(val)
    ends = [s.index(lab) for lab in TAIL_LABELS if lab in s and s.index(lab) > 0]
    if ends:
        s = s[: min(ends)]
    s = re.sub(r"\s+", " ", s).strip(" .;:|—-")
    return s or None


def main() -> None:
    fix_stdout()
    if not SRC.exists():
        sys.exit(f"нет {SRC}")
    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8") if ln.strip()]
    ok = [r for r in rows if r.get("status") == "добрано"]

    pack = []
    for r in ok:
        shelf = cut(r.get("shelf"))
        desc = cut(r.get("istochnik"))
        title = cut(r.get("zagolovok_polnyi"))
        # заголовок вида «7168.pdf» — это имя файла, а не название
        if title and re.fullmatch(r"[\w\-.]+\.(pdf|djvu|jpg|tif)", title, re.I):
            title = None
        blob = " ".join(x for x in (title, desc) if x)
        m = SCALE.search(blob)
        # ⚠️ Поле года у РГО бывает ДИАПАЗОНОМ: «1613-1617», «[1634-1672]» —
        # у старых карт это норма. Класть такое в одно поле нельзя (проверка
        # preflight 10.11.2026), поэтому раскладываем на нижнюю и верхнюю границу.
        raw_year = cut(r.get("god"))
        yrs = sorted({int(x) for x in re.findall(r"1[5-9]\d{2}|20\d{2}", raw_year or "")})
        pack.append({
            "key": r["key"],
            "url": r["url"],
            "shelf": shelf,
            "title": title,
            "description": desc,
            "year": raw_year,
            "year_lo": yrs[0] if yrs else None,
            "year_hi": yrs[-1] if yrs else None,
            "year_src": "из карточки РГО" if yrs else "нет",
            "author": cut(r.get("avtor")),
            "pdf": r.get("pdf"),
            "scale": int(re.sub(r"\D", "", m.group(1))) if m else None,
            "scale_src": "из библиографического описания РГО" if m else None,
            "gub": our_gubernii(blob),
        })

    with OUT.open("w", encoding="utf-8") as f:
        for p in pack:
            f.write(json.dumps(p, ensure_ascii=False) + chr(10))

    print(f"карточек в пакете: {len(pack)}")
    print(f"  со шифром хранения: {sum(1 for p in pack if p['shelf'])}")
    print(f"  с названием: {sum(1 for p in pack if p['title'])}")
    print(f"  с описанием: {sum(1 for p in pack if p['description'])}")
    print(f"  с годом: {sum(1 for p in pack if p['year'])}")
    print(f"  с масштабом (из описания): {sum(1 for p in pack if p['scale'])}")
    print(f"  со ссылкой на PDF: {sum(1 for p in pack if p['pdf'])}")
    ours = [p for p in pack if p["gub"]]
    print(f"\n  по нашим четырём губерниям: {len(ours)}")
    gc: Counter = Counter()
    for p in ours:
        for g in p["gub"]:
            gc[g] += 1
    for g, c in gc.most_common():
        print(f"    {c:4d}  {g}")

    print("\n  примеры по нашим губерниям:")
    for p in ours[:8]:
        print(f"    [{','.join(p['gub'])}] {p['shelf'] or '— без шифра —':14s} "
              f"{(p['title'] or p['description'] or '')[:85]}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
