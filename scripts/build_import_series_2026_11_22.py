"""Сборка набора 4.1 «серийный улов» в пакет заливки (jsonl + CSV + export_review.json).

Вход (соединение по ключу pack+n — так его строил классификатор):
  * output/upload_2026-11-16-series/classified.jsonl — класс, административный уровень,
    территория (батчи 16.11, 118 вызовов);
  * output/triage_G/harvested.jsonl       (pack ser_nash, «наши губернии»);
  * output/triage_G/harvested_mezh.jsonl  (pack ser_mezh, межгубернские)
    — URL, полное название, годы, масштаб и шифр из заголовка.

Выход: output/upload_2026-11-22-series/paket_k_zalivke.jsonl + review_run/{CSV,json}

Чего НЕ пишем (пустое поле честнее неверного):
  * «Серия / массив» — поле `серия` в улове это метка словаря ПОИСКА, а не атрибуция
    серии (грабля реестра: 539 ложных связей). Атрибуция — отдельным проходом
    scripts/attribute_series.py после заливки, как сделано 22.11 для 3 003 записей;
  * «Тип источника» — для этого набора разметка типов не прогонялась (typed.jsonl нет);
  * «Год сведений» при диапазоне лет — поле единичного значения (правило preflight).

Масштаб берётся ТОЛЬКО из заголовка карточки. Эвристику «вёрсты → знаменатель» здесь
не применяем: догадка в числовом поле отравляет подсчёты (42 615 записей каталога уже
пострадали так).

  python scripts/build_import_series_2026_11_22.py [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
CLS = OUT / "upload_2026-11-16-series" / "classified.jsonl"
PACKS = {"ser_nash": "triage_G/harvested.jsonl",
         "ser_mezh": "triage_G/harvested_mezh.jsonl"}
WORK = OUT / "upload_2026-11-22-series"
REVIEW = WORK / "review_run"
SAMPLE = OUT / "upload_2026-11-16" / "belinka_review_run" / "notion_import.csv"

# домен держателя -> (краткое имя, название в справочнике «Архивы»).
# ВАЖНО: названия в справочнике идут С АББРЕВИАТУРОЙ В СКОБКАХ; без неё мост
# не резолвит relation — 21.11 так потерялись 222 записи.
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
# select-поля Notion не принимают запятую в значении (инцидент 21.11: 176 отказов)
SELECTS = ("Масштаб: источник значения", "Год: источник значения",
           "Территория: источник значения", "Административный уровень: источник значения",
           "Административный уровень", "Статус доступа")
DENOM = re.compile(r"1\s*[:\s]\s*([\d\s .,]{3,})")
SCALE_SRC = "из заголовка карточки"
# Периодика: «Сталинский ударник 1953/12» — номер выпуска в названии. Улов словаря
# поиска по Пермской краевой затянул 414 таких записей. ВАЖНО: слепой отсев по этому
# шаблону режет и «Пермские губернские ведомости 1856–1916» (160 записей) —
# первостепенный источник по землевладению и межеванию, и «Пермские епархиальные
# ведомости» (50). Поэтому граница по году выпуска, а не по шаблону: 1918 и позже —
# советская и постсоветская периодика, вне скоупа карт XVIII — начала XX в.
ISSUE = re.compile(r"\b(1[89]\d\d|20[0-2]\d)\s*/\s*\d+\b")
SCOPE_YEAR = 1918


def shelf_mark(raw: str | None) -> str:
    """Шифр для ЭТОГО набора не пишется вообще — поле `шифр_из_заголовка` негодное.

    Проверено на пакете 22.11: из 142 значений 71 оказались названием или территорией
    («Карта Смоленской губернии», «Кунгурский уезд», «Красноуфимский уезд») — парсер
    улова откатывался на начало строки. Отсев по признакам оставил 66, но и они
    поголовно названия выпусков: «Книжка 6», «Колхозный путь 1961/163»,
    «Клуб юристов 2015/1». Ни одного настоящего шифра хранения в выборке не нашлось,
    поэтому фильтровать нечего — поле остаётся пустым и доливается отдельным проходом
    по карточкам держателей. Пустое поле честнее неверного, а неверный шифр ещё и
    выглядит как факт.
    """
    return ""


def denominator(raw: str | None) -> str:
    """Знаменатель масштаба из записи заголовка. «1:11 550 000» -> «11550000»."""
    if not raw:
        return ""
    m = DENOM.search(str(raw))
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(1))
    return digits if 3 <= len(digits) <= 9 else ""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    src: dict[tuple[str, int], dict] = {}
    for pack, rel in PACKS.items():
        for n, line in enumerate((OUT / rel).open(encoding="utf-8")):
            if line.strip():
                src[(pack, n)] = json.loads(line)

    cls = [json.loads(ln) for ln in CLS.open(encoding="utf-8") if ln.strip()]
    WORK.mkdir(parents=True, exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    cols = next(csv.reader(SAMPLE.open(encoding="utf-8-sig")))

    # уже созданное прошлым заходом исключаем по журналу моста
    done: set[str] = set()
    jrn = REVIEW / "created_pages.jsonl"
    if jrn.exists():
        for ln in jrn.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["url"].rstrip("/"))
            except Exception:
                continue
        print(f"уже создано прошлым заходом: {len(done)} — исключаю")

    pkg: list[dict] = []
    out_rows: list[dict] = []
    recs: list[dict] = []
    seen: set[str] = set()
    stat = dict.fromkeys(
        ["нет исходника", "нет url", "дубль внутри набора", "неизвестный домен",
         "уже создано", "с годом", "с шифром", "с масштабом"], 0)

    for r in cls:
        s = src.get((r["pack"], r["n"]))
        if not s:
            stat["нет исходника"] += 1
            continue
        url = (s.get("url") or "").strip()
        if not url:
            stat["нет url"] += 1
            continue
        key = url.rstrip("/")
        if key in done:
            stat["уже создано"] += 1
            continue
        if key in seen:
            stat["дубль внутри набора"] += 1
            continue
        host = urlparse(url).netloc
        if host not in HOLDER:
            stat["неизвестный домен"] += 1
            continue
        seen.add(key)
        holder, archive = HOLDER[host]

        title = (s.get("полное_название") or s.get("title") or "").strip()
        lo = (s.get("год_нижний") or "").strip() or None
        hi = (s.get("год_верхний") or "").strip() or None
        raw_scale = s.get("масштаб_из_заголовка")
        scale = denominator(raw_scale)
        shelf = shelf_mark(s.get("шифр_из_заголовка")) or None

        pkg.append({
            "url": url, "zagolovok_polnyi": title, "holder": holder,
            "год_нижний": lo, "год_верхний": hi,
            "год_источник": SCALE_SRC if lo else "",
            "scale": scale or None, "scale_src": SCALE_SRC if scale else "",
            "scale_ctx": raw_scale if scale else None, "shelf": shelf,
            "class": r.get("class"), "level": r.get("level"), "terr": r.get("terr"),
            "metka_ulova": s.get("серия"), "pack": r["pack"],
        })

        line = dict.fromkeys(cols, "")
        line["Название источника"] = title
        line["Ссылка на онлайн-архив"] = url
        line["Место хранения"] = archive
        line["Статус доступа"] = "Открытый доступ"
        if lo:
            line["Год создания (нижняя)"] = lo
            line["Год создания (верхняя)"] = hi or lo
            if lo == hi:
                line["Год сведений"] = lo
            line["Год: источник значения"] = SCALE_SRC
            stat["с годом"] += 1
        if shelf:
            line["Библиотечный шифр"] = shelf
            stat["с шифром"] += 1
        if scale:
            line["Масштаб (знаменатель)"] = scale
            line["Масштаб: источник значения"] = SCALE_SRC
            line["Оригинальный масштаб"] = raw_scale or ""
            stat["с масштабом"] += 1
        if r.get("level") and r["level"] != "нет":
            line["Административный уровень"] = r["level"]
            line["Административный уровень: источник значения"] = "по заголовку (модель)"
        line["Территория: источник значения"] = "по заголовку (модель)"
        line["Примечания"] = (
            "Серийный улов библиотек 13–16.11.2026; классификация батчами 16.11; "
            f"класс «{r.get('class', '')}»; «Серия / массив» заполняется отдельным "
            "проходом атрибуции (метка улова — след словаря поиска)")
        for col in SELECTS:
            if "," in str(line.get(col, "")):
                line[col] = str(line[col]).replace(",", " —")
        out_rows.append(line)

        recs.append({
            "url": url,
            "relations": [{"property": "Архив хранения", "source_label": archive}],
            "territory_hints": [r["terr"]] if r.get("terr") else [],
        })
        if args.limit and len(out_rows) >= args.limit:
            break

    with (WORK / "paket_k_zalivke.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for rec in pkg:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with (REVIEW / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    (REVIEW / "export_review.json").write_text(
        json.dumps({"records": recs}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nстрок CSV: {len(out_rows)} | relations: {len(recs)}")
    for k, v in stat.items():
        print(f"  {k}: {v}")
    print(f"-> {REVIEW}")


if __name__ == "__main__":
    main()
