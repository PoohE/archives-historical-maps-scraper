"""Что по ЛЕСУ уже есть в нашей базе — по всем держателям, не только РГИА.

Вопрос пользователя 09.11.2026: «а почему ты считаешь что только в РГИА?»
Справедливо: лесоустроительные материалы рассеяны по центральным, региональным
и ведомственным хранилищам. Прежде чем заказывать прогон, надо посмотреть,
что уже добыто и где дыры.

Считает по `данные/найденные_источники.sqlite`:
  * лесные записи по словарю терминов (с отсечением ложных совпадений);
  * разрез держатель x наша губерния (территория — своим гейтом, не флагом базы);
  * какие держатели по лесу не дали НИЧЕГО (это и есть адреса для прогона).

  python forest_audit_store.py
"""

import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from territory_gate import classify, our_gubernii  # noqa: E402

DB = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\найденные_источники.sqlite"
)
OUT = Path(__file__).resolve().parents[1] / "output" / "forest_audit"

# Термины лесоустройства и лесного хозяйства.
FOREST = re.compile(
    r"лесоустро|лесн(?:ая|ой|ые|ых|ым|ого|ом)|лесничеств|таксацион|таксац|"
    r"лесонасажд|насаждени|лесосек|делянк|лесхоз|леспромхоз|лесосплав|"
    r"\bлеса\b|\bлесу\b|\bлесов\b|порубк|вырубк|просек|квартальн|"
    r"корабельн\w*\s+рощ|заказн\w*\s+рощ|\bбор\b|боров|дубрав|лесоторг|"
    r"лесоэкономич|лесотаксац|лесоохран|лесомелиор",
    re.I,
)
# ⚠️ Ложные срабатывания: «лесная улица», фамилии, «Лесной институт» как место издания.
FALSE = re.compile(
    r"лесн\w*\s+(?:улиц|переул|проспект|институт|техникум|журнал|газет)|"
    r"\bЛесной\s+(?:корпус|институт)\b",
    re.I,
)


def main() -> None:
    fix_stdout()
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in con.execute(
            "select klyuch, derzhatel, nazvanie, nazvanie_polnoe, seriya, "
            "gubernii, url, status from istochniki"
        )
    ]
    con.close()

    total_holders = Counter(r["derzhatel"] or "?" for r in rows)
    forest = []
    for r in rows:
        t = (r.get("nazvanie_polnoe") or r.get("nazvanie") or "")
        if FOREST.search(t) and not FALSE.search(t):
            r["_t"] = t
            forest.append(r)

    print(f"записей в базе: {len(rows)}")
    print(f"из них лесных по словарю: {len(forest)}\n")

    by_holder = Counter(r["derzhatel"] or "?" for r in forest)
    print("ЛЕСНЫЕ ЗАПИСИ ПО ДЕРЖАТЕЛЯМ (и сколько всего записей у держателя):")
    for h, n in by_holder.most_common():
        print(f"  {h:<10} лес {n:>5}  из {total_holders[h]:>6} всего")
    nothing = [h for h in total_holders if h not in by_holder]
    if nothing:
        print(f"\n  ⚠️ по лесу НИЧЕГО не дали: {', '.join(sorted(map(str, nothing)))}")

    # разрез по нашим губерниям
    grid: dict[str, Counter] = defaultdict(Counter)
    ours: list[dict] = []
    for r in forest:
        gl = our_gubernii(r["_t"])
        if gl:
            ours.append(r)
            for g in gl:
                grid[r["derzhatel"] or "?"][g] += 1

    print(f"\nлесных записей с НАШЕЙ губернией в заголовке: {len(ours)}")
    gubs = ["Калужская", "Смоленская", "Ярославская", "Пермская"]
    print(f"\n{'держатель':<12}" + "".join(f"{g:>13}" for g in gubs))
    for h in sorted(grid, key=lambda x: -sum(grid[x].values())):
        print(f"{h:<12}" + "".join(f"{grid[h].get(g, 0):>13}" for g in gubs))

    verd = Counter(classify(r["_t"])[0] for r in forest)
    print(f"\nтерриториальный гейт по всем лесным записям: {dict(verd)}")

    rep: list[str] = []
    rep.append("# Лес в нашей базе: что есть и чего нет\n")
    rep.append(
        f"Собрано `forest_audit_store.py` 09.11.2026 по {len(rows)} записям "
        f"`найденные_источники.sqlite`. Лесных по словарю терминов — **{len(forest)}**, "
        f"из них с нашей губернией в заголовке — **{len(ours)}**.\n"
    )
    rep.append("## Держатели\n")
    rep.append("| Держатель | Лесных записей | Всего записей у держателя |")
    rep.append("|---|---|---|")
    for h, n in by_holder.most_common():
        rep.append(f"| {h} | {n} | {total_holders[h]} |")
    if nothing:
        rep.append(
            f"\n⚠️ Держатели, не давшие по лесу **ничего**: "
            f"{', '.join(sorted(map(str, nothing)))}.\n"
        )

    rep.append("\n## Разрез: держатель x наша губерния\n")
    rep.append("| Держатель | Калужская | Смоленская | Ярославская | Пермская |")
    rep.append("|---|---|---|---|---|")
    for h in sorted(grid, key=lambda x: -sum(grid[x].values())):
        rep.append(
            f"| {h} | " + " | ".join(str(grid[h].get(g, 0)) for g in gubs) + " |"
        )

    rep.append("\n## Все лесные записи по нашим губерниям\n")
    rep.append("| Держатель | Губерния | Заголовок | Ссылка |")
    rep.append("|---|---|---|---|")
    for r in sorted(ours, key=lambda x: (x["derzhatel"] or "", x["_t"])):
        rep.append(
            f"| {r['derzhatel']} | {'; '.join(our_gubernii(r['_t']))} | "
            f"{r['_t'][:120]} | {r['url'] or ''} |"
        )

    path = OUT / "ОБЗОР_лес_в_базе.md"
    path.write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"\nотчёт: {path}")


if __name__ == "__main__":
    main()
