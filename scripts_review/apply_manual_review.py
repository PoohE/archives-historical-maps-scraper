# -*- coding: utf-8 -*-
"""Применение решений ручной проверки 2026-10-04 к наборам НЭБ и Перми.

Решения приняты человеком по листу `output/manual_review_20261004/РУЧНАЯ_ПРОВЕРКА.html`
(61 запись). Хранятся здесь в коде, а не в отдельном файле-«свалке», чтобы решение всегда
читалось вместе с его обоснованием и чтобы перенос в пересобранный набор Перми (v9.6) был
воспроизводим: ключ переноса — URL записи, а не её номер в листе.

Что делает:
  — НЭБ: снимает `needs_human` у принятых, помечает отклонённые, вносит уточнения человека
    (масштаб и легенда у «Карты местности, населенной пермяками»; природа масштаба у
    «Карты Смоленской губернии»), отмечает пары дублей;
  — Пермь: сохраняет решения отдельным файлом с ключом по URL — пермский набор будет
    пересобран Codex (v9.6), и решения надо будет наложить на новый набор.

Вход : output/manual_review_20261004/review.csv, output/neb_final_20261003/records.jsonl
Выход: output/manual_review_20261004/ — decisions.csv, neb_records_reviewed.jsonl,
       perm_decisions_for_v9_6.csv, REPORT.json
"""
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
REVIEW = BASE / "output" / "manual_review_20261004"
NEB = BASE / "output" / "neb_final_20261003" / "records.jsonl"

# Решения человека, 2026-10-04. yes = берём, no = не берём.
DECISIONS = {
    1: "no", 2: "yes", 3: "yes", 4: "yes", 5: "yes", 6: "yes", 7: "yes", 8: "yes",
    9: "yes", 10: "yes", 11: "no", 12: "yes", 13: "no", 14: "no", 15: "yes", 16: "no",
    17: "no", 18: "no", 19: "no", 20: "no", 21: "no", 22: "no", 23: "yes", 24: "yes",
    25: "no", 26: "no", 27: "no", 28: "no", 29: "yes", 30: "yes", 31: "no", 32: "no",
    33: "yes", 34: "no", 35: "yes", 36: "no", 37: "yes", 38: "yes", 39: "no", 40: "no",
    41: "yes", 42: "no", 43: "yes", 44: "yes", 45: "yes", 46: "yes", 47: "yes", 48: "yes",
    49: "yes", 50: "yes", 51: "yes", 52: "yes", 53: "yes", 54: "yes", 55: "no", 56: "yes",
    57: "yes", 58: "yes", 59: "yes", 60: "no", 61: "no",
}

# Пары записей, которые человек опознал как один и тот же документ (разные catalog_id НЭБ).
DUPLICATES = [(3, 4), (5, 6)]

# Данные, снятые человеком с самого изображения карты (в описании источника их нет).
FROM_IMAGE = {
    7: {"scale_raw": "1:168000", "scale_min_denom": 168000,
        "legend": "дороги; завод; рудник; мельница; село; деревня; починок",
        "note": "масштаб и легенда сняты человеком с изображения карты 2026-10-04"},
    9: {"note": "указанный масштаб относится к ВРЕЗКЕ, а не к основной карте "
                "(установлено человеком по изображению 2026-10-04); масштаб основной карты не определён"},
}


def main() -> None:
    rows = list(csv.DictReader((REVIEW / "review.csv").open(encoding="utf-8-sig")))
    by_n = {int(r["n"]): r for r in rows}
    missing = [n for n in DECISIONS if n not in by_n]
    if missing:
        print("нет таких номеров в листе:", missing)

    # --- общий журнал решений
    dec_rows = []
    for n, r in sorted(by_n.items()):
        v = DECISIONS.get(n, "")
        dup = next((f"дубль с {b if a == n else a}" for a, b in DUPLICATES if n in (a, b)), "")
        extra = FROM_IMAGE.get(n, {})
        dec_rows.append({
            "n": n, "decision": v, "source": r["source"], "territory": r["territory"],
            "title": r["title"], "url": r["url"], "question": r["question"],
            "duplicate": dup,
            "from_image": "; ".join(f"{k}={val}" for k, val in extra.items() if k != "note"),
            "human_note": extra.get("note", ""),
        })
    with (REVIEW / "decisions.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(dec_rows[0].keys()))
        w.writeheader()
        w.writerows(dec_rows)

    # --- НЭБ: применяем к записям
    url_dec = {r["url"]: (DECISIONS.get(int(r["n"]), ""), int(r["n"]))
               for r in rows if r["source"].startswith("НЭБ") and r["url"]}
    neb = [json.loads(x) for x in NEB.read_text(encoding="utf-8").splitlines() if x.strip()]
    applied = Counter()
    for rec in neb:
        u = rec.get("url", "")
        if u not in url_dec:
            continue
        v, n = url_dec[u]
        rec["human_verdict"] = v
        rec["human_reviewed"] = "2026-10-04"
        if v == "yes":
            rec["needs_human"] = "false"
            rec["needs_human_reason"] = ""
            applied["принято"] += 1
        elif v == "no":
            rec["needs_human"] = "false"
            rec["scope_drop_reason"] = "human_rejected"
            applied["отклонено"] += 1
        for a, b in DUPLICATES:
            if n in (a, b):
                other = by_n[b if a == n else a]
                rec["duplicate_of_url"] = other["url"]
                applied["дубль"] += 1
        if n in FROM_IMAGE:
            for k, val in FROM_IMAGE[n].items():
                if k == "note":
                    rec["human_note"] = val
                else:
                    rec[k] = val
            applied["уточнено с изображения"] += 1

    out = REVIEW / "neb_records_reviewed.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in neb), encoding="utf-8")

    # --- Пермь: решения на перенос в v9.6 (ключ — URL, номера листа после пересборки не совпадут)
    perm = [d for d in dec_rows if d["source"].startswith("Пермь")]
    with (REVIEW / "perm_decisions_for_v9_6.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["url", "decision", "territory", "title", "question"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(perm)

    rep = {
        "reviewed_at": "2026-10-04", "items_total": len(rows),
        "decisions": dict(Counter(DECISIONS.values())),
        "by_source": {
            s: dict(Counter(DECISIONS.get(int(r["n"]), "") for r in rows if r["source"] == s))
            for s in sorted({r["source"] for r in rows})
        },
        "neb_applied": dict(applied),
        "neb_records_total": len(neb),
        "neb_needs_human_left": sum(1 for r in neb if str(r.get("needs_human")).lower() == "true"),
        "duplicates": [{"pair": list(p), "urls": [by_n[p[0]]["url"], by_n[p[1]]["url"]]}
                       for p in DUPLICATES],
        "perm_decisions_pending_v9_6": len(perm),
    }
    (REVIEW / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {REVIEW}")


if __name__ == "__main__":
    main()
