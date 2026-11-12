"""Сборка пакета по ГАСО-Урал: из распознанных описей — записи под каталог.

Вход: output/gaso_ural/opisi_rows.jsonl (результат `gaso_ural_read_opisi.py`).
Выход: output/gaso_ural/package.jsonl — по строке на дело, с шифром, датами,
масштабом и размером, плюс территориальный вердикт.

Что важно в этих данных и чего нет больше нигде:
  * **масштаб прямо из описи** («100 саж. а. д. 1:8400») — происхождение
    «из заголовка описи», а не эвристика по типу источника;
  * **размер листа в сантиметрах** — его в каталоге почти нет;
  * пометка, что значение вписано ОТ РУКИ.

  python gaso_ural_package.py
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

from territory_gate import classify, our_gubernii  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "output" / "gaso_ural"
SRC = ROOT / "opisi_rows.jsonl"
OUT = ROOT / "package.jsonl"
TARGETS = ROOT / "target_funds.json"

#: «100 саж. а. д. 1:8400», «1:8400», «2 версты в дюйме»
SC_DIRECT = re.compile(r"1\s*[:：]\s*(\d[\d\s\u00a0]{2,12})")
SC_SAZH = re.compile(r"(\d{1,4})\s*саж", re.IGNORECASE)
SC_VERST = re.compile(r"(\d{1,3})\s*вер?с?т", re.IGNORECASE)
YEARS = re.compile(r"(1[5-9]\d{2}|20\d{2})")


def scale_of(s: str | None) -> tuple[int | None, str | None]:
    if not s:
        return None, None
    m = SC_DIRECT.search(s)
    if m:
        return int(re.sub(r"\D", "", m.group(1))), "в описи указан знаменатель"
    m = SC_SAZH.search(s)
    if m:
        return int(m.group(1)) * 84, "пересчёт из саженей в дюйме"
    m = SC_VERST.search(s)
    if m:
        return int(m.group(1)) * 42000, "пересчёт из вёрст в дюйме"
    return None, None


def main() -> None:
    fix_stdout()
    if not SRC.exists():
        sys.exit(f"нет {SRC}")
    names = {}
    if TARGETS.exists():
        for num, rec in json.loads(TARGETS.read_text(encoding="utf-8")).items():
            names[num] = rec.get("name") or ""

    seen: dict[str, dict] = {}
    for ln in SRC.open(encoding="utf-8"):
        if not ln.strip():
            continue
        d = json.loads(ln)
        seen[d.get("cid")] = d

    pack: list[dict] = []
    kinds: Counter = Counter()
    # ⚠️ В описях действует конвенция «То же»: заголовок не повторяют, а ссылаются
    # на предыдущий. Без разворачивания ф. 64 даёт нечитаемые строки вида
    # «То же — рзд XIII, лист 3». Поэтому ведём последний ПОЛНЫЙ заголовок внутри
    # одной описи и подставляем его, помечая подстановку.
    SAME = re.compile(r"^\s*(?:то\s*же|-\s*\"?-|то-?же)\b[\s,.:;-]*", re.IGNORECASE)
    last_full: dict[str, str] = {}
    last_dates: dict[str, str] = {}
    for cid, d in sorted(seen.items()):
        kinds[d.get("page_kind") or "?"] += 1
        fond, opis = (cid.split("/")[0].split("_") + ["?"])[:2]
        key = f"{fond}_{opis}"
        for r in d.get("rows") or []:
            title = (r.get("title") or "").strip()
            expanded = False
            if title and SAME.match(title):
                tail = SAME.sub("", title).strip(" ,.;:-")
                base = last_full.get(key)
                if base:
                    title = f"{base} — {tail}" if tail else base
                    expanded = True
            elif title:
                last_full[key] = title

            dates = (r.get("dates") or "").strip()
            if dates in ('-"-', "-''-", "то же", "То же", ""):
                dates = last_dates.get(key, dates)
            elif dates:
                last_dates[key] = dates

            den, how = scale_of(r.get("scale"))
            # ⚠️ Годы в описи идут не по порядку: «1862 ГОД. 1861 г.», «1853–1854»
            # с первым 1854. Брать первый найденный как нижний нельзя — границы
            # переворачивались у 24 записей (найдено проверкой preflight 10.11.2026).
            ys_raw = [int(x) for x in YEARS.findall(str(dates))]
            # ⚠️ Опечатки распознавания в годах имеют один вид: перепутан ВЕК.
            # «1849-1950гг.» (переписка заводов) — это 1850, «1967-1868гг.» — 1867,
            # «1976-1877гг.» — 1876, и последнее подтверждается самим заголовком
            # дела «…за 1876-1877гг.». Поэтому невозможный год не отбрасываем,
            # а чиним: берём век у правдоподобного соседа, сохраняя две последние
            # цифры. Исправление помечается — его должен подтвердить человек.
            plausible = [y for y in ys_raw if y <= 1945]
            fixed: list[int] = []
            year_fix: list[str] = []
            for y in ys_raw:
                if y <= 1945:
                    fixed.append(y)
                    continue
                if plausible:
                    cand = plausible[0] // 100 * 100 + y % 100
                    fixed.append(cand)
                    year_fix.append(f"{y}→{cand}")
                else:
                    fixed.append(y)
            ys = sorted(set(fixed))
            suspect_year = bool(year_fix)
            blob = " ".join(str(x or "") for x in (title, r.get("note")))
            pack.append({
                "arch": "ГАСО-Урал (Свердловск)",
                "fond": fond,
                "fond_name": names.get(fond, ""),
                "opis": opis,
                "delo": r.get("delo"),
                "old_no": r.get("old_no"),
                "title": title or None,
                "title_expanded": expanded,
                "dates": dates or None,
                "year_lo": ys[0] if ys else None,
                "year_hi": ys[-1] if ys else None,
                "year_src": "из описи" if ys else "нет",
                "year_suspect": suspect_year,
                "year_fix": year_fix,
                "scale_raw": r.get("scale"),
                "scale": den,
                "scale_how": how,
                "scale_src": "из заголовка описи" if den else "не установлен",
                "sheets": r.get("sheets"),
                "handwritten": r.get("handwritten") or [],
                "note": r.get("note"),
                "gub": our_gubernii(blob),
                "scope": classify(blob)[0] if blob.strip() else "нет",
                "page": cid,
            })

    with OUT.open("w", encoding="utf-8") as f:
        for p in pack:
            f.write(json.dumps(p, ensure_ascii=False) + chr(10))

    print(f"страниц разобрано: {len(seen)} | виды: {dict(kinds)}")
    print(f"ДЕЛ В ПАКЕТЕ: {len(pack)}\n")
    print("по фондам:")
    for k, c in Counter(f"ф. {p['fond']} оп. {p['opis']}" for p in pack).most_common():
        print(f"  {c:5d}  {k}")
    print(f"\nс масштабом из описи: {sum(1 for p in pack if p['scale'])}")
    print("  способ: " + str(dict(Counter(p["scale_how"] for p in pack if p["scale"]))))
    print(f"с датами: {sum(1 for p in pack if p['year_lo'])}")
    print(f"с размером листа: {sum(1 for p in pack if p['sheets'])}")
    print(f"с рукописными значениями: {sum(1 for p in pack if p['handwritten'])}")
    gc: Counter = Counter()
    for p in pack:
        for g in p["gub"] or ["(территория из заголовка не читается)"]:
            gc[g] += 1
    print("\nпо губерниям (из заголовка дела):")
    for g, c in gc.most_common():
        print(f"  {c:5d}  {g}")
    top = Counter(p["scale"] for p in pack if p["scale"]).most_common(6)
    print("\nмасштабы (ФАКТ из описи, не эвристика):")
    for den, c in top:
        print(f"  {c:5d}  1:{den}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
