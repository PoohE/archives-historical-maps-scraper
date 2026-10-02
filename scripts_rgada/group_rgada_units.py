# -*- coding: utf-8 -*-
"""РГАДА: группировка дело-уровня в логические карты/атласы для внесения в каталог.

Запрос сессии каталогизации (claude-4e, 2026-10-02): одна строка = один атлас/карта,
части-единицы хранения сворачиваются в поле `units` (диапазон или перечень).

КЛЮЧ: territory + adm_unit(уезд) + title без «Часть N / из M» + масштаб.
⚠️ Уезд в ключе ОБЯЗАТЕЛЕН: title часто generic («Генеральный уездный план м-1 в.»),
без уезда разные уезды слились бы в одну строку.
⚠️ Строки с ПУСТЫМ adm_unit вслепую не группируются — выходят как есть с
`needs_human=true`, территория у них определена только по заголовку.

Вход : rgada_units_our_gubernias.csv (779), rgada_f1356_op2_op3_our_gubernias.csv (26)
Выход: *_grouped.csv рядом с ними.
"""
import csv
import io
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\rgada_CONSOLIDATED")

PART = re.compile(r"\s*[.,]?\s*(часть|ч\.)\s*[IVXЧ\d]+\s*(\(\s*из\s+\d+\s*част\w*\)|\(\s*1-я\s+часть\s*\))?", re.I)
PART_TAIL = re.compile(r"\s*\(\s*(из\s+\d+\s+част\w*|1-я\s+часть)\s*\)\s*$", re.I)
# «м-7 в.», «м-2-в», «м-1 в» — хвост НЕ жадный: `в[\w.]*` цеплял «в.Часть»
# и рвал один атлас на две строки (№4306 vs 4307-4330).
SCALE = re.compile(r"м\s*-\s*\d+\s*-?\s*в\.?(?![\wА-Яа-я])", re.I)
# «(в 2-х частях)», «в 25-ти частях», «в 30 частях» — это метаданные комплекта, не название
DECLARED = re.compile(r"\(?\s*в\s+(\d+)\s*(?:-?\s*(?:ти|х|и))?\s*част\w*\s*\)?", re.I)

COLS = ["fund", "opis", "opis_name", "territory", "adm_unit", "title", "scale",
        "units", "parts_count", "parts_declared", "sheets", "dating", "year_from", "year_to",
        "note", "source", "level", "opis_pdf", "opis_url", "image", "needs_human"]


def declared_parts(title: str) -> str:
    m = DECLARED.search(title or "")
    return m.group(1) if m else ""


def strip_part(title: str) -> str:
    """Название без служебных хвостов: «Часть N», «в N частях» и масштаб выносятся в свои поля.

    Иначе один комплект рвётся из-за порядка слов: №4306 «…в 25-ти частях. Часть 1 м-2 в.»
    против №4307 «…в 25-ти частях м-2 в.Часть 2» — разные строки при одинаковом атласе.
    """
    t = PART.sub(" ", title or "")
    t = PART_TAIL.sub(" ", t)
    t = DECLARED.sub(" ", t)
    t = SCALE.sub(" ", t)
    t = re.sub(r"[\s.,;]+", " ", t)
    return t.strip(" .,;")


def scale_of(row: dict) -> str:
    if (row.get("scale") or "").strip():
        return row["scale"].strip()
    m = SCALE.search(row.get("title") or "")
    if not m:
        return ""
    # «м-2 в.» в конце строки и «м-2 в» перед словом «Часть» — один масштаб:
    # конечную точку нормализуем, иначе комплект снова рвётся на две строки.
    return re.sub(r"\s+", " ", m.group(0)).strip().rstrip(".").strip()


def squash(nums: list[str]) -> tuple[str, int]:
    """Список номеров ед.хр. → «4491–4519» для сплошного ряда, иначе перечень через запятую."""
    ints = sorted({int(n) for n in nums if n.isdigit()})
    if not ints:
        return ", ".join(sorted(set(nums))), len(nums)
    if len(ints) > 1 and ints[-1] - ints[0] + 1 == len(ints):
        return f"{ints[0]}\u2013{ints[-1]}", len(ints)
    return ", ".join(str(i) for i in ints), len(ints)


