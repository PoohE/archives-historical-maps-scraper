"""Следующая партия заливки: четыре накопленных пакета, просеянные гейтом (23.11.2026).

Состав партии (реестр добора, строки 4.2–4.5) и почему она собирается только сейчас:
пакеты лежали готовыми с 7–8 ноября, но ни один не проходил территориального гейта —
у 4.4 «серия 11, Менде» 27 записей из 35 оказались по чужим губерниям (Ковровский уезд
Владимирской, Калязинский и Ржевский Тверской, Липецкий и Моршанский Тамбовской,
Подольская, Иваново-Вознесенская, окрестности Севастополя). Залей их как «готовое» —
повторилась бы история 270 вне-скоупных записей, найденных уже в каталоге.

Что делает скрипт:
  * берёт из каждого пакета записи, которых НЕТ в каталоге (выгрузка 15.11 + все журналы
    заливок — одной pages_state мало, проверено 23.11);
  * прогоняет заголовок через `territory_gate.classify` и раскладывает по вердикту;
  * «чужая» — в отсев с записью решения, в каталог не идёт;
  * год 1918 и позже — в отсев ДО решения владельца по строкам 4.27–4.28 реестра
    («советские издания дореволюционных данных» — класса в правилах пока нет);
  * остальное собирает в notion_import.csv + export_review.json для моста.

Решения владельца 23.11.2026, по которым собрана партия:
  1. 62 записи по условным знакам («территория не названа» по природе источника —
     это легенды и справочники знаков) ВКЛЮЧИТЬ;
  2. 55 записей РГИА ф. 380 с `fgurgia.ru` ВКЛЮЧИТЬ. Новых запросов к порталу не
     делается: данные сняты прошлыми прогонами до обнаружения запрета robots. В примечание
     каждой записи идёт та же пометка провенанса, что у 441 записи от 15.11.

Чего скрипт НЕ пишет:
  * «Серия / массив» — у 4.2 и 4.3 в пакете лежит МЕТКА СЕРИИ ПОИСКА, а не атрибуция
    (реестр: 539 ложных связей на этом). Заполняется отдельным проходом attribute_series;
  * значения, начинающиеся с «⚠️» (у 4.2 так помечен административный уровень листа
    межгубернской серии) — в select такое не кладём;
  * поля, унаследованные от серии и не сверенные по листу, остаются как есть в пакете 4.2,
    но факт наследования виден в «Примечания по оцифровке» — так его собрал package_full_fields.

  python scripts/build_import_partiya_2026_11_23.py
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from territory_gate import classify, our_gubernii  # noqa: E402

OUT = ROOT / "output"
DEST = OUT / "upload_2026-11-23-partiya"
REVIEW = DEST / "review_run"
SAMPLE = OUT / "upload_2026-11-16" / "belinka_review_run" / "notion_import.csv"
BASELINE = OUT / "notion_catalog_20261115_121359_baseline.jsonl"

ARCHIVE = {
    "РГБ": "Российская государственная библиотека (РГБ)",
    "НЭБ": "Национальная электронная библиотека (НЭБ)",
    "ПрБ": "Президентская библиотека имени Б.Н. Ельцина (ПБ)",
    "ПБ": "Президентская библиотека имени Б.Н. Ельцина (ПБ)",
    "КП": "Национальная электронная библиотека (НЭБ)",
    "РГО": "Картографический фонд Русского географического общества (Картфонд РГО)",
    "РГИА": "РГИА",
}
HOST_HOLDER = {"search.rsl.ru": "РГБ", "rusneb.ru": "НЭБ", "kp.rusneb.ru": "НЭБ",
               "www.prlib.ru": "ПрБ", "prlib.ru": "ПрБ", "elib.rgo.ru": "РГО",
               "fgurgia.ru": "РГИА"}
SELECTS = ("Масштаб: источник значения", "Год: источник значения",
           "Территория: источник значения", "Административный уровень: источник значения",
           "Административный уровень", "Статус доступа", "DC Type", "Язык",
           "Статус приёмки", "Тип источника")
YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")
GRAN = 1918
RGIA_NOTE = ("Провенанс: метаданные сняты с публичного портала РГИА (fgurgia.ru) до "
             "обнаружения адресного запрета в robots.txt — только открытые описания дел; "
             "образы и закрытые данные не запрашивались, защита сайта не обходилась. "
             "Решение владельца 23.11.2026: запись вносится с этой пометкой, дальнейший "
             "машинный сбор на портале не ведётся.")
SETS = [
    ("4.3 обогащённые 07.11", "series_package_20261107/package_ready.jsonl", "series"),
    ("4.4 серия 11 (Менде)", "series_package_20261107/package_held_seriya11.jsonl", "series"),
    ("4.2 группа A 08.11", "package_2026-11-08/package_A_scope.jsonl", "fields"),
    ("4.5 РГИА ф. 380", "rgia380_ours/package_rgia380.jsonl", "rgia"),
]


def norm(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    p = urlparse(u if "//" in u else "//" + u)
    host = (p.netloc or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host + p.path.rstrip("/") + (("?" + p.query) if p.query else "")


def known_urls() -> set[str]:
    """Что уже в каталоге: выгрузка 15.11 плюс журналы ВСЕХ заливок после неё."""
    known: set[str] = set()
    pat = re.compile(r'"Ссылка на онлайн-архив":\s*"([^"]*)"')
    with BASELINE.open(encoding="utf-8") as f:
        for ln in f:
            for u in pat.findall(ln):
                known.add(norm(u))
    for pattern in ("*/created_pages.jsonl", "*/*/created_pages.jsonl",
                    "*/created.jsonl", "*/*/created.jsonl"):
        for p in glob.glob(str(OUT / pattern)):
            for ln in Path(p).open(encoding="utf-8"):
                if ln.strip():
                    try:
                        known.add(norm(json.loads(ln).get("url") or ""))
                    except json.JSONDecodeError:
                        continue
    return known


def year_pair(rec: dict, shape: str, title: str) -> tuple[str, str, str]:
    """(нижний, верхний, источник значения) — только из полей пакета, не из догадки."""
    if shape == "series":
        lo, hi = rec.get("data_nachato"), rec.get("data_okoncheno")
        if lo:
            return str(lo), str(hi or lo), "из заголовка карточки"
    if shape == "rgia":
        ys = YEAR.findall(str(rec.get("date_raw") or ""))
        if ys:
            return ys[0], ys[-1], "из заголовка дела"
    if shape == "fields":
        nf = rec.get("notion_fields") or {}
        lo = nf.get("Год создания (нижняя)") or nf.get("Год сведений")
        hi = nf.get("Год создания (верхняя)") or lo
        if lo:
            return str(lo), str(hi), str(nf.get("Год: источник значения") or "из карточки библиотеки")
    return "", "", ""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cols = next(csv.reader(SAMPLE.open(encoding="utf-8-sig")))
    known = known_urls()
    print(f"известных ссылок (каталог 15.11 + журналы заливок): {len(known)}")

    rows: list[dict] = []
    recs: list[dict] = []
    drops: list[dict] = []
    stat: Counter = Counter()

    for name, rel, shape in SETS:
        for ln in (OUT / rel).open(encoding="utf-8"):
            if not ln.strip():
                continue
            r = json.loads(ln)
            url = r.get("record_url") or r.get("url") or ""
            key = norm(url)
            if not key:
                stat["нет ссылки"] += 1
                continue
            if key in known:
                stat["уже в каталоге"] += 1
                continue
            known.add(key)
            nf = r.get("notion_fields") or {}
            title = (r.get("zagolovok_polnyi") or nf.get("Название источника")
                     or r.get("title") or r.get("zagolovok") or "").strip()
            no_title = False
            if not title and shape == "rgia" and r.get("fund_code"):
                # У 724 дел ф. 380 из 3 738 названия в описи нет вовсе — только машинописный
                # шифр (описи 21 и 37 ждут распознавания). Имя записи строим ИЗ ШИФРА, а не
                # из аннотации описи: аннотация описывает всю опись, и поставить её в
                # название — это ровно тот дефект «откат на общее поле», из-за которого
                # DSpace отдавал название страницы вместо названия дела. Аннотация идёт
                # в «Описание», где она и уместна.
                title = f"{r['fund_code']} (название дела в описи не указано)"
                no_title = True
            if not title:
                stat["без названия"] += 1
                continue
            verdict, why = classify(title)
            lo, hi, ysrc = year_pair(r, shape, title)
            years = [int(y) for y in YEAR.findall(title)] + [int(x) for x in (lo, hi) if str(x).isdigit()]
            late = max(years) if years else None

            if verdict == "чужая":
                drops.append({"набор": name, "причина": f"чужая территория: {why}",
                              "год": late or "", "название": title[:300], "ссылка": url})
                stat["отсев: чужая губерния"] += 1
                continue
            if late and late >= GRAN:
                drops.append({"набор": name,
                              "причина": "год 1918 и позже — отложено до правила по строкам "
                                         "4.27–4.28 реестра (советские издания "
                                         "дореволюционных данных)",
                              "год": late, "название": title[:300], "ссылка": url})
                stat["отложено: 1918+"] += 1
                continue

            host = urlparse(url).netloc.lower()
            holder = r.get("holder") or HOST_HOLDER.get(host, "")
            archive = ARCHIVE.get(holder) or ARCHIVE.get(HOST_HOLDER.get(host, ""), "")
            if not archive:
                drops.append({"набор": name, "причина": f"неизвестный держатель: {holder or host}",
                              "год": late or "", "название": title[:300], "ссылка": url})
                stat["отсев: держатель не опознан"] += 1
                continue

            line = dict.fromkeys(cols, "")
            if shape == "fields":
                # «Серия / массив», «Тип источника» и «Охватываемая территория» — relation,
                # их в CSV моста вообще нет: связи идут через export_review.json. Поэтому
                # из notion_fields переносим только то, что есть среди колонок, и метку
                # серии не переносим никуда (это метка ПОИСКА, а не атрибуция).
                for k, v in nf.items():
                    if k in line and v not in ("", None, []) and not str(v).startswith("⚠️"):
                        line[k] = v
            line["Название источника"] = title
            line["Ссылка на онлайн-архив"] = url
            line["Место хранения"] = archive
            line["Статус доступа"] = line.get("Статус доступа") or "Открытый доступ"
            if lo:
                line["Год создания (нижняя)"], line["Год создания (верхняя)"] = lo, hi
                if lo == hi:
                    line["Год сведений"] = lo
                line["Год: источник значения"] = ysrc
            if shape == "rgia":
                line["Фонд"] = r.get("fund_code", "").split("Оп.")[0].replace("Ф.", "").strip() or "380"
                line["Опись"] = str(r.get("opis") or "")
                line["Единица хранения"] = str(r.get("delo") or "")
            note_set = {"4.3 обогащённые 07.11": "целевой поиск по названиям серий 07.11.2026",
                        "4.4 серия 11 (Менде)": "целевой поиск по серии 11 (Менде) 07.11.2026",
                        "4.2 группа A 08.11": "добор карточек 08.11.2026, поля чек-листа",
                        "4.5 РГИА ф. 380": "фондовый прогон РГИА ф. 380"}[name]
            note = (f"Партия 23.11.2026 (реестр добора, {name}): {note_set}; "
                    f"территориальный гейт — «{verdict}» ({why}). "
                    "«Серия / массив» заполняется отдельным проходом атрибуции.")
            if shape == "rgia":
                note += " " + RGIA_NOTE
                if r.get("opis_annotation"):
                    line["Описание"] = (f"Аннотация описи (не названия дела): "
                                        f"{r['opis_annotation'][:400]}")
                if no_title:
                    note += (" Название дела в описи не указано — в записи стоит шифр; "
                             "уточняется распознаванием описи (реестр, строки 3.33 и 3.59).")
            if r.get("primechanie"):
                note += f" Из пакета: {str(r['primechanie'])[:220]}"
            line["Примечания"] = (str(line.get("Примечания") or "") + " " + note).strip()[:1950]

            hints: list[str] = []
            if verdict == "наша":
                hints = our_gubernii(title) or ([r["gub_serii"]] if r.get("gub_serii") else [])
            elif verdict == "общая":
                hints = ["Европейская Россия"]
            elif shape == "rgia" and r.get("opis_territory"):
                hints = [r["opis_territory"]]
            elif nf.get("Охватываемая территория"):
                hints = [str(nf["Охватываемая территория"])]

            for col in SELECTS:
                if "," in str(line.get(col, "")):
                    line[col] = str(line[col]).replace(",", " —")
            rows.append(line)
            recs.append({"url": url,
                         "relations": [{"property": "Архив хранения", "source_label": archive}],
                         "territory_hints": hints})
            stat[f"к заливке: {verdict}"] += 1

    REVIEW.mkdir(parents=True, exist_ok=True)
    with (REVIEW / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    (REVIEW / "export_review.json").write_text(
        json.dumps({"records": recs}, ensure_ascii=False, indent=1), encoding="utf-8")
    (DEST / "decisions").mkdir(parents=True, exist_ok=True)
    with (DEST / "decisions" / "otsev_i_otlozheno.csv").open(
            "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(drops[0]) if drops else ["набор"])
        w.writeheader()
        w.writerows(drops)

    print(f"\nстрок CSV: {len(rows)} | relations: {len(recs)}")
    for k, v in stat.most_common():
        print(f"  {v:5d}  {k}")
    print(f"  {sum(1 for x in recs if x['territory_hints']):5d}  с подсказкой территории")
    print(f"пакет: {REVIEW}")
    print(f"журнал отсева и отложенного: {DEST / 'decisions' / 'otsev_i_otlozheno.csv'}")


if __name__ == "__main__":
    main()
