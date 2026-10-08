"""Объединение двух веток обхода Пермской краевой библиотеки.

Зачем: сверка 08.10.2026 показала, что ветки НЕ пересекаются (пересечение URL = НОЛЬ).
  - v8.1 — обход рубрики /node/722, 25 записей, через гейт отбора НЕ проходили;
  - v9.x — обход по node_list, 71 запись → после трёх офлайн-переоценок с 51 решением
    пользователя осталось 27 keep.
Передать в каталог «27 из v9.7» = молча потерять 25 записей рубрики.

Что делает скрипт: прогоняет 25 записей v8.1 через ТОТ ЖЕ гейт (scope_gate из пакета v9.4,
правила ПРАВИЛА_ОТБОРА_источников.md), учитывает решения пользователя там, где URL совпал,
и собирает объединённый набор. Сеть не используется, исходные наборы не меняются.

Запуск из корня проекта:
    python -B scripts_review/permkrai_merge_branches.py
    python -B scripts_review/permkrai_merge_branches.py --output output/permkrai_merged_<дата>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

PKG = OUT / "permkrai_catalog_maps_handoff_20261002_v9_4"
RULES = PKG / "rules" / "ПРАВИЛА_ОТБОРА_источников.md"
BR_RUBRIC = OUT / "permkrai_catalog_maps_20260929_v8_1"          # 25, рубрика
BR_NODELIST = OUT / "permkrai_catalog_maps_20261004_v9_7_release_offline"  # 27 keep
DECISIONS = OUT / "manual_review_20261004" / "perm_decisions_for_v9_6.csv"

sys.path.insert(0, str(PKG / "frozen" / "scripts" / "modules"))
import scope_gate  # noqa: E402


def norm(u: str) -> str:
    return (u or "").strip().rstrip("/")


def read_jsonl(p: Path) -> list[dict]:
    with p.open(encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def url_of(row: dict) -> str:
    rec = row.get("record") or row
    return norm(rec.get("url") or rec.get("source_url") or row.get("url") or "")


def load_decisions() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not DECISIONS.exists():
        return out
    with DECISIONS.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            u = norm(r.get("url", ""))
            if u:
                out[u] = r
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="")
    ap.add_argument("--year-max", type=int, default=1980,
                    help="верхняя граница года издания; позже — отсев как современное "
                         "(решение пользователя 08.10.2026: оставить до 1980)")
    args = ap.parse_args()
    out_dir = Path(args.output) if args.output else OUT / f"permkrai_merged_{time.strftime('%Y%m%d')}"

    policy = scope_gate.load_policy(RULES)
    print(f"правила: {RULES.name}, sha256 {policy.rules_sha256[:16]}…")

    rubric = read_jsonl(BR_RUBRIC / "records_full.jsonl")
    nodelist = read_jsonl(BR_NODELIST / "records_full.jsonl")
    decisions = load_decisions()
    print(f"ветка рубрики (v8.1): {len(rubric)} записей")
    print(f"ветка node_list (v9.7, keep): {len(nodelist)} записей")
    print(f"решений пользователя в файле: {len(decisions)}")

    u_rub = {url_of(r) for r in rubric}
    u_nod = {url_of(r) for r in nodelist}
    overlap = u_rub & u_nod
    print(f"пересечение URL: {len(overlap)}")

    kept, dropped, human_used = [], [], 0
    for row in rubric:
        u = url_of(row)
        rec = row.get("record") or {}
        v = scope_gate.check(rec, source="permkrai", amendments=policy)
        d = decisions.get(u)
        verdict = v.asdict()
        verdict["gate_keep"] = v.keep
        if d:
            human_used += 1
            dec = (d.get("decision") or "").strip().lower()
            if dec in ("yes", "no"):
                verdict["human_verdict"] = dec
                verdict["human_reviewed"] = True
                verdict["keep"] = dec == "yes"
                verdict["needs_human"] = False
                verdict["human_decision_source"] = DECISIONS.name
        # Хронологический отсев: современные карты в историческую ГИС не идут.
        # Год неизвестен -> НЕ отсекаем, помечаем на просмотр человеком.
        yf = rec.get("year_from") or rec.get("publication_year_from")
        if verdict.get("keep", v.keep) and isinstance(yf, int) and yf > args.year_max:
            verdict["keep"] = False
            verdict["reason"] = "modern_edition"
            verdict["evidence"] = f"year_{yf}_after_{args.year_max}"
            verdict["needs_human"] = False
        elif verdict.get("keep", v.keep) and not yf:
            verdict["needs_human"] = True
            verdict["evidence"] = (verdict.get("evidence") or "") + "+year_unknown"

        out_row = dict(row)
        out_row["branch"] = "rubric_v8_1"
        out_row["scope_verdict"] = verdict
        out_row["needs_human"] = verdict.get("needs_human", v.needs_human)
        out_row["needs_human_reason"] = verdict.get("evidence", v.evidence)
        (kept if verdict.get("keep", v.keep) else dropped).append(out_row)

    print(f"\nветка рубрики через гейт: keep {len(kept)}, отсев {len(dropped)}")
    print(f"из них решений пользователя применено: {human_used}")
    if len(kept) + len(dropped) != len(rubric):
        print("ОШИБКА СОХРАНЕНИЯ: сумма не равна входу")
        return 2

    from collections import Counter
    print("\nпричины по ветке рубрики:")
    for k, n in Counter(r["scope_verdict"].get("evidence") for r in kept + dropped).most_common():
        print(f"  {k}: {n}")

    merged = [dict(r, branch="node_list_v9_7") for r in nodelist] + kept
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "records_full.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in merged) + "\n", encoding="utf-8")
    (out_dir / "rubric_scope_drops.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in dropped) + "\n", encoding="utf-8")

    report = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "purpose": "объединение двух непересекающихся веток обхода Пермской краевой библиотеки",
        "network": "not_run",
        "rules_sha256": policy.rules_sha256,
        "year_max": args.year_max,
        "branch_rubric_v8_1": {"input": len(rubric), "keep": len(kept), "scope_drop": len(dropped),
                               "human_decisions_applied": human_used},
        "branch_node_list_v9_7": {"keep": len(nodelist)},
        "url_overlap_between_branches": len(overlap),
        "merged_total": len(merged),
        "conservation_delta": len(rubric) - (len(kept) + len(dropped)),
        "needs_human_in_merged": sum(1 for r in merged if r.get("needs_human")),
        "sources": {"rubric": str(BR_RUBRIC), "node_list": str(BR_NODELIST),
                    "decisions": str(DECISIONS) if DECISIONS.exists() else None},
        "ready_for_import": False,
        "note": "Исходные наборы не изменялись. Схема CSV каталога здесь не собирается — "
                "это зона сессии каталогизации.",
    }
    (out_dir / "MERGE_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nОБЪЕДИНЁННЫЙ НАБОР: {len(merged)} записей "
          f"({len(nodelist)} node_list + {len(kept)} рубрика)")
    print(f"из них needs_human: {report['needs_human_in_merged']}")
    print(f"выход: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
