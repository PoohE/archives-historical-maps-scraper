"""Пакет заливки по разбору 318 «на разбор»: 83 дореволюционных источника (23.11.2026).

Откуда берётся. `razbor_318_na_razbor_2026_11_22.py` разобрал группу «на разбор»: год добран
обходом карточек, решение владельца о границе 1918 года применилось само, и 114 записей
оказались дореволюционными и в скоупе. Решение владельца 23.11.2026 — заливать.

Две вещи, которые здесь делаются иначе, чем в `build_import_series_2026_11_22.py`:

  1. **Одна запись на книгу, а не на страницу просмотрщика.** В ссылках ПГКБ номер страницы
     стоит параметром (`node/24853?fragment=page-14`), и улов отметил каждую страницу, где
     сработал словарь. 114 записей — это 85 книг. В каталог идёт нормализованная ссылка на
     узел, по одной записи на книгу; какие страницы улова свелись в неё, пишется в примечание.
     Тот же дефект уже сидит в залитом наборе 4.1 (50 книг → 240 записей,
     `dedupe_permkrai_fragment_2026_11_22.py`), и повторять его нельзя.

  2. **Год с указанием места, откуда взят.** В «Год: источник значения» идёт не общее «из
     заголовка карточки», а конкретное поле: «Дата публикации» на карточке ПГКБ, «Год
     издания» у НЭБ, выходные данные библиографического описания. Контекст совпадения
     остаётся в журнале добора — дату можно проверить глазами, не повторяя обход.

Поля класса, административного уровня и территории берутся из `paket_k_zalivke.jsonl`
(разметка батчами 16.11), масштаб — только из заголовка карточки, шифр не пишется вовсе
(у этого набора поле негодное — см. докстринг build_import_series_2026_11_22.py).

  python scripts/build_import_razbor_318_2026_11_23.py <harvested_all.jsonl>
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
WORK = OUT / "upload_2026-11-22-series"
LIST = WORK / "decisions" / "razbor_318" / "v_skoupe.csv"
PKG = WORK / "paket_k_zalivke.jsonl"
STATE = WORK / "pages_state.jsonl"
DEST = OUT / "upload_2026-11-23-razbor318"
REVIEW = DEST / "review_run"
SAMPLE = OUT / "upload_2026-11-16" / "belinka_review_run" / "notion_import.csv"

HOLDER = {
    "lib.permkrai.ru": ("ПермьКрай",
                        "Пермская государственная краевая библиотека им. А.М. Горького (ПГКБ)"),
    "rusneb.ru": ("НЭБ", "Национальная электронная библиотека (НЭБ)"),
    "search.rsl.ru": ("РГБ", "Российская государственная библиотека (РГБ)"),
    "www.prlib.ru": ("ПрБ", "Президентская библиотека имени Б.Н. Ельцина (ПБ)"),
    "vivaldi.nlr.ru": ("РНБ-В", "Российская национальная библиотека (РНБ)"),
    "elib.shpl.ru": ("ГПИБ",
                     "Государственная публичная историческая библиотека России (ГПИБ)"),
    "elib.rgo.ru": ("РГО",
                    "Картографический фонд Русского географического общества (Картфонд РГО)"),
}
SELECTS = ("Масштаб: источник значения", "Год: источник значения",
           "Территория: источник значения", "Административный уровень: источник значения",
           "Административный уровень", "Статус доступа")
DENOM = re.compile(r"1\s*[:\s]\s*([\d\s .,]{3,})")


def node(url: str) -> str:
    """Ссылка на книгу: без страницы просмотрщика и без адреса скачивания PDF."""
    u = re.sub(r"[?&]fragment=page-\d+", "", url or "").rstrip("/")
    return re.sub(r"/pdfbook/download/.*$", "", u)


def denominator(raw: str | None) -> str:
    if not raw:
        return ""
    m = DENOM.search(str(raw))
    if not m:
        return ""
    d = re.sub(r"\D", "", m.group(1))
    return d if 3 <= len(d) <= 9 else ""


def year_source(locator: str) -> str:
    """Человеческая формулировка источника года для поля «Год: источник значения»."""
    loc = (locator or "").strip()
    if not loc:
        return "из заголовка карточки"
    if "выходные данные" in loc:
        return "выходные данные библиографического описания"
    return f"подписанное поле карточки «{loc}»"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("harvested", help="журнал добора года (harvested_all.jsonl)")
    args = ap.parse_args()

    harv: dict[str, dict] = {}
    for ln in Path(args.harvested).open(encoding="utf-8"):
        if ln.strip():
            r = json.loads(ln)
            harv[(r.get("url") or "").rstrip("/")] = r

    pkg_by_url = {}
    for ln in PKG.open(encoding="utf-8"):
        if ln.strip():
            r = json.loads(ln)
            pkg_by_url[r["url"].rstrip("/")] = r

    # Что уже в каталоге: страницы этого набора ПЛЮС журналы всех заливок. Одной
    # pages_state.jsonl мало — 23.11 так в пакет прошла запись node/25191, внесённая
    # прогоном 22.11; поймал её только офлайн-гейт. Поэтому читаем журналы так же,
    # как их читает dedup_gate_offline.py.
    in_catalog = {node(json.loads(ln).get("url") or "")
                  for ln in STATE.open(encoding="utf-8") if ln.strip()}
    for pat in ("*/created_pages.jsonl", "*/*/created_pages.jsonl",
                "*/created.jsonl", "*/*/created.jsonl"):
        for p in sorted(OUT.glob(pat)):
            for ln in p.open(encoding="utf-8"):
                if not ln.strip():
                    continue
                try:
                    in_catalog.add(node(json.loads(ln).get("url") or ""))
                except json.JSONDecodeError:
                    continue

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in csv.DictReader(LIST.open(encoding="utf-8-sig")):
        groups[node(r["ссылка"])].append(r)
    print(f"записей в скоупе: {sum(len(v) for v in groups.values())} | книг: {len(groups)}")

    cols = next(csv.reader(SAMPLE.open(encoding="utf-8-sig")))
    REVIEW.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    recs: list[dict] = []
    stat = dict.fromkeys(["уже в каталоге", "неизвестный домен", "нет исходника",
                          "с годом", "с масштабом", "свёрнуто страниц улова"], 0)

    for key, rs in sorted(groups.items()):
        if key in in_catalog:
            stat["уже в каталоге"] += 1
            continue
        host = urlparse(key).netloc
        if host not in HOLDER:
            stat["неизвестный домен"] += 1
            continue
        src = pkg_by_url.get(rs[0]["ссылка"].rstrip("/"))
        if not src:
            stat["нет исходника"] += 1
            continue
        _, archive = HOLDER[host]
        h = harv.get(rs[0]["ссылка"].rstrip("/"), {})
        god = rs[0]["год"]
        raw_scale = src.get("scale_ctx")
        scale = denominator(raw_scale) or (str(src["scale"]) if src.get("scale") else "")

        line = dict.fromkeys(cols, "")
        line["Название источника"] = (h.get("zagolovok_polnyi")
                                      or src.get("zagolovok_polnyi") or "").strip()
        line["Ссылка на онлайн-архив"] = key
        line["Место хранения"] = archive
        line["Статус доступа"] = "Открытый доступ"
        if god:
            line["Год создания (нижняя)"] = god
            line["Год создания (верхняя)"] = god
            line["Год сведений"] = god
            line["Год: источник значения"] = year_source(h.get("god_locator", ""))
            stat["с годом"] += 1
        if scale:
            line["Масштаб (знаменатель)"] = scale
            line["Масштаб: источник значения"] = "из заголовка карточки"
            line["Оригинальный масштаб"] = raw_scale or ""
            stat["с масштабом"] += 1
        if src.get("level") and src["level"] != "нет":
            line["Административный уровень"] = src["level"]
            line["Административный уровень: источник значения"] = "по заголовку (модель)"
        line["Территория: источник значения"] = "по заголовку (модель)"
        pages = len(rs)
        if pages > 1:
            stat["свёрнуто страниц улова"] += pages - 1
        note = ("Серийный улов библиотек 13–16.11.2026; разбор группы «на разбор» 23.11.2026: "
                f"класс «{src.get('class', '')}», год {god or 'не установлен'} "
                f"({year_source(h.get('god_locator', ''))})"
                + (f"; свёрнуто {pages} записей улова по одной книге — различались только "
                   "номером страницы просмотрщика в ссылке" if pages > 1 else "")
                + "; «Серия / массив» заполняется отдельным проходом атрибуции")
        line["Примечания"] = note
        bib = (h.get("bibl_opisanie") or "").strip()
        if bib:
            line["Библиографическое описание"] = bib
        for col in SELECTS:
            if "," in str(line.get(col, "")):
                line[col] = str(line[col]).replace(",", " —")
        rows.append(line)
        recs.append({"url": key,
                     "relations": [{"property": "Архив хранения", "source_label": archive}],
                     "territory_hints": [src["terr"]] if src.get("terr") else []})

    with (REVIEW / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    (REVIEW / "export_review.json").write_text(
        json.dumps({"records": recs}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nстрок CSV: {len(rows)} | relations: {len(recs)}")
    for k, v in stat.items():
        print(f"  {k}: {v}")
    print(f"пакет: {REVIEW}")


if __name__ == "__main__":
    main()
