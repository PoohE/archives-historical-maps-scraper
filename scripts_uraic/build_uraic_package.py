"""Белинка (Свердловская ОУНБ, elib.uraic.ru): пакет каталога из карточек DSpace.

⚠️ ЧЕМ ЭТОТ ИСТОЧНИК ОТЛИЧАЕТСЯ ОТ ОСТАЛЬНЫХ БИБЛИОТЕК — и почему тут свой гейт.

Белинка это не оцифрованный книжный фонд, а РЕПОЗИТОРИЙ КРАЕВЕДЧЕСКИХ ПУБЛИКАЦИЙ:
больше половины записей — доклады Чупинских краеведческих чтений 1990–2010-х годов.
Такой доклад называется, например, «"Географический и статистический словарь Пермской
губернии" Н. К. Чупина как источник по истории сельского расселения» — по заголовку
чистое пространственное описание нашей губернии, а на деле это СТАТЬЯ О СЛОВАРЕ,
написанная в 2001 году. В каталог источников она не идёт.

Различает их только поле `DC.type`:
  * `Book`, `Newspaper`, `Journal`, `Map`, `Other` — сам источник, рассматриваем;
  * `Article` — публикация О чём-то. Берём ТОЛЬКО если это дореволюционная или ранняя
    советская статья (до 1930) — тогда она сама является источником эпохи, как
    «Дополнения к статистическим таблицам по училищам Екатеринбургского уезда за
    1885/6 учебный год». Современный доклад о старой карте — не источник.

Остальные правила общие: класс и территория из `scope_rules`, ловушки из `false_carto`,
верхняя граница для библиотек — 1989 год включительно.

Запуск:
    python -B scripts_uraic/build_uraic_package.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts_review"))
from false_carto import alien_hit, is_false_carto, not_a_place  # noqa: E402
from scope_rules import (  # noqa: E402
    BUILDING,
    BUILDING_EXCEPT,
    LIMIT,
    klass,
    territories,
)

SRC = ROOT / "output" / "uraic_20261021" / "uraic_meta.jsonl"
OUT = ROOT / "output" / "uraic_package_20261022"
ISTOCHNIK = "Свердловская ОУНБ им. В. Г. Белинского (elib.uraic.ru)"

# Типы DSpace, которые сами являются источником
TIP_ISTOCHNIK = {"Book", "Newspaper", "Journal", "Map", "Other", "Image", ""}
# Статья считается источником эпохи, если издана до этого года
STATYA_DO = 1930


def main() -> int:  # noqa: PLR0912
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        print(f"нет файла {SRC} — сначала прогнать uraic_fetch_meta.py")
        return 1

    rows_in = [json.loads(ln) for ln in SRC.open(encoding="utf-8")]
    rows: list[dict] = []
    for c in rows_in:
        t = (c.get("zagolovok") or "").strip()
        if not t:
            continue
        # территорию и класс ищем по заголовку + рубрикам + изданию-контейнеру
        blob = " ".join(str(c.get(k, "")) for k in
                        ("zagolovok", "rubriki", "iz_izdaniya", "opisanie"))
        god_s = str(c.get("god") or "")
        m = re.search(r"(1[5-9]\d{2}|20[0-2]\d)", god_s)
        god_num = int(m.group(1)) if m else None
        tip = (c.get("tip") or "").strip()
        kl = klass(t, carto_ok=not is_false_carto(t)) or klass(blob, carto_ok=not is_false_carto(blob))
        gub = territories(t) or territories(blob)
        rec = {
            "handle": c.get("handle", ""),
            "zagolovok": t[:400],
            "avtor": c.get("avtor", ""),
            "god": god_s,
            "tip_dspace": tip,
            "klass": kl,
            "territoriya": "; ".join(gub),
            "iz_izdaniya": c.get("iz_izdaniya", ""),
            "rubriki": c.get("rubriki", ""),
            "shifr": c.get("shifr", ""),
            "url": c.get("url", ""),
            "url_fajla": c.get("url_fajla", ""),
            "fajlov": c.get("fajlov", 0),
            "zapros": c.get("zapros", ""),
            "istochnik": ISTOCHNIK,
        }

        # --- гейт ---
        fc = is_false_carto(t)
        bld = bool(BUILDING.search(t)) and not BUILDING_EXCEPT.search(t)
        # ⚠️ статья о источнике ≠ источник (см. шапку модуля)
        statya_o_istochnike = (tip == "Article"
                               and god_num is not None and god_num > STATYA_DO)
        if fc:
            rec["gate"], rec["gate_reason"] = "отсев", f"ложный картографический признак: «{fc}»"
        elif bld:
            rec["gate"], rec["gate_reason"] = "отсев", "план постройки, не территории (правило масштаба)"
        elif statya_o_istochnike:
            rec["gate"], rec["gate_reason"] = (
                "отсев", f"статья {god_num} г. О источнике, а не сам источник (DC.type=Article)")
        elif not kl:
            rec["gate"], rec["gate_reason"] = "отсев", "ни картографии, ни пространственного описания"
        elif not gub:
            rec["gate"], rec["gate_reason"] = "needs_human", "территория проекта в карточке не названа"
        elif (nap := not_a_place(blob)):
            rec["gate"], rec["gate_reason"] = "needs_human", f"название губернии — не топоним: «{nap}»"
        elif (al := alien_hit(blob)):
            rec["gate"], rec["gate_reason"] = "needs_human", f"названа чужая территория «{al}»"
        elif god_num and god_num > LIMIT:
            rec["gate"], rec["gate_reason"] = "needs_human", f"издание {god_num} > {LIMIT}"
        else:
            rec["gate"] = "принято"
            rec["gate_reason"] = f"{kl} + территория проекта"
        rows.append(rec)

    acc = [r for r in rows if r["gate"] == "принято"]
    nh = [r for r in rows if r["gate"] == "needs_human"]
    drop = [r for r in rows if r["gate"] == "отсев"]

    def dump(name: str, data: list[dict]) -> None:
        if not data:
            return
        cols = list(dict.fromkeys(k for r in data for k in r))
        with (OUT / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
        with (OUT / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for r in data:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("белинка_accepted", acc)
    dump("белинка_needs_human", nh)
    dump("белинка_scope_drops", drop)

    print(f"Белинка: карточек {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print("\nпо классам (принято):")
    for k, n in Counter(r["klass"] for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    print("\nпо типу DSpace (принято):")
    for k, n in Counter(r["tip_dspace"] or "—" for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    print("\nпричины отсева (топ-8):")
    for k, n in Counter(r["gate_reason"][:58] for r in drop).most_common(8):
        print(f"  {n:>4}  {k}")
    print(f"\nсо ссылкой на файл: {sum(1 for r in acc if r['url_fajla'])} из {len(acc)}")
    print(f"с годом: {sum(1 for r in acc if r['god'])}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
