# -*- coding: utf-8 -*-
"""НЭБ: слияние выдачи (227 записей) с разобранными карточками — итоговый набор для каталога.

Выдача даёт территорию, заголовок, библиотеку, доступ и URL; у части записей — год.
Карточка добирает то, чего в выдаче нет: датировку (в т.ч. десятилетие «[189-]» и
словесный век), масштаб (числовой и верстовой), ББК с кодами территорий и
«Примечание содержания» — поштучный перечень листов атласа с их масштабами.

Правило приоритета: год из карточки ВЫТЕСНЯЕТ год выдачи только когда в выдаче его нет.
Если год есть в обеих и они расходятся — запись помечается needs_human с указанием обоих.

Вход : output/neb_manual_20261003/records.csv, output/neb_cards_20261003/cards.jsonl
Выход: output/neb_final_20261003/ — records.csv, records.jsonl, REPORT.json
"""
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
SEARCH = BASE / "output" / "neb_manual_20261003" / "records.csv"
CARDS = BASE / "output" / "neb_cards_20261003" / "cards.jsonl"
OUT = BASE / "output" / "neb_final_20261003"

COLS = [
    "source", "territory", "territory_count", "catalog_id", "title", "part_of",
    "authors", "place", "publisher", "imprint",
    "year_from", "year_to", "year_source", "year_precision",
    "scale_raw", "scale_min_denom", "scale_count",
    "bbk", "udk", "volume", "contents_note", "sheets_in_note", "subjects",
    "source_library", "access", "url", "level", "card_seen",
    "needs_human", "needs_human_reason", "evidence", "query", "page_file",
]


def precision(y1: str, y2: str, src: str) -> str:
    """Насколько точна датировка — это решает, можно ли привязывать и заказывать."""
    if not y1:
        return "none"
    if src.endswith("_exact"):
        return "year"
    if src.endswith("_decade"):
        return "decade"
    if src.endswith("_century"):
        return "century"
    if src.endswith("_roman"):
        span = int(y2 or y1) - int(y1)
        return "half_century" if span <= 60 else "century"
    return "unknown"


def key(s: str) -> str:
    """Ключ сопоставления «лист ↔ конволют»: part_of приходит в кавычках."""
    return re.sub(r"[^а-яёa-z0-9]+", " ", (s or "").lower()).strip()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    search = list(csv.DictReader(SEARCH.open(encoding="utf-8-sig")))
    cards = {}
    for line in CARDS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            cards[c["catalog_id"]] = c

    # конволюты (атласы) по названию — источник датировки для листов без своего года:
    # лист несёт поле «Входит в» (part_of), карточка конволюта несёт год издания
    parents = {}
    for c in cards.values():
        if c.get("year_from") and c.get("title"):
            parents.setdefault(key(c["title"]), c)

    rows = []
    stat = Counter()
    for s in search:
        r = {k: s.get(k, "") for k in COLS if k in s}
        r["source"] = "neb"
        cid = s.get("catalog_id", "")
        c = cards.get(cid)
        r["card_seen"] = "true" if c else "false"
        reasons = []

        if c:
            stat["merged"] += 1
            # поля, которых в выдаче нет вообще
            for k in ("authors", "bbk", "udk", "volume", "contents_note",
                      "sheets_in_note", "subjects", "scale_raw",
                      "scale_min_denom", "scale_count"):
                r[k] = c.get(k, "")
            if not r.get("place"):
                r["place"] = c.get("place", "")
            if not r.get("publisher"):
                r["publisher"] = c.get("publisher", "")
            # датировка
            sy1, cy1 = (s.get("year_from") or ""), (c.get("year_from") or "")
            if not sy1 and cy1:
                r["year_from"], r["year_to"] = cy1, c.get("year_to", "")
                r["year_source"] = "card_" + c.get("year_source", "")
                stat["year_from_card"] += 1
            elif sy1 and cy1 and sy1 != cy1:
                # не выбираем молча: расхождение решает человек
                r["year_from"], r["year_to"] = sy1, s.get("year_to", "")
                r["year_source"] = "search_exact"
                reasons.append(f"year_conflict:выдача={sy1},карточка={cy1}")
                stat["year_conflict"] += 1
            elif sy1:
                r["year_source"] = r.get("year_source") or "search_exact"
        else:
            stat["no_card"] += 1
            for k in ("authors", "bbk", "udk", "volume", "contents_note",
                      "sheets_in_note", "subjects", "scale_raw",
                      "scale_min_denom", "scale_count"):
                r.setdefault(k, "")
            if s.get("year_from"):
                r["year_source"] = "search_exact"

        # протяжка от конволюта: лист атласа датируется атласом, в который входит.
        # Это НЕ «год от похожего заголовка» — связь берётся из поля «Входит в» самой
        # записи, а год — из карточки родителя (у НЭБ бывают близнецы-листы разных
        # изданий с одним названием и разными годами, их смешивать нельзя).
        if not r.get("year_from") and r.get("part_of"):
            p = parents.get(key(r["part_of"]))
            if p:
                r["year_from"], r["year_to"] = p["year_from"], p.get("year_to", "")
                r["year_source"] = "parent_card_" + p.get("year_source", "")
                reasons.append(f"year_inherited_from:{p['catalog_id']}")
                stat["year_from_parent"] += 1

        r["year_precision"] = precision(r.get("year_from", ""), r.get("year_to", ""),
                                        r.get("year_source", ""))
        # needs_human — только то, что требует РЕШЕНИЯ человека. Отсутствие масштаба
        # решения не требует: источник его не публикует (у 207 из 227 нет и изображения,
        # см. поле access) — это пустое поле, а не спорная запись.
        if not r.get("year_from"):
            reasons.append("no_year")
        if not r.get("territory"):
            reasons.append("territory_unknown")
        if s.get("needs_human") == "true":
            reasons.append("gate_" + (s.get("evidence") or "unknown"))

        r["needs_human"] = "true" if reasons else "false"
        r["needs_human_reason"] = "; ".join(reasons)
        rows.append({k: r.get(k, "") for k in COLS})

    rows.sort(key=lambda x: (x["territory"], x["title"]))
    with (OUT / "records.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (OUT / "records.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")

    rep = {
        "source": "neb", "mode": "search_listing + manual_cards",
        "records": len(rows), "cards_available": len(cards),
        "merge": dict(stat),
        "with_year": sum(1 for r in rows if r["year_from"]),
        "year_precision": dict(Counter(r["year_precision"] for r in rows)),
        "with_scale": sum(1 for r in rows if r["scale_raw"]),
        "with_bbk": sum(1 for r in rows if r["bbk"]),
        "by_territory": dict(Counter(
            t for r in rows for t in (r["territory"].split("; ") if r["territory"]
                                      else ["не определена"]))),
        "needs_human": sum(1 for r in rows if r["needs_human"] == "true"),
        "no_scale_in_source": sum(1 for r in rows if not r["scale_raw"]),
        "needs_human_reasons": dict(Counter(
            x.split(":")[0] for r in rows for x in r["needs_human_reason"].split("; ") if x)),
        "access": dict(Counter(r["access"] for r in rows)),
        "ready_for_import": True,
        "columns": len(COLS),
    }
    (OUT / "REPORT.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    for k, v in rep.items():
        print(f"{k}: {v}")
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
