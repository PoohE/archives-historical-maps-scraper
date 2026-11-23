# -*- coding: utf-8 -*-
"""Какие карточки справочника «Серийные массивы» реально НЕ покрыты фразами прогона.

Зачем отдельный скрипт. В `audit_series_dobor.py` покрытие определялось сверкой НАЗВАНИЙ:
`name[:18] in группа или группа[:12] in name`. Это даёт ложные «нет фраз»: карточка
«Двухвёрстная карта» помечена непокрытой, хотя в словаре есть группа «серия 18 — двухвёрстка
1:84 000» с тремя запросами по ней. Решение по такому признаку послало бы меня сочинять
фразы там, где они есть, и пропустить настоящие дыры.

Здесь покрытие считается по СОДЕРЖАНИЮ запросов: из названия карточки берутся значимые
основы слов (без общих «карта», «атлас», «статистика» — они есть почти в каждом запросе), и
карточка считается покрытой, если хотя бы один запрос словаря содержит её отличительную
основу. Выход — список непокрытых с их свойствами, чтобы сразу писать фразы.

  python scripts/series_coverage_check.py
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402
from series910_notion_link import SERIES_DS, title_of  # noqa: E402

OUT = HERE.parents[0] / "output" / "audit_series"

# Слова, которые есть почти в каждом названии и запросе — по ним совпадение ничего не значит
STOP = {
    "карта", "карты", "картографическая", "картография", "атлас", "атласы", "план", "планы",
    "статистика", "статистический", "статистические", "статистическая", "серия", "серии",
    "материалы", "российской", "россии", "империи", "российская", "губернии", "губерний",
    "издание", "издательская", "оболочка", "описательный", "текстовый", "массив", "комитет",
    "департамент", "министерство", "общество", "книга", "книги", "лист", "листы", "год",
    "года", "века", "съёмка", "съемка", "военно", "топографические", "топографическая",
    "области", "край", "края", "уезд", "уезда", "перепись", "переписи", "сборник", "сборники",
}


def stems(text: str) -> set[str]:
    """Основы значимых слов: 6 первых букв, чтобы пережить склонение."""
    out = set()
    for w in re.findall(r"[А-Яа-яЁёA-Za-z]{4,}", text.lower()):
        if w in STOP:
            continue
        out.add(w[:6])
    return out


def all_queries() -> list[str]:
    qs: list[str] = []
    for mod, attr in (("series_queries_2026_11_12", "EXT"),
                      ("series_queries_G_2026_11_14", "GQ"),
                      ("series_queries_G2_2026_11_15", "GQ2")):
        try:
            m = __import__(mod)
        except ImportError:
            continue
        for group, items in getattr(m, attr).items():
            qs.append(group)
            qs.extend(items)
    return qs


def plain(v: dict) -> str:
    t = v.get("type")
    if t == "title":
        return "".join(x["plain_text"] for x in v["title"])
    if t == "rich_text":
        return "".join(x["plain_text"] for x in v["rich_text"])
    if t == "select":
        return ((v.get("select") or {}).get("name")) or ""
    if t == "multi_select":
        return ", ".join(x["name"] for x in v.get("multi_select") or [])
    if t == "number":
        return "" if v.get("number") is None else str(v["number"])
    return ""


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))

    pages, cur = [], None
    while True:
        body = {"page_size": 100}
        if cur:
            body["start_cursor"] = cur
        r = retry(lambda b=body: c.data_sources.query(data_source_id=SERIES_DS, **b))
        pages += r["results"]
        if not r.get("has_more"):
            break
        cur = r["next_cursor"]
    print(f"карточек справочника: {len(pages)}")

    queries = all_queries()
    qstems = [stems(q) for q in queries]
    print(f"строк в словарях прогона: {len(queries)}")

    covered, uncovered = [], []
    for p in pages:
        name = title_of(p)
        st = stems(name)
        if not st:
            uncovered.append({"серия": name, "основы": [], "совпало": []})
            continue
        hits = [queries[i] for i, qs in enumerate(qstems) if st & qs]
        rec = {"серия": name,
               "основы": sorted(st),
               "совпало": hits[:3],
               "свойства": {k: plain(v) for k, v in p["properties"].items()
                            if plain(v) and v.get("type") in
                            ("rich_text", "select", "multi_select", "number")}}
        (covered if hits else uncovered).append(rec)

    print(f"\nпокрыто фразами: {len(covered)} | НЕ покрыто: {len(uncovered)}")
    print("\nНЕ ПОКРЫТЫ (нужны фразы):")
    for r in uncovered:
        print(f"  • {r['серия']}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "непокрытые_карточки.json").write_text(
        json.dumps(uncovered, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "покрытые_карточки.json").write_text(
        json.dumps([{k: v for k, v in r.items() if k != "свойства"} for r in covered],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {OUT / 'непокрытые_карточки.json'}")


if __name__ == "__main__":
    main()
