"""Проверка пакета ПЕРЕД заливкой в каталог: не воспроизводим ли старые дефекты.

Решение пользователя 10.11.2026. Повод — замер готовых к внесению пакетов:
4 496 записей, и у **970 из них дата дела приходит ДИАПАЗОНОМ** («1881–»,
«16.12.1913–30.12.1916»). Если залить их обычным способом, диапазон уедет в поле
единичного года ровно так же, как раньше уезжали крайние даты описи, — и мы получим
970 новых дефектных записей против 1 847 только что исправленных.

Это НЕ модуль внесения: скрипт ничего не пишет и не правит. Он отвечает на один
вопрос — какие записи пакета нельзя вносить как есть.

Три правила (все выведены из уже случившихся ошибок):
  1. **Диапазон дат не кладётся в одно поле года.** Нижняя и верхняя границы идут
     в «Год создания (нижняя)» и «(верхняя)» раздельно; одно число из диапазона —
     ошибка. Источник правила: 1 847 записей ГАПК с годом по крайним датам описи.
  2. **«Год источника» при диапазоне остаётся пустым.** Это поле единичного
     значения, приблизительного значения у него быть не может.
  3. **Масштаб без признака происхождения не пишется.** Источник правила:
     42 615 эвристических масштабов, из-за которых подсчёт дал ложный вывод
     «в горнозаводском слое доминирует 1:8 400».

  python preflight_upload.py <пакет.jsonl> [--profile gaso|rgo|neb|auto]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")

from common import fix_stdout  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "output" / "defects"

#: диапазон дат в любом виде: «1881–», «1854-1865», «16.12.1913–30.12.1916», «1854 г. 1853»
RANGE = re.compile(
    r"(1[5-9]\d{2}|20\d{2})\s*(?:г\.?)?\s*[–—-]\s*(?:(1[5-9]\d{2}|20\d{2}))?"
    r"|(?:\d{1,2}\.\d{1,2}\.)?(1[5-9]\d{2})\D+(?:\d{1,2}\.\d{1,2}\.)?(1[5-9]\d{2})"
)
YEAR = re.compile(r"(1[5-9]\d{2}|20\d{2})")

#: как поля пакета называются в разных источниках
PROFILES = {
    "gaso": {"dates": "dates", "lo": "year_lo", "hi": "year_hi",
             "scale": "scale", "scale_src": "scale_src", "title": "title"},
    "rgo": {"dates": "year", "lo": None, "hi": None,
            "scale": "scale", "scale_src": "scale_src", "title": "title"},
    "neb": {"dates": "god", "lo": None, "hi": None,
            "scale": "scale", "scale_src": None, "title": "zagolovok_polnyi"},
}


def guess_profile(row: dict) -> str:
    if "year_lo" in row or "fond_name" in row:
        return "gaso"
    if "pdf" in row or "description" in row:
        return "rgo"
    return "neb"


def years_in(s: str) -> list[int]:
    return [int(x) for x in YEAR.findall(s or "")]


def main() -> None:
    fix_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    ap.add_argument("--profile", default="auto")
    args = ap.parse_args()

    src = Path(args.package)
    if not src.exists():
        sys.exit(f"нет файла пакета: {src}")
    rows = [json.loads(ln) for ln in src.open(encoding="utf-8") if ln.strip()]
    if not rows:
        sys.exit("пакет пуст")
    prof_name = args.profile if args.profile != "auto" else guess_profile(rows[0])
    p = PROFILES.get(prof_name)
    if not p:
        sys.exit(f"неизвестный профиль: {prof_name}")
    print(f"пакет: {src.name} | записей: {len(rows)} | профиль полей: {prof_name}\n")

    problems: Counter = Counter()
    flagged: list[dict] = []
    #: осознанные исправления сборщика пакета — не дефект, но требуют глаз
    softs: list[dict] = []
    for i, r in enumerate(rows):
        issues: list[str] = []
        raw = str(r.get(p["dates"]) or "").strip()
        ys = years_in(raw)

        # правило 1: диапазон не кладётся в одно поле.
        # ⚠️ Важно, что считать диапазоном: «28.02.1915–28.11.1915» — это РАЗНЫЕ
        # даты ОДНОГО года, и нижняя = верхняя = 1915 здесь правильно. Дефект —
        # только когда в датах РАЗНЫЕ ГОДЫ, а в полях остался один.
        distinct = sorted(set(ys))
        is_range = len(distinct) > 1
        if is_range:
            lo = r.get(p["lo"]) if p["lo"] else None
            hi = r.get(p["hi"]) if p["hi"] else None
            if p["lo"] is None or p["hi"] is None:
                issues.append("разные годы в датах, а в пакете нет полей нижней и верхней границы")
            elif lo is None or hi is None or lo == hi:
                issues.append(
                    f"разные годы «{raw[:40]}» сведены к одному (нижняя {lo}, верхняя {hi})")
            elif (lo, hi) != (distinct[0], distinct[-1]):
                # ⚠️ Запись могла быть ОСОЗНАННО исправлена сборщиком пакета:
                # в описях встречаются опечатки века («1849-1958гг.» = 1858), и
                # сборщик чинит их, оставляя след в `year_fix`. Тогда расхождение
                # с сырым текстом — не дефект, а само исправление; но человек о нём
                # должен знать, поэтому запись попадает в отдельный, мягкий список.
                if r.get("year_fix"):
                    softs.append({
                        "i": i, "dates": raw[:50],
                        "title": str(r.get(p["title"]) or "")[:90],
                        "fix": r.get("year_fix"),
                    })
                else:
                    issues.append(
                        f"границы не совпадают с датами: в тексте "
                        f"{distinct[0]}–{distinct[-1]}, в полях {lo}–{hi}")

        # правило 2: «Год источника» при диапазоне пуст
        if is_range and r.get("god_istochnika") not in (None, "", 0):
            issues.append("при диапазоне заполнен «Год источника» — поле единичного значения")

        # правило 3: масштаб без признака происхождения
        if r.get(p["scale"]):
            srcf = p["scale_src"]
            if not srcf or not r.get(srcf):
                issues.append("масштаб есть, признак происхождения значения не задан")

        if issues:
            for s in issues:
                problems[s.split("«")[0].strip()] += 1
            flagged.append({"i": i, "title": str(r.get(p["title"]) or "")[:110],
                            "dates": raw[:50], "issues": issues})

    print("НАХОДКИ:")
    if not problems:
        print("  чисто — пакет можно вносить как есть")
    for k, c in problems.most_common():
        print(f"  {c:5d}  {k}")
    if softs:
        print(f"\n⚠️ ОСОЗНАННЫЕ ИСПРАВЛЕНИЯ СБОРЩИКА — подтвердить глазами: {len(softs)}")
        for s in softs:
            print(f"  #{s['i']} «{s['dates']}» {s['fix']} | {s['title'][:70]}")
    print(f"\nзаписей с замечаниями: {len(flagged)} из {len(rows)}")
    for r in flagged[:8]:
        print(f"  #{r['i']} «{r['dates']}» {r['title'][:70]}")
        for s in r["issues"]:
            print(f"      — {s}")

    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"preflight_{src.stem}.jsonl"
    with dst.open("w", encoding="utf-8") as f:
        for r in flagged:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    print(f"\n→ {dst}")
    print("\nвывод: " + ("ВНОСИТЬ МОЖНО" if not flagged
                         else "ВНОСИТЬ НЕЛЬЗЯ как есть — сначала разложить даты по "
                              "двум полям и проставить признак масштаба"))
    sys.exit(2 if flagged else 0)


if __name__ == "__main__":
    main()
