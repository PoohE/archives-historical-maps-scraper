"""УИАД/РГВИА: пакет на внесение по фондам, добранным 19–20.10.2026.

В каталог уже внесены 650 записей из 17 фондов путеводителя (закрыто 16.10). Здесь —
только ПРИБАВКА из семи фондов вне путеводителя: 349, 369, 412, 38, 35, 208, 243.

Как собирали: id фондов в справочнике не было (он делался под путеводитель), нашли
расчётом страницы по номеру фонда — `find_fund_ids.py`, 7 страниц вместо обхода 647.
Сертификат российского УЦ подтверждён человеком в профиле `chrome-debug`.

⚠️ Числа берём ТОЛЬКО из строгой переразметки (`retag_territory.py`): нестрогая сводка
сборщика показывала 13 860 «территориальных», строгая дала 755 — 94,6 % было ложными
совпадениями по подстрокам («ельн» в «насЕЛЬНых» и т.п.).

⚠️ Урок о выборе фондов: размер и профильность названия выход НЕ предсказывают.
Ф. 349 «Главное военно-техническое управление (планы и чертежи)» — 67 779 дел и 13 наших;
ф. 38 — 6977 дел и 30 наших. Перед полным прогоном крупного фонда стоит брать 1–2 описи
пробой.

Запуск:
    python -B scripts_rosarchive/build_uiad_addon_package.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "output" / "uiad_rgvia_maps_20261004" / "records_retagged.jsonl"
OUT = ROOT / "output" / "uiad_addon_package_20261020"

NEW_FUNDS = {"349", "369", "412", "38", "35", "208", "243"}
FIELDS = ["archive", "fund", "fund_title", "opis", "delo", "title", "year_from", "year_to",
          "scale_raw", "scale_denom", "size_cm", "technique", "territory",
          "territory_evidence", "is_map", "url", "needs_human", "needs_human_reason",
          "predmet", "predmet_reason"]

# ⚠️ Флаг `is_map` сборщика стоит у ВСЕХ записей добранных фондов и ничего не значит:
# 35, 38, 369, 412 — делопроизводственные фонды, и территориальная разметка вытаскивает
# оттуда «о дозволении перевезти тело покойного генерал-майора», «переписку эвакуационной
# комиссии», «о выдаче аванса льнопрядильной мануфактуре». Нужен предметный гейт.
# ⚠️ «Пл.» и «Пл» — сокращение «План» в заголовках УИАД («Пл. гор. Калуга»): без них
# такие дела уходили в отсев зря (поймано 20.10 при проверке выборки).
CARTO = re.compile(
    r"\bкарт[аыуеой]\b|\bкарты\b|\bкарт\b|\bплан[ыаеу]?\b|\bпланов\b|\bпл\.\s|атлас"
    r"|чертеж|чертёж|\bчерт\.\s|\bсъемк\w*|\bсъёмк\w*|топограф\w*|межев\w*"
    r"|рекогносцир\w*|глазомерн\w*|кроки\b|профил[ья]\b|нивелир\w*|триангуляц\w*", re.I)
# Канцелярия, где слово-признак стоит в служебном обороте
NOT_CARTO = re.compile(
    r"^\s*(о дозволении|о передаче|о переписке|переписка|об установлении нового маршрута"
    r"|о выдаче|об ассигновании.*(жалован|пособи)|рапорт|отношение|прошение)", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    for ln in SRC.open(encoding="utf-8"):
        r = json.loads(ln)
        if str(r.get("fund")) not in NEW_FUNDS:
            continue
        if not (r.get("territory") or "").strip():
            continue
        rec = {k: r.get(k) for k in FIELDS}
        title = (r.get("title") or "").strip()
        if NOT_CARTO.search(title):
            rec["predmet"], rec["predmet_reason"] = "отсев", "канцелярский оборот в начале заголовка"
        elif CARTO.search(title):
            m = CARTO.search(title)
            rec["predmet"], rec["predmet_reason"] = "карта", f"признак «{m.group(0)}» в заголовке"
        else:
            rec["predmet"] = "отсев"
            rec["predmet_reason"] = "картографического признака в заголовке нет"
        rows.append(rec)

    acc = [r for r in rows if r["predmet"] == "карта"]
    drop = [r for r in rows if r["predmet"] == "отсев"]

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        with (OUT / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(data)
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("uiad_addon_accepted", acc)
    dump("uiad_addon_drops", drop)

    print(f"наша территория: {len(rows)} | НА ВНЕСЕНИЕ (карты): {len(acc)} | отсев: {len(drop)}")
    rows = acc
    print("\nпо фондам:")
    for f, n in Counter(str(r["fund"]) for r in rows).most_common():
        print(f"  ф.{f:<5} {n}")
    print("\nпо губерниям:")
    for t, n in Counter(r["territory"] for r in rows).most_common():
        print(f"  {t:<14} {n}")
    print(f"\nс масштабом: {sum(1 for r in rows if r.get('scale_raw'))}")
    print(f"помечено is_map: {sum(1 for r in rows if r.get('is_map'))}")
    print(f"\n→ {OUT / 'uiad_addon_accepted.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
