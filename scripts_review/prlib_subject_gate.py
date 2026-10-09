"""Предметный отбор в наборе ПрБ v8.1: отделить картографию от прочего.

Зачем: пакет v8.1 собирает СОДЕРЖИМОЕ семи региональных коллекций целиком и честно
помечает всё `needs_human: true` с причиной `source_type_requires_review` — тип источника
на портале не указан (`material_type` пуст у 450 из 451). Поэтому в наборе рядом с картами
лежат фотографии соборов, книги и делопроизводство.

Этот скрипт прогоняет набор через тот же общий гейт отбора, что применялся к Пермской
краевой (`scope_gate` из пакета permkrai v9.4, правила `ПРАВИЛА_ОТБОРА_источников.md`),
и делит набор на три части. Исходный `records_full.jsonl` не изменяется.

Запуск из корня проекта:
    python -B scripts_review/prlib_subject_gate.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

from subject_filters import (
    is_archival_file_subject,
    is_document_plan,
    is_engineering_subject,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = Path("C:/arch/output/prlib_catalog_full_20261008_v8_1")
PKG = ROOT / "output" / "permkrai_catalog_maps_handoff_20261002_v9_4"
RULES = PKG / "rules" / "ПРАВИЛА_ОТБОРА_источников.md"
OUT = ROOT / "output" / f"prlib_subject_gate_{time.strftime('%Y%m%d')}"

sys.path.insert(0, str(PKG / "frozen" / "scripts" / "modules"))
import scope_gate  # noqa: E402


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def flat(row: dict) -> dict:
    """Плоская строка для CSV: запись ПрБ держит данные в record/evidence."""
    rec = row.get("record") or {}
    ev = row.get("evidence") or {}
    subj = (ev.get("subject") or {}) if isinstance(ev, dict) else {}
    return {
        "title": rec.get("title") or subj.get("title") or "",
        "url": rec.get("url") or (subj.get("source") or {}).get("url") or "",
        "territory": row.get("territory") or "",
        "year_from": rec.get("year_from") or "",
        "year_to": rec.get("year_to") or "",
        "collections": ";".join(str(x) for x in (row.get("collections") or [])),
        "material_type": row.get("material_type") or "",
        "scale_raw": rec.get("scale_raw") or "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC))
    args = ap.parse_args()
    src = Path(args.src)

    rows = [json.loads(ln) for ln in (src / "records_full.jsonl").open(encoding="utf-8") if ln.strip()]
    policy = scope_gate.load_policy(RULES)
    print(f"набор: {len(rows)} записей")
    print(f"правила: sha256 {policy.rules_sha256[:16]}…\n")

    # Гейт не отсекает записи с неподтверждённым предметом, а помечает их
    # (правило «где объём не угрожает — помечать, а не выбрасывать»). Для ПрБ это
    # означает, что в keep попадают фотографии соборов наравне с картами.
    # Поэтому делим keep надвое по subject_evidence: предмет подтверждён → в каталог,
    # не подтверждён → очередь проверки.
    keep, spatial, review, drop = [], [], [], []
    reasons: Counter = Counter()
    for row in rows:
        rec = dict(row.get("record") or {})
        # у ПрБ тип материала на портале почти всегда пуст — гейт решает по заголовку
        rec.setdefault("extra", {"card_type": row.get("material_type") or ""})
        v = scope_gate.check(rec, source="prlib", amendments=policy)
        out = dict(flat(row),
                   gate_keep=v.keep,
                   gate_reason=v.reason or "",
                   gate_rule=v.rule,
                   gate_evidence=v.evidence,
                   subject_evidence=v.subject_evidence,
                   needs_human=v.needs_human)
        reasons[(v.reason or v.evidence)] += 1
        title = out["title"]
        if not v.keep:
            drop.append(out)
        elif is_document_plan(title):
            # «план развития промыслов», «план хозяйственного строительства», «дело о…
            # плане устройства» — слово «план» в смысле документа, а не карты (§1.1).
            drop.append(dict(out, gate_reason="document_plan",
                             gate_evidence="«план» как документ, не картографический объект"))
        elif is_engineering_subject(title, strip_prefix=True):
            # «План и общий разрез воспитательного дома», «Чертежи казенных зданий»,
            # «Семинария. Планы, фасады» — предмет записи здание/сооружение, не
            # территория (§1.2; решение 09.10 по мостам и скважинам ф. 380).
            drop.append(dict(out, gate_reason="engineering_subject",
                             gate_evidence="предмет записи — здание/сооружение, не территория"))
        elif is_archival_file_subject(title, strip_prefix=True):
            # «Дело по представлению губернатора об утверждении… на планах города»,
            # «Сборник Отделения русского языка… [Диалектологическая карта]» — дело или
            # книга О планах, а не сам план: единицу каталога определяет человек.
            review.append(dict(out, review_reason="дело/книга о планах, а не сам "
                                                 "картографический объект"))
        elif v.subject_evidence == "spatially_linked_data_in_title":
            # Топографические и статистические описания, «Материалы для географии и
            # статистики» — отдельный класс: пространственно привязанные данные, не карта.
            spatial.append(out)
        elif v.subject_evidence in ("cartographic_term_in_item_title", "typed_cartographic"):
            keep.append(out)
        else:
            review.append(dict(out, review_reason="предмет не подтверждён: в заголовке нет "
                                                  "картографического термина, тип материала "
                                                  "на портале не указан"))

    delta = len(rows) - len(keep) - len(spatial) - len(review) - len(drop)
    print(f"картография (в каталог): {len(keep)}")
    print(f"пространственные данные (описания): {len(spatial)}")
    print(f"предмет не подтверждён (очередь): {len(review)}")
    print(f"отсеяно:                 {len(drop)}")
    print(f"delta:                   {delta}\n")
    print("причины:")
    for k, n in reasons.most_common(12):
        print(f"  {n:>4}  {k}")

    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "keep_cartographic.csv", keep)
    write_csv(OUT / "keep_spatial_data.csv", spatial)
    write_csv(OUT / "review_subject_unconfirmed.csv", review)
    write_csv(OUT / "dropped.csv", drop)
    (OUT / "GATE_REPORT.json").write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "source": str(src),
        "rules_sha256": policy.rules_sha256,
        "input": len(rows),
        "keep_cartographic": len(keep),
        "keep_spatial_data": len(spatial),
        "review_subject_unconfirmed": len(review),
        "dropped": len(drop),
        "conservation_delta": delta,
        "reasons": dict(reasons),
        "note": "Гейт применён к набору v8.1, который собирал содержимое коллекций целиком "
                "(material_type пуст у 450 из 451, всё помечено source_type_requires_review).",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nпримеры прошедших:")
    for r in keep[:8]:
        print(f"  [{r['territory'][:10]:<10}] {r['title'][:76]}")
    print(f"\nвыход: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
