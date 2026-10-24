"""Калужская ОНБ: пакет каталога из обхода Веб-ИРБИС (см. kaluga_sweep.py).

⚠️ ЧТО ЗА КАТАЛОГ. `EK` — ОБЩИЙ электронный каталог областной библиотеки: современные
книги, законы области, художественная литература и краеведение вперемешку. Широкий
невод однословных запросов («КАЛУЖСКОЙ», «КАРТА», «АТЛАС») тащит всё подряд — по слову
«карта» первым номером идёт «Карта Магеллана: роман», по «Калужской» — «Русская
выхухоль в Калужской области» и «Устав Калужской области». Поэтому гейт тут режет
жёстче, чем на специализированных источниках.

Класс определяется ПО ЗАГЛАВИЮ (правило, выведенное на Смоленской: в полном описании
встречается иллюстративный состав, и по нему картографией становится любая книга с
картой внутри). Территория ищется по всему описанию, включая рубрики ИРБИС — там
губерния часто названа явно («Калужская область--Археология--Долина реки Болва»).

⚠️ ОБЛАСТЬ ≠ ГУБЕРНИЯ, но в этом каталоге разделять их на уровне гейта нельзя:
дореволюционные издания описаны и как «Калужская губерния», и через рубрику
«Калужская область». Отбор по веку делает граница 1989 года, а окончательное решение
по советским и современным краеведческим изданиям — за приёмщиком.

Запуск:
    python -B scripts_kaluga/build_kaluga_package.py
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
    ILLUSTR_KARTY,
    LIMIT,
    klass,
    territories,
)

SRC = ROOT / "output" / "kaluga_20261023" / "kaluga_items.jsonl"
OUT = ROOT / "output" / "kaluga_package_20261023"

# Заглавие записи ИРБИС начинается с шифра хранения («К63.4 К 83»); он мешает
# и классу, и территории — срезаем.
SHIFR = re.compile(r"^\s*[А-ЯA-Z]?[\d.]+[А-Яа-яA-Za-z()/\d.\s-]{0,24}?\s+[А-Я]\s?\d{1,3}\s+")


def chitat(path: Path):
    for ln in path.open(encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            yield json.loads(ln)
        except Exception:  # noqa: BLE001, S112
            continue


def main() -> int:  # noqa: PLR0912
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        print(f"нет файла {SRC}")
        return 1

    vidino: set[str] = set()
    rows: list[dict] = []
    for c in chitat(SRC):
        mfn = str(c.get("mfn", ""))
        if not mfn or mfn in vidino:
            continue
        vidino.add(mfn)
        opis = c.get("opisanie") or ""
        # заглавие: описание без шифра хранения, до первой точки-тире
        zagl = SHIFR.sub("", opis).strip()
        zagl = re.split(r"\s+-\s+[А-Я][а-я]+\s*:|\s+/\s+", zagl)[0][:300].strip()
        blob = " ".join([opis, c.get("rubriki") or ""])
        # ⚠️ ГОД БЕЗ ДАТ ЖИЗНИ АВТОРА. ИРБИС пишет «Колесников, Лев Львович
        # (1940-2018)», и сборщик обхода брал первый год записи — анатомический
        # атлас получал 1940, Гоголь 1809, Мандельштам 1891. Вырезаем интервалы
        # в скобках и ищем год заново по очищенному описанию.
        bez_zhizni = re.sub(r"\(\s*1[5-9]\d{2}\s*[-–]\s*(?:1[5-9]\d{2}|20[0-2]\d)?\s*\)", " ", opis)
        gody = re.findall(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", bez_zhizni)
        god = gody[0] if gody else ""
        god_num = int(god) if god else None

        kl = klass(zagl, carto_ok=not is_false_carto(zagl))
        gub = territories(blob)
        est_karty = bool(ILLUSTR_KARTY.search(blob))
        rec = {
            "mfn": mfn,
            "zagolovok": zagl,
            "god": god,
            "klass": kl,
            "karty_v_izdanii": "да" if est_karty else "",
            "territoriya": "; ".join(gub),
            "shifr": c.get("shifr", ""),
            "rubriki": c.get("rubriki", ""),
            "ekzemplyarov": c.get("ekzemplyarov", ""),
            "svobodny": c.get("svobodny", ""),
            "opisanie": opis[:900],
            "url": c.get("url", ""),
            "zapros": c.get("zapros", ""),
            "istochnik": c.get("istochnik", ""),
        }

        fc = is_false_carto(zagl)
        if fc:
            rec["gate"], rec["gate_reason"] = "отсев", f"ложный картографический признак: «{fc}»"
        elif BUILDING.search(zagl) and not BUILDING_EXCEPT.search(zagl):
            rec["gate"], rec["gate_reason"] = "отсев", "план постройки, не территории (правило масштаба)"
        elif not kl and est_karty and gub:
            rec["gate"], rec["gate_reason"] = (
                "needs_human", "класс по заглавию не определён, но в издании есть карты")
        elif not kl:
            rec["gate"], rec["gate_reason"] = "отсев", "ни картографии, ни пространственного описания"
        elif not gub:
            rec["gate"], rec["gate_reason"] = "needs_human", "территория проекта в записи не названа"
        elif (nap := not_a_place(blob)):
            rec["gate"], rec["gate_reason"] = "needs_human", f"название губернии — не топоним: «{nap}»"
        elif (al := alien_hit(blob)):
            rec["gate"], rec["gate_reason"] = "needs_human", f"названа чужая территория «{al}»"
        elif god_num and god_num > LIMIT:
            rec["gate"], rec["gate_reason"] = "needs_human", f"издание {god_num} > {LIMIT}"
        else:
            rec["gate"] = "принято"
            rec["gate_reason"] = (f"{kl} + территория проекта"
                                  + (" + карты в издании" if est_karty else ""))
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

    dump("калужская_accepted", acc)
    dump("калужская_needs_human", nh)
    dump("калужская_scope_drops", drop)

    print(f"Калужская ОНБ: записей {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо классам (принято):")
    for k, n in Counter(r["klass"] for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    veka = Counter(f"{int(r['god']) // 100 + 1} в." for r in acc if r["god"].isdigit())
    print("\nпо векам (принято):", dict(sorted(veka.items())))
    print(f"с картами внутри издания: {sum(1 for r in acc if r['karty_v_izdanii'])}")
    print(f"с годом: {sum(1 for r in acc if r['god'])}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
