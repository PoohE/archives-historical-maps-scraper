"""
Собрать страницы-кандидаты для заливки в Notion «Каталог» из корзин review_run.

Берёт accepted_records.jsonl (авто-оставить) + review_records.jsonl (на проверку),
подтягивает причины из review.csv (по URL) и формирует notion_pages.json — список
объектов {"properties": {...}} в формате notion-create-pages (плоская карта).

Все записи получают Статус приёмки=кандидат, Автор внесения=Агент, Дата внесения=<--date>.
Причина сомнительности проставляется записям из корзины «на проверку».

Запуск:
  python scripts/make_notion_pages.py output/<run>/review_run --date 2026-09-22

Выход: <review_run>/notion_pages.json  (+ печать сводки).
Далее страницы создаёт сессия через MCP notion-create-pages (parent = data source «Каталог»).
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

VALID_REASONS = {"сомнительный тип", "нет маркера карты", "регион неясен", "год не указан"}


def load_reasons(review_csv: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not review_csv.exists():
        return out
    for r in csv.DictReader(io.open(review_csv, encoding="utf-8-sig")):
        url = (r.get("URL") or "").strip()
        raw = (r.get("Причина") or "").strip()
        reasons = [p.strip() for p in raw.split(",") if p.strip() in VALID_REASONS]
        if url:
            out[url] = reasons
    return out


def rec_props(entry: dict, date: str, reasons: list[str] | None) -> dict:
    rec = entry.get("record", {})
    props: dict = {
        "Название источника": (rec.get("title") or "")[:2000],
        "Автор внесения": "Агент",
        "date:Дата внесения:start": date,
        "Статус приёмки": "кандидат",
    }
    url = (rec.get("url") or "").strip()
    if url:
        props["Ссылка на онлайн-архив"] = url
    if isinstance(rec.get("year_from"), int):
        props["Год создания (нижняя)"] = rec["year_from"]
    if isinstance(rec.get("year_to"), int):
        props["Год создания (верхняя)"] = rec["year_to"]
    # Описание в заливку не тащим: приёмщик открывает «Ссылка на онлайн-архив».
    # (полное описание есть в records_full.jsonl / notion_export для обогащения принятых)
    if reasons:
        props["Причина сомнительности"] = reasons
    return props


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(ln) for ln in io.open(p, encoding="utf-8-sig") if ln.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("review_run", type=Path, help="папка review_run")
    ap.add_argument("--date", required=True, help="дата внесения ISO, напр. 2026-09-22")
    args = ap.parse_args()

    d = args.review_run
    reasons = load_reasons(d / "review.csv")

    pages = []
    for e in read_jsonl(d / "accepted_records.jsonl"):      # авто-оставить — без причины
        pages.append({"properties": rec_props(e, args.date, None)})
    for e in read_jsonl(d / "review_records.jsonl"):         # на проверку — с причиной
        url = (e.get("record", {}).get("url") or "").strip()
        pages.append({"properties": rec_props(e, args.date, reasons.get(url, []))})

    out = d / "notion_pages.json"
    out.write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    size = out.stat().st_size
    print(f"страниц собрано: {len(pages)}  → {out}  ({size} байт)")
    with_reason = sum(1 for p in pages if p["properties"].get("Причина сомнительности"))
    print(f"  с причиной сомнительности: {with_reason}  |  без причины (авто): {len(pages) - with_reason}")


if __name__ == "__main__":
    main()
