# -*- coding: utf-8 -*-
"""ПрБ v7.1: свёртка прогона в уникальные карточки и гейт отбора.

Повод: прогон завершён штатно (`query_scope_completed`, exit 0), но `records_full.jsonl`
содержит 253 СТРОКИ при 36 уникальных карточках — одна карточка попадает в набор по каждому
запросу, где нашлась. Передавать такой файл в каталог нельзя: получатель заведёт дубли.

Гейт отсекает две группы, видимые в данных:
  — ловушки поиска по короткому топониму: «Оса» (уездный центр Пермской губернии) ловит
    «осада», «Осада полюса», «поход… осада и взятие»; «Ростов» ловит Ростов-на-Дону;
  — чужая территория и хронология: Тверская губерния по запросу «Ржев», советские издания
    1920-х (Уральская область, «Чердынский край» 1927).

Остальное делится по классу: картографический (карта/атлас/план/чертёж в заголовке) и
текстово-статистический («Списки населённых мест», «Материалы для географии и статистики»,
описания и обозрения губерний) — последний в каталог карт идёт только по решению человека.

Выход: output/prlib_catalog_full_20261004_v7_1/cards_final.csv + .jsonl + FINAL_REPORT.json
Исходный records_full.jsonl не изменяется.
"""
import csv
import io
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив"
           r"\output\prlib_catalog_full_20261004_v7_1")

# ловушки короткого топонима: слово-запрос совпало с другим словом
TRAP = re.compile(r"осад|оса́|\bосады\b|Ростов[а-я]*[- ]на[- ]Дону|Ростов на Дону", re.I)
# чужая территория в заголовке
FOREIGN = re.compile(r"Тверск|Владим|Псков|Казан|Сибир|Уральской област|Новгородск", re.I)
# наши губернии
OURS = re.compile(r"Калужск|Пермск|Смоленск|Ярославск|Ростовск\w*\s+уезд|Переславл", re.I)
# картографический класс
CARTO = re.compile(r"\bкарт|\bатлас|\bплан\b|чертеж|чертёж|съемк|съёмк", re.I)
# текстово-статистический класс
STAT = re.compile(r"списки населенных|материалы для географии|статистическ|"
                  r"топографическое описание|военно-статистическ|обозрени", re.I)
# хронология проекта: до 1917 г.
SOVIET = re.compile(r"\b19[2-9]\d\b")

COLS = ["source", "library", "url", "title", "author", "year_from", "year_to", "place",
        "scale", "territories", "queries", "hits", "klass", "verdict", "verdict_reason",
        "needs_human", "description"]


def classify(rec: dict, terrs: set[str], title: str) -> tuple[str, str, str, bool]:
    """(класс, вердикт, причина, нужно ли решение человека)."""
    year = str(rec.get("year_from") or "")
    if TRAP.search(title):
        return "—", "drop", "ловушка короткого топонима (оса/осада, Ростов-на-Дону)", False
    if FOREIGN.search(title) and not OURS.search(title):
        return "—", "drop", "чужая территория в заголовке", False
    if year and SOVIET.search(year):
        return "—", "drop", f"вне хронологии проекта ({year})", False
    if CARTO.search(title):
        return "картографический", "keep", "карта/атлас в заголовке", False
    if STAT.search(title):
        return "текстово-статистический", "review", \
               "текстовый источник, не карта — вносить по решению человека", True
    return "прочее", "review", "класс не определён по заголовку", True


def main() -> None:
    rows = [json.loads(x) for x in (OUT / "records_full.jsonl").open(encoding="utf-8") if x.strip()]
    cards: dict[str, dict] = {}
    terrs: dict[str, set] = defaultdict(set)
    queries: dict[str, set] = defaultdict(set)
    hits: Counter = Counter()
    for r in rows:
        rec = r.get("record") or {}
        url = rec.get("url")
        if not url:
            continue
        cards[url] = rec
        if r.get("territory"):
            terrs[url].add(r["territory"])
        if r.get("keyword"):
            queries[url].add(r["keyword"])
        hits[url] += 1

    out_rows = []
    for url, rec in sorted(cards.items(), key=lambda kv: (kv[1].get("title") or "")):
        title = rec.get("title") or ""
        klass, verdict, reason, nh = classify(rec, terrs[url], title)
        out_rows.append({
            "source": "prlib", "library": rec.get("library_name") or "Президентская библиотека",
            "url": url, "title": title, "author": rec.get("author") or "",
            "year_from": rec.get("year_from") or "", "year_to": rec.get("year_to") or "",
            "place": rec.get("place") or "", "scale": rec.get("scale") or "",
            "territories": "; ".join(sorted(x for x in terrs[url] if x)),
            "queries": "; ".join(sorted(queries[url])[:6]), "hits": hits[url],
            "klass": klass, "verdict": verdict, "verdict_reason": reason,
            "needs_human": "true" if nh else "false",
            "description": (rec.get("description") or "")[:500],
        })

    with (OUT / "cards_final.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(out_rows)
    (OUT / "cards_final.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows), encoding="utf-8")

    rep = {
        "source": "prlib", "run": "v7_1", "run_status": "query_scope_completed",
        "rows_in_records_full": len(rows), "unique_cards": len(cards),
        "by_verdict": dict(Counter(r["verdict"] for r in out_rows)),
        "by_klass": dict(Counter(r["klass"] for r in out_rows)),
        "keep_cartographic": [r["title"][:80] for r in out_rows
                              if r["verdict"] == "keep"],
        "needs_human": sum(1 for r in out_rows if r["needs_human"] == "true"),
        "with_scale": sum(1 for r in out_rows if r["scale"]),
        "ready_for_import": False,
    }
    (OUT / "FINAL_REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {OUT / 'cards_final.csv'}")


if __name__ == "__main__":
    main()
