"""Ф. 560 ГАЯО: строгая разметка территории по 4 губерниям проекта.

Коллекция картографических документов ГАЯО собрана по всей империи (Киев, Архангельск,
Иркутск, Туркестан, Африка). Решение пользователя 18.10: в каталог идёт то, что относится
к 4 губерниям проекта — Калужской, Смоленской, Ярославской, Пермской; остальное не
вносить, но сохранить на будущее.

⚠️ Нестрогий поиск по подстрокам здесь не годится — на этом уже обожглись дважды:
  * РГВИА: «Смоленская 8438», из 519 совпадений 486 ложных («ельн» в «насЕЛЬНых»);
  * ГАЯО-18.10: прикидка дала «Смоленская 553» в ярославской коллекции — ловились
    «Красн…», «Ельн…», «Бельск…» внутри посторонних слов и фамилий.

Поэтому здесь: границы слов обязательны, уезды пишутся полными основами, а каждая
находка сопровождается ДОКАЗАТЕЛЬСТВОМ — какое слово сработало и в каком окружении.
Доказательство смотрит человек; без него разметке верить нельзя.

Выход: f560_territory.csv (+ .jsonl) в папке пакета.

Запуск:
    python -B scripts_gayo/tag_f560_territory.py output/gayo_package_20261018
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Губернии и их уезды. Основы полные, с границей слова слева — «Красный» (уезд
# Смоленской губ.) берём только как «Красн(ый|ом|инск)» в географическом контексте,
# поэтому он вынесен в «слабые» признаки и сам по себе решения не принимает.
STRONG: dict[str, str] = {
    # ⚠️ Ростов берём только НЕ «на Дону»; «Романовск…» отдельно не берём — это ловит
    # фамилию Романовский (поймано 18.10 на карте Туркестана горного инженера
    # Г. Романовского), только составное «Романово-Борисоглебск».
    # Калязин (Тверская губ.) и Переславль-Залесский (Владимирская) убраны — не наши.
    "Ярославская": r"\bЯрославл\w*|\bЯрославск\w*|\bРостов(?:а|е|ский|ского|ском|у)?\b(?!\s*[–\-]?\s*на\s+Дону)"
                   r"|\bУглич\w*|\bУглицк\w*|\bМышкин\w*|\bПошехон\w*|\bМолог\w*"
                   r"|\bРыбинск\w*|\bРомановo?-Борисоглебск\w*|\bДаниловск\w*"
                   r"|\bЛюбимск\w*",
    "Калужская": r"\bКалуж\w*|\bКалуг[аиуе]\b|\bБоровск\w*|\bКозельск\w*"
                 r"|\bМалоярославец\b|\bМалояросл\w*|\bМедынск\w*|\bМещовск\w*"
                 r"|\bМосальск\w*|\bПеремышльск\w*|\bТарусск\w*|\bЖиздринск\w*"
                 r"|\bЛихвинск\w*|\bСерпейск\w*|\bСухиничи\b",
    "Смоленская": r"\bСмоленск\w*|\bВязьм[аыуе]\b|\bВяземск\w*|\bГжатск\w*"
                  r"|\bДорогобуж\w*|\bДуховщин\w*|\bПоречск\w*|\bРославл\w*"
                  r"|\bСычевск\w*|\bСычёвск\w*|\bЮхновск\w*|\bЕльнинск\w*"
                  r"|\bДорогобужск\w*|\bБельск(?:ий|ого|ом|ому)\b",
    "Пермская": r"\bПермск\w*|\bПерм[ьи]\b|\bСоликамск\w*|\bЧердын\w*|\bКунгур\w*"
                r"|\bОханск\w*|\bОсинск\w*|\bВерхотур\w*|\bИрбитск\w*|\bШадринск\w*"
                r"|\bЕкатеринбург\w*|\bКрасноуфимск\w*|\bКамышлов\w*|\bЗлатоуст\w*",
}
# Явно чужая география — для пояснения, почему запись вне охвата.
ALIEN = re.compile(
    r"\bКиев\w*|\bМоскв\w*|\bС\.-?\s?Петербург\w*|\bСанкт-Петербург\w*|\bПетроград\w*"
    r"|\bНахичеван\w*|\bАрхангельск\w*|\bИркутск\w*|\bТуркестан\w*|\bМаньчжури\w*"
    r"|\bМонголи\w*|\bКита\w*|\bАмур\w*|\bСибир\w*|\bКавказ\w*|\bКрым\w*|\bФинлянд\w*"
    r"|\bВаршав\w*|\bРевел\w*|\bОдесс\w*|\bАстрахан\w*|\bОренбург\w*|\bТифлис\w*"
    r"|\bТашкент\w*|\bБухар\w*|\bКронштадт\w*|\bКамчатк\w*|\bСахалин\w*|\bАфрик\w*"
    r"|\bЕвроп\w*|\bАзи[ияю]\b|\bАмерик\w*|Российск\w+ импери\w*|земного шара", re.I)

COMPILED = {g: re.compile(p, re.I) for g, p in STRONG.items()}


def evidence(text: str, m: re.Match) -> str:
    a, b = max(0, m.start() - 35), min(len(text), m.end() + 35)
    return f"…{text[a:b].strip()}…"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    args = ap.parse_args()
    pkg = Path(args.package)

    rows = []
    for ln in (pkg / "gayo_to_catalog.jsonl").open(encoding="utf-8"):
        r = json.loads(ln)
        if str(r.get("fund")) != "560":
            continue
        title = r.get("zagolovok", "")
        hits = []
        for g, rx in COMPILED.items():
            m = rx.search(title)
            if m:
                hits.append((g, m.group(0), evidence(title, m)))
        if hits:
            r["territory_4gub"] = "; ".join(h[0] for h in hits)
            r["territory_word"] = "; ".join(h[1] for h in hits)
            r["territory_evidence"] = " | ".join(h[2] for h in hits)
            r["v_katalog"] = "да"
        else:
            r["territory_4gub"] = ""
            r["territory_word"] = ""
            am = ALIEN.search(title)
            r["territory_evidence"] = (f"чужая территория: {am.group(0)}" if am
                                       else "ни одной из 4 губерний в заголовке")
            r["v_katalog"] = "нет"
        rows.append(r)

    fields = list(rows[0].keys())
    with (pkg / "f560_territory.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with (pkg / "f560_territory.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    take = [r for r in rows if r["v_katalog"] == "да"]
    print(f"записей ф.560: {len(rows)} | в каталог: {len(take)} | не вносить: {len(rows) - len(take)}")
    print("по губерниям (строгое совпадение):")
    for g, n in Counter(g for r in take for g in r["territory_4gub"].split("; ")).most_common():
        print(f"  {n:>4}  {g}")
    print("\nвсе находки с доказательством:")
    for r in take:
        print(f"  · [{r['territory_4gub']}] {r['zagolovok'][:70]}")
        print(f"      слово: {r['territory_word']} | {r['territory_evidence'][:110]}")
    print(f"\n→ {pkg / 'f560_territory.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
