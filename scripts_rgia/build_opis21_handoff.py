"""Пакет передачи по описи 21 ф. 380: содержание бумажной описи, привязанное к делам.

Ключ связи найден 11.10.2026 (подсказал пользователь): карандашный сквозной номер
в бумажной описи = номер единицы хранения, то есть номер дела в базе РГИА.
Проверка: все 408 карандашных номеров Vision-распознавания уникальны и все до единого
находят дело; ручная расшифровка Чердынского уезда (Влад) нумерует тем же счётом
и доходит до 693 — максимального номера дела описи.

Два источника содержания:
  1. Vision-распознавание 11 уездов + общегубернская часть (мои прогоны 10-11.10);
  2. ручная расшифровка Чердынского уезда (`reference_sets/…cherdyn_opis_vlad.csv`).
При пересечении приоритет у ручной расшифровки, Vision-вариант уходит в примечание.

Запуск:
    python -B scripts_rgia/build_opis21_handoff.py [--out <папка>]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISION_GLOB = "output/rgia_f380_op21_*_vision_2026*/records.jsonl"
VLAD = ROOT / "reference_sets" / "rgia_f380_cherdyn_vlad_20261003" / "cherdyn_opis_vlad.csv"
CASES = ROOT / "output" / "rgia_fund380_handoff_package_20261008" / "records_clean.csv"

# первый сквозной номер Чердынского уезда по указателю разделов описи
CHERDYN_FIRST = 417

FIELDS = [
    "fund_code", "delo_no", "title", "razdel", "uezd", "guberniya",
    "katalog", "dacha_n", "planov", "scale_raw", "udobnoy", "vsego", "podlinnik",
    "list", "scan", "source", "url", "vybylo", "needs_human", "needs_human_reason",
    "arith_ok", "note",
]


def load_vision() -> list[dict]:
    out = []
    for p in sorted(ROOT.glob(VISION_GLOB.replace("output/", "output/"))):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r["_src"] = "vision"
                out.append(r)
    return out


def load_vlad() -> list[dict]:
    rows = list(csv.reader(VLAD.open(encoding="utf-8-sig")))
    out = []
    for r in rows[2:]:
        if len(r) < 11:
            r = r + [""] * (11 - len(r))
        num = r[1].strip()
        # ВАЖНО: в расшифровке Влада колонка «№ п/п» неоднородна. Чердынский уезд идёт
        # сквозным счётом описи (417…693), но в четырёх местах счёт сброшен на нумерацию
        # внутри рубрики (строки 10, 113, 122, 207 — «Крестьянские земли» с 1,
        # «Оброчные статьи» с 97 и 106, «Казенные леса» с 1 и 14). Такие номера НЕ являются
        # номерами дел: взятые как ключ, они затирают записи других уездов
        # (поймано 11.10 при сборке — верхотурские Д. 14-16 были перекрыты чердынскими).
        # Поэтому ключом считаем только номера от 417 — начала Чердынского уезда
        # по указателю разделов.
        n_val = int(num) if num.isdigit() else None
        local = n_val is not None and n_val < CHERDYN_FIRST
        out.append({
            "n": None if local else n_val,
            "n_local": n_val if local else None,
            "razdel": r[0].strip(),
            "katalog": r[2].strip(),
            "dacha_n": r[3].strip(),
            "title": r[4].strip(),
            "planov": r[5].strip(),
            "scale_raw": r[6].strip(),
            "udobnoy": r[7].strip(),
            "vsego": r[8].strip(),
            "podlinnik": r[9].strip(),
            "note": r[10].strip(),
            "uezd": "Чердынский",
            "guberniya": "Пермская",
            "list": "", "scan": "", "vybylo": False,
            "needs_human": False, "needs_human_reason": "", "arith_ok": None,
            "_src": "ручная расшифровка (Влад)",
        })
    return out


def load_cases() -> dict[int, str]:
    url_by_delo: dict[int, str] = {}
    with CASES.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            m = re.search(r"Оп\. 21 Д\. (\d+)", r.get("fund_code", ""))
            if m:
                url_by_delo[int(m.group(1))] = r.get("url", "")
    return url_by_delo


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out_dir = Path(args.out) if args.out else (
        ROOT / "output" / f"rgia_f380_op21_handoff_{datetime.now():%Y%m%d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    vision = load_vision()
    vlad = load_vlad()
    urls = load_cases()

    # приоритет ручной расшифровки при совпадении номера
    by_n: dict[int, dict] = {}
    extra: list[dict] = []
    conflicts = []

    for r in vision:
        n = r.get("n")
        if isinstance(n, int):
            by_n[n] = r
        else:
            extra.append(r)

    for r in vlad:
        n = r.get("n")
        if not isinstance(n, int):
            extra.append(r)
            continue
        if n in by_n and by_n[n]["_src"] == "vision":
            v = by_n[n]
            conflicts.append(n)
            r["note"] = (r.get("note", "") + "; " if r.get("note") else "") + (
                f"Vision прочитал иначе: «{(v.get('title') or '')[:80]}», "
                f"удобной {v.get('udobnoy') or '—'}, всего {v.get('vsego') or '—'}")
        by_n[n] = r

    rows = []
    stat = Counter()
    for n in sorted(by_n):
        r = by_n[n]
        url = urls.get(n, "")
        stat["привязано к делу" if url else "дела нет в базе"] += 1
        stat[r["_src"]] += 1
        rows.append({
            "fund_code": f"Ф. 380 Оп. 21 Д. {n}",
            "delo_no": n,
            "title": r.get("title", ""),
            "razdel": r.get("razdel", ""),
            "uezd": r.get("uezd", ""),
            "guberniya": r.get("guberniya", "Пермская"),
            "katalog": r.get("katalog", ""),
            "dacha_n": r.get("dacha_n", ""),
            "planov": r.get("planov", ""),
            "scale_raw": r.get("scale_raw", ""),
            "udobnoy": r.get("udobnoy", ""),
            "vsego": r.get("vsego", ""),
            "podlinnik": r.get("podlinnik", ""),
            "list": r.get("list", ""),
            "scan": r.get("scan", ""),
            "source": r["_src"],
            "url": url,
            "vybylo": "да" if r.get("vybylo") else "",
            "needs_human": "да" if r.get("needs_human") else "",
            "needs_human_reason": r.get("needs_human_reason", ""),
            "arith_ok": {True: "ok", False: "НЕ СХОДИТСЯ"}.get(r.get("arith_ok"), ""),
            "note": r.get("note", ""),
        })

    linked = out_dir / "opis21_records_linked.csv"
    with linked.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    # записи без номера дела — отдельным файлом, не теряем
    nolink = out_dir / "opis21_records_without_delo.csv"
    with nolink.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in extra:
            w.writerow({
                "fund_code": "", "delo_no": "", "title": r.get("title", ""),
                "razdel": r.get("razdel", ""), "uezd": r.get("uezd", ""),
                "guberniya": r.get("guberniya", "Пермская"),
                "katalog": r.get("katalog", ""), "dacha_n": r.get("dacha_n", ""),
                "planov": r.get("planov", ""), "scale_raw": r.get("scale_raw", ""),
                "udobnoy": r.get("udobnoy", ""), "vsego": r.get("vsego", ""),
                "podlinnik": r.get("podlinnik", ""), "list": r.get("list", ""),
                "scan": r.get("scan", ""), "source": r["_src"], "url": "",
                "vybylo": "да" if r.get("vybylo") else "",
                "needs_human": "да" if r.get("needs_human") else "",
                "needs_human_reason": r.get("needs_human_reason", ""),
                "arith_ok": {True: "ok", False: "НЕ СХОДИТСЯ"}.get(r.get("arith_ok"), ""),
                "note": r.get("note", ""),
            })

    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "link_key": "карандашный сквозной № в бумажной описи = № дела (единицы хранения)",
        "linked_records": len(rows),
        "records_without_delo": len(extra),
        "cases_in_base": len(urls),
        "cases_still_empty": len(set(urls) - set(by_n)),
        "conflicts_vision_vs_manual": conflicts,
        "by_source": {k: v for k, v in stat.items()
                      if k in ("vision", "ручная расшифровка (Влад)")},
        "linked_to_case_url": stat["привязано к делу"],
        "no_case_in_base": stat["дела нет в базе"],
    }
    (out_dir / "HANDOFF_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"записей с номером дела: {len(rows)}")
    print(f"  из них Vision: {stat['vision']}, ручных: "
          f"{stat['ручная расшифровка (Влад)']}")
    print(f"  привязано к карточке РГИА: {stat['привязано к делу']}, "
          f"нет дела в базе: {stat['дела нет в базе']}")
    print(f"записей без номера дела: {len(extra)}")
    print(f"дел в базе всего: {len(urls)}; останутся пустыми: "
          f"{len(set(urls) - set(by_n))}")
    if conflicts:
        print(f"расхождения Vision/человек (взят человек): {conflicts}")
    print(f"\nCSV:   {linked}")
    print(f"CSV:   {nolink}")
    print(f"Отчёт: {out_dir / 'HANDOFF_REPORT.json'}")


if __name__ == "__main__":
    main()
