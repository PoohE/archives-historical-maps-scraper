"""
Собрать страницы-кандидаты для Notion «Каталог» из корзин review_run — с БОГАТЫМ маппингом.

Прогоняет отобранные записи (accepted + review) через notion_export.py (маппинг по инструкции
экспорта: автор из extra.raw_author_field, «Место хранения»=ГПИБ, «Организация оцифровки»,
«Листы/страницы», шифр, язык, том…), затем добавляет статусный слой приёмки и типизирует
значения под notion-create-pages.

Запуск:  python scripts/make_notion_pages.py output/<run>/review_run --date 2026-09-22
Выход:   <review_run>/notion_pages.json  (+ копии notion_import.csv / export_review.json).
Далее страницы создаёт сессия через MCP notion-create-pages (parent = data source «Каталог»).
"""
import argparse
import csv
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "modules"))
import notion_export as ne  # noqa: E402

PROPS = ne.PROPERTIES
VALID_REASONS = {"сомнительный тип", "нет маркера карты", "регион неясен", "год не указан"}
DATE_START = "date:Дата внесения:start"
# Полный текст этих колонок остаётся в notion_import.csv/records_full — в Notion не льём
# (дублирует «Описание», раздувает заливку; приёмщик берёт из карточки по ссылке).
SKIP_UPLOAD = {"Библиографическое описание"}


def load_reasons(review_csv: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if review_csv.exists():
        for r in csv.DictReader(io.open(review_csv, encoding="utf-8-sig")):
            url = (r.get("URL") or "").strip()
            reasons = [p.strip() for p in (r.get("Причина") or "").split(",")
                       if p.strip() in VALID_REASONS]
            if url:
                out[url] = reasons
    return out


def read_lines(p: Path) -> list[str]:
    return [ln for ln in io.open(p, encoding="utf-8-sig") if ln.strip()] if p.exists() else []


def typed(col: str, val: str):
    """Типизация значения CSV под Notion-props по схеме (число/строка); прочее — пропуск."""
    v = (val or "").strip()
    if not v:
        return None
    t = PROPS.get(col, {}).get("type")
    if t == "number":
        try:
            return int(v) if v.lstrip("-").isdigit() else float(v)
        except ValueError:
            return None
    if t == "title":
        return " ".join(v.split())
    if t == "text":
        # схлопнуть переносы + обрезать превью (полный текст — в notion_import.csv/records_full)
        return " ".join(v.split())[:300]
    if t in ("select", "url"):
        return v
    return None  # date / relation / formula / multi_select — не из CSV


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("review_run", type=Path, help="папка review_run")
    ap.add_argument("--date", required=True, help="дата внесения ISO, напр. 2026-09-22")
    a = ap.parse_args()
    d = a.review_run

    reasons = load_reasons(d / "review.csv")
    review_urls = {json.loads(x)["record"].get("url", "") for x in read_lines(d / "review_records.jsonl")}
    combined = read_lines(d / "accepted_records.jsonl") + read_lines(d / "review_records.jsonl")
    if not combined:
        print("Нет записей в корзинах accepted/review")
        return

    tmp = Path(tempfile.mkdtemp(prefix="mnp_"))
    try:
        in_jsonl = tmp / "in.jsonl"
        in_jsonl.write_text("".join(x if x.endswith("\n") else x + "\n" for x in combined),
                            encoding="utf-8")
        out_dir = tmp / "out"
        ne.export(in_jsonl, out_dir)  # богатый маппинг → notion_import.csv
        csv_path = out_dir / "notion_import.csv"
        rows = list(csv.DictReader(io.open(csv_path, encoding="utf-8-sig")))

        pages = []
        for r in rows:
            props = {c: typed(c, v) for c, v in r.items()
                     if c not in SKIP_UPLOAD and typed(c, v) is not None}
            props["Статус приёмки"] = "кандидат"
            props["Автор внесения"] = "Агент"
            props[DATE_START] = a.date
            url = (r.get("Ссылка на онлайн-архив") or "").strip()
            rs = reasons.get(url, []) if url in review_urls else []
            if rs:
                props["Причина сомнительности"] = rs
            pages.append({"properties": props})

        (d / "notion_pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
        shutil.copy(csv_path, d / "notion_import.csv")
        shutil.copy(out_dir / "export_review.json", d / "export_review.json")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    hdr = list(rows[0]) if rows else []
    filled = [c for c in hdr if any((x.get(c) or "").strip() for x in rows)]
    with_reason = sum(1 for p in pages if p["properties"].get("Причина сомнительности"))
    print(f"страниц: {len(pages)}  (с причиной {with_reason} / авто {len(pages) - with_reason})")
    print(f"заполняемость колонок notion_import.csv: {len(filled)}/{len(hdr)}")
    print(f"→ {d / 'notion_pages.json'}")


if __name__ == "__main__":
    main()
