"""Реестр пробелов: серия × держатель — что реально есть в каталоге.

Шаг 0 плана от 07.11.2026. Считает ФАКТ по выгрузке каталога, а не статус из чеклиста
(урок ГПИБ 18.10: «закрыто блокером» месяц держалось на записи в чеклисте, а не на обходе).

Выход — ОБЗОР в output/gap_registry/:
  * матрица «серия × держатель» по числу записей каталога;
  * держатели, которых в каталоге почти нет (структурные дыры);
  * серии без карточки и карточки без записей.

  python gap_registry.py
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH  # noqa: E402
from notion_client import Client  # noqa: E402
from series910_notion_link import SERIES_DS, query_all, title_of  # noqa: E402

BASELINE = Path(
    r"D:\Dropbox\Project\Pooh\19 Каталогизация исторических источников России"
    r"\Представленность исторических картографических источников в федеральных "
    r"и региональных архивах и библиотеках\данные\текущий_baseline.jsonl"
)
OUT = Path(__file__).resolve().parents[1] / "output" / "gap_registry"
ARCH_DS = "fedbea82-520d-4f03-b8bc-793a29a25e79"


def name_map(client: Client, ds: str) -> dict[str, str]:
    return {p["id"].replace("-", ""): title_of(p) for p in query_all(client, ds)}


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN"))

    series = name_map(client, SERIES_DS)
    arch = name_map(client, ARCH_DS)
    print(f"карточек серий: {len(series)}, архивов/библиотек: {len(arch)}")

    matrix: dict[str, Counter] = defaultdict(Counter)
    by_arch: Counter = Counter()
    by_series: Counter = Counter()
    total = no_series = 0

    with BASELINE.open(encoding="utf-8") as f:
        for line in f:
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            fl = rec.get("fields", {})

            def ids(val) -> list[str]:
                if not val:
                    return []
                if isinstance(val, list):
                    out = []
                    for x in val:
                        i = x.get("id") if isinstance(x, dict) else x
                        if i:
                            out.append(str(i).replace("-", ""))
                    return out
                return [str(val).replace("-", "")]

            a_ids = ids(fl.get("Архив хранения")) or ["(не указан)"]
            s_ids = ids(fl.get("Серия / массив"))
            if not s_ids:
                no_series += 1
                s_ids = ["(без серии)"]
            for a in a_ids:
                an = arch.get(a, a if a == "(не указан)" else "??")
                by_arch[an] += 1
                for s in s_ids:
                    sn = series.get(s, s if s == "(без серии)" else "??")
                    matrix[sn][an] += 1
                    by_series[sn] += 1

    OUT.mkdir(parents=True, exist_ok=True)
    L: list[str] = []
    L.append("# Реестр пробелов: серия × держатель\n")
    L.append(f"Выгрузка каталога: **{total}** записей. "
             f"Без привязки к серии: **{no_series}** ({no_series * 100 // max(total, 1)} %).\n")
    L.append("Считано по факту из выгрузки, не по статусам чеклиста.\n")

    L.append("\n## Держатели: сколько записей в каталоге\n")
    L.append("| Держатель | Записей |")
    L.append("|---|---|")
    for a, n in by_arch.most_common():
        L.append(f"| {a} | {n} |")

    L.append("\n## Серии: сколько записей привязано\n")
    L.append("| Серия | Записей | Держатели |")
    L.append("|---|---|---|")
    for s, n in by_series.most_common():
        if s == "(без серии)":
            continue
        tops = ", ".join(f"{a} {c}" for a, c in matrix[s].most_common(4))
        L.append(f"| {s[:70]} | {n} | {tops} |")

    empty = [s for s in series.values() if s not in by_series]
    L.append(f"\n## Карточки серий без единой записи — {len(empty)}\n")
    for s in sorted(empty):
        L.append(f"- {s}")

    (OUT / "ОБЗОР_реестр_пробелов.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\nзаписей: {total}; без серии: {no_series}")
    print(f"карточек серий без записей: {len(empty)}")
    print(f"файл: {OUT / 'ОБЗОР_реестр_пробелов.md'}")


if __name__ == "__main__":
    main()
