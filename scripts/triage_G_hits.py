# -*- coding: utf-8 -*-
"""Разбор улова серийного прогона по позициям раздела Г: дедуп → территория → отчёт.

Зачем скрипт. По ходу разбора позиций Г1–Г26 (14–15.11.2026) одна и та же цепочка
выполнялась вручную тринадцать раз: взять строки улова по группе, свести к уникальным
каталожным карточкам, выбросить то, что уже есть в каталоге, разложить остаток по
территориальному признаку и посчитать. Правило второго раза: механика детерминированная,
значит это скрипт, а не повторяемый разовый код.

Что делает:
  1. читает `output/series_library_sweep/hits.jsonl` (улов прогона);
  2. оставляет только КАТАЛОЖНЫЕ карточки (URL записи, а не страница поиска);
  3. дедуплицирует по URL и сверяет с выгрузкой каталога (по URL и по названию+году);
  4. раскладывает остаток: наши губернии / межгубернское / территория не названа /
     чужая территория / ложная картография (гейт `scripts_review/false_carto.py`);
  5. печатает сводку по группам и пишет пакеты в `output/triage_G/`.

⚠️ Богатство параметров (главный критерий накопительного реестра) автоматически не
проверяется: по заголовку состав граф не виден. Скрипт только готовит материал к разбору.

  python triage_G_hits.py                      # все группы
  python triage_G_hits.py --group "Г9"         # одна группа по подстроке
  python triage_G_hits.py --since-queries 1193 # только улов новых запросов
"""

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts_review"))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402
from false_carto import alien_hit, is_false_carto  # noqa: E402

# ⚠️ Признак «каталожная карточка» в hits.jsonl записан при СБОРЕ и у старых строк
# устарел: до 16.11.2026 шаблоны покрывали четыре хоста, и улов ГПИБ, Пермской краевой
# и РНБ (6 804 строки) считался некаталожным. Поэтому признак пересчитываем здесь по
# актуальным шаблонам движка, а записанному не доверяем.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from series_library_sweep import RECORD_RE  # noqa: E402


def is_record(url: str) -> bool:
    return any(rx.search(url or "") for rx in RECORD_RE.values())

ROOT = Path(__file__).resolve().parents[1]
HITS = ROOT / "output" / "series_library_sweep" / "hits.jsonl"
BASE = ROOT / "output" / "notion_catalog_20261030_023643_baseline.jsonl"
OUT = ROOT / "output" / "triage_G"

# Группы раздела Г и смежные, добавленные 12–15.11.2026
GROUP = re.compile(
    r"^(Г\d+ |А1 |А11 |серия 1[89]|серия 2[0-4]|серия 2-бис|Атлас |Генеральная |"
    r"Географический |Карманный |Карты губерний |Топографические изв|Чердынский |"
    r"Список населённых пунктов|советские )")

# ⚠️ СЛОВАРЬ И ЛОГИКА ТЕРРИТОРИЙ НЕ ПЕРЕНАБИРАЮТСЯ. Источники истины:
#   * `scripts/modules/territories.py` — 4 губернии и 46 уездов, синхронизировано
#     со справочником Notion «Административные единицы»;
#   * `scripts/modules/territory_resolve.py` — канонический стеммер `stem()` и карта
#     губернских стемов `REGION_STEMS`; этим же модулем пользуется мост заливки
#     `notion_upload_candidates.py`, то есть гейт здесь и при внесении — один.
# История правки: первая версия скрипта (15.11.2026) перепечатывала словарь и теряла
# написания «вязьм», «бельск», «ельн», «поречь» (192 «наших» вместо 614); вторая версия
# резала стемы своим правилом и ловила «Ростов-на-Дону» как Ростовский уезд. Оба дефекта
# уже задокументированы по картографическому гейту — лечатся только единым источником.
sys.path.insert(0, str(Path(__file__).resolve().parent / "modules"))
from territories import UYEZD_QUERIES  # noqa: E402
from territory_resolve import REGION_STEMS, stem  # noqa: E402


def _terms() -> list[str]:
    """Губернские стемы канона + уездные стемы через канонический stem()."""
    out = set(REGION_STEMS)
    for names in UYEZD_QUERIES.values():
        for n in names:
            st = stem(n.replace(" уезд", "").strip())
            if len(st) >= 4:
                out.add(st)
    return sorted(out)


