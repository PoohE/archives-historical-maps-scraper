"""
Импорт очищенного пакета ГАСО (Смоленская губерния) в каталог Notion.

Источник: output/gaso_package_20261013/gaso_accepted.csv (5321 запись после QA 16.10.2026,
см. ПЕРЕДАЧА_на_внесение.md и ИНСТРУКЦИЯ_внесение_в_Notion_2026-09-30.md). Пишет через
официальный notion_client (как import_rgvia_notion.py) — в стороне от лимита Query Data
Source чат-инструмента Notion MCP.

Ключ привязки к архиву — тройка Фонд+Опись+Единица хранения (у ГАСО нет ссылок на карточки
дел — портал единиц хранения не публикует вообще, см. ПЕРЕДАЧА_на_внесение.md). Повторяющийся
номер дела у ф.814 — НЕ дубль (разные селения одной межевой книги, см. п.4-бис хендоффа).

Все записи заводятся со **Статус приёмки = кандидат** (внутренний гейт `gate` в CSV — это
ЛОКАЛЬНАЯ проверка качества распознавания, не статус приёмки каталога; человеческую приёмку
в "принято" делает пользователь позже, как было с РГВИА).

## Классификация (судебные решения — см. --dry-run перед запуском на всём пакете)

DC Type по `kartograficheskiy_priznak` (может содержать несколько через запятую):
  есть маркер карты/плана (план/чертёж/карта/выкопировка/съёмка)
    + есть маркер текстового документа (межевая книга/межевание/владенная запись/
      оценка земель/полюбовная сказка/размежевание/ведомость дачам/полевые записки/
      экономические примечания)              -> "StillImage+Text"
  только маркер карты/плана                   -> "StillImage"
  только маркер текстового документа           -> "Text"
  ни один не узнан (не должно встречаться)     -> "Text" (безопасный дефолт)

Административный уровень — по дача-правилу §2.3 `catalog_guidelines_ru.md` (найдено 16.10.2026
на ГАКО, подтверждено пользователем и перенесено в онтологию
`Ontology/20_domains/hgis/inbox/from_projects/poisk-arhivov_dacha-pravilo-i-terminy_2026-10-16.md`):
губерния/уезд/волость в заголовке часто ТОЛЬКО локатор, не охват документа. Если предмет
дела — поименованный земельный участок (дача, пустошь, надел, часть земли/землепользование
села/деревни/сельца) -> "Дача", ДАЖЕ когда назван целый уезд/волость — у ГАСО это дела «по
ходатайству крестьян деревни Х о выделе надела/отрубного участка» (о НАДЕЛЕ, не о деревне
целиком). Признак действительно волостного/уездного охвата — явный предмет «план волости»/
«карта уезда»/обзорная съёмка (override по `zagolovok`, в корпусе ГАСО не встретился — 0 из
5321). Остаток без именованного места (нрзб/товарищество/только волость/уезд названы) ->
"Волость"/"Уезд" как residual.
  поименованное место (дача/пустошь/сельцо/деревня/село/слобода/погост) -> "Дача"
  явный предмет «план волости»/«карта уезда»/обзорная съёмка (override)  -> "Волость"/"Уезд"
  без места, только волость названа                                      -> "Волость"
  без места, нрзб/товарищество/только уезд (residual)                     -> "Уезд"

Запуск:
  python scripts/import_gaso_notion.py --dry-run           # статистика классификации + 3 примера
  python scripts/import_gaso_notion.py --dry-run --limit 20
  python scripts/import_gaso_notion.py                      # реальная заливка (резюмируемая)
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
SOURCE_CSV = ROOT / "output" / "gaso_package_20261013" / "gaso_accepted.csv"
LEDGER_PATH = ROOT / "output" / "gaso_package_20261013" / "_notion_import_ledger.jsonl"
OPIS_MANIFEST = Path(r"C:\arch\output\gaso_opisi_20261013\manifest.json")
_OPIS_PART_PAT = re.compile(r"_часть\d+$")


def load_opis_urls() -> dict:
    """(фонд, опись) -> URL страницы описи на портале (НЕ карточка дела — портал её не
    публикует вообще, см. ПЕРЕДАЧА_на_внесение.md). Найдено 16.10.2026 (пользователь указал,
    что ГАСО заносился без ссылок вовсе) — часть описей собрана через портал и имеет
    `page_url` в манифесте, фонд 814 получен архивом по прямому запросу и ссылки не имеет."""
    if not OPIS_MANIFEST.exists():
        return {}
    manifest = json.loads(OPIS_MANIFEST.read_text(encoding="utf-8"))
    urls = {}
    for m in manifest:
        if not m.get("page_url"):
            continue
        opis_key = _OPIS_PART_PAT.sub("", m["opis"])  # "1_часть2" -> "1" (многостраничный скан)
        urls[(m["fund"], opis_key)] = m["page_url"]
    return urls


OPIS_URLS = load_opis_urls()

ARCHIVE_GASO = "https://app.notion.com/3830ba89eabe816ba8f6df1a2eb1fc05"
TERRITORY_SMOLENSK = "https://app.notion.com/3920ba89eabe815a87d3f5d067caf24a"
REGION_SMOLENSK = "https://app.notion.com/3c30ba89eabe81abb513e23ee6e2d3a8"

FUND_NAMES = {
    "814": "Смоленская межевая контора",
    "237": "Сычевская уездная землеустроительная комиссия",
    "428": "Ельнинская уездная землеустроительная комиссия",
    "576": "Смоленская губернская посредническая комиссия",
    "890": "Смоленская губернская оценочная комиссия",
    "334": "Смоленская губернская землеустроительная комиссия",
    "1027": "Велижская уездная землеустроительная комиссия",
    "458": "Рославльская уездная землеустроительная комиссия",
    "89": "Краснинская уездная землеустроительная комиссия",
}

IMAGE_KW = ("план", "чертёж", "карта", "выкопировка", "съёмка")
TEXT_KW = ("межевая книга", "межевание", "владенная запись", "оценка земель",
           "полюбовная сказка", "размежевание", "ведомость дачам", "полевые записки",
           "экономические примечания")

YEAR_PAT = re.compile(r"\b(1[6-9]\d{2}|20[0-2]\d)\b")

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


PLACE_ANCHOR_PAT = r"пустош|\bдач[аи]\b|сельц|дер\.|деревн|\bсело\b|слобод|погост|сельск\w* общест|хутор"


def admin_level(obyekt: str, zagolovok: str) -> str:
    """Найдено 17.10.2026 спот-чеком: у части фондов (ф.890 — оценочная комиссия) именованная
    общность («Кобызевского сельского общества») лежит ТОЛЬКО в `zagolovok`, `obyekt` несёт
    лишь волость+уезд как локатор — проверять обязательно оба поля, не только `obyekt`."""
    o, z = obyekt or "", zagolovok or ""
    combined = f"{o} {z}"
    if re.search(r"план волост|карта уезда|обзорн|сводн.*(волост|уезд)", z, re.I):
        return "Волость" if re.search(r"волост", z, re.I) else "Уезд"
    # Губернский охват -- "губерния" явно названа, а конкретного места/уезда/волости нет вовсе
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


def build_properties(rec: dict) -> dict:
    zagolovok = (rec["zagolovok"] or "").strip()
    fund = rec["fund"]
    year_lo = extract_year(rec["data_nachato"]) or extract_year(rec["data_okoncheno"])
    year_hi = extract_year(rec["data_okoncheno"]) or year_lo

    notes = []
    if rec.get("primechanie"):
        notes.append(f"№ по порядку в описи: {rec['primechanie']}")
    if rec.get("page"):
        notes.append(f"страница скана описи: {rec['page']} (способ: {rec.get('sposob', '')})")
    if rec.get("flags") == "проверить_топонимы":
        notes.append("⚠️ собственные имена читались неуверенно (Vision/focr) — сверить топонимы")
    elif rec.get("flags") == "ответ_обрезан":
        notes.append("⚠️ ответ модели распознавания был обрезан — возможна неполнота заголовка")
    if fund in FUND_NAMES:
        notes.append(f"Фондообразователь: {FUND_NAMES[fund]}")

    opis_url = OPIS_URLS.get((fund, rec["opis"]))
    if opis_url:
        notes.append("Ссылка — на опись фонда (карточки дел портал не публикует), не на дело")
    elif fund == "814":
        notes.append("Опись получена архивом по прямому запросу, страницы портала нет")

    props = {
        "Название источника": zagolovok[:250] or f"ф.{fund} оп.{rec['opis']} д.{rec['n_delo']}",
        "Описание": zagolovok,
        "Фонд": fund,
        "Опись": rec["opis"],
        "Единица хранения": rec["n_delo"],
        "DC Type": dc_type(rec["kartograficheskiy_priznak"]),
        "Архив хранения": [ARCHIVE_GASO],
        "Охватываемая территория": [TERRITORY_SMOLENSK],
        "Современные регионы": [REGION_SMOLENSK],
        "Место хранения": "Государственный архив Смоленской области (ГАСО), г. Смоленск",
        "Язык": "Русский",
        "Статус доступа": "Только метаданные",
        "Статус приёмки": "кандидат",
        "Автор внесения": "Агент",
        "Дата внесения": time.strftime("%Y-%m-%d"),
        "Административный уровень": admin_level(rec["obyekt"], zagolovok),
    }
    if opis_url:
        props["Ссылка на онлайн-архив"] = opis_url
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
        return list(csv.DictReader(f))


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
    if args.limit:
        source = source[: args.limit]

    if args.dry_run:
        import collections
        dc_counts = collections.Counter(dc_type(r["kartograficheskiy_priznak"]) for r in source)
        lvl_counts = collections.Counter(admin_level(r["obyekt"], r["zagolovok"]) for r in source)
        print(f"Записей: {len(source)}")
        print("DC Type:", dict(dc_counts))
        print("Административный уровень:", dict(lvl_counts))
        print("\n=== примеры (первые 3) ===")
        for rec in source[:3]:
            props = build_properties(rec)
            print(f"\n-- ф{rec['fund']} оп{rec['opis']} д{rec['n_delo']} --")
            for k, v in props.items():
                print(f"  {k}: {v}")
        return

    load_env(ENV_PATH)
    client = Client(auth=env("NOTION_TOKEN", required=True))
    logger = log("import_gaso")
    catalog_id = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["data_source_id"]
    done_ledger = load_ledger()

    ok, failed, skipped = 0, 0, 0
    for i, rec in enumerate(source, 1):
        key = (rec["fund"], rec["opis"], rec["n_delo"], rec.get("page", ""))
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
