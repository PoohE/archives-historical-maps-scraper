"""
Импорт пакета ГАЯО (Ярославская губерния, фонды кроме 560) в каталог Notion.

Источник: output/gayo_package_20261018/gayo_to_catalog.csv (84 101 запись от claude-e1,
см. ПЕРЕДАЧА_на_внесение.md в той же папке) — этот скрипт берёт ТОЛЬКО fund != "560"
(83 031 запись): фонд 455 (Ярославский губернский межевой архив, сплошной массив
генерального межевания), 82 (губернская чертёжная), 80/76/452/459/462/1441 (губернские
учреждения). Эти фонды ярославские по фондовой принадлежности, территориального вопроса
нет. Фонд 560 (общероссийская коллекция карт) — ОТДЕЛЬНЫЙ скрипт после строгой разметки
claude-e1 (f560_territory.csv, 395 из 1070 проходят охват 4 губерний).

Решения пользователя 18.10.2026 (сверено в сессии, не принято со слов пакета как есть):
- Новое поле/класс «Класс документа» в каталог НЕ вводится. `klass_vremenno` пакета
  (Межевой акт/Картографический документ/Делопроизводство/Требует уточнения) заменяется
  собственной классификацией по содержанию (как для ГАСО): DC Type по `kartograficheskiy_
  priznak` + Административный уровень по дача-правилу (§2.3 catalog_guidelines_ru.md).
  Проверка по сути показала: 1741 из 1848 «Делопроизводство» имеют конкретный объект
  (obyekt) и по содержанию не отличаются от «Межевой акт» — отдельный тип не нужен,
  DC Type/admin_level сами разведут их корректно без привязки к ярлыку пакета.
- Территория: fund 455/82/80/76/452/459/462/1441 — ярославские по фондовой принадлежности,
  без дополнительного отбора (`territoriya`/`territoriya_osnovanie` пакета здесь надёжны).

⚠️ Ссылка на дело (чего НЕ было у первой версии импорта ГАСО, исправлено задним числом —
здесь делаем сразу): собирается из `flags` вида `arc<N>;unit<ID>` ->
`https://af.yar-archives.ru/archive<N>/unit/<ID>`.

Запуск:
  python scripts/import_gayo_notion.py --dry-run
  python scripts/import_gayo_notion.py --dry-run --limit 20
  python scripts/import_gayo_notion.py
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import env, fix_stdout, load_env, log  # noqa: E402

from notion_client import Client  # noqa: E402

ROOT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
SCHEMA_PATH = ROOT / "scripts" / "modules" / "notion_schema.json"
ENV_PATH = Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env")
SOURCE_CSV = ROOT / "output" / "gayo_package_20261018" / "gayo_to_catalog.csv"
LEDGER_PATH = ROOT / "output" / "gayo_package_20261018" / "_notion_import_ledger.jsonl"

ARCHIVE_GAYO = "https://app.notion.com/3830ba89eabe81a393e8de7dd0afbcf0"
TERRITORY_YAROSLAVL = "https://app.notion.com/3920ba89eabe819abd11e27ba6a2ac05"
REGION_YAROSLAVL = "https://app.notion.com/3c30ba89eabe8173ad9bc0470e9efdc7"

FUND_NAMES = {
    "455": "Ярославский губернский межевой архив",
    "82": "Ярославская губернская чертёжная",
}

IMAGE_KW = ("план", "чертёж", "карта", "выкопировка", "съёмка")
TEXT_KW = ("межевая книга", "межевание", "владенная запись", "оценка земель",
           "полюбовная сказка", "размежевание", "ведомость дачам", "полевые записки",
           "экономические примечания", "описание границ")

PLACE_ANCHOR_PAT = r"пустош|\bдач[аи]\b|сельц|дер\.|деревн|\bсело\b|слобод|погост|сельск\w* общест|хутор"
YEAR_PAT = re.compile(r"\b(1[6-9]\d{2}|20[0-2]\d)\b")
FLAGS_PAT = re.compile(r"arc(\d+);unit(\d+)")

# ЧЕКЛИСТ_ПРЕДЗАЛИВКИ_полей.md п.1: короткое название, п.5: Тип источника по виду документа,
# п.14/15: масштаб (реальный или приближённый ПО ТИПУ, единый формат) — не проставлялись ни
# здесь, ни в GASO-импорте; добавлено при сверке с пользователем 18.10.2026.
BRACKETS_PAT = re.compile(r"[\[\]]")
# id запрошены напрямую у живой базы 18.10.2026 (не из памяти/другого скрипта — там
# найдена путаница A1/A2/A3/A6, см. урок сессии).
TIP_A2 = "https://app.notion.com/3830ba89eabe816e90d4eced7e4ce20f"
TIP_A3 = "https://app.notion.com/3830ba89eabe81e88960d51ab3be3447"
TIP_A6 = "https://app.notion.com/3830ba89eabe8171ac4aee07e78f3a7e"
TIP_B8 = "https://app.notion.com/3c30ba89eabe8156867dd8a6f3cec753"


def short_title(full_title: str) -> str:
    """Суть до первого «/» (слэш-вставка вида «/и губернскому архитектору/») или до конца
    первого предложения, без хвоста «/Сост…/Рукописн.» (ЧЕКЛИСТ_ПРЕДЗАЛИВКИ п.1)."""
    t = full_title.strip()
    if len(t) <= 150:
        return BRACKETS_PAT.sub("", t)[:250]
    slash_pos = t.find("/")
    dot_pos = t.find(". ")
    cuts = [p for p in (slash_pos, dot_pos) if p > 7]
    cand = t[: min(cuts)].strip() if cuts else t
    return BRACKETS_PAT.sub("", cand)[:250]


def tip_istochnika(dc: str, lvl: str, zagolovok: str):
    """A3 (межевой план) — только для «Дача»: конкретный поименованный объект. Без
    конкретного объекта (Уезд/Волость/Губерния) это либо план города/селения (A6), либо
    обзорная карта/многотемное дело широкого охвата (A2) — НЕ единичный межевой план,
    масштаб 1:8400 для них не характерен (найдено спот-чеком 18.10.2026 — тип/масштаб
    авто-ставились даже многотемным делам без объекта)."""
    z = zagolovok.lower()
    if dc in ("StillImage", "StillImage+Text"):
        if re.search(r"план[ы]?\s+(города|селени|погоста|села\b)", z):
            return TIP_A6
        return TIP_A3 if lvl == "Дача" else TIP_A2
    if dc == "Text" and any(k in z for k in TEXT_KW):
        return TIP_B8
    return None


def scale_for_type(tip_url: str):
    if tip_url == TIP_A3:
        return 8400.0, 'приближённо по типу «межевой план» (~1:8400, 100 саж. в дюйме)'
    return None, None

RETRIES = 6


def call_retry(fn, *a, **kw):
    for attempt in range(RETRIES):
        try:
            return fn(*a, **kw)
        except Exception:  # noqa: BLE001 -- транспортные ошибки httpx разных классов
            if attempt == RETRIES - 1:
                raise
            time.sleep(min(2**attempt, 30))
    raise RuntimeError("unreachable")


def dc_type(priznak: str) -> str:
    p = (priznak or "").lower()
    has_img = any(k in p for k in IMAGE_KW)
    has_txt = any(k in p for k in TEXT_KW)
    if has_img and has_txt:
        return "StillImage+Text"
    if has_img:
        return "StillImage"
    return "Text"


def admin_level(obyekt: str, zagolovok: str) -> str:
    """Дача-правило §2.3 (та же функция, что в import_gaso_notion.py после фикса 17.10)."""
    o, z = obyekt or "", zagolovok or ""
    combined = f"{o} {z}"
    if re.search(r"план волост|карта уезда|обзорн|сводн.*(волост|уезд)", z, re.I):
        return "Волость" if re.search(r"волост", z, re.I) else "Уезд"
    if re.search(r"губерни", z, re.I) and not re.search(r"уезд|волост|" + PLACE_ANCHOR_PAT, combined, re.I):
        return "Губерния"
    if re.search(PLACE_ANCHOR_PAT, combined, re.I):
        return "Дача"
    if re.search(r"волост", o, re.I):
        return "Волость"
    return "Уезд"


def extract_year(s: str):
    m = YEAR_PAT.search(s or "")
    return int(m.group(1)) if m else None


DELO_NUM_PAT = re.compile(r"^(\d+)")
NEIGHBOR_WINDOW = 5
NEIGHBOR_MAX_GAP = 15
_DATE_INTERP: dict = {}


def build_date_interpolation(rows: list) -> dict:
    """Решение пользователя 18.10.2026: для дел без собственной даты — год по соседям
    описи (по номеру дела, окно ±5), только если разброс соседних лет <=15 (иначе честно
    пусто). Диапазон ВСЕЙ описи слишком широк для этой цели (проверено: ф.455 оп.2Л
    1663-1919) — используется только локальное окно, не вся опись."""
    from collections import defaultdict

    by_opis = defaultdict(list)
    for r in rows:
        by_opis[(r["fund"], r["opis"])].append(r)

    interp = {}
    for recs in by_opis.values():
        def sort_key(rec):
            m = DELO_NUM_PAT.match(rec["n_delo"] or "")
            return (m is None, int(m.group(1)) if m else 0)

        recs_sorted = sorted(recs, key=sort_key)
        years = [extract_year(r["data_nachato"]) or extract_year(r["data_okoncheno"]) for r in recs_sorted]
        for i, r in enumerate(recs_sorted):
            if years[i] is not None or not DELO_NUM_PAT.match(r["n_delo"] or ""):
                continue
            lo = hi = None
            for d in range(1, NEIGHBOR_WINDOW + 1):
                if i - d >= 0 and years[i - d] is not None:
                    lo = years[i - d]
                    break
            for d in range(1, NEIGHBOR_WINDOW + 1):
                if i + d < len(recs_sorted) and years[i + d] is not None:
                    hi = years[i + d]
                    break
            if lo is not None and hi is not None and abs(hi - lo) <= NEIGHBOR_MAX_GAP:
                key = (r["fund"], r["opis"], r["n_delo"], r.get("flags", ""))
                interp[key] = (min(lo, hi), max(lo, hi))
    return interp


def archive_url(flags: str):
    m = FLAGS_PAT.search(flags or "")
    if not m:
        return None
    arc, unit = m.groups()
    return f"https://af.yar-archives.ru/archive{arc}/unit/{unit}"


def build_properties(rec: dict) -> dict:
    zagolovok = (rec["zagolovok"] or "").strip()
    fund = rec["fund"]
    year_lo = extract_year(rec["data_nachato"]) or extract_year(rec["data_okoncheno"])
    year_hi = extract_year(rec["data_okoncheno"]) or year_lo
    interpolated = False
    if year_lo is None:
        key = (fund, rec["opis"], rec["n_delo"], rec.get("flags", ""))
        bounds = _DATE_INTERP.get(key)
        if bounds:
            year_lo, year_hi = bounds
            interpolated = True
    dc = dc_type(rec["kartograficheskiy_priznak"])
    lvl = admin_level(rec["obyekt"], zagolovok)
    tip = tip_istochnika(dc, lvl, zagolovok)
    scale_denom, scale_text = scale_for_type(tip)

    primechanie = (rec.get("primechanie") or "").strip()
    notes = []
    if primechanie:
        notes.append(primechanie)
    if rec.get("iz_needs_human") == "да":
        notes.append("Поднято из needs_human claude-e1 по фондовой принадлежности (18.10.2026)")
    if interpolated:
        notes.append(f"Год датирован по соседям описи (интерполяция, {year_lo}-{year_hi})")
    if fund in FUND_NAMES and FUND_NAMES[fund] not in primechanie:
        notes.append(f"Фондообразователь: {FUND_NAMES[fund]}")

    url = archive_url(rec.get("flags", ""))

    props = {
        "Название источника": short_title(zagolovok) or f"ф.{fund} оп.{rec['opis']} д.{rec['n_delo']}",
        "Описание": zagolovok,
        "Фонд": fund,
        "Опись": rec["opis"],
        "Единица хранения": rec["n_delo"],
        "DC Type": dc,
        "Архив хранения": [ARCHIVE_GAYO],
        "Охватываемая территория": [TERRITORY_YAROSLAVL],
        "Современные регионы": [REGION_YAROSLAVL],
        "Место хранения": "Государственный архив Ярославской области (ГАЯО), г. Ярославль",
        "Язык": "Русский",
        "Статус доступа": "Только метаданные",
        "Статус приёмки": "кандидат",
        "Автор внесения": "Агент",
        "Дата внесения": time.strftime("%Y-%m-%d"),
        "Административный уровень": lvl,
    }
    if tip:
        props["Тип источника"] = [tip]
    if scale_denom:
        props["Масштаб (знаменатель)"] = scale_denom
        props["Оригинальный масштаб"] = scale_text
    if url:
        props["Ссылка на онлайн-архив"] = url
    if rec.get("listov"):
        props["Листы / страницы"] = rec["listov"]
    if year_lo:
        props["Год создания (нижняя)"] = float(year_lo)
    if year_hi:
        props["Год создания (верхняя)"] = float(year_hi)
    if notes:
        props["Примечания"] = "\n".join(notes)
    return props


PROPERTY_TYPES = {
    "Название источника": "title", "Описание": "rich_text", "Фонд": "rich_text",
    "Опись": "rich_text", "Единица хранения": "rich_text", "Примечания": "rich_text",
    "Листы / страницы": "rich_text", "Место хранения": "rich_text",
    "Год создания (нижняя)": "number", "Год создания (верхняя)": "number",
    "DC Type": "select", "Язык": "select", "Статус доступа": "select",
    "Статус приёмки": "select", "Автор внесения": "select",
    "Административный уровень": "select", "Архив хранения": "relation",
    "Охватываемая территория": "relation", "Современные регионы": "relation",
    "Дата внесения": "date", "Ссылка на онлайн-архив": "url",
    "Тип источника": "relation", "Масштаб (знаменатель)": "number",
    "Оригинальный масштаб": "rich_text",
}


def page_id_from_url(url: str) -> str:
    hexid = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    m = re.search(r"([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$", hexid, re.I)
    return "-".join(m.groups())


def to_rest_value(name: str, value):
    t = PROPERTY_TYPES[name]
    if t == "title":
        return {"title": [{"text": {"content": str(value)[:2000]}}]}
    if t == "rich_text":
        return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
    if t == "number":
        return {"number": value}
    if t == "select":
        return {"select": {"name": value}}
    if t == "date":
        return {"date": {"start": value}}
    if t == "url":
        return {"url": value}
    if t == "relation":
        urls = value if isinstance(value, list) else [value]
        return {"relation": [{"id": page_id_from_url(u)} for u in urls]}
    raise ValueError(name)


def serialize(props: dict) -> dict:
    return {k: to_rest_value(k, v) for k, v in props.items()}


def load_source():
    with SOURCE_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["fund"] != "560"]


def load_ledger() -> set:
    done = set()
    if LEDGER_PATH.exists():
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("status") == "ok":
                done.add(tuple(rec["key"]))
    return done


def append_ledger(entry: dict):
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="ограничить число записей (0=все)")
    args = parser.parse_args()

    fix_stdout()
    source = load_source()
    global _DATE_INTERP
    _DATE_INTERP = build_date_interpolation(source)
    if args.limit:
        source = source[: args.limit]

    if args.dry_run:
        import collections
        with_year = sum(
            1 for r in source
            if extract_year(r["data_nachato"]) or extract_year(r["data_okoncheno"])
            or (r["fund"], r["opis"], r["n_delo"], r.get("flags", "")) in _DATE_INTERP
        )
        print(f"С годом (прямым + интерполяцией по соседям): {with_year}/{len(source)}")
        dc_counts = collections.Counter(dc_type(r["kartograficheskiy_priznak"]) for r in source)
        lvl_counts = collections.Counter(admin_level(r["obyekt"], r["zagolovok"]) for r in source)
        with_url = sum(1 for r in source if archive_url(r.get("flags", "")))
        print(f"Записей: {len(source)}")
        print("DC Type:", dict(dc_counts))
        print("Административный уровень:", dict(lvl_counts))
        print(f"Со ссылкой на дело: {with_url}/{len(source)}")
        print("\n=== примеры (первые 3) ===")
        for rec in source[:3]:
            props = build_properties(rec)
            print(f"\n-- ф{rec['fund']} оп{rec['opis']} д{rec['n_delo']} --")
            for k, v in props.items():
                print(f"  {k}: {v}")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("import_gayo")
    catalog_id = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["data_source_id"]
    done_ledger = load_ledger()

    ok, failed, skipped = 0, 0, 0
    for i, rec in enumerate(source, 1):
        key = (rec["fund"], rec["opis"], rec["n_delo"], rec.get("flags", ""))
        if key in done_ledger:
            skipped += 1
            continue
        props = build_properties(rec)
        try:
            page = call_retry(
                client.pages.create,
                parent={"type": "data_source_id", "data_source_id": catalog_id},
                properties=serialize(props),
            )
            append_ledger({"key": list(key), "status": "ok", "page_id": page["id"]})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_ledger({"key": list(key), "status": "fail", "error": str(exc)[:300]})
            failed += 1
            logger.info(f"FAIL {key}: {exc}")
        if i % 50 == 0:
            logger.info(f"{i}/{len(source)} ok={ok} failed={failed} skipped={skipped}")
        time.sleep(0.34)

    print(f"Готово: ok={ok} failed={failed} skipped={skipped} из {len(source)}")


if __name__ == "__main__":
    main()
