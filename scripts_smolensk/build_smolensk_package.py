"""Смоленская ОУНБ им. Твардовского: пакет каталога из обхода `/main/last`.

Вход — `output/smolensk_20261022/smolensk_items.jsonl` (см. `smolensk_sweep.py`).
Гейт общий: класс и территория из `scope_rules`, ловушки из `false_carto`, верхняя
граница для библиотек 1989 год включительно.

⚠️ ОСОБЕННОСТИ ЭТОГО ИСТОЧНИКА, учтённые в сборщике:

 1. ПОЛНОЕ ОПИСАНИЕ УЖЕ В ЛИСТИНГЕ. Класс и территорию ищем по `bibl_opisanie`
    целиком, а не по заголовку: выходные данные часто называют губернию там, где
    в заглавии её нет («Цебриков М. М. Смоленская губерния» — том «Материалов для
    географии и статистики России, собранных офицерами Генерального штаба»).

 2. РЕЖИМ ДОСТУПА РАЗНЫЙ, и это важно приёмщику. Книги (коллекция `books`) почти
    все «по паролю из сети Интернет» — читаются по регистрации, ссылка на PDF есть,
    но свободно не открывается. Газеты (`gazeta`) — свободный доступ. Поле `dostup`
    передаётся в каталог как есть.

 3. КОЛЛЕКЦИЯ `patent_ru` — патенты РФ, к проекту отношения не имеют; `gazeta` —
    подшивки номеров областных газет, это отдельный класс материала (периодика),
    в картографический каталог они не идут, но помечаются, а не выбрасываются молча.

Запуск:
    python -B scripts_smolensk/build_smolensk_package.py
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

SRC = ROOT / "output" / "smolensk_20261022" / "smolensk_items.jsonl"
OUT = ROOT / "output" / "smolensk_package_20261022"
# коллекции, которые в картографический каталог не идут
NE_NASH = {"patent_ru": "патенты РФ", "gazeta": "подшивка областной газеты (периодика)"}


def main() -> int:  # noqa: PLR0912
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        print(f"нет файла {SRC}")
        return 1

    def chitat(path: Path):
        """Строки jsonl, пропуская недописанные: прогон идёт порциями под timeout."""
        for ln in path.open(encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield json.loads(ln)
            except Exception:  # noqa: BLE001, S112
                continue

    # ⚠️ дедуп по url прямо здесь: рабочий jsonl пишется порциями и дозаписывается
    # при каждом возобновлении, поэтому одна и та же страница могла попасть в него
    # дважды. Чистку нельзя откладывать на подмену файла — папка на Я.Диске, и
    # замена срывается, пока идёт синхронизация.
    vidino: set[str] = set()
    rows: list[dict] = []
    for c in chitat(SRC):
        if c.get("url") in vidino:
            continue
        vidino.add(c.get("url"))
        t = (c.get("zagolovok") or "").strip()
        blob = c.get("bibl_opisanie") or t
        if not t:
            continue
        god = str(c.get("god") or "")
        m = re.search(r"(1[5-9]\d{2}|20[0-2]\d)", god)
        god_num = int(m.group(1)) if m else None
        kol = c.get("kollekciya", "")
        # ⚠️ КЛАСС — ТОЛЬКО ПО ЗАГЛАВИЮ. В описании есть иллюстративный состав
        # («198 с.: ил., карты»), и по нему картографией становится любая книга
        # с картой внутри — так в класс попали шесть выпусков журнала «Революция
        # и война». Территорию, наоборот, ищем по всему описанию.
        kl = klass(t, carto_ok=not is_false_carto(t))
        gub = territories(blob)
        # карты внутри издания — ценная пометка, но не класс (как prilozhenie_karta
        # в пакете ГПИБ)
        est_karty = bool(ILLUSTR_KARTY.search(blob))
        if not kl and est_karty:
            kl = klass(blob.split("[Электронный ресурс]")[0], carto_ok=True)
        rec = {
            "nomer": c.get("nomer", ""),
            "zagolovok": t,
            "god": god,
            "klass": kl,
            "karty_v_izdanii": "да" if est_karty else "",
            "territoriya": "; ".join(gub),
            "kollekciya": kol,
            "dostup": c.get("dostup", ""),
            "bibl_opisanie": blob[:900],
            "url": c.get("url", ""),
            "url_fajla": c.get("url_fajla", ""),
            "data_postupleniya": c.get("data_postupleniya", ""),
            "istochnik": c.get("istochnik", ""),
        }
        fc = is_false_carto(t)
        if kol in NE_NASH:
            rec["gate"], rec["gate_reason"] = "отсев", f"коллекция «{kol}» — {NE_NASH[kol]}"
        elif fc:
            rec["gate"], rec["gate_reason"] = "отсев", f"ложный картографический признак: «{fc}»"
        elif BUILDING.search(t) and not BUILDING_EXCEPT.search(t):
            rec["gate"], rec["gate_reason"] = "отсев", "план постройки, не территории (правило масштаба)"
        elif not kl and est_karty and gub:
            # ⚠️ НЕ ОТСЕВ: по заглавию класс не читается, но в издании ЕСТЬ карты
            # и названа наша губерния — «Революция и война: военно-научный журнал…
            # 252 с.: карты», «Достопамятности Смоленска… 80 с.: ил., карты».
            # Такие тома в ГПИБ принимались как носители карты, здесь отдаём
            # человеку: решение, брать ли книгу ради карт внутри, за приёмщиком.
            rec["gate"], rec["gate_reason"] = (
                "needs_human", "класс по заглавию не определён, но в издании есть карты")
        elif not kl:
            rec["gate"], rec["gate_reason"] = "отсев", "ни картографии, ни пространственного описания"
        elif not gub:
            rec["gate"], rec["gate_reason"] = "needs_human", "территория проекта в описании не названа"
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

    dump("смоленская_accepted", acc)
    dump("смоленская_needs_human", nh)
    dump("смоленская_scope_drops", drop)

    print(f"Смоленская ОУНБ: записей {len(rows)}")
    print(f"  принято:     {len(acc)}")
    print(f"  needs_human: {len(nh)}")
    print(f"  отсев:       {len(drop)}")
    print("\nпо губерниям (принято):")
    for g, n in Counter(x for r in acc for x in r["territoriya"].split("; ") if x).most_common():
        print(f"  {n:>4}  {g}")
    print("\nпо классам (принято):")
    for k, n in Counter(r["klass"] for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    print("\nрежим доступа (принято):")
    for k, n in Counter(r["dostup"] or "не указан" for r in acc).most_common():
        print(f"  {n:>4}  {k}")
    veka = Counter(f"{int(r['god']) // 100 + 1} в." for r in acc if r["god"].isdigit())
    print("\nпо векам (принято):", dict(sorted(veka.items())))
    print(f"\nс картами внутри издания: {sum(1 for r in acc if r['karty_v_izdanii'])}")
    print(f"со ссылкой на файл: {sum(1 for r in acc if r['url_fajla'])} из {len(acc)}")
    print(f"с годом: {sum(1 for r in acc if r['god'])}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
