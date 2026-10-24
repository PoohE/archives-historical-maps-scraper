"""
Резюмируемый импортёр РГВИА (650-набор, 09.10.2026) в Notion-каталог.

Источники:
  - output/uiad_rgvia_maps_20261004/rgvia_650_keep.json          (полные записи)
  - output/uiad_rgvia_maps_20261004/РЕВЬЮ_классификации_РГВИА_v3.md  (финальные типы)

Пропускает:
  - [ОТКЛОНИТЬ_территория] и [ИСКЛЮЧИТЬ_линейный]
  - строки-тома 6 внутридельных серий (уже внесены вручную как образцы 09.10)
  - коды, уже отмеченные в ledger (резюмируемость)

Запуск:
  python import_rgvia_notion.py --dry-run        # только построить и показать примеры, не писать
  python import_rgvia_notion.py                  # реальная заливка (резюмируемая)
"""
import sys
import re
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\IG Dropbox\Andy PoohV\Project\Claude\scripts\lib")))
from common import fix_stdout, load_env, env, log  # noqa

from notion_client import Client

ROOT = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
BASE = ROOT / "output" / "uiad_rgvia_maps_20261004"
SOURCE_JSON = BASE / "rgvia_650_keep.json"
CLASSIFICATION_MD = BASE / "РЕВЬЮ_классификации_РГВИА_v3.md"
LEDGER_PATH = BASE / "_notion_import_ledger.jsonl"

CATALOG_DATA_SOURCE_ID = "decdf63c-6f64-4852-ada2-65e72c79d9bc"

# -------- id-справочники (собраны и проверены по живой базе 09.10.2026) --------
ARCHIVE_RGVIA = "https://app.notion.com/3830ba89eabe8130abb0ee4750059351"

TERRITORY = {
    "Пермская": "https://app.notion.com/3920ba89eabe8108a1aae715a5891796",
    "Калужская": "https://app.notion.com/3920ba89eabe81beaf09c20fea0fb910",
    "Смоленская": "https://app.notion.com/3920ba89eabe815a87d3f5d067caf24a",
    "Ярославская": "https://app.notion.com/3920ba89eabe819abd11e27ba6a2ac05",
}
REGION = {
    "Пермская": "https://app.notion.com/3c30ba89eabe8149ab49cada9e1804a1",
    "Калужская": "https://app.notion.com/3c30ba89eabe811eb25bd2ca491ba56f",
    "Смоленская": "https://app.notion.com/3c30ba89eabe81abb513e23ee6e2d3a8",
    "Ярославская": "https://app.notion.com/3c30ba89eabe8173ad9bc0470e9efdc7",
}

TYPE_ID = {
    "A1": "https://app.notion.com/3830ba89eabe816da278cf6ce9cdeec6",
    "A2": "https://app.notion.com/3830ba89eabe816e90d4eced7e4ce20f",
    "A3": "https://app.notion.com/3830ba89eabe81e88960d51ab3be3447",
    "A4": "https://app.notion.com/3830ba89eabe81cc9d0cf59aadf5b7a5",
    "A5": "https://app.notion.com/3830ba89eabe8180a87dd5d89c0de70d",
    "A6": "https://app.notion.com/3830ba89eabe8171ac4aee07e78f3a7e",
    "B2": "https://app.notion.com/3830ba89eabe812b8503fc918c8a2b0b",
    "B6": "https://app.notion.com/3c30ba89eabe8161b533c149b6f12aa8",
    "B10": "https://app.notion.com/3c30ba89eabe81019c97e344090c601a",
    "C4": "https://app.notion.com/3830ba89eabe8110b837eb024a84ab10",
    "C7": "https://app.notion.com/3c30ba89eabe81048ccbfb73355a9995",
    # ДЕЛОПРОИЗВ, ПОСТРОЙКА -- тип источника не ставим (нет в справочнике канона)
}

