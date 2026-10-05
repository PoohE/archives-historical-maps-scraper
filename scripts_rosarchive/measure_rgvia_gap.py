# -*- coding: utf-8 -*-
"""Измерение пробела по РГВИА: есть ли картография вне 17 собранных фондов.

Повод (05.10): набор УИАД собран обходом 17 картографических фондов по списку путеводителя,
а в РГВИА их 12 935. Это не ошибка области (как было у ПрБ, где прогон сидел в учебной
коллекции), но и не «архив пройден»: по запросу «план Смоленской губернии» два результата
из трёх пришли из фондов 369 и 412, которых в списке нет.

Метод: межархивный поиск УИАД с фильтром `arrFilter[archive]=РГВИА` и `arrFilter[type]=unit`
по территориям и картографическим словам; из каждой ссылки выдачи берётся идентификатор фонда
и сверяется со списком собранных. Считаем, сколько картографических дел лежит ВНЕ наших фондов.

⚠️ Поиск портала фразовый и по релевантности: счётчик «Найдено» и реальная выдача расходятся,
поэтому меряем не полноту, а наличие и порядок величины пробела.
⚠️ Работает в СВОЕЙ вкладке (own_tab=True): параллельно может идти сборщик.

Запуск: python measure_rgvia_gap.py
"""
import io
import json
import re
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from cdp import fetch  # noqa: E402
from parsing import MAP_SUBJ  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = "https://online.archives.ru/search/"
RGVIA = "10000000001003"
ROOT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
IDS = ROOT / "output" / "rosarchive_rgvia_20261004" / "fund_ids.json"
OUT = ROOT / "output" / "rgvia_gap_20261005"
PAUSE = 3.0

# ⚠️ Поиск УИАД фразовый и ЧУВСТВИТЕЛЕН К ПАДЕЖУ: «карта Калужская губерния» → 0 результатов,
# «карта Калужской губернии» → 6. Территории подставляем в родительном падеже.
TERRS = ["Калужской губернии", "Пермской губернии", "Смоленской губернии", "Ярославской губернии"]
WORDS = ["карта", "план", "атлас", "съемка", "чертеж", "топографическая"]


def search_page(q: str, page: int = 1) -> tuple[list[tuple[str, str, str]], int]:
    """[(fund_id, url, заголовок)], «Найдено»."""
    p = {"q": q, "arrFilter[archive]": RGVIA, "arrFilter[type]": "unit"}
    url = BASE + "?" + urllib.parse.urlencode(p) + (f"&page={page}" if page > 1 else "")
    html, text = fetch(url, wait=6.0, own_tab=True)
    m = re.search(r"Найдено\s+([\d\s]+)", re.sub(r"[ \t]+", " ", text))
    total = int(re.sub(r"\s", "", m.group(1))) if m else 0
    so = BeautifulSoup(html, "lxml")
    rows = []
    for a in so.find_all("a", href=True):
        mm = re.search(rf"/search/{RGVIA}/(\d+)/(\d+)/(\d+)/?$", a["href"])
        if not mm:
            continue
        t = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        t = re.sub(r"\s*Полный/Краткий заголовок\s*$", "", t)
        rows.append((mm.group(1), a["href"], t))
    return rows, total


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    our_ids = {v[0]: num for num, v in json.loads(IDS.read_text(encoding="utf-8")).items()}
    seen: dict[str, dict] = {}
    counts, outside_funds = Counter(), Counter()
    for terr in TERRS:
        for word in WORDS:
            q = f"{word} {terr}"
            try:
                rows, total = search_page(q)
            except Exception as e:
                print(f"«{q}» → {type(e).__name__}", flush=True)
                time.sleep(PAUSE)
                continue
            new_out = 0
            for fid, href, title in rows:
                if href in seen:
                    continue
                inside = fid in our_ids
                carto = bool(MAP_SUBJ.search(title))
                seen[href] = {"fund_id": fid, "fund": our_ids.get(fid, "?"), "title": title,
                              "inside": inside, "cartographic": carto, "query": q,
                              "url": "https://online.archives.ru" + href}
                counts["внутри" if inside else "вне"] += 1
                if not inside:
                    outside_funds[fid] += 1
                    if carto:
                        new_out += 1
            print(f"«{q}»: найдено {total}, разобрано {len(rows)}, новых вне наших фондов "
                  f"с картографическим заголовком {new_out}", flush=True)
            time.sleep(PAUSE)

    outside_carto = [v for v in seen.values() if not v["inside"] and v["cartographic"]]
    rep = {
        "source": "uiad", "archive": "РГВИА", "method": "межархивный поиск, type=unit",
        "queries": len(TERRS) * len(WORDS),
        "results_parsed": len(seen),
        "inside_our_funds": counts["внутри"], "outside_our_funds": counts["вне"],
        "outside_cartographic": len(outside_carto),
        "outside_fund_ids": dict(outside_funds.most_common(20)),
        "note": "поиск фразовый и по релевантности: мера наличия пробела, не его полноты",
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "outside_records.jsonl").write_text(
        "\n".join(json.dumps(v, ensure_ascii=False) for v in seen.values() if not v["inside"]),
        encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    if outside_carto:
        print("\nкартографические дела ВНЕ собранных фондов:")
        for v in outside_carto[:20]:
            print(f"   fund_id={v['fund_id']} | {v['title'][:95]}")


if __name__ == "__main__":
    main()
