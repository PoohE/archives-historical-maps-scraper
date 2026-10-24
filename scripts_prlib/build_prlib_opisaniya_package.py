"""Президентская библиотека, слой описаний: пакет каталога.

Отдельно от пакета 09.10 (тот шёл по маршруту публичных региональных коллекций,
43 записи в каталог). Здесь — переоткрытый слой земско-статистических описаний,
найденный после того, как пользователь прислал `prlib.ru/item/1618094`
(«Статистическое описание Калужской губернии. Т. 6. Мещовский уезд»), которого
в наших наборах ПБ не было вовсе.

Отличия от ГПИБ, которые пришлось учесть:
 * карточка ПБ не делится на «издание/том» — всё библиографическое описание лежит
   одним блоком, поэтому territория и класс определяются по нему целиком;
 * у части изданий стоит «Доступно только в Электронных читальных залах» — карточка
   и описание читаются, скан нет. Для каталога это НЕ препятствие, но помечается
   полем `tolko_chitalnyy_zal`, чтобы приёмщик не искал скан напрасно;
 * «Место хранения оригинала» заполнено часто (ГПИБ, ЦВМБ, НБ Респ. Карелия и др.) —
   это ценное поле: показывает, чей оригинал оцифрован, и позволяет не заводить
   вторую запись, когда то же издание придёт из другого источника.

⚠️ Правила отбора берутся из общего `scripts_review/scope_rules.py`, ловушки —
из `scripts_review/false_carto.py`. Своих регулярок тут нет намеренно.

Запуск:
    python -B scripts_prlib/build_prlib_opisaniya_package.py
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from false_carto import alien_hit, is_false_carto, not_a_place  # noqa: E402
from scope_rules import (BUILDING, BUILDING_EXCEPT, LIMIT,  # noqa: E402
                         PRILOZHENIE, god_iz, klass, territories)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "output" / "prlib_opisaniya_20261021"
                                        / "prlib_items.jsonl"))
    ap.add_argument("--out", default=str(ROOT / "output" / "prlib_opisaniya_package_20261021"))
    ap.add_argument("--exclude-from", default="",
                   help="папка прежнего пакета ПБ: его item_id исключить (защита от дублей)")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seen_before: set[str] = set()
    if args.exclude_from:
        for f in Path(args.exclude_from).glob("*.jsonl"):
            for ln in f.open(encoding="utf-8"):
                try:
                    r = json.loads(ln)
                    for k in ("item_id", "id", "prlib_id"):
                        if r.get(k):
                            seen_before.add(str(r[k]))
                except Exception:  # noqa: BLE001, S112
                    continue
        print(f"исключаю уже переданные ранее: {len(seen_before)} карточек")

    rows = []
    for ln in src.open(encoding="utf-8"):
        try:
            c = json.loads(ln)
        except Exception:  # noqa: BLE001, S112
            continue
        if str(c.get("item_id")) in seen_before:
            continue
        title = (c.get("zagolovok") or "").strip()
        blob = " ".join(str(c.get(k, "")) for k in
                        ("zagolovok", "opisanie", "mesto", "kollekcii", "izdatel"))
        if not blob.strip():
            continue
        gub = territories(blob)
        god, god_num = god_iz(blob, c.get("god", ""), title)
        kl = klass(blob)
        pril = bool(PRILOZHENIE.search(blob))
        rec = {
            "item_id": c.get("item_id", ""),
            "zagolovok": title,
            "god": god,
            "mesto": c.get("mesto", ""),
            "izdatel": c.get("izdatel", ""),
            "klass": kl,
            "prilozhenie_karta": "да" if pril else "",
            "territoriya": "; ".join(gub),
            "hranenie_originala": c.get("hranenie_originala", ""),
            "tolko_chitalnyy_zal": c.get("tolko_chitalnyy_zal", ""),
            "opisanie": (c.get("opisanie") or "")[:900],
            "url": c.get("url", ""),
            "zapros": c.get("zapros", ""),
            "istochnik": "Президентская библиотека",
        }
        # ⚠️ Правило масштаба объекта (21.10): берём территорию, не постройку
        is_building = bool(BUILDING.search(title)) and not BUILDING_EXCEPT.search(title)
        fc = is_false_carto(title)
        nap = not_a_place(blob)
        al = alien_hit(blob)
        if is_building:
            rec["gate"], rec["gate_reason"] = "отсев", "план постройки/объекта, не территории (правило масштаба 21.10)"
        elif fc:
            rec["gate"], rec["gate_reason"] = "отсев", f"ложный картографический признак: «{fc}»"
        elif not kl:
            rec["gate"], rec["gate_reason"] = "отсев", "ни картографии, ни пространственного описания"
        elif not gub:
            rec["gate"], rec["gate_reason"] = "needs_human", "территория проекта в карточке не названа"
        elif nap:
            rec["gate"], rec["gate_reason"] = "needs_human", f"название губернии — не топоним: «{nap}»"
        elif al:
            rec["gate"], rec["gate_reason"] = "needs_human", f"названа чужая территория «{al}»"
        elif god_num and god_num > LIMIT:
            rec["gate"], rec["gate_reason"] = "needs_human", f"издание {god_num} > {LIMIT}"
        else:
            rec["gate"] = "принято"
            rec["gate_reason"] = kl + (" + карта в приложении" if pril else "")
        rows.append(rec)

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(data[0]))
            w.writeheader()
            w.writerows(data)
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("prlib_accepted", acc)
    dump("prlib_needs_human", nh)
    dump("prlib_scope_drops", drop)

    print(f"ПБ (слой описаний): карточек {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print("\nпо классам (принято):")
    for k, n in Counter(r["klass"] for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    print(f"\nс картой в приложении: {sum(1 for r in acc if r['prilozhenie_karta'])}")
    print(f"только читальный зал:  {sum(1 for r in acc if r['tolko_chitalnyy_zal'])}")
    print(f"с хранилищем оригинала: {sum(1 for r in acc if r['hranenie_originala'])}")
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
