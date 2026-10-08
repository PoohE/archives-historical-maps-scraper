"""Сверка всех прогонов проекта: что собрано, что завершено, что брошено.

Проходит по всем папкам output/, у которых есть признаки прогона (records*, state,
REPORT), и для каждой печатает: источник, число записей, статус состояния, когда
последняя запись, есть ли конфликтные копии Я.Диска и stale-локи.

Запуск из корня проекта:
    python -B scripts_review/audit_all_runs.py [--min-records 1] [--out output/AUDIT_ALL_RUNS_<дата>.md]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
NOW = time.time()

REC_FILES = ("records.jsonl", "records_full.jsonl", "records.csv")
STATE_FILES = ("state.json", "permkrai_rubric_state.json", "prlib_state.json")
REPORT_FILES = ("REPORT.json", "LATEST_REPORT.json", "REASSESSMENT.json", "COVERAGE.json")


def count_lines(p: Path) -> int:
    try:
        with p.open(encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return -1


def age_h(p: Path) -> float:
    try:
        return (NOW - p.stat().st_mtime) / 3600
    except OSError:
        return -1


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def state_summary(d: Path) -> str:
    """Статус прогона из любого найденного файла состояния."""
    for name in STATE_FILES:
        p = d / name
        if not p.exists():
            continue
        j = read_json(p)
        if not isinstance(j, dict):
            continue
        # форма 1: coverage-блок (Пермь, ПрБ)
        cov = j.get("coverage")
        if isinstance(cov, dict):
            parts = [f"status={cov.get('status')}"]
            for k in ("completed_cards", "card_candidates", "pending_listing_urls"):
                v = cov.get(k)
                if isinstance(v, list):
                    parts.append(f"{k}={len(v)}")
            if cov.get("stop_reason"):
                parts.append(f"stop={cov['stop_reason']}")
            return " ".join(parts)
        # форма 2: словарь единиц обхода (УИАД, ГАПК)
        units = [v for v in j.values() if isinstance(v, dict) and "status" in v]
        if units:
            done = sum(1 for v in units if v.get("status") == "complete")
            return f"единиц {done}/{len(units)} complete"
        # форма 3: pending/completed списками (ПрБ)
        if "pending" in j or "completed" in j:
            pen = j.get("pending") or []
            com = j.get("completed") or []
            return f"pending={len(pen)} completed={len(com)}"
        return f"ключи: {', '.join(list(j)[:4])}"
    # состояния описей отдельными файлами (ф.380)
    sub = d / "fund380_opis_state"
    if sub.is_dir():
        files = [f for f in sub.iterdir() if re.fullmatch(r"\d+\.json", f.name)]
        from collections import Counter
        c = Counter()
        for f in files:
            j = read_json(f)
            if isinstance(j, dict):
                c[j.get("status")] += 1
        return "описи: " + ", ".join(f"{k}={v}" for k, v in c.most_common())
    return "—"


def report_summary(d: Path) -> str:
    for name in REPORT_FILES:
        p = d / name
        if not p.exists():
            continue
        j = read_json(p)
        if not isinstance(j, dict):
            continue
        keys = ("exit_code", "stop_reason", "status", "csv_rows", "input_total",
                "records", "ready_for_import")
        got = [f"{k}={j[k]}" for k in keys if k in j]
        return f"{name}: " + (" ".join(got) if got else ", ".join(list(j)[:4]))
    return "—"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-records", type=int, default=1)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = []
    for d in sorted(OUT.iterdir()):
        if not d.is_dir():
            continue
        recs = {n: count_lines(d / n) for n in REC_FILES if (d / n).exists()}
        has_state = any((d / n).exists() for n in STATE_FILES) or (d / "fund380_opis_state").is_dir()
        has_report = any((d / n).exists() for n in REPORT_FILES)
        if not recs and not has_state and not has_report:
            continue
        n = max(recs.values()) if recs else 0
        if recs and max(recs.values()) < args.min_records and not has_state:
            continue
        # свежесть = самый НЕДАВНО изменённый файл набора (не самый старый)
        newest = min((age_h(d / k) for k in recs), default=-1)
        conflicts = sum(1 for _ in d.rglob("*копия с компьютера*"))
        locks = [p.name for p in d.glob("*.lock")]
        rows.append({
            "dir": d.name,
            "records": n,
            "files": ",".join(recs),
            "age_h": newest,
            "state": state_summary(d),
            "report": report_summary(d),
            "conflicts": conflicts,
            "locks": locks,
        })

    rows.sort(key=lambda r: (-r["records"], r["dir"]))

    lines = [f"# Сверка всех прогонов — {time.strftime('%Y-%m-%d %H:%M')}", ""]
    lines.append(f"Папок с признаками прогона: **{len(rows)}**. "
                 f"Суммарно записей в крупнейших наборах: "
                 f"**{sum(r['records'] for r in rows if r['records'] >= 100):,}**".replace(",", " "))
    lines.append("")
    probl = [r for r in rows if r["conflicts"] or r["locks"]]
    if probl:
        lines += ["## Требует внимания", ""]
        for r in probl:
            bits = []
            if r["conflicts"]:
                bits.append(f"конфликтных копий Я.Диска: {r['conflicts']}")
            if r["locks"]:
                bits.append(f"локи: {', '.join(r['locks'])}")
            lines.append(f"- `{r['dir']}` — {'; '.join(bits)}")
        lines.append("")
    lines += ["## Все наборы (по убыванию числа записей)", ""]
    lines.append("| Папка | Записей | Свежесть | Состояние | Отчёт |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        age = "—" if r["age_h"] < 0 else (f"{r['age_h']:.1f} ч" if r["age_h"] < 48 else f"{r['age_h'] / 24:.0f} дн")
        lines.append(f"| `{r['dir']}` | {r['records']} | {age} | {r['state'][:70]} | {r['report'][:70]} |")

    text = "\n".join(lines) + "\n"
    out = Path(args.out) if args.out else OUT / f"AUDIT_ALL_RUNS_{time.strftime('%Y%m%d')}.md"
    out.write_text(text, encoding="utf-8")
    print(f"папок с прогонами: {len(rows)}")
    print(f"с конфликтными копиями или локами: {len(probl)}")
    print(f"отчёт: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
