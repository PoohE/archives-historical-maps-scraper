# -*- coding: utf-8 -*-
"""Кандидаты на привязку записей каталога к карточкам серий — подбор без записи.

Состояние на 16.11.2026: поле «Серия / массив» заполнено у 81 572 записей из 113 055, но
привязки есть лишь у 27 карточек справочника из 57; у 30 — ноль. (Инвентарь
`audit_series_dobor.py` показывал ноль у всех 57: он сверял НАЗВАНИЕ карточки со значением
поля, а там лежат id страниц.)

Здесь для каждой карточки без привязок подбираются записи каталога по её же поисковым
фразам из словарей прогона. Правила подбора намеренно строгие — ошибочная привязка тяжелее
пропуска, потому что она врёт о составе серии:
  * совпасть должны ВСЕ значимые основы одной фразы (общие слова «карта», «атлас»,
    «статистика», «губерния» в счёт не идут);
  * год записи обязан попадать в хронологию карточки (с запасом ±2 года на разночтения
    изданий), если год у записи есть;
  * запись, уже привязанная к другой серии, идёт отдельным списком — её судьбу решает
    человек, автоматически вторую связь не добавляем.

Скрипт НИЧЕГО не пишет: выход — файл разбора для приёмки.

  python scripts/series_link_candidates.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")
from common import env, fix_stdout, load_env, log  # noqa: E402
from mezh_batch_tag import ENV_PATH, retry  # noqa: E402
from notion_client import Client  # noqa: E402
from series910_notion_link import SERIES_DS, title_of  # noqa: E402

LOG = log("series_link_candidates")
OUT = ROOT / "output" / "audit_series"

STOP = {
    "карта", "карты", "картой", "атлас", "атласы", "план", "планы", "планов",
    "статистика", "статистический", "статистические", "статистическая", "статистических",
    "серия", "серии", "материалы", "российской", "россии", "империи", "российская",
    "губернии", "губерний", "губерния", "губернская", "уезда", "уезд", "уезды", "уездов",
    "года", "год", "году", "годы", "издание", "издания", "том", "часть", "выпуск",
    "лист", "листы", "дюйме", "вёрст", "верст", "версты", "вёрсты", "сведения", "сведений",
    "комитет", "комитета", "министерства", "департамент", "департамента", "главного",
    "центрального", "общие", "подробная", "специальная", "европейской", "западной",
}
YEAR = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")


def stems(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[А-Яа-яЁёA-Za-z]{4,}", text.lower()):
        if w in STOP:
            continue
        s = w[:6]
        if s not in out:
            out.append(s)
    return out


def card_phrases() -> dict[str, list[str]]:
    d: dict[str, list[str]] = {}
    for mod, attr in (("series_queries_2026_11_12", "EXT"),
                      ("series_queries_G_2026_11_14", "GQ"),
                      ("series_queries_G2_2026_11_15", "GQ2"),
                      ("series_queries_2026_11_16", "GQ3")):
        try:
            m = __import__(mod)
        except ImportError:
            continue
        for group, items in getattr(m, attr).items():
            d.setdefault(group, [])
            d[group] += items
    return d


def newest_baseline() -> Path:
    files = sorted((ROOT / "output").glob("notion_catalog_*baseline.jsonl"))
    if not files:
        sys.exit("нет выгрузки каталога")
    return files[-1]


def main() -> None:
    fix_stdout()
    load_env(ENV_PATH)
    c = Client(auth=env("NOTION_TOKEN"))

    pages, cur = [], None
    while True:
        b = {"page_size": 100}
        if cur:
            b["start_cursor"] = cur
        r = retry(lambda bb=b: c.data_sources.query(data_source_id=SERIES_DS, **bb))
        pages += r["results"]
        if not r.get("has_more"):
            break
        cur = r["next_cursor"]

    cards = {}
    for p in pages:
        props = p["properties"]

        def num(key: str, pr=props) -> int | None:
            v = pr.get(key) or {}
            if v.get("type") == "number":
                return v.get("number")
            txt = "".join(x["plain_text"] for x in v.get("rich_text", []))
            m = YEAR.search(txt)
            return int(m.group(1)) if m else None

        cards[p["id"].replace("-", "")] = {
            "имя": title_of(p),
            "низ": num("Хронология нижняя"),
            "верх": num("Хронология верхняя"),
        }
    LOG.info(f"карточек справочника: {len(cards)}")

    phr = card_phrases()
    # сопоставление «группа словаря → карточка» по значимым основам названия
    gr2card: dict[str, str] = {}
    for g in phr:
        gs = set(stems(g))
        best, score = None, 0
        for cid, c0 in cards.items():
            sc = len(gs & set(stems(c0["имя"])))
            if sc > score:
                best, score = cid, sc
        if best and score >= 1:
            gr2card[g] = best

    base = newest_baseline()
    LOG.info(f"выгрузка: {base.name}")
    linked_cnt: dict[str, int] = defaultdict(int)
    cand: dict[str, list] = defaultdict(list)
    busy: dict[str, list] = defaultdict(list)

    patterns = []
    for g, items in phr.items():
        cid = gr2card.get(g)
        if not cid:
            continue
        for ph in items:
            st = stems(ph)
            if len(st) >= 2:
                patterns.append((cid, g, ph, st))
    LOG.info(f"фраз к сопоставлению: {len(patterns)}")

    n = 0
    for line in base.open(encoding="utf-8"):
        if not line.strip():
            continue
        n += 1
        rec = json.loads(line)
        f = rec.get("fields") or {}
        cur_links = [str(x).replace("-", "") for x in (f.get("Серия / массив") or [])]
        for cid in cur_links:
            linked_cnt[cid] += 1
        title = str(f.get("Название источника") or "")
        if not title:
            continue
        low = title.lower()
        ys = [int(y) for y in YEAR.findall(title)]
        for cid, g, ph, st in patterns:
            if cid in cur_links:
                continue
            if not all(s in low for s in st):
                continue
            lo, hi = cards[cid]["низ"], cards[cid]["верх"]
            if ys and lo and hi and not any(lo - 2 <= y <= hi + 2 for y in ys):
                continue
            row = {"page_id": rec.get("page_id", ""),
                   "url": f.get("Ссылка на онлайн-архив", ""), "название": title[:160],
                   "фраза": ph, "группа": g}
            (busy if cur_links else cand)[cid].append(row)
            break

    LOG.info(f"записей каталога просмотрено: {n}")
    report = []
    for cid, c0 in sorted(cards.items(), key=lambda x: -len(cand.get(x[0], []))):
        if not cand.get(cid) and not busy.get(cid):
            continue
        report.append({"карточка": c0["имя"], "id": cid,
                       "уже привязано": linked_cnt.get(cid, 0),
                       "кандидатов (без серии)": len(cand.get(cid, [])),
                       "кандидатов (уже в другой серии)": len(busy.get(cid, [])),
                       "примеры": cand.get(cid, [])[:5],
                       "спорные примеры": busy.get(cid, [])[:3]})
        LOG.info(f"{len(cand.get(cid, [])):6} + {len(busy.get(cid, [])):5} спорн.  "
                 f"{c0['имя'][:66]}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "кандидаты_привязки.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    full = {cid: cand[cid] for cid in cand}
    (OUT / "кандидаты_привязки_полные.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    LOG.info(f"→ {OUT / 'кандидаты_привязки.json'}")


if __name__ == "__main__":
    main()
