"""Кросс-пакетная сверка дублей: один источник, оцифрованный разными библиотеками.

⚠️ ЗАЧЕМ. Приёмка Смоленской ОУНБ 24.10 показала: из 97 записей пакета 54 оказались
дублями уже внесённых карточек ГПИБ — «Памятная книжка Смоленской губернии» (17 томов),
«Справочная книжка» (4), «Обзор Смоленской губернии за ГОД» (33, весь ряд 1870–1913).
Это не ошибка гейта: один и тот же исторический источник оцифрован двумя библиотеками,
и каждая отдала его в своём каталоге. Приёмщик вычищал дубли вручную уже ПОСЛЕ передачи.

Скрипт делает эту сверку ДО передачи и помечает записи, у которых в других пакетах есть
двойник. Решение, какую карточку оставить, остаётся за приёмщиком — здесь только
обнаружение.

КАК СОПОСТАВЛЯЕМ. Прямое сравнение заглавий не работает: у одной библиотеки
«Памятная книжка Смоленской губернии на 1858 год», у другой — «Памятная книжка
Смоленской губернии… Адрес-календарь и памятная книжка Смоленской губернии на 1858 г.».
Поэтому ключ строится из двух частей:
  * СЕРИЯ — заглавие, очищенное от шифров, томов, выпусков, года и издательских
    сведений, приведённое к нижнему регистру и к общему ядру;
  * ГОД ТОМА — год из заглавия («на 1858 год»), а не год издания.
Совпадение ключа «серия + год» и есть вероятный дубль.

Запуск:
    python -B scripts_review/cross_dubli.py
    python -B scripts_review/cross_dubli.py --pometit output/prlib_opisaniya_package_20261021
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

# Шифры хранения, тома, выпуски, издательские сведения — всё это мешает сопоставлению
MUSOR = re.compile(
    r"\[электронный ресурс\]|\[текст\]|электрон\w*\.?\s*(?:текстов\w*\s*)?дан\w*\.?"
    r"|\d+\s*с\.|\d+\s*л\."  # том/выпуск НЕ вычищаем: он различает издания серии
    r"|загл\.?\s*с\s*титул\w*\.?\s*экрана|режим\s+доступа.*$|систем\w*\.?\s*требовани.*$"
    r"|доступ\s+по\s+паролю.*$|свободный\s+доступ.*$|<url:[^>]*>|https?://\S+"
    r"|^[А-ЯA-Z]?[\d.]{2,10}\s+[А-Я]\s?\d{1,3}\b", re.I)
# Год тома: «на 1858 год», «за 1884 год»
GOD_TOMA = re.compile(r"(?:на|за)\s+(1[5-9]\d{2}|19[0-4]\d)(?:\s*[-–/]\s*\d{2,4})?\s*(?:год|г\b|гг)", re.I)
LYUBOY_GOD = re.compile(r"\b(1[5-9]\d{2}|19[0-8]\d)\b")
PROBEL = re.compile(r"[\s\-—–.,:;/\\()\[\]«»\"']+")

# Серийные издания, выходившие ежегодно: именно они дублируются между библиотеками
SERII = re.compile(
    r"памятн\w+\s+книжк|справочн\w+\s+книжк|адрес[- ]календар|обзор\s+\w+\s+губерни"
    r"|обзор\s+губерни|календар\w+\s+\w+\s+губерни|статистическ\w+\s+обзор"
    r"|отчет\w*\s+\w*\s*губернск|список\w*\s+населенн\w+\s+мест|труд\w*\s+\w*губернск",
    re.I)


def seriya(zagl: str) -> str:
    """Ядро серии: заглавие без шифров, томов, года и издательских примечаний."""
    s = MUSOR.sub(" ", (zagl or "").lower())
    s = GOD_TOMA.sub(" ", s)
    s = LYUBOY_GOD.sub(" ", s)
    s = PROBEL.sub(" ", s).strip()
    # «адрес-календарь и памятная книжка X губернии» ≈ «памятная книжка X губернии»
    s = re.sub(r"^(?:адрес календарь|календарь|справочная книжка)\s+и\s+", "", s)
    s = re.sub(r"\s+и\s+(?:адрес календарь|памятная книжка|справочная книжка)\b", " ", s)
    return " ".join(s.split()[:9])


def god_toma(zagl: str, zapas: str = "") -> str:
    m = GOD_TOMA.search(zagl or "")
    if m:
        return m.group(1)
    m = LYUBOY_GOD.search(zagl or "")
    if m:
        return m.group(1)
    m = LYUBOY_GOD.search(str(zapas))
    return m.group(1) if m else ""


# Номер тома/выпуска: «т. 31», «Т. XXXI», «31:», «Вып. 15», «Ч. 2»
TOM = re.compile(r"\b(?:т|том|вып|выпуск|ч|часть|кн|книга)\.?\s*([IVXLC\d]{1,6})\b"
                 r"|^\s*(\d{1,3})\s*[:.]\s", re.I)


def nomer_toma(zagl: str) -> str:
    """Номер тома или выпуска — он различает издания ОДНОЙ серии.

    ⚠️ «Списки населённых мест Российской империи» выходили томами по губерниям
    (т. 15 Калужская, т. 31 Пермская, т. 40 Смоленская, т. 50 Ярославская). Без
    номера тома все четыре слипались в один ключ и выглядели дублями друг друга.
    """
    m = TOM.search(zagl or "")
    if not m:
        return ""
    return (m.group(1) or m.group(2) or "").upper()


def kluch(zagl: str, god: str = "", territoriya: str = "") -> str:
    """Ключ сопоставления: серия + год тома + территория + номер тома.

    Территория берётся из поля, уже проставленного гейтом: она окончательно
    разводит тома одной серии, изданные по разным губерниям.
    """
    ser = seriya(zagl)
    if not ser:
        return ""
    g = god_toma(zagl, god)
    terr = " ".join(sorted(x.strip() for x in str(territoriya).split(";") if x.strip()))
    return f"{ser}|{g}|{terr}|{nomer_toma(zagl)}"


def chitat(path: str):
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            yield json.loads(ln)
        except Exception:  # noqa: BLE001, S112
            continue


def rabochie_papki() -> list[str]:
    """Только рабочие пакеты: без резервных копий и без старых версий.

    ⚠️ Без этого отбора сверка сравнивает пакет сам с собой: рядом лежат копии вида
    `_gpib_package_..._do_ispravleniya_Roslavl` (снимок перед правкой) и несколько
    версий ГАЯО за разные дни. Первый прогон 24.10 из-за этого пометил в ГПИБ
    202 дубля из 233 — почти весь пакет.
    """
    vse = [os.path.basename(os.path.dirname(f))
           for f in glob.glob(str(OUT / "*_package_*" / "*accepted.jsonl"))]
    # резервные копии помечены ведущим подчёркиванием
    vse = [p for p in vse if not p.startswith("_")]
    # из нескольких версий одного источника — самая свежая по дате в имени
    svezhie: dict[str, str] = {}
    for p in vse:
        m = re.match(r"(.+?_package)_?(\d{8})?$", p)
        osnova = m.group(1) if m else p
        data = (m.group(2) or "") if m else ""
        if osnova not in svezhie or data > svezhie[osnova].rsplit("_", 1)[-1]:
            svezhie[osnova] = p
    return sorted(svezhie.values())


def sobrat() -> dict[str, list[dict]]:
    """Принятые записи рабочих пакетов: {папка: [записи]}."""
    out: dict[str, list[dict]] = {}
    rabochie = set(rabochie_papki())
    for f in glob.glob(str(OUT / "*_package_*" / "*accepted.jsonl")):
        papka = os.path.basename(os.path.dirname(f))
        if papka not in rabochie:
            continue
        rows = []
        for r in chitat(f):
            zagl = str(r.get("zagolovok") or r.get("nazvanie") or "")
            rows.append({
                "papka": papka,
                "id": str(r.get("node_id") or r.get("predmet_id") or r.get("mfn")
                          or r.get("handle") or r.get("nomer") or ""),
                "zagolovok": zagl,
                "god": str(r.get("god") or r.get("data") or ""),
                "kluch": kluch(zagl, str(r.get("god") or r.get("data") or ""),
                               str(r.get("territoriya") or "")),
                "seriynoe": bool(SERII.search(zagl)),
                "istochnik": str(r.get("istochnik") or ""),
            })
        if rows:
            out[papka] = rows
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pometit", default="", help="папка пакета: дописать пометки в CSV")
    args = ap.parse_args()

    pakety = sobrat()
    print("пакетов:", len(pakety))
    for p, rows in sorted(pakety.items()):
        print(f"  {len(rows):>5}  {p}")

    # индекс ключей по всем пакетам
    indeks: dict[str, list[dict]] = defaultdict(list)
    for rows in pakety.values():
        for r in rows:
            if r["kluch"]:
                indeks[r["kluch"]].append(r)

    peresech = {k: v for k, v in indeks.items()
                if len({x["papka"] for x in v}) > 1}
    print(f"\nКЛЮЧЕЙ, ВСТРЕЧАЮЩИХСЯ В РАЗНЫХ ПАКЕТАХ: {len(peresech)}")

    pary = Counter()
    for v in peresech.values():
        papki = sorted({x["papka"] for x in v})
        for i in range(len(papki)):
            for j in range(i + 1, len(papki)):
                pary[(papki[i], papki[j])] += 1
    print("\nПЕРЕСЕЧЕНИЯ МЕЖДУ ПАКЕТАМИ (сколько общих ключей):")
    for (a, b), n in pary.most_common(20):
        print(f"  {n:>4}  {a}  ×  {b}")

    print("\nПРИМЕРЫ ДУБЛЕЙ (первые 12):")
    for k, v in list(peresech.items())[:12]:
        print(f"  ключ «{k}»")
        for x in v[:3]:
            print(f"      [{x['papka'][:30]:32}] {x['zagolovok'][:76]}")

    # отчёт
    rep = OUT / "кросс_дубли_по_пакетам.csv"
    with rep.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ключ_серия_год", "пакет", "id", "год", "серийное", "заголовок"])
        for k, v in sorted(peresech.items()):
            for x in v:
                w.writerow([k, x["papka"], x["id"], x["god"],
                            "да" if x["seriynoe"] else "", x["zagolovok"][:300]])
    print(f"\n→ {rep}")

    # пометки в конкретный пакет
    if args.pometit:
        d = Path(args.pometit)
        f = next(iter(glob.glob(str(d / "*accepted.jsonl"))), None)
        if not f:
            print(f"нет accepted в {d}")
            return 1
        papka = d.name
        chuzhie = {k: [x for x in v if x["papka"] != papka] for k, v in peresech.items()}
        rows = list(chitat(f))
        pomecheno = 0
        for r in rows:
            zagl = str(r.get("zagolovok") or r.get("nazvanie") or "")
            k = kluch(zagl, str(r.get("god") or r.get("data") or ""),
                      str(r.get("territoriya") or ""))
            dvoyniki = chuzhie.get(k) or []
            r["dubl_v_drugom_pakete"] = "; ".join(
                f"{x['papka']}:{x['id']}" for x in dvoyniki)[:300]
            r["seriynoe_izdanie"] = "да" if SERII.search(zagl) else ""
            if dvoyniki:
                pomecheno += 1
        with open(f, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with open(f.replace(".jsonl", ".csv"), "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print(f"\nв пакете {papka}: помечено дублей {pomecheno} из {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
