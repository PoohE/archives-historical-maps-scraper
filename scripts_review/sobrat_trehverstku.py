"""Выборка листов трёхвёрстной карты из всех собранных данных в отдельный пакет.

⚠️ ЗАЧЕМ ОТДЕЛЬНЫМ ПАКЕТОМ. Трёхвёрстная военно-топографическая карта (3 версты в
дюйме, издание Военно-топографического депо) — основной крупномасштабный источник
XIX века: на ней видны отдельные дворы, угодья и урочища. Пользователь решил внести
её целиком, потому что она понадобится для реконструкции землепользования.

⚠️ ЧТО НЕ ПУТАТЬ. Слово «трёхвёрстный» в описаниях значит два разных предмета:
  * ЛИСТ ТРЁХВЁРСТНОЙ КАРТЫ — то, что нужно;
  * «план города с ТРЁХВЁРСТНОЙ СИТУАЦИЕЙ вокруг оного» — план города, у которого
    местность показана на три версты вокруг. Это другое, в выборку не идёт.
Кроме того, считать надо ПО ЗАГОЛОВКУ: подсчёт по всем полям записи даёт ложные
срабатывания (слово попадает в название фонда или описи) — первый прогон так дал
934 «листа» вместо 421.

Источник листов — собранные данные всех прогонов, прежде всего ГАЯО, где карта
описана полистно с именами граверов: «Трёхвёрстная карта Европейской России.
Гравировали специалисты Эглов, Захаров, Иванов 5-й… Исправлена по рекогносцировке».

Запуск:
    python -B scripts_review/sobrat_trehverstku.py
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "trehverstka_package_20261024"

# Лист трёхвёрстной карты — по ЗАГОЛОВКУ
LIST_TRI = re.compile(
    r"тр[её]хверстн\w*\s+карт|карт\w*\s+тр[её]хверст"
    r"|(?:3|три)\s*версты\s+в\s+дюйм"
    r"|военно-топографическ\w+\s+карт\w*\s+(?:европейск|росси)", re.I)
# «трёхвёрстная ситуация» вокруг города — НЕ лист карты
SITUACIYA = re.compile(r"тр[её]хверстн\w+\s+ситуац", re.I)
# номер ряда и листа — ключ комплекта
RYAD_LIST = re.compile(r"ряд\s*([IVXLC\d]+)[\s,.]*лист\s*(\d+)"
                       r"|лист\s*(\d+)[\s,.]*ряд\s*([IVXLC\d]+)", re.I)

# версии одного пакета: берём самую свежую
# ⚠️ и собственный выход: иначе повторный запуск читает свой же пакет
PROPUSK = re.compile(r"^_|gayo_package_2026101[46]$|_do_|_sweep$|^trehverstka_package")


def chitat(path: str):
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            yield json.loads(ln)
        except Exception:  # noqa: BLE001, S112
            continue


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)

    vidino: set[str] = set()
    rows: list[dict] = []
    for f in glob.glob(str(ROOT / "output" / "*" / "*.jsonl")):
        papka = os.path.basename(os.path.dirname(f))
        if PROPUSK.search(papka):
            continue
        for r in chitat(f):
            z = str(r.get("title") or r.get("zagolovok") or r.get("nazvanie") or "")
            if not z or SITUACIYA.search(z) or not LIST_TRI.search(z):
                continue
            # ⚠️ Ключ против дублей — ШИФР, а не заголовок: у листов одного
            # издания описания почти совпадают («Трёхвёрстная карта Европейской
            # России. Гравировали специалисты …»), и дедуп по тексту схлопывает
            # разные листы в один (на первом прогоне 180 → 80).
            fond = str(r.get("fund") or "")
            opis = str(r.get("opis") or "")
            delo = str(r.get("delo") or r.get("n_delo") or "")
            k = "|".join([str(r.get("archive") or r.get("istochnik") or papka),
                          fond, opis, delo]) if (fond or delo) else \
                re.sub(r"\s+", " ", z.lower())[:200]
            if k in vidino:
                continue
            vidino.add(k)
            m = RYAD_LIST.search(z)
            rows.append({
                "istochnik_papka": papka,
                "arhiv": str(r.get("archive") or r.get("istochnik") or ""),
                "shifr": (f"Ф.{r.get('fund', '')} оп.{r.get('opis', '')} "
                          f"д.{r.get('delo') or r.get('n_delo') or ''}"
                          if r.get("fund") else str(r.get("shifr") or "")),
                "listov": str(r.get("listov") or ""),
                "zagolovok": z[:500],
                "ryad": (m.group(1) or m.group(4) or "") if m else "",
                "list": (m.group(2) or m.group(3) or "") if m else "",
                "god": str(r.get("god") or r.get("year_from") or r.get("data") or ""),
                "masshtab": str(r.get("scale_raw") or r.get("masshtab") or "3 версты в дюйме"),
                "territoriya": str(r.get("territoriya") or ""),
                "url": str(r.get("url") or ""),
                "klass": "картография",
                "vid": "лист трёхвёрстной военно-топографической карты",
            })

    rows.sort(key=lambda r: (r["ryad"], r["list"], r["zagolovok"]))
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with (OUT / "трехверстка_accepted.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with (OUT / "трехверстка_accepted.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"листов трёхвёрстки собрано: {len(rows)}")
    print("\nпо источникам:")
    for k, v in Counter(r["istochnik_papka"] for r in rows).most_common():
        print(f"  {v:>5}  {k}")
    print("\nс номером ряда и листа:", sum(1 for r in rows if r["ryad"] and r["list"]))
    print("с территорией проекта:  ", sum(1 for r in rows if r["territoriya"]))
    print("с годом:                ", sum(1 for r in rows if r["god"]))
    ryady = Counter(r["ryad"] for r in rows if r["ryad"])
    if ryady:
        print("\nряды:", dict(sorted(ryady.items())))
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