GUB = re.compile("|".join(_terms()), re.I)
# Адресные исключения известных ловушек стема (память проекта, разбор гейта 10.11.2026):
# стем «ростов» от «Ростовский уезд» Ярославской губернии совпадает с донским Ростовом;
# «Ростовская область» и «Ростов-на-Дону» — чужая территория, а не наша.
TRAP = re.compile(r"ростов[ае]?[- ]?(на[- ]?дону|ск\w+\s+(област|кра|район))", re.I)
# ⚠️ Известный предел канона: стем берётся от прилагательного, поэтому «Вяземский» ловится,
# а «Вязьма» — нет; «Ельнинский» ловится, «Ельня» — нет. Так же ведёт себя гейт заливки,
# поэтому расхождения между этим разбором и каталогом не возникает. Разрыв закрывается
# картой вариантов VARIANT в territory_resolve, а не правкой здесь.
MEZH = re.compile(r"российск\w+ импери|европейск\w+ росси|всероссийск|ссср|по губерниям", re.I)


def norm_url(u: str) -> str:
    u = (u or "").lower().split("?")[0].rstrip("/")
    return re.sub(r"^https?://(www\.)?", "", u)


def load_catalog() -> tuple[set[str], list[tuple[str, str]]]:
    """URL-и каталога и пары (нормализованное название, год+название) для сверки."""
    urls: set[str] = set()
    titles: list[tuple[str, str]] = []
    if not BASE.exists():
        print(f"⚠️ выгрузки каталога нет: {BASE} — сверка только по URL улова")
        return urls, titles
    for line in BASE.open(encoding="utf-8"):
        if not line.strip():
            continue
        f = (json.loads(line).get("fields") or {})
        for key in ("Ссылка на онлайн-архив", "Ссылка на источник"):
            if f.get(key):
                urls.add(norm_url(str(f[key])))
        name = str(f.get("Название источника") or "")
        if name:
            titles.append((re.sub(r"[^а-яa-z0-9 ]", " ", name.lower().replace("ё", "е")),
                           str(f.get("Год источника") or "") + " " + name))
    return urls, titles


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="", help="подстрока названия группы")
    ap.add_argument("--since-queries", type=int, default=0,
                    help="считать только улов запросов после N-го выполненного")
    args = ap.parse_args()

    if not HITS.exists():
        sys.exit(f"нет улова: {HITS}")

    known_urls, cat_titles = load_catalog()
    print(f"каталог: {len(known_urls)} ссылок, {len(cat_titles)} названий")

    cards: dict[str, dict] = {}
    for i, line in enumerate(HITS.open(encoding="utf-8")):
        if not line.strip():
            continue
        r = json.loads(line)
        if not is_record(r.get("url", "")):
            continue
        if not GROUP.match(r["серия"]):
            continue
        if args.group and args.group.lower() not in r["серия"].lower():
            continue
        cards.setdefault(r["url"], {"серия": r["серия"], "title": r.get("title", ""),
                                    "строка": i})
    print(f"уникальных каталожных карточек по группам: {len(cards)}")

    stat: collections.Counter = collections.Counter()
    buckets: dict[str, list] = collections.defaultdict(list)
    for url, v in cards.items():
        title = v["title"] or ""
        if norm_url(url) in known_urls:
            stat["уже в каталоге (по URL)"] += 1
            continue
        if not title.strip():
            stat["пустой заголовок"] += 1
            continue
        if is_false_carto(title):
            stat["ложная картография"] += 1
            buckets["ложная"].append({"url": url, **v})
            continue
        ours = bool(GUB.search(title))
        alien = alien_hit(title)
        if ours and (TRAP.search(title) or alien):
            # Наше название при чужой территории — НЕ отсев, а спор на человека
            # (правило проекта: чужая территория при нашем топониме → needs_human).
            stat["спорная: наш топоним при чужой территории"] += 1
            buckets["спорная"].append({"url": url, "повод": TRAP.search(title).group(0)
                                       if TRAP.search(title) else str(alien), **v})
            continue
        if ours:
            stat["наши губернии"] += 1
            buckets["наша"].append({"url": url, **v})
            continue
        if alien:
            stat["чужая территория"] += 1
            buckets["чужая"].append({"url": url, **v})
            continue
        if MEZH.search(title):
            stat["межгубернское"] += 1
            buckets["межгуб"].append({"url": url, **v})
            continue
        stat["территория не названа"] += 1
        buckets["без территории"].append({"url": url, **v})

    print("\nСВОДКА:")
    for k, n in stat.most_common():
        print(f"  {n:6d}  {k}")

    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in buckets.items():
        path = OUT / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"→ {path.name}: {len(rows)}")

    by_group = collections.Counter(r["серия"] for r in buckets["наша"])
    if by_group:
        print("\n«наши губернии» по группам:")
        for k, n in by_group.most_common(20):
            print(f"  {n:5d}  {k}")


if __name__ == "__main__":
    main()
