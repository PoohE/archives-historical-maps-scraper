"""ПрБ: пакет на внесение из картографических рубрик портала (добор 18.10.2026).

Находка прогона: карты Президентской библиотеки достижимы не только внутри семи
региональных коллекций, но и через тематические рубрики общего рубрикатора
(«Физические карты», «Планы населенных пунктов», «Исторические карты» и др.).
Прежний вывод «общий фонд не покрыт и покрыт быть не может, потому что поиск закрыт
robots» этим опровергнут: поиск действительно закрыт, но рубрики открыты.

Обход рубрик сошёлся: 241 запрос, очередь 0, 3245 карточек, 270 картографических.
По 4 губерниям проекта — 19, из них 6 уже в каталоге, 4 отсеяны гейтом как
делопроизводство, 9 НОВЫЕ (ни в одном прежнем наборе ПрБ их нет).

Запуск:
    python -B scripts_prlib/build_prlib_carto_handoff.py
"""
from __future__ import annotations

import csv
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "output" / "prlib_perm_sections" / "carto_d1.jsonl"
OUT = ROOT / "output" / "prlib_carto_handoff_20261018"

GUB = {
    "Ярославская": r"\bЯрославл\w*|\bЯрославск\w*|\bУглич\w*|\bМышкин\w*|\bПошехон\w*"
                   r"|\bМолог\w*|\bРыбинск\w*|\bРостовск\w*",
    "Калужская": r"\bКалуж\w*|\bКалуг[аиуе]\b|\bБоровск\w*|\bКозельск\w*|\bМедынск\w*"
                 r"|\bМещовск\w*|\bМосальск\w*|\bТарусск\w*",
    "Смоленская": r"\bСмоленск\w*|\bВязьм\w*|\bВяземск\w*|\bГжатск\w*|\bДорогобуж\w*"
                  r"|\bДуховщин\w*|\bРославл\w*|\bСычевск\w*|\bЮхновск\w*",
    "Пермская": r"\bПермск\w*|\bПерм[ьи]\b|\bСоликамск\w*|\bЧердын\w*|\bКунгур\w*"
                r"|\bОханск\w*|\bВерхотур\w*|\bИрбитск\w*|\bШадринск\w*|\bЕкатеринбург\w*"
                r"|\bПрикам\w*",
}
CARTO_OK = re.compile(r"\bкарт[аыуеой]\b|\bкарты\b|\bплан\b|\bпланы\b|\bплана\b|атлас"
                      r"|чертеж|чертёж|съемк|съёмк|топограф|межев", re.I)
# Канцелярия с «планом» в заголовке — не карта (решение гейта ПрБ 09.10).
NOT_CARTO = re.compile(r"^\s*(дело|об утверждении|о даче указаний|документы комиссии"
                       r"|о выполнении|положение|отчет)", re.I)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    for p in glob.glob(str(ROOT / "output" / "prlib_handoff_*" / "*.csv")) + \
            glob.glob(str(ROOT / "output" / "prlib_subject_gate_*" / "*.csv")) + \
            glob.glob(str(ROOT / "output" / "prlib_subject_gate_*" / "*.json")):
        seen |= set(re.findall(r"prlib\.ru/item/(\d+)",
                               Path(p).read_text(encoding="utf-8", errors="replace")))

    rows, skipped = [], []
    for ln in SRC.open(encoding="utf-8"):
        r = json.loads(ln)
        t = r["title"]
        if not CARTO_OK.search(t):
            continue
        gub = [g for g, p in GUB.items() if re.search(p, t, re.I)]
        if not gub:
            continue
        rec = {
            "zagolovok": t,
            "territoriya": "; ".join(gub),
            "url": r["url"],
            "item_id": r["item_id"],
            "rubrika": r["section"],
            "sposob": "portal: рубрикатор",
            "istochnik": "Президентская библиотека",
            "primechanie": f"рубрика портала: {r['section']}",
        }
        if r["item_id"] in seen:
            rec["status"] = "уже в прежних наборах ПрБ — не вносить повторно"
            skipped.append(rec)
        elif NOT_CARTO.search(t):
            rec["status"] = "делопроизводство с словом «план» — отсев по правилу гейта"
            skipped.append(rec)
        else:
            rec["status"] = "НОВАЯ — на внесение"
            rows.append(rec)

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        with (OUT / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)

    dump("prlib_carto_new", rows)
    dump("prlib_carto_already_known", skipped)

    print(f"на внесение: {len(rows)} | уже известны или отсев: {len(skipped)}")
    for r in rows:
        print(f"  · [{r['territoriya']}] {r['zagolovok'][:70]}")
        print(f"     {r['url']}  [{r['rubrika'][:38]}]")
    print(f"\n→ {OUT / 'prlib_carto_new.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
