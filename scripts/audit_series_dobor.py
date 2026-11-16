# -*- coding: utf-8 -*-
"""Инвентарь незакрытого добора по ВСЕМ карточкам справочника «Серийные массивы».

Поручение владельца 15.11.2026: после раздела Г пройти по всем серийным источникам и
собрать, что по ним ещё не добрано. Слепой прогон тут не годится — сначала инвентарь,
адресные фондовые прогоны по архивам идут по его результату.

Что проверяется по каждой карточке:
  1. тип массива и наличие связи с издательской оболочкой;
  2. сколько записей каталога привязано полем «Серия / массив» (по выгрузке каталога,
     офлайн: живой запрос обрывается на 10 000 записях при 112 тыс. в базе);
  3. маркеры незакрытости в тексте карточки — «НЕ УСТАНОВЛЕНО», «не прогонялся»,
     «не проверено», «адресных дел не установлено», «нужна смета», «не подтверждено»;
  4. есть ли у позиции фразы в словарях прогона (значит библиотеки покрыты).

Выход — `output/audit_series/ИНВЕНТАРЬ_добора.md`: таблица с приоритетом и предложенным
следующим шагом по каждой карточке.

  python audit_series_dobor.py
"""

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import env, fix_stdout, load_env  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402

from series910_notion_link import SERIES_DS, title_of  # noqa: E402

OUT = ROOT / "output" / "audit_series"
MARKERS = [
    ("НЕ УСТАНОВЛЕН", "не установлено"),
    ("не прогонял", "фонд не прогонялся"),
    ("НЕ ПРОВЕРЕН", "не проверено"),
    ("не проверено", "не проверено"),
    ("адресных дел", "адресных дел не установлено"),
    ("нужна смета", "ждёт сметы"),
    ("НЕ ПОДТВЕРЖД", "не подтверждено"),
    ("НЕ ВЫЯВЛЕН", "не выявлено"),
    ("НЕ СДЕЛАНО", "не сделано"),
]


def newest_baseline() -> Path | None:
    cands = sorted((ROOT / "output").glob("notion_catalog_*baseline.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def catalog_series_counts() -> collections.Counter:
    """Сколько записей каталога привязано к каждой серии — КЛЮЧ: page_id карточки.

    ⚠️ Правка 16.11.2026 (блокер Б-10). «Серия / массив» — поле-RELATION: в выгрузке
    там лежит СПИСОК id страниц (`['4130ba89-eabe-…']`), а не название серии. Прежний
    счёт резал эту строку по «;» и сравнивал с названием карточки, поэтому совпадений
    не было никогда и инвентарь показывал «0 записей» у ВСЕХ 57 карточек — при том что
    у серии 24 их 2 068. Сверяем по id, дефисы в id не учитываем (в разных выгрузках
    он приходит и с ними, и без).
    """
    cnt: collections.Counter = collections.Counter()
    base = newest_baseline()
    if not base:
        print("⚠️ выгрузки каталога нет — счёт привязанных записей пропущен")
        return cnt
    print(f"выгрузка каталога: {base.name}")
    for line in base.open(encoding="utf-8"):
        if not line.strip():
            continue
        f = (json.loads(line).get("fields") or {})
        val = f.get("Серия / массив")
        if not val:
            continue
        ids = val if isinstance(val, list) else re.findall(r"[0-9a-f-]{32,36}", str(val))
        for pid in ids:
            key = str(pid).replace("-", "").strip().lower()
            if key:
                cnt[key] += 1
    return cnt


def phrases_by_group() -> set[str]:
    """Группы, под которые есть фразы в словарях прогона."""
    groups: set[str] = set()
    for mod, attr in (("series_queries_2026_11_12", "EXT"),
                      ("series_queries_G_2026_11_14", "GQ"),
                      ("series_queries_G2_2026_11_15", "GQ2")):
        try:
            m = __import__(mod)
            groups |= set(getattr(m, attr))
        except Exception:  # noqa: BLE001 — словаря может не быть
            continue
    return groups


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))

    pages = []
    cur = None
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

    counts = catalog_series_counts()
    swept = phrases_by_group()

    rows = []
    for p in pages:
        name = title_of(p)
        props = p["properties"]
        kind = ((props.get("Тип массива") or {}).get("select") or {}).get("name", "—")
        shell = len(((props.get("Входит в оболочку") or {}).get("relation")) or [])
        text = " ".join(
            "".join(x["plain_text"] for x in v.get("rich_text", []))
            for v in props.values() if v.get("type") == "rich_text")
        found = sorted({label for needle, label in MARKERS if needle.lower() in text.lower()})
        linked = counts.get(p["id"].replace("-", "").lower(), 0)
        has_phrases = any(name[:18].lower() in g.lower() or g.lower()[:12] in name.lower()
                          for g in swept)
        rows.append({"серия": name, "тип": kind, "оболочка": shell, "записей": linked,
                     "пробелы": found, "фразы": has_phrases})

    OUT.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["записей"], -len(r["пробелы"])))

    lines = ["---", "дата: 2026-11-16",
             "задача: инвентарь незакрытого добора по всем карточкам справочника «Серийные массивы»",
             "основание: поручение владельца 15.11.2026 — после раздела Г пройти по всем серийным",
             "  источникам и собрать, что ещё не добрано; адресные фондовые прогоны идут по этому списку",
             "---", "", "# Инвентарь добора по серийным массивам", "",
             f"Карточек в справочнике: **{len(rows)}**. Сортировка: сначала те, у которых "
             "НЕТ привязанных записей каталога и больше всего пробелов.", "",
             "| Серия | Тип | Оболочка | Записей каталога | Пробелы в карточке | Фразы прогона |",
             "|---|---|---:|---:|---|---|"]
    for r in rows:
        lines.append(
            f"| {r['серия'][:70]} | {r['тип'][:18]} | {r['оболочка'] or '—'} | "
            f"{r['записей'] or '**0**'} | {', '.join(r['пробелы']) or '—'} | "
            f"{'✅' if r['фразы'] else '⛔ нет'} |")

    no_rec = [r for r in rows if not r["записей"]]
    no_phr = [r for r in rows if not r["фразы"]]
    lines += ["", "## Итоги", "",
              f"- карточек БЕЗ привязанных записей каталога: **{len(no_rec)}**",
              f"- карточек без фраз в словарях прогона (библиотеки не покрыты): **{len(no_phr)}**",
              f"- карточек с пометками незакрытости: "
              f"**{sum(1 for r in rows if r['пробелы'])}**", "",
              "## Следующий шаг по каждой группе", "",
              "1. **Нет записей и нет фраз** — сначала дописать фразы в словарь, прогнать по "
              "библиотекам, затем фондовый прогон по архивам.",
              "2. **Нет записей, фразы есть** — улов уже собран: разобрать "
              "`triage_G_hits.py` и внести, а не искать заново.",
              "3. **Записи есть, но стоят пометки «адресных дел не установлено»** — это "
              "архивная задача: фондовый прогон или письмо (строки А33–А39 реестра "
              "отложенного добора).",
              "4. **«ждёт сметы»** — решение владельца по деньгам (ГАСО-Урал ф. 59 и др.)."]

    path = OUT / "ИНВЕНТАРЬ_добора.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {path}")
    print(f"без записей каталога: {len(no_rec)} | без фраз прогона: {len(no_phr)}")


if __name__ == "__main__":
    main()