def group(src: str, dst: str, uezd_field: str) -> None:
    rows = list(csv.DictReader((OUT / src).open(encoding="utf-8-sig")))
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    loners: list[dict] = []
    for r in rows:
        uezd = (r.get(uezd_field) or "").strip()
        if not uezd:                       # §: территория только по заголовку → на глаз
            loners.append(r)
            continue
        buckets[(r["fund"], r["opis"], r["territory"], uezd,
                 strip_part(r["title"]), scale_of(r))].append(r)

    out: list[dict] = []
    for (fund, opis, terr, uezd, title, scale), grp in buckets.items():
        units, n = squash([g["unit"] for g in grp])
        first = grp[0]
        sheets = [g.get("sheets", "") for g in grp if (g.get("sheets") or "").strip()]
        out.append({
            "fund": fund, "opis": opis, "opis_name": first.get("opis_name", ""),
            "territory": terr, "adm_unit": uezd, "title": title, "scale": scale,
            "units": units, "parts_count": n,
            "parts_declared": declared_parts(first["title"]),
            "sheets": "; ".join(sheets) if sheets else "",
            "dating": first.get("dating", ""),
            "year_from": first.get("year_from", ""), "year_to": first.get("year_to", ""),
            "note": first.get("note", ""), "source": "rgada", "level": "unit",
            "opis_pdf": first.get("opis_pdf", ""), "opis_url": first.get("opis_url", ""),
            "image": first.get("image", ""), "needs_human": "false",
        })
    for r in loners:
        out.append({
            "fund": r["fund"], "opis": r["opis"], "opis_name": r.get("opis_name", ""),
            "territory": r["territory"], "adm_unit": "", "title": r["title"],
            "scale": scale_of(r), "units": r["unit"], "parts_count": 1,
            "parts_declared": declared_parts(r["title"]),
            "sheets": r.get("sheets", ""), "dating": r.get("dating", ""),
            "year_from": r.get("year_from", ""), "year_to": r.get("year_to", ""),
            "note": r.get("note", ""), "source": "rgada", "level": "unit",
            "opis_pdf": r.get("opis_pdf", ""), "opis_url": r.get("opis_url", ""),
            "image": r.get("image", ""), "needs_human": "true",
        })

    # Комплект собран не полностью («в 5 частях», а найдено 4) — это не всегда ошибка
    # группировки: в описи встречаются варианты заголовка и выбывшие части. На приёмку.
    for x in out:
        if x["parts_declared"] and str(x["parts_declared"]) != str(x["parts_count"]):
            x["needs_human"] = "true"
            x["note"] = (x["note"] + "; " if x["note"] else "") + \
                f"заявлено частей {x['parts_declared']}, собрано {x['parts_count']} — сверить по описи"

    out.sort(key=lambda x: (x["fund"], x["opis"], x["territory"], x["adm_unit"], x["title"]))
    with (OUT / dst).open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    grouped = len(out) - len(loners)
    print(f"{src}: {len(rows)} дел → {len(out)} строк "
          f"({grouped} сгруппировано, {len(loners)} на ручную проверку — пустой уезд)")
    import collections
    print("   по губерниям:", dict(collections.Counter(x["territory"] for x in out)))
    big = sorted(out, key=lambda x: -x["parts_count"])[:3]
    for b in big:
        print(f"   пример: {b['adm_unit']} | {b['title'][:46]} | ед.хр. {b['units']} ({b['parts_count']} ч.)")
    print(f"   → {OUT / dst}")


def main() -> None:
    group("rgada_units_our_gubernias.csv",
          "rgada_units_our_gubernias_grouped.csv", "adm_unit")
    print()
    group("rgada_f1356_op2_op3_our_gubernias.csv",
          "rgada_f1356_op2_op3_grouped.csv", "uezd")


if __name__ == "__main__":
    main()
