"""Пакет передачи по описи 37 ф. 380 (Ярославская губерния): содержание, привязанное к делам.

Ключ связи тот же, что для описи 21: карандашный сквозной номер в бумажной описи =
номер единицы хранения = номер дела в базе РГИА. Для описи 37 ключ проверен итогами
ревизии 1946 г.: в семи уездах из десяти число карандашных номеров точно совпало
с «налицо» по штампу ревизора, а диапазоны уездов стыкуются без разрывов
(116→117, 249→250, 310→311, 390→391, 542→543, 642→643, 752→753, 807→808, 961→962).

ВАЖНО — сшивка. В описи 37 один карандашный номер часто поставлен овалом или скобкой
на несколько чернильных строк: это одно дело из нескольких планов. Сама ревизия это
подтверждает дважды: «в разделе „в" 135 №№ составляют 97 ед. хр.» (Ростовский, л. 120)
и «266 №№ составляют 143 ед. хр.» (Ярославский, л. 178). Поэтому записи распознавания
с одинаковым номером здесь СЛИВАЮТСЯ в одну строку на дело: заголовки и номера
каталога объединяются, площади берутся из первой (головной) строки группы, площади
остальных строк уходят в примечание — иначе в Notion одно дело размножилось бы
на десяток строк.

Записи без карандашного номера (выбывшие и перенесённые в другие рубрики) номерами
дел не являются и выносятся отдельным файлом.

Запуск:
    python -B scripts_rgia/build_opis37_handoff.py [--out <папка>]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISION = ROOT / "output" / "rgia_f380_op37_yaroslavl_vision_20261011" / "records.jsonl"
CASES = ROOT / "output" / "rgia_f380_op37_restored_20261011" / "opis37_restored_queue.csv"

FIELDS = [
    "fund_code", "delo_no", "title", "razdel", "uezd", "guberniya",
    "katalog", "dacha_n", "planov", "scale_raw", "udobnoy", "vsego", "podlinnik",
    "list", "scan", "source", "url", "vybylo", "needs_human", "needs_human_reason",
    "arith_ok", "note",
]


def load_vision() -> list[dict]:
    return [json.loads(ln) for ln in VISION.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def load_cases() -> dict[int, str]:
    url_by_delo: dict[int, str] = {}
    with CASES.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            m = re.search(r"Д\. (\d+)", r.get("fund_code", "") or "")
            if m:
                url_by_delo[int(m.group(1))] = r.get("url", "")
    return url_by_delo


def join_uniq(values) -> str:
    seen, out = set(), []
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return "; ".join(out)


def merge_group(n: int, group: list[dict]) -> dict:
    """Свести записи одного дела в одну строку."""
    head = group[0]
    extra_areas = []
    for g in group[1:]:
        if g.get("udobnoy") or g.get("vsego"):
            extra_areas.append(
                f"{(g.get('title') or '')[:60]}: "
                f"{g.get('udobnoy') or '—'} → {g.get('vsego') or '—'}")
    notes = [g.get("note", "") for g in group]
    if len(group) > 1:
        notes.insert(0, f"дело сшито из {len(group)} строк описи")
    if extra_areas:
        notes.append("площади остальных строк: " + "; ".join(extra_areas))
    lists = join_uniq(str(g.get("list") or "") for g in group)
    scans = sorted({g.get("scan") for g in group if g.get("scan")})
    return {
        "n": n,
        "title": join_uniq(g.get("title") for g in group),
        "razdel": join_uniq(g.get("razdel") for g in group),
        "uezd": head.get("uezd", ""),
        "guberniya": head.get("guberniya", "Ярославская"),
        "katalog": join_uniq(g.get("katalog") for g in group),
        "dacha_n": join_uniq(g.get("dacha_n") for g in group),
        "planov": head.get("planov", ""),
        "scale_raw": head.get("scale_raw", ""),
        "udobnoy": head.get("udobnoy", ""),
        "vsego": head.get("vsego", ""),
        "podlinnik": head.get("podlinnik", ""),
        "list": lists,
        "scan": f"{scans[0]}-{scans[-1]}" if len(scans) > 1 else (
            str(scans[0]) if scans else ""),
        "vybylo": any(g.get("vybylo") for g in group),
        "needs_human": any(g.get("needs_human") for g in group),
        "needs_human_reason": join_uniq(g.get("needs_human_reason") for g in group),
        "arith_ok": False if any(g.get("arith_ok") is False for g in group) else None,
        "note": join_uniq(notes),
        "_rows": len(group),
    }


def row_out(r: dict, url: str = "") -> dict:
    return {
        "fund_code": f"Ф. 380 Оп. 37 Д. {r['n']}" if r.get("n") else "",
        "delo_no": r.get("n") or "",
        "title": r.get("title", ""),
        "razdel": r.get("razdel", ""),
        "uezd": r.get("uezd", ""),
        "guberniya": r.get("guberniya", "Ярославская"),
        "katalog": r.get("katalog", ""),
        "dacha_n": r.get("dacha_n", ""),
        "planov": r.get("planov", ""),
        "scale_raw": r.get("scale_raw", ""),
        "udobnoy": r.get("udobnoy", ""),
        "vsego": r.get("vsego", ""),
        "podlinnik": r.get("podlinnik", ""),
        "list": r.get("list", ""),
        "scan": r.get("scan", ""),
        "source": "vision",
        "url": url,
        "vybylo": "да" if r.get("vybylo") else "",
        "needs_human": "да" if r.get("needs_human") else "",
        "needs_human_reason": r.get("needs_human_reason", ""),
        "arith_ok": {True: "ok", False: "НЕ СХОДИТСЯ"}.get(r.get("arith_ok"), ""),
        "note": r.get("note", ""),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out_dir = Path(args.out) if args.out else (
        ROOT / "output" / f"rgia_f380_op37_handoff_{datetime.now():%Y%m%d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    vision = load_vision()
    urls = load_cases()

    groups: dict[int, list[dict]] = defaultdict(list)
    extra: list[dict] = []
    for r in vision:
        n = r.get("n")
        if isinstance(n, int):
            groups[n].append(r)
        else:
            extra.append(r)

    rows, stat = [], Counter()
    sewn = []
    for n in sorted(groups):
        merged = merge_group(n, groups[n])
        if merged["_rows"] > 1:
            sewn.append({"delo": n, "строк": merged["_rows"]})
        url = urls.get(n, "")
        stat["привязано к делу" if url else "дела нет в базе"] += 1
        if merged["vybylo"]:
            stat["выбыло"] += 1
        if merged["arith_ok"] is False:
            stat["арифметика не сходится"] += 1
        rows.append(row_out(merged, url))

    linked = out_dir / "opis37_records_linked.csv"
    with linked.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    nolink = out_dir / "opis37_records_without_delo.csv"
    with nolink.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in extra:
            w.writerow(row_out(r))

    by_uezd = Counter(r["uezd"] for r in rows)
    report = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "opis": "Ф. 380 Оп. 37 (Ярославская губерния)",
        "link_key": "карандашный сквозной № в бумажной описи = № дела (единицы хранения)",
        "source_records": len(vision),
        "linked_deals": len(rows),
        "deals_sewn_from_several_rows": len(sewn),
        "records_without_delo": len(extra),
        "cases_in_base": len(urls),
        "cases_still_empty": len(set(urls) - set(groups)),
        "linked_to_case_url": stat["привязано к делу"],
        "no_case_in_base": stat["дела нет в базе"],
        "vybylo": stat["выбыло"],
        "arith_failed": stat["арифметика не сходится"],
        "by_uezd": dict(by_uezd),
        "annotation_fix": (
            "аннотация РГИА к описи 37 «Черниговская-Ярославская» неверна: "
            "по машинописному указателю описи (скан 3) вторая губерния — ЭСТЛЯНДСКАЯ"),
        "deals_1_9_out_of_scope": (
            "дела 1-9 относятся к ПЕРВОЙ части описи (лл. 1-9) — это Эстляндская "
            "губерния, а не Ярославская: её последняя запись на л. 9 — «Острова "
            "Наргена» (Найссаар под Ревелем, кат. 1103), там же свой штамп ревизии "
            "1946 г.: внесено 10, выбыла 1, налицо 9. Ярославская часть открывается "
            "титулом «ЧАСТЬ XIX» и начинается с л. 10 (дело № 10). Поэтому 9 дел "
            "без содержания — не пробел распознавания, а материал вне охвата проекта"),
        "control_note": (
            "сверка с итогами ревизии 1946 г. сошлась в 7 уездах из 10; "
            "расхождения на единицы — в Мышкинском (+1), Пошехонском (−3), "
            "Угличском (−1), Ярославском (+1), причина одна: сшивка нескольких "
            "каталожных номеров в одно дело. Подробности — КОНТРОЛЬ_ПО_УЕЗДАМ.md "
            "в папке распознавания"),
    }
    (out_dir / "HANDOFF_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"записей распознавания: {len(vision)}")
    print(f"дел с номером: {len(rows)} (из них сшитых из нескольких строк: {len(sewn)})")
    print(f"  привязано к карточке РГИА: {stat['привязано к делу']}, "
          f"нет дела в базе: {stat['дела нет в базе']}")
    print(f"  выбыло: {stat['выбыло']}, арифметика не сходится: "
          f"{stat['арифметика не сходится']}")
    print(f"записей без номера дела: {len(extra)}")
    print(f"дел оп. 37 в базе: {len(urls)}; останутся пустыми: "
          f"{len(set(urls) - set(groups))}")
    print(f"\nCSV:   {linked}")
    print(f"CSV:   {nolink}")
    print(f"Отчёт: {out_dir / 'HANDOFF_REPORT.json'}")


if __name__ == "__main__":
    main()