DC_TYPE = {
    "A1": "StillImage", "A2": "StillImage", "A3": "StillImage", "A4": "StillImage",
    "A5": "StillImage", "A6": "StillImage",
    "B2": "Text", "B6": "Text", "B10": "Text", "ДЕЛОПРОИЗВ": "Text", "ПОСТРОЙКА": "Text",
    "C4": "Dataset", "C7": "Dataset",
}

SKIP_TAGS = {"ОТКЛОНИТЬ_территория", "ИСКЛЮЧИТЬ_линейный"}

# коды, которые уже внесены вручную 09.10 как образцы (включая 6 внутридельных серий
# и 2 первых образца) -- пропускаем целиком, не дублировать
ALREADY_DONE_DELO_PREFIXES = {
    ("386", "1", "4096"),
    ("846", "16", "18766"),
}
# внутридельные серии: все строки-тома этих дел пропускаем (слиты в 1 запись каждая, сделано вручную)
MERGED_SERIES_BASE_DELO = {
    ("846", "16", "19040"),
    ("846", "16", "18929"),
    ("846", "16", "18753"),
    ("846", "16", "19182"),
    ("846", "16", "26082"),
    ("846", "16", "5101"),
    # найдены дополнительно при dry-run 09-10.10.2026 (пропущены в первом аудите серий):
    ("846", "16", "18754"),
    ("846", "16", "18930"),
    ("846", "16", "19038"),
    ("846", "16", "19187"),
    ("846", "16", "24022"),
}
# многотомные дела, где в НАШЕМ наборе есть лишь РАЗНЫЕ по теме тома (разные губернии на
# одно общеимперское дело) -- НЕ сливать, импортировать как отдельные записи как обычно
# (поведение по умолчанию и так их не трогает, здесь только для документации):
#   ф846д17290 (т.11 Калужская / т.27 Пермская), ф846д17469А и ф846д17469Б (по 3 губернии)

TECHNIQUE_MAP = [
    (re.compile(r"рукоп|рук\.", re.I), "Рукописная"),
    (re.compile(r"печ\.|печат", re.I), "Печатная"),
    (re.compile(r"хромолитограф", re.I), "Хромолитография"),
    (re.compile(r"литограф", re.I), "Литография"),
    (re.compile(r"грав", re.I), "Гравюра"),
    (re.compile(r"фотокопи|светоп", re.I), "Фотокопия"),
]

AUTHOR_PAT = re.compile(
    r"(?:Сост(?:авил)?\.?\s+|составил[а]?\s+|Черт\.\s+|черт[её]ж[а]?\s+|снимал\s+|Подп\.\s*[-–—]?\s*)"
    r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ]\.(?:\s*[А-ЯЁ]\.)?)?)",
    re.I,
)

CUT_PAT = re.compile(r"^(.*?)\.\s*(?:Рук(?:оп)?\.|Печ(?:ат)?\.|Масштаб\b|М-бы?\b)", re.S)


def short_title(full_title: str) -> str:
    m = CUT_PAT.match(full_title)
    cand = (m.group(1) if m else full_title).strip()
    if len(cand) < 8 or len(cand) > 220:
        cand = full_title.strip()
    return cand[:250]


def guess_technique(technique_raw: str, title: str):
    hay = f"{technique_raw} {title}"
    for pat, val in TECHNIQUE_MAP:
        if pat.search(hay):
            return val
    return None


def guess_author(title: str):
    m = AUTHOR_PAT.search(title)
    return m.group(1).strip() if m else None


def guess_admin_level(typ: str, title: str):
    if typ == "A6":
        return "Нас. пункт"
    if re.search(r"\bволост", title, re.I):
        return "Волость"
    if re.search(r"\bдач[аи]\b", title, re.I) and typ == "A3":
        return "Дача"
    if re.search(r"\bуезд", title, re.I):
        return "Уезд"
    return "Губерния"


def parse_classification(path: Path):
    line_pat = re.compile(r"^\[([^\]]+)\]\s+(\S+)\s+\|\s+([^|]+?)\s*\|\s+(.*)$")
    code_pat = re.compile(r"ф(\d+)оп(\d+)д(.+)")
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = line_pat.match(line)
            if not m:
                continue
            typ, territory, code, title_in_file = m.groups()
            cm = code_pat.match(code.strip())
            if not cm:
                continue
            fund, opis, delo = cm.groups()
            rows.append({"typ": typ, "territory_tag": territory, "fund": fund, "opis": opis, "delo": delo.strip()})
    return rows


