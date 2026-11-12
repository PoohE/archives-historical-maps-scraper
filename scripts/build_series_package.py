"""Второй маршрут отбора: СЕРИЙНЫЕ издания, у которых в заголовке нет нашей губернии.

Зачем отдельный сборщик. Общий гейт (`scripts_gaso/build_gaso_package.apply_gate`) и сборщик
РГБ требуют территориального якоря — дачи, села, уезда, губернии. Для архивных дел это верно,
но межгубернские серийные издания названы без губернии вовсе («Специальная карта западной
части Российской империи», «Российский атлас», «Подробная карта Российской империи…»),
и поэтому систематически выпадали из улова. Сверка 07.11.2026: в каталоге из 112 202 записей
не было ни одного листа десятивёрстки Шуберта.

Здесь якорем служит САМА СЕРИЯ: её охват установлен разбором и задан в SERIES ниже.
Автоматически в каталог ничего не идёт: привязка листа к серии требует сверки номера листа,
это решение приёмщика. Всё, что прошло, получает статус needs_human с указанием причины.

  python build_series_package.py            # собрать пакет
  python build_series_package.py --stats    # только сводка
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout  # noqa: E402

SRC = ROOT / "output" / "series_library_sweep" / "hits.jsonl"
OUT = ROOT / "output" / "series_package_20261107"

HOST_RE = re.compile(r"^https?://(?:www\.)?([^/]+)", re.I)
RECORD_URL = re.compile(
    r"search\.rsl\.ru/ru/record/\d+"
    r"|rusneb\.ru/catalog/[0-9A-Za-z_]+"
    r"|prlib\.ru/item/\d+"
    r"|elib\.rgo\.ru/handle/[0-9/]+"
    r"|primo\.nlr\.ru/.*(permalink|fulldisplay)",
    re.I,
)
# Страницы-СПИСКИ, а не карточки: у РГО тот же /handle/, но с параметрами постраничного
# перебора или формой поиска. Их улики относятся к соседним записям коллекции, не к самой
# странице, и в пакет идти не должны.
LISTING_URL = re.compile(r"[?&](offset|start|rpp|query|sort_by|filter_)|simple-search|/browse", re.I)
# Произведения-однофамильцы по ключевым словам: другая война, другой театр, другая часть света.
GLOBAL_NO = re.compile(
    r"западно-?европейск|театр\w*\s+войн|европейск\w+\s+войн|мировой\s+войн", re.I)
HOLDER = {
    "search.rsl.ru": "РГБ",
    "rusneb.ru": "НЭБ",
    "kp.rusneb.ru": "НЭБ",
    "prlib.ru": "ПБ",
    "elib.rgo.ru": "Картфонд РГО",
    "primo.nlr.ru": "РНБ",
    "nlr.ru": "РНБ",
}

# Серия: как опознать, что НЕ она, и какие губернии проекта она покрывает (по разбору).
SERIES = {
    "серия 8 — Шуберт, десятивёрстка 1:420 000": {
        "yes": re.compile(
            r"западн\w+ част\w+ рос|зап\.?\s*части\s*рос"
            r"|спец\w*\.?\s*карт\w*\s+(западн|зап\.)", re.I),
        "no": re.compile(
            r"план\s+павловска|военно-дорожн|тригонометрическ\w+ съемк|топографическ\w+ "
            r"карт\w+ санкт-петербургской|1/210|1/1680000",
            re.I,
        ),
        "gub": "Калужская; Смоленская; Ярославская",
        "note": "Калужская — лист XXX, Смоленская — XXIII и XXIX, Ярославская — XIX–XX; "
                "Пермская губерния в охват НЕ входит",
    },
    "серия 13 — Стрельбицкий 1:420 000": {
        "yes": re.compile(r"стрельбиц|спец\w*\.?\s*карт\w*\s+европейск", re.I),
        "no": re.compile(r"западн\w+ част|шуберт", re.I),
        "gub": "Калужская; Смоленская; Ярославская; Пермская",
        "note": "охват — вся Европейская Россия; номер листа сверять по сборной таблице",
    },
    "серия 10 — трёхвёрстка 1:126 000": {
        "yes": re.compile(r"трёхвёрст|трехверст|3\s*верст|три\s+версты|1\s*:\s*126\s*000", re.I),
        "no": re.compile(r"стрельбиц|западн\w+ част\w+ рос", re.I),
        "gub": "Калужская; Смоленская",
        "note": "Ярославская и Пермская в охват трёхвёрстки Западной России не входят",
    },
    "серия 5 — Российский атлас Вильбрехта": {
        "yes": re.compile(r"вильбрехт|российск\w+ атлас", re.I),
        "no": re.compile(r"атлас российск\w+ академии|1745", re.I),
        "gub": "Калужская; Смоленская; Ярославская; Пермская",
        "note": "издания 1792 и 1800 гг.; таблицы условных знаков у атласа нет",
    },
    "серия 5а — Столистовая карта": {
        "yes": re.compile(r"столистов|подробн\w+ карт\w+ российской империи", re.I),
        "no": re.compile(r"стрельбиц|шуберт", re.I),
        "gub": "Калужская; Смоленская; Ярославская; Пермская",
        "note": "Калужская и Смоленская — л. 35, 36 (+46), Ярославская — л. 44, Пермская — л. 78–84",
    },
    "серия 11 — атласы и карты Менде": {
        "yes": re.compile(r"менде", re.I),
        "no": re.compile(r"мендел|менделеев", re.I),
        "gub": "Ярославская",
        "note": "съёмка Менде по Ярославской губернии 1855–1857; прочие наши губернии не снимались",
    },
    "серия 4 — карты и атласы наместничеств": {
        "yes": re.compile(r"наместничеств", re.I),
        "no": re.compile(r"", re.I) if False else re.compile(r"(?!x)x"),
        "gub": "Калужская; Смоленская; Ярославская; Пермская",
        "note": "атлас Калужского наместничества 1782 г. — печатный образец серии",
    },
    "серия 2 — Атлас Российский Академии наук 1745": {
        "yes": re.compile(r"атлас российск\w*.{0,40}(академи|1745)|1745.{0,40}атлас", re.I),
        "no": re.compile(r"вильбрехт", re.I),
        "gub": "Калужская; Смоленская; Ярославская; Пермская",
        "note": "19 специальных карт + генеральная; таблица ≈46 знаков",
    },
    "условные знаки и инструкции": {
        "yes": re.compile(
            r"условн\w+ знак|изъяснен\w+ знак|межев\w+ инструкц|наставлен\w+ землемер"
            r"|правил\w+ для надписыван|инструкц\w+ о съ[её]мк", re.I),
        "no": re.compile(r"(?!x)x"),
        "gub": "",
        "note": "материал для главы 5А пособия и статьи о преемственности знаков",
    },
}

YEAR = re.compile(r"\b(1[5-9]\d{2}|19[0-3]\d)\b")
MODERN = re.compile(r"\bСССР\b|Российск\w+ Федерац|\b19[5-9]\d\b|\b20\d\d\b", re.I)
CARTO = re.compile(r"\[Карты\]|карт|план|атлас|чертеж|чертёж|съемк|съёмк|топограф|знак", re.I)

OUT_FIELDS = [
    "holder", "record_url", "zagolovok", "seriya", "gub_serii", "data_nachato",
    "data_okoncheno", "gate", "gate_reason", "primechanie",
]


def years(text: str) -> tuple[str | None, str | None]:
    yy = YEAR.findall(text or "")
    if not yy:
        return None, None
    return yy[0], (yy[-1] if yy[-1] != yy[0] else None)


def classify(title: str, snippet: str) -> list[tuple[str, dict]]:
    text = f"{title} {snippet}"
    if GLOBAL_NO.search(text):
        return []
    out = []
    for name, cfg in SERIES.items():
        if cfg["yes"].search(text) and not cfg["no"].search(text):
            out.append((name, cfg))
    return out


def main() -> int:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    by_url: dict[str, dict] = {}
    for line in SRC.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        u = r["url"].split("#")[0].rstrip("/")
        if not RECORD_URL.search(u) or LISTING_URL.search(u):
            continue
        # Аннотации из РАЗНЫХ запросов несут разные куски описания (у одного — номер листа,
        # у другого — масштаб). Склеиваем их все, иначе улика теряется при дедупе.
        prev = by_url.get(u)
        sn = (r.get("snippet") or "").strip()
        if prev is None:
            by_url[u] = {**r, "url": u, "snippets": [sn] if sn else []}
        else:
            if sn and sn not in prev["snippets"]:
                prev["snippets"].append(sn)
            if len(r.get("title") or "") > len(prev.get("title") or ""):
                prev["title"] = r["title"]
    for r in by_url.values():
        r["snippet"] = " │ ".join(r.get("snippets", []))

    rows, stats = [], Counter()
    for u, r in sorted(by_url.items()):
        title = re.sub(r"\s*[-–]\s*(Search RSL|НЭБ.*|Президентская библиотека.*)$", "",
                       r.get("title") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        hits = classify(title, snippet)
        if not hits:
            stats["отсев: серия не опознана"] += 1
            continue
        host = (HOST_RE.match(u).group(1) if HOST_RE.match(u) else "").lower()
        holder = HOLDER.get(host, host)
        text = f"{title} {snippet}"
        if not CARTO.search(text):
            stats["отсев: не картографический предмет"] += 1
            continue
        d1, d2 = years(text)
        for name, cfg in hits:
            # современные переиздания отличаем по году; у серий верхняя граница 1930-е
            if MODERN.search(text) and not d1:
                gate, reason = "отсев", "современное издание без исторической датировки"
            else:
                gate = "needs_human"
                reason = (
                    "опознано по названию серии, территориального якоря в заголовке нет — "
                    "привязка листа к серии требует сверки номера листа приёмщиком"
                )
            stats[f"{name}: {gate}"] += 1
            rows.append({
                "holder": holder,
                "record_url": u,
                "zagolovok": title[:300],
                "seriya": name,
                "gub_serii": cfg["gub"],
                "data_nachato": d1,
                "data_okoncheno": d2,
                "gate": gate,
                "gate_reason": reason,
                "primechanie": f"{cfg['note']}. Аннотация поиска: {snippet[:220]}",
            })

    print(f"карточек каталогов: {len(by_url)}")
    print(f"строк пакета: {len(rows)}\n")
    for k, v in sorted(stats.items()):
        print(f"  {v:>5}  {k}")

    if args.stats:
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "series_package.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with (OUT / "series_package.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n→ {OUT / 'series_package.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
