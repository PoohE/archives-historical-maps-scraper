"""
Мост: богатый notion_import.csv → Notion «Каталог» с дедупом (вариант а2, канон п.5).

Санкционированный писатель на REST-токене (НЕ MCP): берёт обогащённый notion_import.csv
(маппинг notion_export/prlib_card, п.1), проставляет статусный слой приёмки и пишет в базу
«Каталог» с дедупом по «Ссылка на онлайн-архив» (prlib без фонд/опись, поэтому ключ — URL
карточки). Токен NOTION_TOKEN из Каталогизация/.env (как в notion_archive_pages.py).

Режимы:
  по умолчанию — только создание; URL уже в базе → пропуск (дедуп);
  --update     — URL уже в базе → ОБНОВИТЬ запись новыми данными (перезалив v1.6):
                 * пишутся только НЕПУСТЫЕ значения (пустым существующее не затирается);
                 * защищённый список полей НЕ обновляется (канон: «Автор внесения»,
                   слой приёмки «Статус приёмки»/«Дата внесения», статусы нашей работы —
                   геопривязка/векторизация/OCR/привязка);
                 * «Причина сомнительности» обновляется только у записей со статусом «кандидат»;
                 * relation «Архив хранения» резолвится по Аббревиатуре/Названию справочника
                   «Архивы» (из export_review.json: relations c source_label), «Тип источника» —
                   по target_url; нерезолвленное — пропуск с пометкой в отчёте.

Запуск:
  python scripts/notion_upload_candidates.py output/<run>/review_run --date 2026-09-22 --dry-run
  python scripts/notion_upload_candidates.py output/<run>/review_run --date 2026-09-22
  python scripts/notion_upload_candidates.py output/<run>/review_run --date 2026-09-23 --update [--dry-run]
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "modules"))
import notion_export as ne  # noqa: E402  (PROPERTIES — типы колонок схемы)
import territory_resolve as tr  # noqa: E402  (авто-простановка территории/региона)

PROPS = ne.PROPERTIES
DB_ID = "5ead971c-b9bd-4bc2-90d8-73d0841b1f93"
ARCHIVES_DB_ID = "a9e98744-faf8-493f-93e5-cb14c0374fd8"  # справочник «Архивы»
TERR_DB_ID = "3920ba89-eabe-81a2-86a2-d50d1bfee1c0"  # справочник «Территории» (уезды/города)
REG_DB_ID = "6c6a3cfb-8d87-491e-8ce6-da7194bc857b"   # справочник «Современные регионы»
ENV = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
URL_COL = "Ссылка на онлайн-архив"
VALID_REASONS = {"сомнительный тип", "нет маркера карты", "регион неясен", "год не указан"}
# Канон (защищённый список импортёра): при ОБНОВЛЕНИИ существующей записи не трогаем.
PROTECTED_ON_UPDATE = {
    "Автор внесения", "Дата внесения", "Статус приёмки",
    "Геопривязка: статус", "Геопривязка: метод", "Геопривязка: RMSE (м)",
    "Тип привязки", "Векторизация", "OCR (распознавание текста)",
    "Число GCP", "Год оцифровки", "Система координат",
    "Возможность векторизации", "RMSE оцифровки (м)",
}


def load_token() -> str:
    t = os.environ.get("NOTION_TOKEN", "")
    if t:
        return t
    if ENV.exists():
        for ln in ENV.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("NOTION_TOKEN"):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


TOKEN = load_token()
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
           "Content-Type": "application/json"}


def api(method: str, url: str, data: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e


def chunks(s: str, n: int = 2000) -> list[dict]:
    return [{"text": {"content": s[i:i + n]}} for i in range(0, len(s), n)]


def to_prop(col: str, val: str):
    """CSV-значение → свойство Notion REST по типу колонки схемы."""
    v = (val or "").strip()
    if not v:
        return None
    t = PROPS.get(col, {}).get("type")
    if t == "title":
        return {"title": chunks(v)}
    if t == "text":
        return {"rich_text": chunks(v)}
    if t == "number":
        try:
            return {"number": int(v) if v.lstrip("-").isdigit() else float(v)}
        except ValueError:
            return None
    if t == "url":
        return {"url": v}
    if t == "select":
        return {"select": {"name": v}}
    return None  # relation / date / multi_select / formula / rollup — отдельно/пропуск


def load_reasons(review_csv: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if review_csv.exists():
        for r in csv.DictReader(io.open(review_csv, encoding="utf-8-sig")):
            url = (r.get("URL") or "").strip()
            rs = [p.strip() for p in (r.get("Причина") or "").split(",") if p.strip() in VALID_REASONS]
            if url:
                out[url] = rs
    return out


def load_relations(review_json: Path) -> dict[str, list[dict]]:
    """export_review.json → url -> relations (Архив хранения по label, Тип источника по target_url)."""
    out: dict[str, list[dict]] = {}
    if review_json.exists():
        data = json.loads(review_json.read_text(encoding="utf-8-sig"))
        for rec in data.get("records", []):
            url = rec.get("url", "")
            rels = rec.get("relations", [])
            if url and rels:
                out[url] = rels
    return out


def archives_map() -> dict[str, str]:
    """Справочник «Архивы»: Аббревиатура И Название (lower) → page_id."""
    out: dict[str, str] = {}
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = api("POST", f"https://api.notion.com/v1/databases/{ARCHIVES_DB_ID}/query", body)
        for p in res.get("results", []):
            pr = p["properties"]
            abbr = "".join(x.get("plain_text", "") for x in
                           pr.get("Аббревиатура", {}).get("rich_text", [])).strip()
            name = "".join(x.get("plain_text", "") for x in
                           pr.get("Название", {}).get("title", [])).strip()
            for key in (abbr, name):
                if key:
                    out[key.lower()] = p["id"]
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


# Алиасы держателей: подпись карточки -> аббревиатура справочника «Архивы»
HOLDER_ALIASES = {"иркутская огунб": "иогунб"}
# Д2: архивный шифр в держателе («РГИА.Ф. 1290. Оп.4. Д.68») -> Архив + Фонд/Опись/Единица
SHELFMARK_RE = re.compile(
    r"^([А-ЯЁа-яё]{2,15})[.,]?\s*Ф\.?\s*(\d+[а-яё]?)\.?\s*Оп\.?\s*(\d+[а-яё]?)\.?"
    r"(?:\s*Д\.?\s*([\d\-]+[а-яё]?))?", re.I)


def page_id_from_url(u: str) -> str:
    m = re.search(r"([0-9a-f]{32})", (u or "").replace("-", ""))
    if not m:
        return ""
    s = m[1]
    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"


def find_page(url: str) -> dict | None:
    if not url:
        return None
    body = {"filter": {"property": URL_COL, "url": {"equals": url}}, "page_size": 1}
    res = api("POST", f"https://api.notion.com/v1/databases/{DB_ID}/query", body)
    hits = res.get("results", [])
    return hits[0] if hits else None


def relation_props(rels: list[dict], arch_map: dict[str, str], unresolved: list[str]) -> dict:
    props: dict = {}
    for rel in rels:
        prop = rel.get("property", "")
        if prop == "Архив хранения":
            raw = (rel.get("source_label") or "").strip()
            label = HOLDER_ALIASES.get(raw.lower(), raw.lower())
            pid = arch_map.get(label)
            if pid:
                props[prop] = {"relation": [{"id": pid}]}
                continue
            # Д2: держатель = архивный шифр -> Архив (по аббревиатуре) + Фонд/Опись/Единица
            m = SHELFMARK_RE.match(raw)
            if m and m[1].lower() in arch_map:
                props[prop] = {"relation": [{"id": arch_map[m[1].lower()]}]}
                props["Фонд"] = {"rich_text": chunks(m[2])}
                props["Опись"] = {"rich_text": chunks(m[3])}
                if m[4]:
                    props["Единица хранения"] = {"rich_text": chunks(m[4])}
            elif raw:
                unresolved.append(f"Архив хранения: «{raw}»")
        elif rel.get("target_url"):
            pid = page_id_from_url(rel["target_url"])
            if pid and prop in PROPS:
                props[prop] = {"relation": [{"id": pid}]}
    return props


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("review_run", type=Path)
    ap.add_argument("--date", required=True)
    ap.add_argument("--update", action="store_true",
                    help="обновлять существующие записи (по URL) вместо пропуска")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN:
        print("Нет NOTION_TOKEN (env или Каталогизация/.env)")
        sys.exit(1)

    d = a.review_run
    csv_path = d / "notion_import.csv"
    if not csv_path.exists():
        print(f"Нет {csv_path} — сначала make_notion_pages.py")
        sys.exit(1)
    reasons = load_reasons(d / "review.csv")
    review_urls = {json.loads(x)["record"].get("url", "")
                   for x in io.open(d / "review_records.jsonl", encoding="utf-8-sig") if x.strip()} \
        if (d / "review_records.jsonl").exists() else set()
    relations = load_relations(d / "export_review.json")
    arch_map = archives_map() if relations else {}
    unresolved: list[str] = []
    # индексы справочников территорий/регионов для авто-простановки (общее правило)
    terr_stem_index, terr_gub, reg_index = tr.load_indexes(api, TERR_DB_ID, REG_DB_ID)

    rows = list(csv.DictReader(io.open(csv_path, encoding="utf-8-sig")))
    added = updated = skipped = errors = 0
    for r in rows:
        url = (r.get(URL_COL) or "").strip()
        props: dict = {}
        for col, val in r.items():
            p = to_prop(col, val)
            if p is not None:
                props[col] = p
        props.update(relation_props(relations.get(url, []), arch_map, unresolved))
        # Авто-простановка территории/региона (общее правило, только если ещё не заданы)
        full_title = r.get("Название источника", "")
        terr_ids, reg_ids = tr.resolve(full_title, url, terr_stem_index, terr_gub, reg_index)
        if terr_ids and "Охватываемая территория" not in props:
            props["Охватываемая территория"] = {"relation": [{"id": i} for i in terr_ids]}
        if reg_ids and "Современные регионы" not in props:
            props["Современные регионы"] = {"relation": [{"id": i} for i in reg_ids]}
        # Д18-страж: «Номер в серии» только вместе с «Серия / массив» — иначе отбросить
        # (том без серии = нарушение; серию линкует детектор A / регистрирует эксперт).
        if "Номер в серии" in props and "Серия / массив" not in props:
            props.pop("Номер в серии")
        title = r.get("Название источника", "")[:60]
        existing = find_page(url)

        if existing is None:
            props["Статус приёмки"] = {"select": {"name": "кандидат"}}
            props["Автор внесения"] = {"select": {"name": "Агент"}}
            props["Дата внесения"] = {"date": {"start": a.date}}
            rs = reasons.get(url, []) if url in review_urls else []
            if rs:
                props["Причина сомнительности"] = {"multi_select": [{"name": x} for x in rs]}
            added += 1
            if a.dry_run:
                continue
            try:
                api("POST", "https://api.notion.com/v1/pages",
                    {"parent": {"database_id": DB_ID}, "properties": props})
                time.sleep(0.34)
            except RuntimeError as e:
                added -= 1
                errors += 1
                print(f"  Ошибка создания [{title}]: {e}")
            continue

        if not a.update:
            skipped += 1
            continue

        # --- ОБНОВЛЕНИЕ: только непустое, без защищённого списка ---
        upd = {k: v for k, v in props.items() if k not in PROTECTED_ON_UPDATE}
        status = (existing["properties"].get("Статус приёмки", {})
                  .get("select") or {}).get("name", "")
        rs = reasons.get(url, []) if url in review_urls else []
        if rs and status == "кандидат":
            upd["Причина сомнительности"] = {"multi_select": [{"name": x} for x in rs]}
        if not upd:
            skipped += 1
            continue
        updated += 1
        if a.dry_run:
            continue
        try:
            api("PATCH", f"https://api.notion.com/v1/pages/{existing['id']}",
                {"properties": upd})
            time.sleep(0.34)
        except RuntimeError as e:
            updated -= 1
            errors += 1
            print(f"  Ошибка обновления [{title}]: {e}")

    tag = "DRY-RUN " if a.dry_run else ""
    print(f"{tag}создано: {added} | обновлено: {updated} | пропущено: {skipped} | ошибок: {errors}")
    if unresolved:
        print("Нерезолвленные relation (завести/сверить в справочнике «Архивы»):")
        for u in sorted(set(unresolved)):
            print("  ", u)


if __name__ == "__main__":
    main()
