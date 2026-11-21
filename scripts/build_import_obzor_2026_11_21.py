"""Сборка ОБЗОРНЫХ источников улова (территория — «Европейская Россия»).

Отличие от основного сборщика: каждой записи добавляется relation
«Охватываемая территория» → «Европейская Россия» (решение владельца 21.11:
общероссийские источники с губернским разрезом вносим, территорию ставим
межгубернскую по правилу rule_territory_multiprovince).

Вход:  output/upload_2026-11-21/paket_k_zalivke.jsonl (после гейта, классификации,
       добора года/масштаба и preflight «ВНОСИТЬ МОЖНО»).
Выход: output/upload_2026-11-21/review_run/{notion_import.csv, export_review.json}

Поля заполняются только фактами карточки. Незаполненное остаётся пустым: пустое
поле честнее неверного и доливается отдельным проходом. Поэтому НЕ пишутся:
  * «Серия / массив» — в улове лежит метка словаря поиска, а не атрибуция серии;
  * «Тип источника» для 348 предположительных кодов (решение владельца 21.11);
  * «Год сведений» при диапазоне лет — поле единичного значения (правило preflight).

  python scripts/build_import_2026_11_21.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "output" / "upload_2026-11-21-obzor"
SRC = WORK / "paket_k_zalivke.jsonl"
OUT = WORK / "review_run"
SAMPLE = ROOT / "output" / "upload_2026-11-16" / "belinka_review_run" / "notion_import.csv"

#: держатель улова → название в справочнике «Архивы». ⚠️ Названия там идут С
#: АББРЕВИАТУРОЙ В СКОБКАХ, и без неё мост не резолвит: 21.11 так потерялись
#: «Картфонд РГО» и «ПГКБ» — 222 записи остались бы без «Архива хранения».
#: Сверять по живому справочнику (archives_map()), а не по старой выгрузке.
ARCHIVE = {
    "ГАЯО": "Государственный архив Ярославской области (ГАЯО)",
    "ПермьКрай": "Пермская государственная краевая библиотека им. А.М. Горького (ПГКБ)",
    "РГБ": "Российская государственная библиотека (РГБ)",
    "НЭБ": "Национальная электронная библиотека (НЭБ)",
    "ПрБ": "Президентская библиотека имени Б.Н. Ельцина (ПБ)",
    "ГПИБ": "Государственная публичная историческая библиотека России (ГПИБ)",
    "РНБ-В": "Российская национальная библиотека (РНБ)",
    "РГО": "Картографический фонд Русского географического общества (Картфонд РГО)",
}
TYPE_REL = ROOT / "output" / "notion_catalog_20261024_181943_relations.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    cols = next(csv.reader(SAMPLE.open(encoding="utf-8-sig")))
    types = json.loads(TYPE_REL.read_text(encoding="utf-8"))["Тип источника"]
    rows = [json.loads(ln) for ln in SRC.open(encoding="utf-8") if ln.strip()]
    OUT.mkdir(parents=True, exist_ok=True)

    # 21.11.2026: первая попытка записи упала на 176 записях — Notion не принимает
    # ЗАПЯТУЮ в значении select («по заголовку, модель»). Поля происхождения значения —
    # select, поэтому перед записью они чистятся, а не проверяются глазами.
    SELECTS = ("Масштаб: источник значения", "Год: источник значения",
               "Территория: источник значения", "Административный уровень: источник значения",
               "Административный уровень", "Статус доступа")
    done = set()
    jrn = OUT / "created_pages.jsonl"
    if jrn.exists():
        for ln in jrn.open(encoding="utf-8"):
            try:
                done.add(json.loads(ln)["url"].rstrip("/"))
            except Exception:
                continue
        print(f"уже создано в прошлый заход: {len(done)} — исключаю из пакета")

    recs, out_rows, no_type = [], [], 0
    for r in rows:
        if (r.get("istochnik_kartochki") or r.get("url") or "").rstrip("/") in done:
            continue
        url = r.get("istochnik_kartochki") or r.get("url")
        lo, hi = r.get("год_нижний"), r.get("год_верхний")
        line = dict.fromkeys(cols, "")
        line["Название источника"] = r.get("zagolovok_polnyi") or ""
        line["Ссылка на онлайн-архив"] = url
        line["Место хранения"] = ARCHIVE.get(r.get("holder"), r.get("holder") or "")
        line["Статус доступа"] = "Открытый доступ"
        if lo:
            line["Год создания (нижняя)"] = lo
            line["Год создания (верхняя)"] = hi or lo
            if lo == hi:                       # единичное значение — можно
                line["Год сведений"] = lo
            line["Год: источник значения"] = r.get("год_источник") or ""
        if r.get("shelf"):
            line["Библиотечный шифр"] = r["shelf"]
        if r.get("scale"):
            line["Масштаб (знаменатель)"] = r["scale"]
            line["Масштаб: источник значения"] = r.get("scale_src") or ""
            if r.get("scale_ctx"):
                line["Оригинальный масштаб"] = r["scale_ctx"]
        if r.get("level") and r["level"] != "нет":
            line["Административный уровень"] = r["level"]
            line["Административный уровень: источник значения"] = "по заголовку (модель)"
        line["Территория: источник значения"] = "обзорный источник — Европейская Россия"
        line["Примечания"] = ("Улов добора 16–20.11.2026; территориальный гейт — «обзорная»; "
                              f"класс «{r.get('class','')}»")
        for col in SELECTS:                      # select не принимает запятую
            if "," in str(line.get(col, "")):
                line[col] = str(line[col]).replace(",", " —")
        out_rows.append(line)

        rel = [{"property": "Архив хранения", "source_label": ARCHIVE.get(r.get("holder"), "")}]
        code = r.get("type_code")
        if code and code in types:
            rel.append({"property": "Тип источника",
                        "target_url": "https://www.notion.so/" + types[code].replace("-", "")})
        else:
            no_type += 1
        rel.append({"property": "Охватываемая территория",
                    "target_url": "https://www.notion.so/3f80ba89eabe816ea713ebd7c24143c5"})
        recs.append({"url": url, "relations": rel,
                     "territory_hints": [r.get("terr_class")] if r.get("terr_class") else []})

    with (OUT / "notion_import.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    (OUT / "export_review.json").write_text(
        json.dumps({"records": recs}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"строк CSV: {len(out_rows)} | relations: {len(recs)} | без «Типа источника»: {no_type}")
    print(f"→ {OUT}")


if __name__ == "__main__":
    main()