def load_ledger():
    done = set()
    if LEDGER_PATH.exists():
        with open(LEDGER_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("status") == "ok":
                    done.add(tuple(rec["key"]))
    return done


def append_ledger(entry: dict):
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# -------- типы свойств схемы каталога (для сериализации под сырой REST API) --------
PROPERTY_TYPES = {
    "Название источника": "title",
    "Описание": "rich_text",
    "Фонд": "rich_text",
    "Опись": "rich_text",
    "Единица хранения": "rich_text",
    "Номер в серии": "rich_text",
    "Автор / составитель": "rich_text",
    "Оригинальный масштаб": "rich_text",
    "Размер листа (мм)": "rich_text",
    "Примечания": "rich_text",
    "Масштаб (знаменатель)": "number",
    "Год создания (нижняя)": "number",
    "Год создания (верхняя)": "number",
    "DC Type": "select",
    "Язык": "select",
    "Статус доступа": "select",
    "Статус приёмки": "select",
    "Автор внесения": "select",
    "Административный уровень": "select",
    "Техника исполнения": "select",
    "Ссылка на онлайн-архив": "url",
    "Архив хранения": "relation",
    "Охватываемая территория": "relation",
    "Современные регионы": "relation",
    "Тип источника": "relation",
    "Серия / массив": "relation",
    "Дата внесения": "date",
}

UUID_PAT = re.compile(r"([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$", re.I)


def page_id_from_url(url: str) -> str:
    """https://app.notion.com/<32 hex> -> стандартный UUID с дефисами."""
    hexid = url.rstrip("/").rsplit("/", 1)[-1]
    hexid = hexid.split("?")[0]
    m = UUID_PAT.search(hexid)
    if not m:
        raise ValueError(f"не похоже на id страницы Notion: {url}")
    return "-".join(m.groups())


def to_rest_value(prop_name: str, value):
    """Простое значение (строка/число/список URL) -> форма REST API Notion."""
    ptype = PROPERTY_TYPES[prop_name]
    if ptype == "title":
        return {"title": [{"text": {"content": str(value)[:2000]}}]}
    if ptype == "rich_text":
        return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
    if ptype == "number":
        return {"number": value}
    if ptype == "select":
        return {"select": {"name": value}}
    if ptype == "url":
        return {"url": value}
    if ptype == "date":
        return {"date": {"start": value}}
    if ptype == "relation":
        urls = value if isinstance(value, list) else [value]
        return {"relation": [{"id": page_id_from_url(u)} for u in urls]}
    raise ValueError(f"неизвестный тип свойства: {prop_name}")


def serialize_for_rest(props: dict) -> dict:
    return {k: to_rest_value(k, v) for k, v in props.items()}


def build_properties(rec: dict, typ: str):
    title = rec["title"]
    territory = rec["territory"]
    props = {
        "Название источника": short_title(title),
        "Описание": title,
        "Фонд": rec["fund"],
        "Опись": rec["opis"],
        "Единица хранения": rec["delo"],
        "DC Type": DC_TYPE.get(typ, "Text"),
        "Архив хранения": [ARCHIVE_RGVIA],
        "Язык": "Русский",
        "Статус доступа": "Только метаданные",
        "Статус приёмки": "кандидат",
        "Автор внесения": "Агент",
        "Дата внесения": time.strftime("%Y-%m-%d"),
        "Административный уровень": guess_admin_level(typ, title),
    }
    if territory in TERRITORY:
        props["Охватываемая территория"] = [TERRITORY[territory]]
        props["Современные регионы"] = [REGION[territory]]
    if rec.get("url"):
        props["Ссылка на онлайн-архив"] = rec["url"]
    if typ in TYPE_ID:
        props["Тип источника"] = [TYPE_ID[typ]]
    if rec.get("scale_denom"):
        try:
            props["Масштаб (знаменатель)"] = float(rec["scale_denom"])
        except ValueError:
            pass
    if rec.get("scale_raw"):
        props["Оригинальный масштаб"] = rec["scale_raw"]
    if rec.get("year_from"):
        try:
            props["Год создания (нижняя)"] = float(rec["year_from"])
        except ValueError:
            pass
    if rec.get("year_to"):
        try:
            props["Год создания (верхняя)"] = float(rec["year_to"])
        except ValueError:
            pass
    if rec.get("size_cm"):
        props["Размер листа (мм)"] = f"{rec['size_cm']} см"
    tech = guess_technique(rec.get("technique", ""), title)
    if tech:
        props["Техника исполнения"] = tech
    author = guess_author(title)
    if author:
        props["Автор / составитель"] = author
    return props


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="ограничить число записей (0=все)")
    args = parser.parse_args()

    fix_stdout()
    load_env(Path(r"D:\Yandex.Disk\History&Geography\БД\Каталогизация\.env"))
    token = env("NOTION_TOKEN", required=True)
    client = Client(auth=token)

    with open(SOURCE_JSON, encoding="utf-8") as f:
        source = json.load(f)
    by_code = {(r["fund"], r["opis"], r["delo"]): r for r in source}

    cls_rows = parse_classification(CLASSIFICATION_MD)
    done_ledger = load_ledger()

    to_import = []
    skipped_tag = 0
    skipped_merged = 0
    skipped_done = 0
    skipped_nosrc = 0

    for row in cls_rows:
        key = (row["fund"], row["opis"], row["delo"])
        if row["typ"] in SKIP_TAGS:
            skipped_tag += 1
            continue
        delo_base = re.sub(r"\s*т\.\d+\w*$", "", row["delo"])
        if (row["fund"], row["opis"], delo_base) in MERGED_SERIES_BASE_DELO:
            skipped_merged += 1
            continue
        if key in ALREADY_DONE_DELO_PREFIXES:
            skipped_merged += 1
            continue
        if key in done_ledger:
            skipped_done += 1
            continue
        src = by_code.get(key)
        if not src:
            skipped_nosrc += 1
            continue
        to_import.append((row["typ"], src))

    print(f"К заливке: {len(to_import)}  (пропущено: тег={skipped_tag}, слито-серии={skipped_merged}, "
          f"уже в ledger={skipped_done}, нет в источнике={skipped_nosrc})")

    if args.limit:
        to_import = to_import[: args.limit]

    if args.dry_run:
        print("\n=== DRY-RUN: первые 5 примеров ===")
        for typ, src in to_import[:5]:
            props = build_properties(src, typ)
            print(f"\n-- [{typ}] ф{src['fund']}оп{src['opis']}д{src['delo']} --")
            for k, v in props.items():
                print(f"  {k}: {v}")
        return

    ok, failed = 0, 0
    for i, (typ, src) in enumerate(to_import, 1):
        key = (src["fund"], src["opis"], src["delo"])
        props = build_properties(src, typ)
        rest_props = serialize_for_rest(props)
        try:
            page = client.pages.create(
                parent={"type": "data_source_id", "data_source_id": CATALOG_DATA_SOURCE_ID},
                properties=rest_props,
            )
            append_ledger({"key": list(key), "status": "ok", "page_id": page["id"], "typ": typ})
            ok += 1
        except Exception as exc:  # noqa: BLE001 -- логируем и продолжаем, резюмируемо через ledger
            append_ledger({"key": list(key), "status": "fail", "error": str(exc)[:300], "typ": typ})
            failed += 1
            log(f"FAIL ф{key[0]}оп{key[1]}д{key[2]}: {exc}")
        if i % 25 == 0:
            log(f"{i}/{len(to_import)} ok={ok} failed={failed}")
        time.sleep(0.4)

    print(f"\nГотово: ok={ok} failed={failed} из {len(to_import)}")


if __name__ == "__main__":
    main()
