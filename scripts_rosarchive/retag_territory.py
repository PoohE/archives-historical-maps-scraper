# -*- coding: utf-8 -*-
"""Переразметка территории в наборе УИАД: строгие правила вместо подстрок.

Повод (04.10): первая разметка ловила подстроки и дала 486 ложных «Смоленских» из 519 —
`ельн` срабатывало на «насЕЛЬНых», «отдЕЛЬНых», «сЕЛЬНых»; `рославл` — на «ЯРОСЛАВЛя»;
`Ростов` — на крепости Св. Дмитрия Ростовского (это Ростов-на-Дону); `Романов`, `Данилов` —
на фамилиях; `Камышлов` — на озере Камышлов.

Правила теперь такие:
  — губерния засчитывается по паре «<название> губерн*» (в любом падеже, допускается
    «губ.»), либо по прилагательному города-центра рядом со словом «г.»/«город»;
  — уезд засчитывается только в паре «<Название>ский уезд» — одиночная фамилия или
    озеро так не пройдут;
  — всё остальное уходит в needs_human с причиной, а не приписывается территории.

Исходный `records.jsonl` НЕ меняется (исторический артефакт): результат пишется рядом
как `records_retagged.jsonl` + `records.csv` + `REPORT.json`.

Запуск:
    python retag_territory.py
"""
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parsing import parse_scale  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив\output\uiad_rgvia_maps_20261004")

GUB = r"губерн\w*|губ\."
# губерния названа прямо
GUBERNIA = {
    "Калужская": re.compile(rf"Калужск\w*\s+(?:{GUB})", re.I),
    "Пермская": re.compile(rf"Пермск\w*\s+(?:{GUB})", re.I),
    "Смоленская": re.compile(rf"Смоленск\w*\s+(?:{GUB})", re.I),
    "Ярославская": re.compile(rf"Ярославск\w*\s+(?:{GUB})", re.I),
}
# губернский город (как объект карты/плана)
CITY = {
    "Калужская": re.compile(r"\bг\.\s*Калуг\w+|город\w*\s+Калуг\w+|\bКалуг[аи]\b", re.I),
    "Пермская": re.compile(r"\bг\.\s*Перм\w+|город\w*\s+Перм\w+|\bПермь\b", re.I),
    "Смоленская": re.compile(r"\bг\.\s*Смоленск\w*|город\w*\s+Смоленск\w*|\bСмоленск\b", re.I),
    "Ярославская": re.compile(r"\bг\.\s*Ярославл\w+|город\w*\s+Ярославл\w+|\bЯрославль\b", re.I),
}
# уезды — только в паре со словом «уезд»
UEZD = {
    "Калужская": r"Боровск|Козельск|Лихвин|Малоярославец|Медынск|Мещовск|Мосальск|Перемышльск|Тарусск|Жиздринск|Калужск",
    "Пермская": r"Екатеринбургск|Ирбитск|Камышловск|Красноуфимск|Кунгурск|Осинск|Оханск|Соликамск|Чердынск|Шадринск|Верхотурск|Пермск",
    "Смоленская": r"Вяземск|Гжатск|Дорогобужск|Духовщинск|Ельнинск|Поречск|Рославльск|Сычевск|Юхновск|Бельск|Краснинск|Смоленск",
    "Ярославская": r"Ростовск|Рыбинск|Угличск|Мологск|Мышкинск|Даниловск|Любимск|Пошехонск|Романово-Борисоглебск|Ярославск",
}
UEZD_RX = {k: re.compile(rf"(?:{v})\w*\s+уезд\w*", re.I) for k, v in UEZD.items()}

# Ростов Ярославской против Ростова-на-Дону и Ростовской крепости
ROSTOV_FALSE = re.compile(r"Ростовск\w*\s+крепост|Дмитри\w*\s+Ростовск|Ростов[а-я]*[- ]на[- ]Дону", re.I)

COLS = ["source", "archive", "fund", "fund_title", "opis", "opis_title", "delo", "title",
        "year_from", "year_to", "scale_raw", "scale_denom", "size_cm", "technique",
        "territory", "territory_evidence", "is_map", "url", "needs_human", "needs_human_reason"]


def tag(title: str) -> tuple[list[str], list[str]]:
    """(территории, доказательства) — только по строгим правилам."""
    terr, ev = [], []
    for k in GUBERNIA:
        m = GUBERNIA[k].search(title)
        if m:
            terr.append(k)
            ev.append(f"{k}:губерния «{m.group(0)}»")
            continue
        m = UEZD_RX[k].search(title)
        if m:
            if k == "Ярославская" and ROSTOV_FALSE.search(title):
                continue
            terr.append(k)
            ev.append(f"{k}:уезд «{m.group(0)}»")
            continue
        m = CITY[k].search(title)
        if m:
            terr.append(k)
            ev.append(f"{k}:город «{m.group(0)}»")
    return terr, ev


def main() -> None:
    src = OUT / "records.jsonl"
    rows = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    old_hits = sum(1 for r in rows if r.get("territory"))
    out_rows = []
    for r in rows:
        terr, ev = tag(r["title"])
        reasons = []
        if not terr:
            reasons.append("territory_not_in_title")
        if r.get("is_map") != "true":
            reasons.append("subject_not_cartographic")
        r = dict(r)
        # масштаб пересчитывается здесь же: формат «в 1 дюйме N вёрст» (основной в ф.386)
        # первая версия разбора не ловила — у 305 записей масштаб терялся
        if not r.get("scale_denom"):
            raw, den = parse_scale(r["title"])
            if den:
                r["scale_raw"], r["scale_denom"] = raw, den
        r["territory"] = "; ".join(terr)
        r["territory_evidence"] = " | ".join(ev)
        r["needs_human"] = "true" if reasons else "false"
        r["needs_human_reason"] = "; ".join(reasons)
        out_rows.append(r)

    (OUT / "records_retagged.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows), encoding="utf-8")
    with (OUT / "records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)

    new_hits = [r for r in out_rows if r["territory"]]
    rep = {
        "source": "uiad", "archive": "РГВИА", "records": len(out_rows),
        "retagged": True,
        "territory_before": old_hits, "territory_after": len(new_hits),
        "by_territory": dict(Counter(t for r in new_hits for t in r["territory"].split("; "))),
        "by_fund_with_territory": dict(Counter(r["fund"] for r in new_hits)),
        "with_scale": sum(1 for r in out_rows if r["scale_denom"]),
        "with_size": sum(1 for r in out_rows if r["size_cm"]),
        "is_map": sum(1 for r in out_rows if r["is_map"] == "true"),
        "ready_for_import": False,
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print("\nнаши записи:")
    for r in new_hits[:25]:
        print(f"   ф.{r['fund']} оп.{r['opis']} д.{r['delo']:>5} [{r['territory']:24}] "
              f"{r['title'][:88]}")
        print(f"        ↳ {r['territory_evidence'][:100]}")


if __name__ == "__main__":
    main()
